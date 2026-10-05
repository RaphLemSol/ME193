import json
import math
import time

import paho.mqtt.client as mqtt
from arduino.app_utils import *

# Must match BROKER and TOPIC in track_minifig.py on the computer.
BROKER = "test.mosquitto.org"
TOPIC = "ME193_Raphael_minifig"

# UnoQ LED matrix size.
MATRIX_COLS = 13
MATRIX_ROWS = 8

# Positions from the computer: x -1 (left edge) .. 1 (right edge),
# y -1 (top) .. 1 (bottom), (0, 0) = middle of the screen.
CENTER_RADIUS = 0.12    # stop when the minifig is this close to the middle
NEAR_RADIUS = 0.3       # ...or this close, once the car is level with the middle
RESUME_RADIUS = 0.3     # after stopping, stay stopped until it is this far away
MIN_SPEED = 75          # PWM 0-255; below this the DC motors may not turn
MAX_SPEED = 130         # PWM 0-255; lower = slower
FLIP_MARGIN = 0.1       # only reverse once the middle is clearly behind the car

# The car's heading on screen is learned from how the minifig moves while
# driving, so the car can be placed facing any direction. Until it has
# moved, it assumes driving forward moves the minifig this way on screen:
INITIAL_HEADING = (0.0, 1.0)  # forward = toward the computer = down on screen
LEARN_DISTANCE = 0.06   # how far the minifig must move to update the heading
SETTLE_TICKS = 5        # loop ticks (0.05 s each) to wait after changing direction
                        # before measuring, so coasting isn't mistaken for the heading
FORGET_AFTER = 1.0      # seconds without the minifig before re-learning the heading

# Steering: the outer wheel speeds up and the inner wheel slows down.
STEER_GAIN = 50         # PWM difference at a full turn; 0 = no steering
LEFT_MOTOR = 1          # which motor (1 or 2) is on the car's left side
STEER_DIRECTION = 1     # set to -1 if it turns away from the middle

TIMEOUT = 0.5           # stop if no minifig message for this many seconds

latest = {"data": None, "time": 0.0}
nav = {
    "heading": INITIAL_HEADING,  # screen direction the car moves when driving forward
    "learned": False,
    "sign": 0,                   # drive direction: 1 forward, -1 backward, 0 stopped
    "ticks": 0,                  # loop ticks since the direction last changed
    "anchor": None,              # position where the current measurement started
    "arrived": False,            # stopped at the middle; ignore small jitter
    "last_seen": 0.0,
}


def on_connect(client, userdata, flags, reason_code, properties):
    client.subscribe(TOPIC)
    print(f"Connected to {BROKER}, listening on '{TOPIC}'")


def on_message(client, userdata, msg):
    try:
        latest["data"] = json.loads(msg.payload.decode())
        latest["time"] = time.time()
    except ValueError:
        print(f"Ignoring non-JSON message: {msg.payload!r}")


def set_sign(sign):
    if sign != nav["sign"]:
        nav["sign"], nav["ticks"], nav["anchor"] = sign, 0, None


def learn_heading(x, y):
    """Learn which way driving forward moves the minifig on screen."""
    nav["ticks"] += 1
    if nav["sign"] == 0 or nav["ticks"] < SETTLE_TICKS:
        return
    if nav["anchor"] is None:
        nav["anchor"] = (x, y)
        return
    dx, dy = x - nav["anchor"][0], y - nav["anchor"][1]
    dist = math.hypot(dx, dy)
    if dist < LEARN_DISTANCE:
        return
    hx, hy = nav["sign"] * dx / dist, nav["sign"] * dy / dist
    if nav["learned"]:
        # Blend with the previous estimate to smooth out detection jitter.
        hx, hy = hx + nav["heading"][0], hy + nav["heading"][1]
        norm = math.hypot(hx, hy) or 1.0
        hx, hy = hx / norm, hy / norm
    nav["heading"] = (hx, hy)
    nav["learned"] = True
    nav["anchor"] = (x, y)


def control(x, y):
    """Return (motor1, motor2) to bring the minifig to the middle."""
    learn_heading(x, y)
    ex, ey = -x, -y  # direction from the minifig to the middle
    distance = math.hypot(ex, ey)
    hx, hy = nav["heading"]
    along = ex * hx + ey * hy  # how far ahead (+) or behind (-) the middle is

    if nav["arrived"]:
        if distance < RESUME_RADIUS:
            return 0, 0
        nav["arrived"] = False  # the minifig was moved away; drive again
    # Stop at the middle, or when driving further can't get any closer to it.
    level = nav["learned"] and abs(along) < CENTER_RADIUS and distance < NEAR_RADIUS
    if distance < CENTER_RADIUS or level:
        nav["arrived"] = True
        set_sign(0)
        return 0, 0

    # Pick forward or backward. Until the heading is known, keep going one
    # way so it can be measured; after that, only reverse when clearly past.
    sign = nav["sign"]
    if sign == 0 or (nav["learned"] and along * sign < -FLIP_MARGIN):
        sign = 1 if along >= 0 else -1
    set_sign(sign)
    if nav["learned"]:
        speed = sign * (MIN_SPEED + (MAX_SPEED - MIN_SPEED) * min(distance, 1.0))
    else:
        speed = sign * MIN_SPEED  # creep while working out which way it faces

    # Steer only once the heading is known. `side` is how far the middle is
    # to the right (+) or left (-) of the way the car is moving; turning that
    # way works both driving forward and backward.
    turn = 0.0
    if nav["learned"]:
        side = sign * (hx * ey - hy * ex) / distance
        turn = STEER_DIRECTION * STEER_GAIN * side
        turn = max(-0.6 * abs(speed), min(turn, 0.6 * abs(speed)))
    left, right = int(speed + turn), int(speed - turn)
    return (left, right) if LEFT_MOTOR == 1 else (right, left)


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
        set_sign(0)
        if now - nav["last_seen"] > FORGET_AFTER:
            # The car may have been picked up and turned; learn the heading again.
            nav["heading"], nav["learned"] = INITIAL_HEADING, False
            nav["arrived"] = False
    else:
        nav["last_seen"] = now
        x, y = data["x"], data["y"]
        m1, m2 = control(x, y)
        col, row = to_matrix(x, y)
        Bridge.call("show_dot", col, row)
        Bridge.call("set_motors", m1, m2)
        hx, hy = nav["heading"]
        state = "arrived" if nav["arrived"] else ("learned" if nav["learned"] else "learning")
        print(f"x={x:.2f} y={y:.2f} heading=({hx:.2f}, {hy:.2f}) {state} "
              f"-> motors {m1}, {m2}")
    time.sleep(0.05)


App.run(user_loop=loop)
