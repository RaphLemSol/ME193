import base64
import functools
import json
import queue
import time
from pathlib import Path

import cv2
import numpy as np
import paho.mqtt.client as mqtt
from arduino.app_utils import *

import lock_policy as lp
import vision

# Docker gives print() a pipe, which holds output in a buffer; send each line right away
print = functools.partial(print, flush=True)

# "board":  the webcam is plugged into the UNO Q and the net runs here (final version)
# "laptop": the webcam is on the laptop; safe_laptop.py does the vision and sends
#           the lock's events here over MQTT. The board just runs the box.
MODE = "board"

# Must match MQTT_BROKER, BUTTON_TOPIC and EVENT_TOPIC in "the impenetrable safe"/safe_config.py.
BROKER = "broker.hivemq.com"
PLAYER_NAME = "Raphael"
BUTTON_TOPIC = f"ME193_{PLAYER_NAME}_safe/button"
EVENT_TOPIC = f"ME193_{PLAYER_NAME}_safe/event"
PREVIEW_TOPIC = f"ME193_{PLAYER_NAME}_safe/preview"

# Board mode: send the camera's view of the square and the net's guess to the
# laptop (watch_board.py) a few times a second. Turn this off for real use:
# anyone on the public broker who knows the topic could watch the code being entered.
PREVIEW = True
PREVIEW_EVERY_S = 0.25

SETTLE_S = 0.5            # after the button, skip frames from before you were ready
FLASH_S = 0.6             # how long an accepted digit shows on the matrix
RESULT_S = 2.0            # how long the X shows after a wrong code
INTRUDER_DIR = Path(__file__).resolve().parent / "intruders"

events_in = queue.Queue()   # laptop mode: events from safe_laptop.py


def on_connect(client, userdata, flags, reason_code, properties):
    if MODE == "laptop":
        client.subscribe(EVENT_TOPIC)
    print(f"Connected to {BROKER} ({MODE} mode)")


def on_message(client, userdata, msg):
    try:
        events_in.put(json.loads(msg.payload.decode()))
    except ValueError:
        print(f"Ignoring bad event: {msg.payload!r}")


client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
client.on_connect = on_connect
client.on_message = on_message
client.connect_async(BROKER, 1883)
client.loop_start()

# What the matrix goes back to after a digit flash or a wrong-code X: (time, function)
revert = None


def handle(event, now):
    """Turn one lock event into the status LED, the latch motor and the LED matrix."""
    global revert
    kind = event.get("event")
    print(f"event: {event}")
    if kind == "lights":                   # button pressed: blue LED, empty boxes on the matrix
        Bridge.call("set_status", 3)
        Bridge.call("show_entry", 0, -1)
        revert = None
    elif kind == "digit":
        entered = int(event["slot"]) + 1
        Bridge.call("show_entry", entered, int(event["n"]))
        revert = (now + FLASH_S, lambda: Bridge.call("show_entry", entered, -1))
    elif kind == "open":
        Bridge.call("set_status", 1)
        Bridge.call("set_latch", 1)
        Bridge.call("show_icon", 1)
        revert = None
    elif kind == "wrong":
        Bridge.call("set_status", 2)
        Bridge.call("show_icon", 2)
        revert = (now + RESULT_S, show_locked)
    elif kind == "lockout":
        Bridge.call("set_status", 2)
        Bridge.call("show_icon", 3)
        revert = None
    elif kind == "locked":
        show_locked()
        revert = None


def show_locked():
    Bridge.call("set_status", 0)
    Bridge.call("set_latch", 0)
    Bridge.call("show_icon", 0)


def save_intruder(crops, frame):
    """A wrong code: keep what the camera saw for each digit, and the whole view."""
    INTRUDER_DIR.mkdir(exist_ok=True)
    stamp = time.strftime("%Y%m%d_%H%M%S")
    if crops:
        cv2.imwrite(str(INTRUDER_DIR / f"{stamp}_digits.jpg"), np.hstack(crops))
    if frame is not None:
        cv2.imwrite(str(INTRUDER_DIR / f"{stamp}_view.jpg"), frame)
    print(f"Wrong code: saved {INTRUDER_DIR}/{stamp}_*.jpg")


# --- Board mode setup --------------------------------------------------------------

if MODE == "board":
    from numpy_net import NumpyFingerNet

    lock = lp.SafeLock()
    net = NumpyFingerNet()
    roi = vision.load_roi()
    if roi is None:
        raise SystemExit("No roi.json: run calibrate.py on the laptop, then deploy again")


def wait_for_camera():
    """Keep looking until the webcam shows up (a loose hub can drop it)."""
    while True:
        cap, index = vision.open_camera()
        if cap is not None:
            raw = cap.read()[1]
            print(f"Camera {index} open at {raw.shape[1]}x{raw.shape[0]} "
                  f"(should be {vision.CAMERA_W}x{vision.CAMERA_H}), net loaded, waiting for the button")
            client.publish(EVENT_TOPIC, json.dumps({"event": "camera", "ok": 1}))
            return cap
        print("No USB camera found - is the webcam plugged into the UNO Q's hub? Trying again in 3 s")
        client.publish(EVENT_TOPIC, json.dumps({"event": "camera", "ok": 0}))
        time.sleep(3)


if MODE == "board":
    cap = wait_for_camera()

frame = None
last_crop = [None]
crops = []                # the crop at each accepted digit, for intruder snapshots
settle_until = 0.0
stats = {"frames": 0, "net_s": 0.0, "since": time.monotonic()}
last_preview = [0.0]
missed = [0]              # frames in a row the camera didn't give


def send_preview(crop, probs, now):
    """What the camera sees and what the net thinks, for watch_board.py on the laptop."""
    ok, jpg = cv2.imencode(".jpg", crop, [cv2.IMWRITE_JPEG_QUALITY, 70])
    if not ok:
        return
    digit, hold = lock.hold_progress(now)
    client.publish(PREVIEW_TOPIC, json.dumps({
        "jpg": base64.b64encode(jpg.tobytes()).decode(),
        "probs": [round(float(p), 3) for p in probs],
        "state": lock.state, "entered": len(lock.entered), "holding": digit, "hold": round(hold, 2)}))


def board_step(now):
    """One pass of the whole lock on the UNO Q: button, camera, net, policy."""
    global frame, settle_until, cap
    if missed[0] >= 20:                  # the webcam dropped out: wait for it to come back
        print("Camera stopped giving pictures; looking for it again")
        cap.release()
        cap = wait_for_camera()
        missed[0] = 0
    events = []
    if Bridge.call("button"):
        events += lock.press(now)
        if lock.state == lp.ENTERING:
            crops.clear()
            settle_until = now + SETTLE_S
            stats.update(frames=0, net_s=0.0, since=now)
            for _ in range(4):           # throw away frames from before the press
                cap.grab()

    probs = None
    entering = lock.state == lp.ENTERING
    preview_due = PREVIEW and now - last_preview[0] >= PREVIEW_EVERY_S
    if entering or preview_due:
        frame = vision.read_frame(cap)
        missed[0] = 0 if frame is not None else missed[0] + 1
        if frame is not None and (not entering or now >= settle_until):
            crop = vision.crop_square(frame, roi)
            t0 = time.monotonic()
            probs = net.predict(vision.to_input(crop))
            if entering:
                stats["net_s"] += time.monotonic() - t0
                stats["frames"] += 1
            last_crop[0] = crop
    events += lock.update(probs if entering else None, now)

    if preview_due and probs is not None:
        last_preview[0] = now
        send_preview(last_crop[0], probs, now)

    for e in events:
        if e["event"] == "digit":
            crops.append(last_crop[0])
        if e["event"] == "wrong":
            save_intruder(crops, frame)
        handle(e, now)
        client.publish(EVENT_TOPIC, json.dumps(e))     # anyone can watch the safe

    if stats["frames"] and now - stats["since"] > 5.0:
        fps = stats["frames"] / (now - stats["since"])
        print(f"{fps:.1f} frames/s, net {1000 * stats['net_s'] / stats['frames']:.0f} ms per frame")
        stats.update(frames=0, net_s=0.0, since=now)
    if lock.state != lp.ENTERING:
        time.sleep(0.05)


def laptop_step(now):
    """The laptop decides; here we only pass on button presses and show results."""
    if Bridge.call("button"):
        client.publish(BUTTON_TOPIC, json.dumps({"pressed": 1}))
        print("button -> laptop")
    while not events_in.empty():
        handle(events_in.get(), now)
    time.sleep(0.03)


def loop():
    global revert
    now = time.monotonic()
    if revert and now >= revert[0]:
        revert[1]()
        revert = None
    if MODE == "board":
        board_step(now)
    else:
        laptop_step(now)


show_locked()
App.run(user_loop=loop)
