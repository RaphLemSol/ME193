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

# Driving. x from the computer is -1 (left edge) .. 0 (middle) .. 1 (right edge).
CENTER_DEADBAND = 0.08  # |x| below this counts as "in the middle" -> stop
MIN_SPEED = 75          # PWM 0-255; below this the DC motor may not turn
MAX_SPEED = 130         # PWM 0-255; lower = slower
DIRECTION = 1           # set to -1 if the car drives away from the middle

# Steering. y from the computer is -1 (top) .. 0 (middle) .. 1 (bottom).
# While driving, one wheel speeds up and the other slows down to curve the
# minifig back toward the middle line.
STEER_GAIN = 60         # PWM difference between wheels at |y| = 1; 0 = no steering
STEER_DIRECTION = 1     # set to -1 if it curves away from the middle line
TIMEOUT = 0.5          # stop if no minifig message for this many seconds

latest = {"data": None, "time": 0.0}


def on_connect(client, userdata, flags, reason_code, properties):
    client.subscribe(TOPIC)
    print(f"Connected to {BROKER}, listening on '{TOPIC}'")


def on_message(client, userdata, msg):
    try:
        latest["data"] = json.loads(msg.payload.decode())
        latest["time"] = time.time()
    except ValueError:
        print(f"Ignoring non-JSON message: {msg.payload!r}")


def speed_for(x):
    """Faster when the minifig is far from the middle, 0 when it is there."""
    if abs(x) < CENTER_DEADBAND:
        return 0
    speed = MIN_SPEED + (MAX_SPEED - MIN_SPEED) * min(abs(x), 1.0)
    return int(-DIRECTION * speed) if x > 0 else int(DIRECTION * speed)


def wheel_speeds(x, y):
    """Return (motor1, motor2) speeds: drive toward the middle, steer by y."""
    speed = speed_for(x)
    if speed == 0:
        return 0, 0
    # Steering flips with driving direction, like reversing a car.
    turn = STEER_DIRECTION * STEER_GAIN * max(-1.0, min(y, 1.0))
    turn = turn if speed > 0 else -turn
    return int(speed + turn), int(speed - turn)


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
    data = latest["data"]
    stale = time.time() - latest["time"] > TIMEOUT
    if data is None or stale or not data.get("found", True):
        Bridge.call("set_motors", 0, 0)
        Bridge.call("show_dot", -1, -1)  # clear the display
    else:
        x, y = data["x"], data["y"]
        col, row = to_matrix(x, y)
        m1, m2 = wheel_speeds(x, y)
        Bridge.call("show_dot", col, row)
        Bridge.call("set_motors", m1, m2)
        print(f"x={x:.2f} y={y:.2f} -> LED ({col}, {row}), motors {m1}, {m2}")
    time.sleep(0.05)


App.run(user_loop=loop)
