"""
Live step counter: the neural nets count your steps and estimate how far
you've walked, on the laptop screen and on the UNO Q's LED matrix.

    python live_steps.py              # window + terminal
    python live_steps.py --no-window  # terminal only

In the window: r = reset the count to 0, q or Esc = quit (or Ctrl+C).

Every NET_HOP_S seconds the nets look at the last 4 s. A stride is counted
COUNT_DELAY_S after it happens, so the count lags you by about half a second.
The +- next to the count is a 95% range: it combines how far off the counter
was in testing (train_steps.py) with how much the ensemble's nets disagree
right now.
"""

import argparse
import json
import math
import sys
import time

import cv2
import numpy as np

import gait_config as cfg
import step_net as sn
from gait_stream import IMUStream


def count_range(steps, counter, report):
    """Half-width of the 95% range of the step count."""
    rel = report.get("count", {}).get("rel_sd")
    rel = rel if rel is not None and math.isfinite(rel) else 0.05
    return 1.96 * math.sqrt((rel * steps) ** 2 + counter.spread() ** 2) + 1   # +1: which foot went first


def distance_range(model):
    """Distance uncertainty as a fraction."""
    if not model:
        return 0.20
    for key in ("tested_rel_sd", "tested_mape"):
        v = model.get(key)
        if v is not None and math.isfinite(v):
            return 1.96 * v if key == "tested_rel_sd" else 1.5 * v
    return 0.20


def cadence(counter, end):
    """Steps per minute over the last few strides, or None when stopped."""
    periods = [s["period"] for s in counter.strides[-4:] if s["period"]]
    if not periods or end - counter.events[-1] > 2.5 * sn.HZ:
        return None
    return 2 * 60 / float(np.median(periods))


def draw(counter, steps_pm, dist, dist_pm, cad, probs, model, connected):
    img = np.full((470, 900, 3), 30, np.uint8)
    cv2.putText(img, "STEPS", (30, 55), cv2.FONT_HERSHEY_SIMPLEX, 1.0, (200, 200, 200), 2)
    cv2.putText(img, f"{counter.steps}", (30, 190), cv2.FONT_HERSHEY_SIMPLEX, 4.5, (80, 220, 80), 9)
    cv2.putText(img, f"+-{steps_pm:.0f} (95%)", (40, 235), cv2.FONT_HERSHEY_SIMPLEX, 0.9,
                (180, 180, 180), 2)

    cv2.putText(img, "DISTANCE", (470, 55), cv2.FONT_HERSHEY_SIMPLEX, 1.0, (200, 200, 200), 2)
    cv2.putText(img, f"{dist:.1f} m", (470, 140), cv2.FONT_HERSHEY_SIMPLEX, 2.3, (230, 160, 40), 5)
    cv2.putText(img, f"+-{dist * dist_pm:.1f} m" + ("" if model else "  (not calibrated)"),
                (475, 180), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (180, 180, 180), 2)
    cv2.putText(img, f"cadence: {cad:.0f} steps/min" if cad else "cadence: -",
                (475, 230), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (180, 180, 180), 2)

    # The ensemble's output over the last 4 s: each peak above the line is a stride
    x0, y0, w, h = 30, 270, 840, 150
    cv2.rectangle(img, (x0, y0), (x0 + w, y0 + h), (70, 70, 70), 1)
    yt = int(y0 + h - sn.THRESHOLD * h)
    cv2.line(img, (x0, yt), (x0 + w, yt), (90, 90, 90), 1)
    if probs is not None:
        for p, color in [(m, (110, 110, 110)) for m in probs] + [(probs.mean(axis=0), (80, 220, 80))]:
            pts = np.column_stack([x0 + np.arange(len(p)) * w / (len(p) - 1), y0 + h - p * h])
            cv2.polylines(img, [pts.astype(np.int32)], False, color, 2 if color[1] == 220 else 1)
    cv2.putText(img, "net output, last 4 s (green = ensemble average, gray = each net)",
                (x0, y0 + h + 25), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (150, 150, 150), 1)
    if not connected:
        cv2.putText(img, "NO DATA FROM WEARABLE", (470, 260), cv2.FONT_HERSHEY_SIMPLEX,
                    0.8, (60, 60, 255), 2)
    return img


def main():
    ap = argparse.ArgumentParser(description="Live neural-net step counter")
    ap.add_argument("--no-window", action="store_true")
    args = ap.parse_args()

    if not cfg.STEP_MODEL_PATH.exists():
        sys.exit("No trained step counter yet. Record data with record.py, then run train_steps.py.")
    nets, saved = sn.load_nets()
    report, model = saved.get("report", {}), saved.get("distance_model")
    c = report.get("count")
    if c:
        print(f"Counter in testing: {c['mape']:.1%} average error vs {report['count_source']}")
    print("Distance: " + (f"'{model['kind']}' stride model fitted to {model['recordings']} walk(s)"
                          if model else f"rule of thumb from your height ({cfg.HEIGHT_M} m), not calibrated"))

    stream = IMUStream(keep_s=cfg.NET_WINDOW_S + 2).start()
    print(f"Waiting for the wearable on '{cfg.IMU_TOPIC}'...")
    if not stream.wait_for_data():
        sys.exit("No IMU data. Is the Steps-UnoQ app running? "
                 "(python ../tools/deploy.py Steps-UnoQ)")
    print("Running. r = reset, q = quit.\n")

    counter = sn.StepCounter(len(nets), since=stream.total)
    shown, probs = None, None
    dist = 0.0
    try:
        while True:
            time.sleep(cfg.NET_HOP_S)
            win, end = stream.latest_with_end(sn.T)
            if win is not None:
                probs = sn.predict(nets, [win])[:, 0]
                before = counter.steps
                counter.update(probs, win, end)
                if counter.steps != before:
                    dist = sn.distance_m(counter.strides, model)
            steps_pm = count_range(counter.steps, counter, report)
            dist_pm = distance_range(model)
            cad = cadence(counter, end)

            if counter.steps != shown:
                stream.client.publish(cfg.ACTIVITY_TOPIC, json.dumps({"steps": counter.steps}))
                shown = counter.steps
                print(f"{time.strftime('%H:%M:%S')}  {counter.steps:5d} steps (+-{steps_pm:.0f})  "
                      f"{dist:7.1f} m (+-{dist * dist_pm:.1f})  "
                      f"{f'{cad:.0f} steps/min' if cad else ''}", flush=True)

            if not args.no_window:
                cv2.imshow("How many steps?", draw(counter, steps_pm, dist, dist_pm, cad, probs,
                                                    model, stream.connected()))
                key = cv2.waitKey(1) & 0xFF
                if key in (ord("q"), 27):
                    break
                if key == ord("r"):
                    counter = sn.StepCounter(len(nets), since=stream.total)
                    dist = 0.0
                    print("Reset to 0")
    except KeyboardInterrupt:
        pass
    finally:
        print(f"\nFinal: {counter.steps} steps (+-{count_range(counter.steps, counter, report):.0f}), "
              f"{dist:.1f} m")
        stream.client.publish(cfg.ACTIVITY_TOPIC, json.dumps({"code": -1}))
        time.sleep(0.2)
        stream.stop()
        cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
