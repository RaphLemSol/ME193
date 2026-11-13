"""
See what the UNO Q's camera sees and what its net thinks, live on the laptop,
while the safe runs on the board (MODE = "board", PREVIEW = True in
Safe-UnoQ/python/main.py).

    python watch_board.py          # q = quit

Shows the square as the net sees it, a bar for each of 0-5 fingers, the
lock's state, and the digits entered so far (as dots). The board sends about
4 pictures a second over MQTT, so it lags a little behind the real safe.
"""

import base64
import json
import queue
import time

import cv2
import numpy as np
import paho.mqtt.client as mqtt

import safe_config as cfg

COLORS = {"idle": (200, 200, 200), "entering": (0, 255, 255), "open": (0, 255, 0), "lockout": (0, 0, 255)}


def draw(msg, event):
    view = np.zeros((400, 760, 3), np.uint8)
    crop = cv2.imdecode(np.frombuffer(base64.b64decode(msg["jpg"]), np.uint8), cv2.IMREAD_COLOR)
    view[10:394, 10:394] = cv2.resize(crop, (384, 384), interpolation=cv2.INTER_NEAREST)

    probs = msg["probs"]
    best = int(np.argmax(probs))
    cv2.putText(view, f"{best} fingers ({probs[best]:.0%})", (410, 45), cv2.FONT_HERSHEY_SIMPLEX, 1.0,
                (0, 255, 255), 2)
    for c, p in enumerate(probs):
        y = 75 + 32 * c
        cv2.putText(view, str(c), (410, y + 18), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)
        cv2.rectangle(view, (435, y), (435 + int(250 * p), y + 22), (0, 200, 255) if c == best else (120, 120, 120), -1)
        cv2.putText(view, f"{p:.0%}", (695, y + 18), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (255, 255, 255), 1)

    state = msg["state"]
    cv2.putText(view, state.upper(), (410, 290), cv2.FONT_HERSHEY_SIMPLEX, 0.9, COLORS.get(state, (255, 255, 255)), 2)
    if state == "entering":
        for k in range(3):
            cv2.circle(view, (425 + 40 * k, 320), 12, (0, 255, 255), -1 if k < msg["entered"] else 2)
        if msg["holding"] is not None:
            cv2.putText(view, f"holding {msg['holding']}", (550, 328), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 255), 2)
            cv2.rectangle(view, (550, 340), (550 + int(180 * msg["hold"]), 352), (0, 255, 255), -1)
    if event:
        cv2.putText(view, f"last: {event}", (410, 385), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (255, 255, 255), 1)
    return view


def main():
    previews, events = queue.Queue(), queue.Queue()

    def on_message(client, userdata, m):
        try:
            (previews if m.topic == cfg.PREVIEW_TOPIC else events).put(json.loads(m.payload.decode()))
        except ValueError:
            pass

    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
    client.on_connect = lambda c, *a: c.subscribe([(cfg.PREVIEW_TOPIC, 0), (cfg.EVENT_TOPIC, 0)])
    client.on_message = on_message
    client.connect(cfg.MQTT_BROKER, 1883)
    client.loop_start()
    print("Waiting for the board (Safe-UnoQ in board mode, PREVIEW = True)... q = quit")

    msg, event, last = None, "", time.monotonic()
    camera_ok = None                   # from the board's "camera" events
    waiting = np.zeros((400, 760, 3), np.uint8)
    while True:
        while not previews.empty():
            msg, last = previews.get(), time.monotonic()
        while not events.empty():
            e = events.get()
            if e.get("event") == "camera":
                camera_ok = bool(e.get("ok"))
            else:
                event = ", ".join(f"{k}={v}" for k, v in e.items())
        if msg and time.monotonic() - last < 3:
            cv2.imshow("UNO Q camera", draw(msg, event))
        else:
            view = waiting.copy()
            text = ("the board can't find the webcam - check the hub" if camera_ok is False
                    else "waiting for the board...")
            cv2.putText(view, text, (20, 200), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (255, 255, 255), 2)
            cv2.imshow("UNO Q camera", view)
        if cv2.waitKey(30) & 0xFF == ord("q"):
            break
    client.loop_stop()
    cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
