"""
The Whistling World Cup: drive a LEGO Education robot by whistling.

A microphone stream (PyAudio) is analysed with an FFT to find the pitch of your
whistle, and the pitch band picks a driving command:

    pitch band          command
    ------------------  -------------------------------------------------
    LOW                 stop (speed -> 0, wheels straight)
    MID-LOW             turn left
    MID-HIGH            turn right
    HIGH                speed up (keep whistling to keep accelerating)
    VERY HIGH, held     "GOAL!" special command (ball only)

Silence keeps the current speed and straightens the wheels. If you whistle a
turn while stopped, the robot spins in place so you can aim.

Game flow (both roles wait for "start" on MQTT topic ME193/Rogers):

  ball   - Drives at the goal. The Color Sensor (the "light sensor", open and
           facing forward) watches for the goalie getting close. If it does:
           stop, publish MSG_BALL_CAUGHT, play the death song. If you reach the
           goal, whistle the special GOAL command: stop, publish MSG_GOAL_SCORED,
           play the victory song.
  goalie - Drives to block the ball. On MSG_BALL_CAUGHT it plays the victory
           song; on MSG_GOAL_SCORED it plays the death song.

Agree on MSG_BALL_CAUGHT / MSG_GOAL_SCORED with your opponent before the match.

Two whistlers, one robot: a second computer runs --role motor and whistles a
Single Motor on the same robot (low = reverse, middle = stop, high = forward,
further from the middle = faster), in its own calibrated range. It publishes
the speed on MOTOR_TOPIC; the robot computer, started with --single-motor,
drives the Single Motor from it and stops it if the messages stop.

Usage:
    python theWhistlignWorldCup.py --role ball
    python theWhistlignWorldCup.py --role goalie
    python theWhistlignWorldCup.py --calibrate          # print your whistle pitch
    python theWhistlignWorldCup.py --role ball --no-robot --skip-start   # test without hardware
    python theWhistlignWorldCup.py --role ball --practice   # offline: no MQTT, starts immediately
    python theWhistlignWorldCup.py --role ball --practice --no-robot   # ...and watch a simulated robot
    python theWhistlignWorldCup.py --role goalie --practice --no-robot # goalie vs a CPU ball
    python theWhistlignWorldCup.py --test-sensor        # live light-sensor readings
    python theWhistlignWorldCup.py --role ball --no-spectrogram   # no live spectrogram window
    python theWhistlignWorldCup.py --role ball --single-motor     # robot computer, + Single Motor
    python theWhistlignWorldCup.py --role motor --low 700 --high 1900   # 2nd computer whistles it

Press Ctrl+C to quit; the robot always stops and disconnects.
"""

import argparse
import queue
import sys
import time
import uuid

import numpy as np
try:
    import pyaudio
except ImportError:  # no PyAudio wheel for this Python (e.g. 3.14): use the drop-in fork
    import pyaudiowpatch as pyaudio
import paho.mqtt.client as mqtt

import legoeducation as le

# --- Hardware identity (Connection Card shared by the Double Motor and Color Sensor) ---
CARD_COLOR = le.LEGO_COLOR_PURPLE
CARD_SERIAL = "6065"  # <-- update to match your Connection Card

# --- MQTT: agree on these with your opponent! ---
MQTT_BROKER = "broker.hivemq.com"
MQTT_PORT = 1883
MQTT_TOPIC = "ME193/Rogers"
MSG_START = "start"
MSG_BALL_CAUGHT = "ball_caught"    # ball -> everyone: the goalie got me (goalie wins)
MSG_GOAL_SCORED = "goal_scored"    # ball -> everyone: I made it into the goal (ball wins)

# --- Audio / pitch detection ---
SAMPLE_RATE = 44100
CHUNK = 2048                 # ~46 ms per analysis frame
MIN_WHISTLE_HZ = 500         # ignore anything outside the human whistle range
MAX_WHISTLE_HZ = 4500
MIN_RMS = 0.01               # frame must be at least this loud (0..1 full scale)
MIN_TONALITY = 15.0          # peak / median spectrum; whistles are pure tones, speech/noise isn't
STABLE_FRAMES = 3            # a band must repeat this many frames in a row before it counts

# Your comfortable whistle range in Hz. Run --calibrate, whistle your lowest and
# highest notes, then paste the suggested values it prints here. The range is
# split into pitch bands, lowest to highest, sized by these weights. "faster" is
# used most, so it gets a double-width band that's easy to hit.
WHISTLE_LOW_HZ = 520
WHISTLE_HIGH_HZ = 1744
BAND_WEIGHTS = [("stop", 1), ("left", 1), ("right", 1), ("faster", 2), ("goal", 1)]
_unit_hz = (WHISTLE_HIGH_HZ - WHISTLE_LOW_HZ) / sum(w for _, w in BAND_WEIGHTS)
# (lower bound in Hz, command); the lowest band catches everything below it too
BANDS = []
_lower = WHISTLE_LOW_HZ
for _name, _weight in BAND_WEIGHTS:
    BANDS.append((0 if not BANDS else _lower, _name))
    _lower += _weight * _unit_hz
GOAL_HOLD_S = 1.0            # hold the GOAL whistle this long to claim a goal
GOAL_GAP_S = 0.3             # a GOAL hold survives dropouts shorter than this

# --- Driving ---
MAX_SPEED = 80               # percent
SPEED_STEP = 4               # speed added per "faster" frame (~46 ms)
TURN_DIFF = 30               # speed difference between wheels while turning
SEND_INTERVAL_S = 1 / 15     # throttle BLE commands to ~15 Hz

# --- Single Motor, whistled from a second computer over MQTT (--role motor) ---
# The second whistler's own range: they run --calibrate on their computer and
# paste the MOTOR_ values it prints here (or pass --low / --high).
MOTOR_WHISTLE_LOW_HZ = 600
MOTOR_WHISTLE_HIGH_HZ = 1700
# Their range, lowest to highest: full reverse ... stop ... full forward. The
# further from the middle, the faster; the middle STOP band is this share of it.
MOTOR_STOP_SHARE = 0.2
MOTOR_MAX_SPEED = 100        # percent at either end of the range
MOTOR_MIN_SPEED = 20         # percent just outside the STOP band (slower barely turns)
MOTOR_SILENCE_S = 0.25       # stop the Single Motor after this long without a whistle
MOTOR_SEND_INTERVAL_S = 0.1  # the motor computer publishes its speed ~10x a second
MOTOR_TIMEOUT_S = 1.0        # robot stops the Single Motor if messages stop this long
# Our robot only (the opponent listens on MQTT_TOPIC itself, not below it)
MOTOR_TOPIC = f"{MQTT_TOPIC}/{CARD_SERIAL}/single_motor"

# --- Light (Color) sensor catch detection ---
BASELINE_SAMPLES = 20        # readings averaged at startup as "nothing nearby"
CATCH_DELTA = 15             # reflection change (0-100) that means the goalie is close
CATCH_SAMPLES = 3            # consecutive readings over the threshold before we're "caught"

# --- Songs: (frequency Hz, beats); 0 Hz is a rest ---
BEAT_S = 0.3
DEATH_SONG = [  # Chopin's funeral march
    (233, 1.5), (233, 1), (233, 0.5), (233, 1.5), (277, 1), (262, 0.5),
    (262, 1), (233, 0.5), (233, 1), (220, 0.5), (233, 3),
]
VICTORY_SONG = [  # stadium "Charge!"
    (392, 0.5), (523, 0.5), (659, 0.5), (784, 1), (0, 0.25), (659, 0.5), (784, 3),
]


# ----------------------------------------------------------------------------
# Pitch detection
# ----------------------------------------------------------------------------

class PitchDetector:
    """Finds the dominant whistle frequency in one chunk of audio, or None."""

    def __init__(self):
        self.window = np.hanning(CHUNK).astype(np.float32)
        freqs = np.fft.rfftfreq(CHUNK, 1 / SAMPLE_RATE)
        self.band = (freqs >= MIN_WHISTLE_HZ) & (freqs <= MAX_WHISTLE_HZ)
        self.band_start = int(np.argmax(self.band))
        self.hz_per_bin = SAMPLE_RATE / CHUNK

    def pitch(self, samples):
        rms = float(np.sqrt(np.mean(samples ** 2)))
        if rms < MIN_RMS:
            return None, rms
        spectrum = np.abs(np.fft.rfft(samples * self.window))
        in_band = spectrum[self.band]
        peak = int(np.argmax(in_band))
        if in_band[peak] < MIN_TONALITY * (np.median(in_band) + 1e-9):
            return None, rms

        # Parabolic interpolation between neighbouring bins for sub-bin accuracy
        i = self.band_start + peak
        offset = 0.0
        if 0 < i < len(spectrum) - 1:
            a, b, c = spectrum[i - 1], spectrum[i], spectrum[i + 1]
            denom = a - 2 * b + c
            if denom != 0:
                offset = 0.5 * (a - c) / denom
        return (i + offset) * self.hz_per_bin, rms


def band_for(freq, bands=BANDS):
    if freq is None:
        return None
    command = bands[0][1]
    for lower, name in bands:
        if freq >= lower:
            command = name
    return command


class WhistleCommands:
    """Debounces raw per-frame bands into stable commands and tracks GOAL holds."""

    def __init__(self):
        self.candidate = None
        self.count = 0
        self.goal_since = None
        self.goal_last_seen = 0.0

    def update(self, band):
        if band == self.candidate:
            self.count += 1
        else:
            self.candidate, self.count = band, 1
        stable = self.candidate if self.count >= STABLE_FRAMES else None

        now = time.monotonic()
        if stable is not None and stable != "goal":
            self.goal_since = None
        elif self.goal_since is not None and now - self.goal_last_seen > GOAL_GAP_S:
            self.goal_since = None
        if stable == "goal":
            if self.goal_since is None:
                self.goal_since = now
            self.goal_last_seen = now
        goal_claimed = self.goal_since is not None and now - self.goal_since >= GOAL_HOLD_S
        return stable, goal_claimed


def motor_bands(low_hz, high_hz):
    """(lower bound Hz, name) bands for the Single Motor whistler, like BANDS."""
    mid, half_stop = (low_hz + high_hz) / 2, MOTOR_STOP_SHARE * (high_hz - low_hz) / 2
    return [(0, "reverse"), (mid - half_stop, "stop"), (mid + half_stop, "forward")]


def motor_speed_for(freq, low_hz, high_hz):
    """Single Motor speed (-100..100) for a whistle: low = reverse, middle = stop, high = forward."""
    if freq is None:
        return 0
    x = float(np.clip((freq - low_hz) / (high_hz - low_hz), 0, 1)) - 0.5   # -0.5..0.5
    half_stop = MOTOR_STOP_SHARE / 2
    if abs(x) <= half_stop:
        return 0
    how_far = (abs(x) - half_stop) / (0.5 - half_stop)                      # 0..1 past the STOP band
    speed = MOTOR_MIN_SPEED + how_far * (MOTOR_MAX_SPEED - MOTOR_MIN_SPEED)
    return int(round(np.sign(x) * speed))


NOTE_NAMES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]


def note_for(freq):
    """Nearest musical note and how far off it is, e.g. 'A5 +12c'."""
    midi = 69 + 12 * np.log2(freq / 440)
    nearest = int(round(midi))
    cents = int(round(100 * (midi - nearest)))
    return f"{NOTE_NAMES[nearest % 12]}{nearest // 12 - 1} {cents:+d}c"


# ----------------------------------------------------------------------------
# Live spectrogram window
# ----------------------------------------------------------------------------

COMMAND_COLORS = {"stop": "#ef5350", "left": "#42a5f5", "right": "#ab47bc",
                  "faster": "#66bb6a", "goal": "#ffca28",
                  "reverse": "#ffa726", "forward": "#66bb6a"}   # single motor bands


class Spectrogram:
    """Scrolling spectrogram of the mic, with the detected pitch, its note, the
    command bands, and what the robot is doing. Closing the window quits."""

    IMG_W, IMG_H = 500, 300   # spectrogram image in px (time x frequency)
    COLS_PER_FRAME = 2        # px scrolled per audio frame (~11 s of history)
    LEFT, RIGHT, TOP = 55, 90, 80   # margins for Hz ticks, band names, header
    DB_RANGE = 60             # dB from the loudest recent bin down to black
    MIN_TOP_DB = 20           # keeps silence dark instead of amplifying noise

    def __init__(self, master=None, low_hz=WHISTLE_LOW_HZ, high_hz=WHISTLE_HIGH_HZ, bands=BANDS,
                 title="live spectrogram"):
        import tkinter as tk
        self.owns_root = master is None
        self.win = tk.Tk() if self.owns_root else tk.Toplevel(master)
        self.win.title(f"Whistling World Cup - {title}")
        self.bands = bands
        self.win.protocol("WM_DELETE_WINDOW", self._on_close)
        self.closed = False
        self.tk = tk

        self.lo_hz = max(0, int(low_hz) - 300)
        self.hi_hz = int(high_hz) + 500
        self.row_hz = np.linspace(self.hi_hz, self.lo_hz, self.IMG_H)   # top row = highest pitch
        self.bin_hz = np.fft.rfftfreq(CHUNK, 1 / SAMPLE_RATE)
        self.window = np.hanning(CHUNK).astype(np.float32)
        self.top_db = self.MIN_TOP_DB
        self.img = np.zeros((self.IMG_H, self.IMG_W, 3), dtype=np.uint8)
        # black -> purple -> orange -> pale yellow, like matplotlib's "magma"
        anchors = np.array([[0, 0, 4], [80, 18, 123], [182, 54, 121], [251, 136, 97], [252, 253, 191]])
        x = np.linspace(0, 1, len(anchors))
        self.lut = np.stack([np.interp(np.linspace(0, 1, 256), x, anchors[:, c])
                             for c in range(3)], axis=1).astype(np.uint8)

        w = self.LEFT + self.IMG_W + self.RIGHT
        h = self.TOP + self.IMG_H + 25
        self.canvas = tk.Canvas(self.win, width=w, height=h, bg="#121212", highlightthickness=0)
        self.canvas.pack()
        self.photo = None
        self.image = self.canvas.create_image(self.LEFT, self.TOP, anchor="nw")

        # Hz ticks on the left
        for hz in range(int(np.ceil(self.lo_hz / 250) * 250), self.hi_hz + 1, 250):
            y = self._y(hz)
            self.canvas.create_line(self.LEFT - 5, y, self.LEFT, y, fill="#888")
            self.canvas.create_text(self.LEFT - 8, y, anchor="e", text=str(hz), fill="#aaa",
                                    font=("Helvetica", 9))
        self.canvas.create_text(self.LEFT + self.IMG_W / 2, self.TOP + self.IMG_H + 13,
                                text="time -> (newest on the right)", fill="#777", font=("Helvetica", 9))

        # Command bands: dashed boundaries across the image, coloured strips on the right
        self.strips = {}
        x0, x1 = self.LEFT + self.IMG_W + 5, self.LEFT + self.IMG_W + self.RIGHT - 5
        for i, (lower, name) in enumerate(bands):
            upper = bands[i + 1][0] if i + 1 < len(bands) else self.hi_hz
            y_top, y_bot = self._y(upper), self._y(max(lower, self.lo_hz))
            color = COMMAND_COLORS.get(name, "#bbb")
            self.strips[name] = self.canvas.create_rectangle(x0, y_top, x1, y_bot, fill="#1e1e1e",
                                                             outline=color, width=2)
            self.canvas.create_text((x0 + x1) / 2, (y_top + y_bot) / 2, text=name.upper(),
                                    fill=color, font=("Helvetica", 11, "bold"))
            if i > 0:
                self.canvas.create_line(self.LEFT, y_bot, self.LEFT + self.IMG_W, y_bot,
                                        fill=color, dash=(4, 4))
        self.marker = self.canvas.create_polygon(0, 0, 0, 0, 0, 0, fill="white", state="hidden")

        # Header: pitch + note on the left, robot action on the right
        self.pitch_text = self.canvas.create_text(12, 12, anchor="nw", fill="white",
                                                  font=("Courier", 22, "bold"), text="-- Hz")
        self.note_text = self.canvas.create_text(12, 48, anchor="nw", fill="#bbb",
                                                 font=("Courier", 14), text="no whistle")
        self.action_text = self.canvas.create_text(w - 12, 10, anchor="ne", fill="white",
                                                   font=("Helvetica", 26, "bold"), text="WAITING")
        self.detail_text = self.canvas.create_text(w - 12, 50, anchor="ne", fill="#bbb",
                                                   font=("Courier", 13), text="")
        self.win.update()

    def _on_close(self):
        self.closed = True

    def _y(self, hz):
        return self.TOP + (self.hi_hz - hz) / (self.hi_hz - self.lo_hz) * (self.IMG_H - 1)

    def update(self, samples, freq, action, command=None, detail=""):
        """Add one audio frame and show the robot's current action."""
        if self.closed:
            raise KeyboardInterrupt

        # New spectrum column, in dB, scaled to the loudest recent bin
        db = 20 * np.log10(np.abs(np.fft.rfft(samples * self.window)) + 1e-9)
        column = np.interp(self.row_hz, self.bin_hz, db)
        self.top_db = max(self.top_db - 0.3, float(column.max()), self.MIN_TOP_DB)
        level = np.clip((column - (self.top_db - self.DB_RANGE)) / self.DB_RANGE, 0, 1)
        colors = self.lut[(level * 255).astype(int)]

        n = self.COLS_PER_FRAME
        self.img[:, :-n] = self.img[:, n:]
        self.img[:, -n:] = colors[:, None, :]
        if freq is not None and self.lo_hz <= freq <= self.hi_hz:   # detected pitch trace
            row = int(round(self._y(freq) - self.TOP))
            self.img[max(0, row - 1):row + 2, -n:] = (0, 255, 255)
        header = b"P6 %d %d 255 " % (self.IMG_W, self.IMG_H)
        self.photo = self.tk.PhotoImage(data=header + self.img.tobytes(), format="PPM")
        self.canvas.itemconfig(self.image, image=self.photo)

        # Labels
        if freq is None:
            self.canvas.itemconfig(self.pitch_text, text="-- Hz")
            self.canvas.itemconfig(self.note_text, text="no whistle")
            self.canvas.itemconfig(self.marker, state="hidden")
        else:
            self.canvas.itemconfig(self.pitch_text, text=f"{freq:5.0f} Hz")
            self.canvas.itemconfig(self.note_text, text=f"{note_for(freq)}  -> {band_for(freq, self.bands)}")
            y = min(max(self._y(freq), self.TOP), self.TOP + self.IMG_H)
            x = self.LEFT + self.IMG_W
            self.canvas.coords(self.marker, x, y, x + 10, y - 7, x + 10, y + 7)
            self.canvas.itemconfig(self.marker, state="normal")
            self.canvas.tag_raise(self.marker)
        for name, strip in self.strips.items():
            self.canvas.itemconfig(strip, fill=COMMAND_COLORS[name] if name == command else "#1e1e1e")
        self.canvas.itemconfig(self.action_text, text=action,
                               fill=COMMAND_COLORS.get(command, "white"))
        self.canvas.itemconfig(self.detail_text, text=detail)
        if self.owns_root:
            self.win.update()
        else:
            self.win.update_idletasks()

    def show(self, action, detail=""):
        """Freeze on a final message, e.g. the match result."""
        self.canvas.itemconfig(self.action_text, text=action, fill="white")
        self.canvas.itemconfig(self.detail_text, text=detail)
        self.win.update()

    def close(self):
        try:
            self.win.destroy()
        except Exception:
            pass


# ----------------------------------------------------------------------------
# Simulator (--no-robot)
# ----------------------------------------------------------------------------

class Simulator:
    """Top-down window where a virtual robot drives from the same tank commands.

    A computer opponent plays the other role: as the ball you dodge a CPU goalie,
    as the goalie you stop a CPU ball. The ball's forward light sensor is
    simulated as a cone in front of it (drawn dashed).
    """

    W, H = 800, 500
    PX_PER_PCT = 3.0     # px/s per % of wheel speed (80% -> 240 px/s)
    TRACK_PX = 80        # distance between the wheels; smaller turns faster
    TRAIL_MAX = 600      # trail segments kept on screen
    GOAL_HALF_H = 80     # goal mouth is H/2 +- this
    SENSOR_RANGE_PX = 80                 # ball's light sensor sees this far (centre to centre)
    SENSOR_HALF_ANGLE = np.radians(30)   # ...within this angle of straight ahead
    TOUCH_PX = 35        # robots this close always count as a catch
    CPU_GOALIE_SPEED = 100   # px/s the CPU goalie slides across its goal
    CPU_BALL_SPEED = 55      # px/s the CPU ball advances toward the goal

    def __init__(self, role, inbox):
        import tkinter as tk
        self.role, self.inbox = role, inbox
        self.root = tk.Tk()
        self.root.title(f"Whistling World Cup - simulator ({role} practice)")
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)
        self.canvas = tk.Canvas(self.root, width=self.W, height=self.H, bg="#2e7d32", highlightthickness=0)
        self.canvas.pack()
        w, h, g = self.W, self.H, self.GOAL_HALF_H
        self.canvas.create_line(w / 2, 0, w / 2, h, fill="white", width=2)
        self.canvas.create_oval(w / 2 - 60, h / 2 - 60, w / 2 + 60, h / 2 + 60, outline="white", width=2)
        self.canvas.create_rectangle(w - 25, h / 2 - g, w, h / 2 + g, outline="white", width=3)
        self.canvas.create_text(w - 40, h / 2, text="GOAL", fill="white", angle=90, font=("Arial", 14, "bold"))
        self.cone = self.canvas.create_polygon(0, 0, 0, 0, 0, 0, fill="", outline="white", dash=(3, 3))
        self.opponent = self.canvas.create_polygon(0, 0, 0, 0, 0, 0, fill="#42a5f5", outline="black", width=2)
        self.body = self.canvas.create_polygon(0, 0, 0, 0, 0, 0, fill="#fdd835", outline="black", width=2)
        self.status = self.canvas.create_text(10, 10, anchor="nw", fill="white", font=("Consolas", 14))
        self.banner = self.canvas.create_text(w / 2, 40, fill="white", font=("Arial", 22, "bold"))
        self.canvas.create_text(10, h - 10, anchor="sw", fill="#c8e6c9", font=("Arial", 10),
                                text="yellow = you   blue = CPU " + ("goalie" if role == "ball" else "ball"))
        self.trail = []
        if role == "ball":   # you start on the left, CPU goalie guards the goal
            self.x, self.y, self.heading = 80.0, h / 2, 0.0
            self.opp_x, self.opp_y, self.opp_heading = w - 70.0, h / 2, np.pi
        else:                # you guard the goal, CPU ball starts on the left
            self.x, self.y, self.heading = w - 90.0, h / 2, np.pi
            self.opp_x, self.opp_y, self.opp_heading = 60.0, h / 2, 0.0
        self.left = self.right = 0
        self.start = self.last = time.monotonic()
        self.banner_until = 0.0
        self.finished = False
        self.closed = False
        self.update("")

    def _on_close(self):
        self.closed = True

    @staticmethod
    def _triangle(x, y, heading):
        c, s = np.cos(heading), np.sin(heading)
        points = []
        for fwd, side in ((24, 0), (-16, 15), (-16, -15)):
            points += [x + fwd * c - side * s, y - fwd * s - side * c]
        return points

    def _sees(self, bx, by, bheading, tx, ty):
        """Would a forward light sensor at (bx, by) facing bheading detect a robot at (tx, ty)?"""
        dx, dy = tx - bx, by - ty   # flip y so angles are counter-clockwise
        dist = np.hypot(dx, dy)
        if dist <= self.TOUCH_PX:
            return True
        off_axis = abs((np.arctan2(dy, dx) - bheading + np.pi) % (2 * np.pi) - np.pi)
        return dist <= self.SENSOR_RANGE_PX and off_axis <= self.SENSOR_HALF_ANGLE

    def _in_mouth(self, x, y, depth):
        return x >= self.W - depth and abs(y - self.H / 2) <= self.GOAL_HALF_H

    def goalie_is_close(self):
        """Ball practice: the simulated light sensor sees the CPU goalie."""
        return self._sees(self.x, self.y, self.heading, self.opp_x, self.opp_y)

    def in_goal(self):
        """Ball practice: close enough to the goal for a GOAL whistle to count."""
        return self._in_mouth(self.x, self.y, depth=90)

    def flash(self, text, seconds=1.5):
        self.canvas.itemconfig(self.banner, text=text)
        self.banner_until = time.monotonic() + seconds

    def _move_opponent(self, now, dt):
        if self.role == "ball":
            # CPU goalie slides along its goal line to stay between you and the goal
            target = np.clip(self.y, self.H / 2 - self.GOAL_HALF_H, self.H / 2 + self.GOAL_HALF_H)
            step = np.clip(target - self.opp_y, -self.CPU_GOALIE_SPEED * dt, self.CPU_GOALIE_SPEED * dt)
            self.opp_y += float(step)
            return
        # CPU ball weaves toward the goal, the weave narrowing as it gets close
        old_x, old_y = self.opp_x, self.opp_y
        self.opp_x += self.CPU_BALL_SPEED * dt
        weave = 130 * max(0.0, (self.W - 60 - self.opp_x) / self.W)
        self.opp_y = self.H / 2 + weave * np.sin(0.8 * (now - self.start))
        if self.opp_x != old_x:
            self.opp_heading = float(np.arctan2(old_y - self.opp_y, self.opp_x - old_x))
        # The CPU ball reports the result the way a real one would over MQTT
        if self._sees(self.opp_x, self.opp_y, self.opp_heading, self.x, self.y):
            self.finished = True
            print(f"[sim] CPU ball's light sensor saw you -> {MSG_BALL_CAUGHT!r}")
            self.inbox.put(MSG_BALL_CAUGHT)
        elif self._in_mouth(self.opp_x, self.opp_y, depth=30):
            self.finished = True
            print(f"[sim] CPU ball reached the goal -> {MSG_GOAL_SCORED!r}")
            self.inbox.put(MSG_GOAL_SCORED)

    def update(self, status):
        """Advance the physics to now and redraw. Closing the window quits the game."""
        if self.closed:
            raise KeyboardInterrupt
        now = time.monotonic()
        dt, self.last = min(now - self.last, 0.2), now

        # Differential drive: average wheel speed moves, the difference turns
        v = (self.left + self.right) / 2 * self.PX_PER_PCT
        self.heading += (self.right - self.left) * self.PX_PER_PCT / self.TRACK_PX * dt
        nx = float(np.clip(self.x + v * np.cos(self.heading) * dt, 15, self.W - 15))
        ny = float(np.clip(self.y - v * np.sin(self.heading) * dt, 15, self.H - 15))
        if (nx, ny) != (self.x, self.y):
            self.trail.append(self.canvas.create_line(self.x, self.y, nx, ny, fill="#a5d6a7", width=2))
            if len(self.trail) > self.TRAIL_MAX:
                self.canvas.delete(self.trail.pop(0))
        self.x, self.y = nx, ny
        if not self.finished:
            self._move_opponent(now, dt)

        # Draw both robots, plus the light-sensor cone on whichever one is the ball
        self.canvas.coords(self.body, *self._triangle(self.x, self.y, self.heading))
        self.canvas.coords(self.opponent, *self._triangle(self.opp_x, self.opp_y, self.opp_heading))
        bx, by, bh = ((self.x, self.y, self.heading) if self.role == "ball"
                      else (self.opp_x, self.opp_y, self.opp_heading))
        r, a = self.SENSOR_RANGE_PX, self.SENSOR_HALF_ANGLE
        self.canvas.coords(self.cone, bx, by,
                           bx + r * np.cos(bh + a), by - r * np.sin(bh + a),
                           bx + r * np.cos(bh - a), by - r * np.sin(bh - a))
        for item in (self.cone, self.opponent, self.body, self.status, self.banner):
            self.canvas.tag_raise(item)
        self.canvas.itemconfig(self.status, text=status)
        if self.banner_until and now > self.banner_until:
            self.canvas.itemconfig(self.banner, text="")
            self.banner_until = 0.0
        self.root.update()

    def close(self):
        try:
            self.root.destroy()
        except Exception:
            pass


# ----------------------------------------------------------------------------
# Robot
# ----------------------------------------------------------------------------

class Robot:
    """Double Motor + Color Sensor (+ optional Single Motor), or an on-screen simulator with --no-robot."""

    def __init__(self, use_hardware, need_sensor, need_motor=True, role="ball", inbox=None,
                 need_single_motor=False):
        self.use_hardware = use_hardware
        self.motor = None
        self.sensor = None
        self.single_motor = None
        self.single_speed = 0
        self.single_last_sent = None
        self.single_send_time = 0.0
        self.last_sent = None
        self.last_send_time = 0.0
        self.baseline = None
        self.over_count = 0
        self.sim = None
        if not use_hardware:
            print("[no-robot] Driving a simulated robot in a window (close it or Ctrl+C to quit).")
            self.sim = Simulator(role, inbox if inbox is not None else queue.Queue())
            return

        if need_motor:
            print(f"Connecting to Double Motor (card serial {CARD_SERIAL})...")
            self.motor = le.DoubleMotor()
            self.motor.connect(card_color=CARD_COLOR, card_serial=CARD_SERIAL)
            if not self.motor.connected:
                raise RuntimeError("Could not connect to the Double Motor. Is it on and broadcasting?")
            self.motor.movement_set_end_state(le.MOTOR_END_STATE_BRAKE)
            print("Double Motor connected.")

        if need_sensor:
            print(f"Connecting to Color Sensor (card serial {CARD_SERIAL})...")
            self.sensor = le.ColorSensor()
            self.sensor.connect(card_color=CARD_COLOR, card_serial=CARD_SERIAL)
            if not self.sensor.connected:
                raise RuntimeError("Could not connect to the Color Sensor. Is it on and broadcasting?")
            print("Color Sensor connected.")

        if need_single_motor:
            print(f"Connecting to Single Motor (card serial {CARD_SERIAL})...")
            self.single_motor = le.SingleMotor()
            self.single_motor.connect(card_color=CARD_COLOR, card_serial=CARD_SERIAL)
            if not self.single_motor.connected:
                raise RuntimeError("Could not connect to the Single Motor. Is it on and broadcasting?")
            self.single_motor.motor_set_end_state(le.MOTOR_END_STATE_BRAKE)
            print("Single Motor connected.")

    def run_single_motor(self, speed):
        """Single Motor speed -100..100 (negative = counter-clockwise); 0 stops it."""
        speed = int(np.clip(speed, -100, 100))
        self.single_speed = speed
        if self.single_motor is None:
            return   # simulator: the speed is only shown on screen
        now = time.monotonic()
        if speed == self.single_last_sent or now - self.single_send_time < SEND_INTERVAL_S:
            return
        self.single_last_sent, self.single_send_time = speed, now
        if speed == 0:
            self.single_motor.motor_stop(blocking=False)
        else:
            self.single_motor.motor_run(speed=speed, blocking=False)

    def drive(self, left, right, force=False):
        left, right = int(np.clip(left, -100, 100)), int(np.clip(right, -100, 100))
        if self.sim is not None:
            self.sim.left, self.sim.right = left, right
            return
        now = time.monotonic()
        if not force and ((left, right) == self.last_sent or now - self.last_send_time < SEND_INTERVAL_S):
            return
        self.last_sent, self.last_send_time = (left, right), now
        self.motor.movement_move_tank(left, right, blocking=False)

    def stop(self):
        self.last_sent = (0, 0)
        self.single_last_sent, self.single_speed = 0, 0
        if self.motor is not None:
            self.motor.movement_stop(blocking=True)
        if self.single_motor is not None:
            self.single_motor.motor_stop(blocking=True)
        if self.sim is not None:
            self.sim.left = self.sim.right = 0

    def update(self, status=""):
        """Redraw the simulator (no-op with real hardware)."""
        if self.sim is not None:
            self.sim.update(status)

    def flash(self, text):
        """Big message in the simulator window (no-op with real hardware)."""
        if self.sim is not None:
            self.sim.flash(text)
            self.sim.update("")

    def in_goal(self):
        """Only the simulator can tell; on the real field the GOAL whistle is on your honour."""
        return self.sim is None or self.sim.in_goal()

    def reflection(self):
        if self.sensor is None:
            return None
        value = self.sensor.sensor.reflection
        return None if value != value else float(value)  # NaN until the first notification

    def calibrate_light(self):
        """Average the sensor with nothing in front of it, as the 'open' baseline."""
        if self.sensor is None:
            return
        print("Calibrating light sensor: keep the area in front of it clear...")
        readings = []
        deadline = time.monotonic() + 10
        while len(readings) < BASELINE_SAMPLES and time.monotonic() < deadline:
            value = self.reflection()
            if value is not None:
                readings.append(value)
            time.sleep(0.05)
        if not readings:
            raise RuntimeError("No readings from the Color Sensor.")
        self.baseline = sum(readings) / len(readings)
        print(f"Light baseline reflection = {self.baseline:.1f}")

    def goalie_is_close(self):
        if self.sim is not None:
            return self.sim.goalie_is_close()
        value = self.reflection()
        if value is None or self.baseline is None:
            return False
        if abs(value - self.baseline) >= CATCH_DELTA:
            self.over_count += 1
        else:
            self.over_count = 0
        return self.over_count >= CATCH_SAMPLES

    def close(self):
        if self.sim is not None:
            self.sim.close()
        for device in (self.motor, self.single_motor, self.sensor):
            if device is None:
                continue
            try:
                if device is self.motor:
                    device.movement_stop(blocking=True)
                elif device is self.single_motor:
                    device.motor_stop(blocking=True)
                device.disconnect()
            except Exception as e:
                print(f"Warning while disconnecting: {e}")


# ----------------------------------------------------------------------------
# MQTT
# ----------------------------------------------------------------------------

def new_mqtt_client():
    client_id = f"ME193-whistle-{uuid.uuid4().hex[:8]}"
    try:  # paho-mqtt 2.x
        return mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=client_id)
    except AttributeError:  # paho-mqtt 1.x
        return mqtt.Client(client_id=client_id)


def connect_mqtt(broker, inbox):
    client = new_mqtt_client()

    def on_connect(client, *args):
        client.subscribe(MQTT_TOPIC)
        print(f"MQTT connected to {broker}, subscribed to {MQTT_TOPIC}")

    def on_message(client, userdata, msg):
        text = msg.payload.decode(errors="ignore").strip()
        print(f"MQTT <- {text!r}")
        inbox.put(text)

    client.on_connect = on_connect
    client.on_message = on_message
    client.connect(broker, MQTT_PORT, keepalive=60)
    client.loop_start()
    return client


def publish(client, text):
    if client is None:
        print(f"[practice] would send {text!r} on {MQTT_TOPIC}")
        return
    print(f"MQTT -> {text!r}")
    client.publish(MQTT_TOPIC, text, qos=1).wait_for_publish(timeout=3)


class SingleMotorLink:
    """Robot computer: listens on MOTOR_TOPIC for the Single Motor speed the
    second whistler's computer sends. Its own MQTT connection, so it works in
    --practice too (where the game connection is off)."""

    def __init__(self, broker):
        self.speed = 0
        self.last_heard = 0.0
        self.client = new_mqtt_client()

        def on_connect(client, *args):
            client.subscribe(MOTOR_TOPIC)
            print(f"Single Motor link: listening on {MOTOR_TOPIC}")

        def on_message(client, userdata, msg):
            try:
                self.speed = int(np.clip(int(msg.payload.decode().strip()), -100, 100))
                self.last_heard = time.monotonic()
            except ValueError:
                pass   # ignore anything that isn't a plain number

        self.client.on_connect = on_connect
        self.client.on_message = on_message
        self.client.connect(broker, MQTT_PORT, keepalive=60)
        self.client.loop_start()

    def current_speed(self):
        """Latest speed, or 0 if the motor computer has gone quiet (crashed, Wi-Fi drop)."""
        if time.monotonic() - self.last_heard > MOTOR_TIMEOUT_S:
            return 0
        return self.speed

    def connected(self):
        return time.monotonic() - self.last_heard <= MOTOR_TIMEOUT_S

    def close(self):
        self.client.loop_stop()
        self.client.disconnect()


# ----------------------------------------------------------------------------
# Songs
# ----------------------------------------------------------------------------

def play_song(pa, notes):
    stream = pa.open(format=pyaudio.paFloat32, channels=1, rate=SAMPLE_RATE, output=True)
    try:
        for freq, beats in notes:
            n = int(SAMPLE_RATE * beats * BEAT_S)
            t = np.arange(n) / SAMPLE_RATE
            tone = np.zeros(n) if freq == 0 else 0.4 * np.sin(2 * np.pi * freq * t)
            fade = min(n // 2, int(0.01 * SAMPLE_RATE))  # 10 ms fades avoid clicks
            if fade:
                tone[:fade] *= np.linspace(0, 1, fade)
                tone[-fade:] *= np.linspace(1, 0, fade)
            stream.write(tone.astype(np.float32).tobytes())
    finally:
        stream.stop_stream()
        stream.close()


# ----------------------------------------------------------------------------
# Main loops
# ----------------------------------------------------------------------------

def open_mic(pa):
    return pa.open(format=pyaudio.paFloat32, channels=1, rate=SAMPLE_RATE,
                   input=True, frames_per_buffer=CHUNK)


def read_chunk(mic):
    return np.frombuffer(mic.read(CHUNK, exception_on_overflow=False), dtype=np.float32)


def calibrate(pa, show_spectrogram=True):
    """Print the pitch you're whistling, then suggest WHISTLE_LOW_HZ / WHISTLE_HIGH_HZ."""
    detector = PitchDetector()
    mic = open_mic(pa)
    spectrogram = Spectrogram() if show_spectrogram else None
    print("Current bands: " + ", ".join(f"{name} >= {lower:.0f} Hz" for lower, name in BANDS))
    print("Whistle your LOWEST and HIGHEST comfortable notes, then press Ctrl+C (or close the window).")
    seen = []
    try:
        while True:
            samples = read_chunk(mic)
            freq, rms = detector.pitch(samples)
            if freq is not None:
                seen.append(freq)
                print(f"{freq:7.0f} Hz  {note_for(freq):9s} rms={rms:.3f}  -> {band_for(freq)}")
            if spectrogram is not None:
                band = band_for(freq)
                spectrogram.update(samples, freq, "CALIBRATING", band,
                                   f"heard {len(seen)} whistle frames")
    finally:
        mic.close()
        if spectrogram is not None:
            spectrogram.close()
        if len(seen) >= 10:
            # percentiles ignore the odd glitchy frame at either end
            low, high = np.percentile(seen, [5, 95])
            print(f"\nYour range: about {low:.0f}-{high:.0f} Hz. Set these at the top of the file.")
            print("If you drive the robot (--role ball / goalie):")
            print(f"    WHISTLE_LOW_HZ = {low:.0f}")
            print(f"    WHISTLE_HIGH_HZ = {high:.0f}")
            print("If you whistle the Single Motor (--role motor):")
            print(f"    MOTOR_WHISTLE_LOW_HZ = {low:.0f}")
            print(f"    MOTOR_WHISTLE_HIGH_HZ = {high:.0f}")
            print(f"  (or run: --role motor --low {low:.0f} --high {high:.0f})")


def test_sensor():
    """Live Color Sensor readout, to check it can see the goalie (needs the sensor, not the motor)."""
    robot = Robot(use_hardware=True, need_sensor=True, need_motor=False)
    try:
        robot.calibrate_light()
        print(f"Move the goalie (or your hand) in front of the sensor. A catch is a change of "
              f"{CATCH_DELTA}+ for {CATCH_SAMPLES} readings in a row. Ctrl+C to quit.")
        while True:
            value = robot.reflection()
            caught = robot.goalie_is_close()
            if value is not None:
                change = value - robot.baseline
                bar = "#" * int(min(abs(change), 40))
                print(f"reflection {value:5.1f}  change {change:+6.1f}  |{bar:<40s}|"
                      f"{'  CAUGHT!' if caught else ''}")
            time.sleep(0.1)
    finally:
        robot.close()


def whistle_single_motor(pa, broker, low_hz, high_hz, show_spectrogram=True):
    """Second computer: whistle the Single Motor's speed and send it to the robot over MQTT.

    Low pitch = reverse, middle = stop, high = forward; the further from the
    middle, the faster. Silence stops the motor. Runs until Ctrl+C.
    """
    bands = motor_bands(low_hz, high_hz)
    print("Single Motor bands: " + ", ".join(f"{name} >= {lower:.0f} Hz" for lower, name in bands))
    client = new_mqtt_client()
    client.on_connect = lambda c, *a: print(f"MQTT connected to {broker}; sending speeds on {MOTOR_TOPIC}")
    client.connect(broker, MQTT_PORT, keepalive=60)
    client.loop_start()
    detector = PitchDetector()
    mic = open_mic(pa)
    spectrogram = (Spectrogram(low_hz=low_hz, high_hz=high_hz, bands=bands, title="Single Motor whistle")
                   if show_spectrogram else None)
    recent = []                      # last few detected pitches, median-filtered against glitches
    last_whistle = 0.0
    speed = last_printed = 0
    last_send = 0.0
    try:
        while True:
            samples = read_chunk(mic)
            freq, _ = detector.pitch(samples)
            now = time.monotonic()
            if freq is not None:
                recent = (recent + [freq])[-STABLE_FRAMES:]
                last_whistle = now
                if len(recent) == STABLE_FRAMES:
                    speed = motor_speed_for(float(np.median(recent)), low_hz, high_hz)
            elif now - last_whistle > MOTOR_SILENCE_S:
                recent, speed = [], 0

            if now - last_send >= MOTOR_SEND_INTERVAL_S:   # steady heartbeat, even when unchanged
                client.publish(MOTOR_TOPIC, str(speed), qos=0)
                last_send = now
            if speed != last_printed:
                print(f"Single Motor -> {speed:+4d}%")
                last_printed = speed

            if spectrogram is not None:
                command = band_for(float(np.median(recent)), bands) if recent else None
                action = "MOTOR STOP" if speed == 0 else f"MOTOR {'FWD' if speed > 0 else 'REV'} {abs(speed)}%"
                spectrogram.update(samples, freq, action, command, f"sending {speed:+d}% to robot")
    finally:
        try:   # leave the motor stopped
            client.publish(MOTOR_TOPIC, "0", qos=1).wait_for_publish(timeout=2)
        except Exception as e:
            print(f"Warning: couldn't send the final stop: {e}")
        client.loop_stop()
        client.disconnect()
        mic.close()
        if spectrogram is not None:
            spectrogram.close()


def wait_for_start(inbox):
    print(f"Waiting for '{MSG_START}' on {MQTT_TOPIC}...")
    while True:
        try:  # short timeouts so Ctrl+C still works on Windows
            message = inbox.get(timeout=0.5)
        except queue.Empty:
            continue
        if message.lower() == MSG_START:
            print("KICK OFF!")
            return


def describe_action(command, speed):
    """What the robot is doing, in words, for the spectrogram header."""
    if command == "left":
        return "SPIN LEFT" if speed == 0 else "TURN LEFT"
    if command == "right":
        return "SPIN RIGHT" if speed == 0 else "TURN RIGHT"
    if command == "stop":
        return "STOP"
    if command == "faster":
        return "MAX SPEED" if speed >= MAX_SPEED else "FASTER"
    if command == "goal":
        return "GOAL? HOLD IT"
    return "STRAIGHT" if speed > 0 else "STOPPED"


def play(role, robot, client, inbox, pa, spectrogram=None, motor_link=None):
    """Whistle-drive until the match ends; returns the song to play.

    With motor_link, the Single Motor also follows the speed whistled on the
    second computer."""
    detector = PitchDetector()
    commands = WhistleCommands()
    speed = 0.0
    last_command = None
    mic = open_mic(pa)
    try:
        while True:
            # --- MQTT results (the goalie learns the outcome here) ---
            while not inbox.empty():
                message = inbox.get_nowait()
                if role == "goalie" and message == MSG_BALL_CAUGHT:
                    robot.stop()
                    robot.flash("You caught the ball!")
                    print("We caught the ball! Victory!")
                    return VICTORY_SONG
                if role == "goalie" and message == MSG_GOAL_SCORED:
                    robot.stop()
                    robot.flash("The ball scored...")
                    print("The ball scored. Defeat...")
                    return DEATH_SONG

            # --- Ball: did the goalie get close to our light sensor? ---
            if role == "ball" and robot.goalie_is_close():
                robot.stop()
                robot.flash("Caught by the goalie!")
                print("Caught by the goalie!")
                publish(client, MSG_BALL_CAUGHT)
                return DEATH_SONG

            # --- Whistle -> command ---
            samples = read_chunk(mic)
            freq, _ = detector.pitch(samples)
            command, goal_claimed = commands.update(band_for(freq))

            if goal_claimed and role == "ball" and not robot.in_goal():
                print("Not in the goal yet - drive into the box first!")
                robot.flash("Not in the goal yet!")
                commands = WhistleCommands()   # make them hold the GOAL whistle again
                goal_claimed = False
            if goal_claimed and role == "ball":
                robot.stop()
                robot.flash("GOOOAL!")
                print("GOOOAL!")
                publish(client, MSG_GOAL_SCORED)
                return VICTORY_SONG

            if command != last_command and command is not None:
                print(f"{freq:6.0f} Hz -> {command}")
            last_command = command

            steer = 0
            if command == "stop":
                speed = 0.0
            elif command == "faster":
                speed = min(MAX_SPEED, speed + SPEED_STEP)
            elif command == "left":
                steer = -TURN_DIFF
            elif command == "right":
                steer = TURN_DIFF
            # "goal" (not yet held long enough) and silence: keep speed, go straight

            robot.drive(speed + steer, speed - steer)
            single = ""
            if motor_link is not None:
                robot.run_single_motor(motor_link.current_speed())
                single = (f"  motor {robot.single_speed:+4d}%" if motor_link.connected()
                          else "  motor (no signal)")
            pitch = "  -  " if freq is None else f"{freq:5.0f}"
            robot.update(f"{command or 'silence':8s} speed {speed:3.0f}%   {pitch} Hz{single}")
            if spectrogram is not None:
                left, right = int(np.clip(speed + steer, -100, 100)), int(np.clip(speed - steer, -100, 100))
                spectrogram.update(samples, freq, describe_action(command, speed), command,
                                   f"speed {speed:3.0f}%  L{left:+4d} R{right:+4d}{single}")
    finally:
        mic.close()


def main():
    parser = argparse.ArgumentParser(description="Whistle-controlled World Cup robot")
    parser.add_argument("--role", choices=["ball", "goalie", "motor"],
                        help="your assigned role; 'motor' = second computer whistling the Single Motor")
    parser.add_argument("--broker", default=MQTT_BROKER, help="MQTT broker host")
    parser.add_argument("--calibrate", action="store_true", help="just print whistle pitch")
    parser.add_argument("--no-robot", action="store_true", help="drive an on-screen simulated robot instead of using BLE")
    parser.add_argument("--skip-start", action="store_true", help="don't wait for the MQTT 'start' message")
    parser.add_argument("--practice", action="store_true",
                        help=f"offline practice: no MQTT ({MQTT_TOPIC}), starts immediately")
    parser.add_argument("--test-sensor", action="store_true",
                        help="live Color Sensor readings, to check goalie detection")
    parser.add_argument("--no-spectrogram", action="store_true",
                        help="don't open the live spectrogram window")
    parser.add_argument("--single-motor", action="store_true",
                        help="robot computer: also run the Single Motor from the --role motor computer")
    parser.add_argument("--low", type=float, default=MOTOR_WHISTLE_LOW_HZ,
                        help="--role motor: lowest whistle in Hz (from --calibrate)")
    parser.add_argument("--high", type=float, default=MOTOR_WHISTLE_HIGH_HZ,
                        help="--role motor: highest whistle in Hz (from --calibrate)")
    args = parser.parse_args()

    if args.test_sensor:
        try:
            test_sensor()
        except KeyboardInterrupt:
            pass
        return

    pa = pyaudio.PyAudio()
    if args.calibrate:
        try:
            calibrate(pa, show_spectrogram=not args.no_spectrogram)
        except KeyboardInterrupt:
            pass
        finally:
            pa.terminate()
        return
    while args.role is None:  # e.g. launched from the IDE's Run button with no arguments
        answer = input("Role? [b]all / [g]oalie / [m]otor (2nd computer) / [p]ractice (offline) / "
                       "[s]ensor test / [c]alibrate: ").strip().lower()
        if answer in ("m", "motor"):
            args.role = "motor"
        elif answer in ("b", "ball"):
            args.role = "ball"
        elif answer in ("g", "goalie"):
            args.role = "goalie"
        elif answer in ("p", "practice"):
            args.practice = True
            practice_role = input("Practice as [b]all or [g]oalie? ").strip().lower()
            args.role = "goalie" if practice_role in ("g", "goalie") else "ball"
            robot_here = input("Is the robot connected? [y/N]: ").strip().lower()
            args.no_robot = robot_here not in ("y", "yes")
        elif answer in ("s", "sensor"):
            pa.terminate()
            try:
                test_sensor()
            except KeyboardInterrupt:
                pass
            return
        elif answer in ("c", "calibrate"):
            try:
                calibrate(pa, show_spectrogram=not args.no_spectrogram)
            except KeyboardInterrupt:
                pass
            finally:
                pa.terminate()
            return
        if args.role in ("ball", "goalie"):
            args.single_motor = input("Also run the Single Motor from the 2nd computer? [y/N]: "
                                      ).strip().lower() in ("y", "yes")

    if args.role == "motor":
        if args.low >= args.high:
            parser.error("--low must be below --high")
        try:
            whistle_single_motor(pa, args.broker, args.low, args.high,
                                 show_spectrogram=not args.no_spectrogram)
        except KeyboardInterrupt:
            print("\nQuitting.")
        finally:
            pa.terminate()
        return

    robot = None
    client = None
    spectrogram = None
    motor_link = None
    try:
        inbox = queue.Queue()
        robot = Robot(use_hardware=not args.no_robot, need_sensor=args.role == "ball",
                      role=args.role, inbox=inbox, need_single_motor=args.single_motor and not args.no_robot)
        if args.single_motor:
            motor_link = SingleMotorLink(args.broker)
        robot.calibrate_light()
        if args.practice:
            print(f"[practice] Not connecting to MQTT; nothing is sent on {MQTT_TOPIC}. Ctrl+C to quit.")
        else:
            client = connect_mqtt(args.broker, inbox)

        if not (args.skip_start or args.practice):
            wait_for_start(inbox)
        if not args.no_spectrogram:   # shares the simulator's window loop when there is one
            spectrogram = Spectrogram(robot.sim.root if robot.sim is not None else None)
        song = play(args.role, robot, client, inbox, pa, spectrogram, motor_link)
        robot.stop()
        if spectrogram is not None:
            spectrogram.show("VICTORY!" if song is VICTORY_SONG else "DEFEAT...", "playing the song")
        play_song(pa, song)
    except KeyboardInterrupt:
        print("\nQuitting.")
    finally:
        if spectrogram is not None:
            spectrogram.close()
        if motor_link is not None:
            motor_link.close()
        if robot is not None:
            robot.close()
        if client is not None:
            client.loop_stop()
            client.disconnect()
        pa.terminate()


if __name__ == "__main__":
    sys.exit(main())
