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

Usage:
    python theWhistlignWorldCup.py --role ball
    python theWhistlignWorldCup.py --role goalie
    python theWhistlignWorldCup.py --calibrate          # print your whistle pitch
    python theWhistlignWorldCup.py --role ball --no-robot --skip-start   # test without hardware
    python theWhistlignWorldCup.py --role ball --practice   # offline: no MQTT, starts immediately

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
WHISTLE_LOW_HZ = 600
WHISTLE_HIGH_HZ = 1700
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


def band_for(freq):
    if freq is None:
        return None
    command = BANDS[0][1]
    for lower, name in BANDS:
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


# ----------------------------------------------------------------------------
# Robot
# ----------------------------------------------------------------------------

class Robot:
    """Double Motor + Color Sensor, or a print-only stand-in with --no-robot."""

    def __init__(self, use_hardware, need_sensor):
        self.use_hardware = use_hardware
        self.motor = None
        self.sensor = None
        self.last_sent = None
        self.last_send_time = 0.0
        self.baseline = None
        self.over_count = 0
        if not use_hardware:
            print("[no-robot] Motor commands will only be printed.")
            return

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

    def drive(self, left, right, force=False):
        left, right = int(np.clip(left, -100, 100)), int(np.clip(right, -100, 100))
        now = time.monotonic()
        if not force and ((left, right) == self.last_sent or now - self.last_send_time < SEND_INTERVAL_S):
            return
        self.last_sent, self.last_send_time = (left, right), now
        if self.motor is None:
            print(f"[no-robot] tank L={left:+d} R={right:+d}")
        else:
            self.motor.movement_move_tank(left, right, blocking=False)

    def stop(self):
        self.last_sent = (0, 0)
        if self.motor is not None:
            self.motor.movement_stop(blocking=True)
        else:
            print("[no-robot] STOP")

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
        value = self.reflection()
        if value is None or self.baseline is None:
            return False
        if abs(value - self.baseline) >= CATCH_DELTA:
            self.over_count += 1
        else:
            self.over_count = 0
        return self.over_count >= CATCH_SAMPLES

    def close(self):
        for device in (self.motor, self.sensor):
            if device is None:
                continue
            try:
                if device is self.motor:
                    device.movement_stop(blocking=True)
                device.disconnect()
            except Exception as e:
                print(f"Warning while disconnecting: {e}")


# ----------------------------------------------------------------------------
# MQTT
# ----------------------------------------------------------------------------

def connect_mqtt(broker, inbox):
    client_id = f"ME193-whistle-{uuid.uuid4().hex[:8]}"
    try:  # paho-mqtt 2.x
        client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=client_id)
    except AttributeError:  # paho-mqtt 1.x
        client = mqtt.Client(client_id=client_id)

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


def calibrate(pa):
    """Print the pitch you're whistling, then suggest WHISTLE_LOW_HZ / WHISTLE_HIGH_HZ."""
    detector = PitchDetector()
    mic = open_mic(pa)
    print("Current bands: " + ", ".join(f"{name} >= {lower:.0f} Hz" for lower, name in BANDS))
    print("Whistle your LOWEST and HIGHEST comfortable notes, then press Ctrl+C.")
    seen = []
    try:
        while True:
            freq, rms = detector.pitch(read_chunk(mic))
            if freq is not None:
                seen.append(freq)
                print(f"{freq:7.0f} Hz  rms={rms:.3f}  -> {band_for(freq)}")
    finally:
        mic.close()
        if len(seen) >= 10:
            # percentiles ignore the odd glitchy frame at either end
            low, high = np.percentile(seen, [5, 95])
            print(f"\nYour range: about {low:.0f}-{high:.0f} Hz. Set these at the top of the file:")
            print(f"WHISTLE_LOW_HZ = {low:.0f}")
            print(f"WHISTLE_HIGH_HZ = {high:.0f}")


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


def play(role, robot, client, inbox, pa):
    """Whistle-drive until the match ends; returns the song to play."""
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
                    print("We caught the ball! Victory!")
                    return VICTORY_SONG
                if role == "goalie" and message == MSG_GOAL_SCORED:
                    print("The ball scored. Defeat...")
                    return DEATH_SONG

            # --- Ball: did the goalie get close to our light sensor? ---
            if role == "ball" and robot.goalie_is_close():
                robot.stop()
                print("Caught by the goalie!")
                publish(client, MSG_BALL_CAUGHT)
                return DEATH_SONG

            # --- Whistle -> command ---
            freq, _ = detector.pitch(read_chunk(mic))
            command, goal_claimed = commands.update(band_for(freq))

            if goal_claimed and role == "ball":
                robot.stop()
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
    finally:
        mic.close()


def main():
    parser = argparse.ArgumentParser(description="Whistle-controlled World Cup robot")
    parser.add_argument("--role", choices=["ball", "goalie"], help="your assigned role")
    parser.add_argument("--broker", default=MQTT_BROKER, help="MQTT broker host")
    parser.add_argument("--calibrate", action="store_true", help="just print whistle pitch")
    parser.add_argument("--no-robot", action="store_true", help="print motor commands instead of using BLE")
    parser.add_argument("--skip-start", action="store_true", help="don't wait for the MQTT 'start' message")
    parser.add_argument("--practice", action="store_true",
                        help=f"offline practice: no MQTT ({MQTT_TOPIC}), starts immediately")
    args = parser.parse_args()

    pa = pyaudio.PyAudio()
    if args.calibrate:
        try:
            calibrate(pa)
        except KeyboardInterrupt:
            pass
        finally:
            pa.terminate()
        return
    while args.role is None:  # e.g. launched from the IDE's Run button with no arguments
        answer = input("Role? [b]all / [g]oalie / [p]ractice (ball, offline) / [c]alibrate: ").strip().lower()
        if answer in ("b", "ball"):
            args.role = "ball"
        elif answer in ("g", "goalie"):
            args.role = "goalie"
        elif answer in ("p", "practice"):
            args.role, args.practice = "ball", True
        elif answer in ("c", "calibrate"):
            try:
                calibrate(pa)
            except KeyboardInterrupt:
                pass
            finally:
                pa.terminate()
            return

    robot = None
    client = None
    try:
        robot = Robot(use_hardware=not args.no_robot, need_sensor=args.role == "ball")
        robot.calibrate_light()
        inbox = queue.Queue()
        if args.practice:
            print(f"[practice] Not connecting to MQTT; nothing is sent on {MQTT_TOPIC}. Ctrl+C to quit.")
        else:
            client = connect_mqtt(args.broker, inbox)

        if not (args.skip_start or args.practice):
            wait_for_start(inbox)
        song = play(args.role, robot, client, inbox, pa)
        robot.stop()
        play_song(pa, song)
    except KeyboardInterrupt:
        print("\nQuitting.")
    finally:
        if robot is not None:
            robot.close()
        if client is not None:
            client.loop_stop()
            client.disconnect()
        pa.terminate()


if __name__ == "__main__":
    sys.exit(main())
