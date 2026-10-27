"""
Live gait identification: runs both models on the wearable's stream.

    python live.py              # window + terminal; LED matrix shows model 2
    python live.py --led 1      # LED matrix shows model 1 instead
    python live.py --no-window  # terminal only

Every STEP_S seconds both models classify the last WINDOW_S seconds. The
answer shown averages each model's confidence over the last SMOOTH windows,
so one odd window doesn't make it flicker. Press q or Esc in the window (or Ctrl+C) to quit.
"""

import argparse
import json
import sys
import time
from collections import deque

import cv2
import joblib
import numpy as np

import gait_config as cfg
from gait_features import WINDOW, all_features, peak_accel
from gait_stream import IMUStream

SMOOTH = 3

COLORS = {"still": (200, 200, 200), "walk": (80, 200, 80), "run": (60, 80, 230),
          "bike": (230, 160, 40)}   # BGR


def draw(results, peak, axis, connected):
    img = np.full((360, 900, 3), 30, np.uint8)
    for i, (title, label, conf) in enumerate(results):
        x0 = 30 + i * 440
        cv2.putText(img, title, (x0, 50), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (220, 220, 220), 2)
        cv2.putText(img, label.upper(), (x0, 190), cv2.FONT_HERSHEY_SIMPLEX, 3.2,
                    COLORS.get(label, (255, 255, 255)), 7)
        cv2.putText(img, f"{conf:.0%} sure", (x0, 240), cv2.FONT_HERSHEY_SIMPLEX, 0.9,
                    (180, 180, 180), 2)
    cv2.putText(img, f"peak |{axis}| = {peak:.2f} g", (30, 300), cv2.FONT_HERSHEY_SIMPLEX,
                0.8, (180, 180, 180), 2)
    if not connected:
        cv2.putText(img, "NO DATA FROM WEARABLE", (30, 340), cv2.FONT_HERSHEY_SIMPLEX,
                    0.9, (60, 60, 255), 2)
    return img


def main():
    ap = argparse.ArgumentParser(description="Live gait identification")
    ap.add_argument("--led", type=int, choices=(1, 2), default=2,
                    help="which model's answer to show on the UNO Q's LED matrix")
    ap.add_argument("--no-window", action="store_true")
    args = ap.parse_args()

    if not cfg.MODEL_PATH.exists():
        sys.exit("No trained models yet. Record data with record.py, then run train.py.")
    saved = joblib.load(cfg.MODEL_PATH)
    model1, model2, axis = saved["model1"], saved["model2"], saved["axis"]
    print(f"Model 1: peak |{axis}| -> {saved['accuracy']['model1']:.0%} in testing")
    print(f"Model 2: all IMU outputs -> {saved['accuracy']['model2']:.0%} in testing")

    stream = IMUStream(keep_s=cfg.WINDOW_S + 1).start()
    print(f"Waiting for the wearable on '{cfg.IMU_TOPIC}'...")
    if not stream.wait_for_data():
        sys.exit("No IMU data. Is the Gait-UnoQ app running? "
                 "(python ../tools/deploy.py Gait-UnoQ)")
    print("Running. Ctrl+C to stop.\n")

    history = {1: deque(maxlen=SMOOTH), 2: deque(maxlen=SMOOTH)}
    sent = None
    try:
        while True:
            time.sleep(cfg.STEP_S)
            win = stream.latest(WINDOW)
            if win is None:
                continue
            peak = peak_accel(win, axis)
            p1 = model1.predict_proba([[peak]])[0]
            p2 = model2.predict_proba([all_features(win)[0]])[0]
            history[1].append(p1)
            history[2].append(p2)

            results = []
            for n, model in ((1, model1), (2, model2)):
                p = np.mean(history[n], axis=0)
                label, conf = model.classes_[np.argmax(p)], float(np.max(p))
                results.append((f"Model {n}: " + (f"peak {axis}" if n == 1 else "all IMU"),
                                label, conf))
            print(f"{time.strftime('%H:%M:%S')}  peak|{axis}|={peak:5.2f} g   "
                  f"model 1: {results[0][1]:6s} ({results[0][2]:.0%})   "
                  f"model 2: {results[1][1]:6s} ({results[1][2]:.0%})", flush=True)

            led = results[args.led - 1][1]
            if led != sent:
                stream.client.publish(cfg.ACTIVITY_TOPIC,
                                      json.dumps({"code": cfg.ACTIVITIES.index(led)}))
                sent = led

            if not args.no_window:
                cv2.imshow("Gait Identifier", draw(results, peak, axis, stream.connected()))
                if cv2.waitKey(1) & 0xFF in (ord("q"), 27):
                    break
    except KeyboardInterrupt:
        pass
    finally:
        stream.client.publish(cfg.ACTIVITY_TOPIC, json.dumps({"code": -1}))
        time.sleep(0.2)
        stream.stop()
        cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
