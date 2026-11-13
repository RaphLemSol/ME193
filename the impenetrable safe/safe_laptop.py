"""
The whole safe, run from the laptop with the USB webcam (step 1 of the
assignment). The box's button, LEDs and latch are on the UNO Q, running
Safe-UnoQ with MODE = "laptop"; they talk over MQTT.

    python safe_laptop.py               # with the box
    python safe_laptop.py --no-board    # no box: the space bar is the button
    python safe_laptop.py --numpy       # use the UNO Q's numpy net instead of PyTorch

Keys: space = the button, q = quit. The window always shows what the net
thinks (a live finger counter), but only counts digits after the button.
"""

import argparse
import json
import queue
import time

import cv2
import numpy as np

import safe_config as cfg
import lock_policy as lp
import vision

SETTLE_S = 0.5           # same as the UNO Q: skip frames from before you were ready


def save_intruder(crops, frame):
    cfg.INTRUDER_DIR.mkdir(exist_ok=True)
    stamp = time.strftime("%Y%m%d_%H%M%S")
    if crops:
        cv2.imwrite(str(cfg.INTRUDER_DIR / f"{stamp}_digits.jpg"), np.hstack(crops))
    cv2.imwrite(str(cfg.INTRUDER_DIR / f"{stamp}_view.jpg"), frame)
    print(f"  intruder snapshot: {cfg.INTRUDER_DIR / stamp}_*.jpg")


def draw(frame, crop, roi, probs, lock, now, message, fps, net_ms):
    view = frame.copy()
    cv2.polylines(view, [roi.astype(np.int32)], True, (0, 255, 0), 2)
    view[10:266, -266:-10] = cv2.resize(crop, (256, 256), interpolation=cv2.INTER_NEAREST)

    # What the net thinks right now
    for c, p in enumerate(probs):
        y = 60 + 28 * c
        cv2.putText(view, str(c), (10, y + 16), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 2)
        cv2.rectangle(view, (30, y), (30 + int(200 * p), y + 20), (0, 200, 255), -1)
        cv2.putText(view, f"{p:.0%}", (240, y + 16), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)

    # The lock: state, digits entered (as dots), and how long the current digit has been held
    colors = {lp.IDLE: (200, 200, 200), lp.ENTERING: (0, 255, 255), lp.OPEN: (0, 255, 0), lp.LOCKOUT: (0, 0, 255)}
    cv2.putText(view, f"{lock.state.upper()}  {message}", (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.8,
                colors[lock.state], 2)
    if lock.state == lp.ENTERING:
        for k in range(lp.CODE_LENGTH):
            center = (40 + 40 * k, 260)
            cv2.circle(view, center, 12, (0, 255, 255), -1 if k < len(lock.entered) else 2)
        digit, frac = lock.hold_progress(now)
        if digit is not None:
            cv2.putText(view, f"holding {digit}", (10, 310), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 255), 2)
            cv2.rectangle(view, (10, 320), (10 + int(200 * frac), 335), (0, 255, 255), -1)
    cv2.putText(view, f"{fps:.0f} fps, net {net_ms:.1f} ms", (10, vision.FRAME_H - 15),
                cv2.FONT_HERSHEY_SIMPLEX, 0.55, (255, 255, 255), 1)
    return view


def main():
    ap = argparse.ArgumentParser(description="Run the finger-code safe from the laptop")
    ap.add_argument("--camera", type=int, default=cfg.CAMERA_INDEX)
    ap.add_argument("--no-board", action="store_true", help="no box: the space bar is the button")
    ap.add_argument("--numpy", action="store_true", help="use the numpy net the UNO Q runs")
    args = ap.parse_args()

    if args.numpy:
        from numpy_net import NumpyFingerNet
        np_net = NumpyFingerNet(cfg.NPZ_PATH)
        predict = lambda crop: np_net.predict(vision.to_input(crop))
    else:
        import finger_net
        net, _ = finger_net.load()
        predict = lambda crop: finger_net.predict(net, crop)

    lock = lp.SafeLock()
    roi = vision.load_roi()
    if roi is None:
        raise SystemExit("Run calibrate.py first")
    cap, _ = vision.open_camera(args.camera)
    if cap is None:
        raise SystemExit(f"Camera {args.camera} didn't open. Try: python calibrate.py --list")

    presses = queue.Queue()
    client = None
    if not args.no_board:
        import paho.mqtt.client as mqtt
        client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
        client.on_connect = lambda c, *a: c.subscribe(cfg.BUTTON_TOPIC)
        client.on_message = lambda c, u, msg: presses.put(1)
        client.connect(cfg.MQTT_BROKER, 1883)
        client.loop_start()
        client.publish(cfg.EVENT_TOPIC, json.dumps({"event": "locked"}))
    print("Press the box's button (or space) to enter the code. q = quit.")

    message, crops, settle_until = "press the button", [], 0.0
    fps, net_ms, last = 0.0, 0.0, time.monotonic()
    while True:
        frame = vision.read_frame(cap)
        if frame is None:
            continue
        now = time.monotonic()
        crop = vision.crop_square(frame, roi)
        t0 = time.monotonic()
        probs = predict(crop)
        net_ms = 0.9 * net_ms + 0.1 * 1000 * (time.monotonic() - t0)
        fps = 0.9 * fps + 0.1 / max(now - last, 1e-3)
        last = now

        key = cv2.waitKey(1) & 0xFF
        if key == ord("q"):
            break
        events = []
        pressed = key == ord(" ")
        while not presses.empty():
            presses.get()
            pressed = True
        if pressed:
            events += lock.press(now)
            if lock.state == lp.ENTERING:
                crops, settle_until = [], now + SETTLE_S
        events += lock.update(probs if now >= settle_until else None, now)

        for e in events:
            print(f"  {e}")
            if client:
                client.publish(cfg.EVENT_TOPIC, json.dumps(e))
            kind = e["event"]
            if kind == "lights":
                message = "show 3 numbers"
            elif kind == "digit":
                crops.append(crop)
                message = f"got digit {e['slot'] + 1}"
            elif kind == "open":
                message = "UNLOCKED"
            elif kind == "wrong":
                message = f"wrong code ({e['tries_left']} tries left)"
                save_intruder(crops, frame)
            elif kind == "lockout":
                message = f"locked out for {e['seconds']} s"
            elif kind == "timeout":
                message = "too slow - press again"

        cv2.imshow("impenetrable safe", draw(frame, crop, roi, probs, lock, now, message, fps, net_ms))

    if client:
        client.publish(cfg.EVENT_TOPIC, json.dumps({"event": "locked"}))
        time.sleep(0.3)
    cap.release()
    cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
