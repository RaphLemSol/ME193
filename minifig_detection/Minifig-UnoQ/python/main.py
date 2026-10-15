import json
import time

import paho.mqtt.client as mqtt
from arduino.app_utils import *

# Must match BROKER and TOPIC in track_minifig.py on the computer.
BROKER = "test.mosquitto.org"
TOPIC = "ME193_Raphael_minifig"

# UnoQ LED matrix size.
MATRIX_COLS = 13
MATRIX_ROWS = 8

# Distance: the minifig's box height (fraction of the frame, 0-1) grows as it
# gets closer to the laptop. Find TARGET_HEIGHT by trial and error: put the
# car where it should stop and read "h=" from the console.
TARGET_HEIGHT = 0.20
HEIGHT_TOLERANCE = 0.03  # close enough to TARGET_HEIGHT to count as "there"

# Side to side: x is -1 (left edge) .. 0 (middle) .. 1 (right edge).
CENTER_TOLERANCE = 0.1   # |x| below this counts as centered

# Driving. Forward = toward the laptop.
DRIVE_SPEED = 85         # PWM 0-255; lower = slower
STEER_GAIN = 35          # how much it turns toward the middle while driving
STEER_DAMPING = 60       # eases off the turn once it's already heading to the middle
BACKUP_TIME = 1.0        # seconds to back up before trying again
STEER_DIRECTION = 1      # set to -1 if it turns away from the middle
LEFT_MOTOR = 1           # which motor (1 or 2) is on the car's left side

TIMEOUT = 0.5            # stop if no minifig message for this many seconds

latest = {"data": None, "time": 0.0}
nav = {"mode": "drive", "backup_until": 0.0}  # mode: drive, backup, arrived
history = []  # recent (time, x) readings, used to predict where it's heading


def on_connect(client, userdata, flags, reason_code, properties):
    client.subscribe(TOPIC)
    print(f"Connected to {BROKER}, listening on '{TOPIC}'")


def on_message(client, userdata, msg):
    try:
        latest["data"] = json.loads(msg.payload.decode())
        latest["time"] = time.time()
    except ValueError:
        print(f"Ignoring non-JSON message: {msg.payload!r}")


def x_speed(x, now):
    """How fast the minifig is moving side to side (x units per second)."""
    history.append((now, x))
    while now - history[0][0] > 0.3:
        history.pop(0)
    t0, x0 = history[0]
    return (x - x0) / (now - t0) if now > t0 else 0.0


def motors(speed, x, vx):
    """Drive at `speed` (negative = backward) while steering by x.

    Forward, it turns toward the middle, easing off once x is already
    moving toward 0 so it doesn't over-turn. Backward, it goes straight to
    make room; the next forward run comes in at a better angle, so each
    back-up-and-forward cycle brings it closer to center.
    """
    x = max(-1.0, min(x, 1.0))
    turn = STEER_GAIN * x + STEER_DAMPING * vx if speed > 0 else 0.0
    turn = STEER_DIRECTION * max(-0.6 * abs(speed), min(turn, 0.6 * abs(speed)))
    left, right = int(speed + turn), int(speed - turn)
    return (left, right) if LEFT_MOTOR == 1 else (right, left)


def control(x, h, now):
    """Return (motor1, motor2) for the minifig at x with box height h."""
    far = h < TARGET_HEIGHT - HEIGHT_TOLERANCE
    close = h > TARGET_HEIGHT + HEIGHT_TOLERANCE
    centered = abs(x) < CENTER_TOLERANCE
    vx = x_speed(x, now)

    if nav["mode"] == "arrived":
        # Stay put unless the minifig is clearly moved away.
        if abs(x) < 2 * CENTER_TOLERANCE and abs(h - TARGET_HEIGHT) < 2 * HEIGHT_TOLERANCE:
            return 0, 0
        nav["mode"] = "drive"

    if nav["mode"] == "backup":
        if now < nav["backup_until"]:
            return motors(-DRIVE_SPEED, x, vx)
        nav["mode"] = "drive"

    if not far and not close and centered:
        nav["mode"] = "arrived"
        return 0, 0
    if close or (not far and not centered):
        # Too close, or at the right distance but off to the side: back up
        # to make room, then come in again at an angle.
        nav["mode"], nav["backup_until"] = "backup", now + BACKUP_TIME
        return motors(-DRIVE_SPEED, x, vx)
    return motors(DRIVE_SPEED, x, vx)  # far: drive toward the laptop


def to_matrix(x, y):
    """Scale x, y in [-1, 1] to an LED column and row."""
    col = round((x + 1) / 2 * (MATRIX_COLS - 1))
    row = round((y + 1) / 2 * (MATRIX_ROWS - 1))
    return min(max(col, 0), MATRIX_COLS - 1), min(max(row, 0), MATRIX_ROWS - 1)


client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
client.on_connect = on_connect
client.on_message = on_message
client.connect(BROKER, 1883)
client.loop_start()


def loop():
    now = time.time()
    data = latest["data"]
    found = (
        data is not None
        and now - latest["time"] <= TIMEOUT
        and data.get("found", True)
    )

    if not found:
        Bridge.call("set_motors", 0, 0)
        Bridge.call("show_dot", -1, -1)  # clear the display
        history.clear()
        if nav["mode"] != "arrived":
            nav["mode"] = "drive"
    else:
        x, y, h = data["x"], data["y"], data["height"]
        m1, m2 = control(x, h, now)
        col, row = to_matrix(x, y)
        Bridge.call("show_dot", col, row)
        Bridge.call("set_motors", m1, m2)
        print(f"x={x:.2f} h={h:.3f} {nav['mode']} -> motors {m1}, {m2}")
    time.sleep(0.05)


App.run(user_loop=loop)
