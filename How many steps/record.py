"""
Record labeled training data from the wearable.

    python record.py                     # guided: every activity, 2 rounds, Enter to start each
    python record.py --rounds 3 --seconds 45
    python record.py walk                # just one recording of one activity
    python record.py run --seconds 45

Each recording is saved as its own CSV in data/, named after the activity and
the time. train.py tests each model on recordings it didn't train on, so it
needs at least 2 recordings per activity.

After a walk or run it asks how many steps you took and how far you went
(Enter to skip either). Those go in data/labels.json and are what
train_steps.py tests the step counter and distance estimate against. To get
them: start standing still, count every footfall (both feet) out loud, and
stop and stand still before the time runs out (or press Ctrl+C). For the
distance, walk a course you measured (a track, tape-measured hallway, ...).
"""

import argparse
import json
import sys
import time

import numpy as np

import gait_config as cfg
from gait_stream import IMUStream

COUNTDOWN_S = 5   # time to get into position after pressing Enter

HOW = {
    "still": "stand still (shift your weight a little, like waiting in line)",
    "walk": "walk at a normal pace, counting your steps",
    "run": "run or jog, counting your steps",
    "bike": "ride a bike, or lie on your back and air-bike",
}


def record_one(stream, activity, seconds):
    for i in range(COUNTDOWN_S, 0, -1):
        print(f"  start {activity.upper()} in {i}...", flush=True)
        time.sleep(1)
    stream.take()   # throw away everything from the countdown
    print(f"  RECORDING {activity.upper()} for {seconds:.0f} s. Ctrl+C to stop early.")

    start = time.time()
    try:
        while time.time() - start < seconds:
            time.sleep(1)
            left = seconds - (time.time() - start)
            status = "" if stream.connected() else "   (no data! check the board)"
            print(f"\r  {max(left, 0):4.0f} s left{status}          ", end="", flush=True)
    except KeyboardInterrupt:
        pass
    print("\a")   # beep: done

    times, rows = stream.take()
    if len(rows) < cfg.WINDOW_S * cfg.SAMPLE_HZ:
        print(f"  Only {len(rows)} samples - too short to use, nothing saved.")
        return None

    gaps = np.diff(times)
    dropped = int(np.sum(np.clip(gaps // (1000 // cfg.SAMPLE_HZ) - 1, 0, None)))
    cfg.DATA_DIR.mkdir(exist_ok=True)
    path = cfg.DATA_DIR / f"{activity}_{time.strftime('%Y%m%d_%H%M%S')}.csv"
    np.savetxt(path, np.column_stack([times, rows]), delimiter=",", fmt="%.4f",
               header="t_ms," + ",".join(cfg.CHANNELS), comments="")
    rate = len(rows) / max((times[-1] - times[0]) / 1000, 1e-3)
    print(f"  Saved {len(rows)} samples ({rate:.0f} Hz, {dropped} dropped) to {path.name}")
    if activity in cfg.STEP_ACTIVITIES:
        ask_labels(path)
    return path


def ask_number(prompt, kind):
    while True:
        answer = input(prompt).strip()
        if not answer:
            return None
        try:
            return kind(answer)
        except ValueError:
            print("  Type a number, or just press Enter to skip.")


def ask_labels(path):
    """Save the step count and distance you enter for this recording."""
    steps = ask_number("  How many steps did you take (both feet)? Enter = didn't count: ", int)
    dist = ask_number("  How far did you go, in metres? Enter = don't know: ", float)
    if steps is None and dist is None:
        return
    labels = json.loads(cfg.LABELS_PATH.read_text()) if cfg.LABELS_PATH.exists() else {}
    labels[path.name] = {k: v for k, v in (("steps", steps), ("distance_m", dist)) if v is not None}
    cfg.LABELS_PATH.write_text(json.dumps(labels, indent=2))
    print(f"  Saved to {cfg.LABELS_PATH.name}")


def counts():
    have = {a: 0 for a in cfg.ACTIVITIES}
    for p in cfg.DATA_DIR.glob("*.csv"):
        a = p.stem.split("_")[0]
        if a in have:
            have[a] += 1
    return have


def main():
    ap = argparse.ArgumentParser(description="Record labeled IMU data")
    ap.add_argument("activity", nargs="?", choices=cfg.ACTIVITIES,
                    help="record just this one (default: guided session of all of them)")
    ap.add_argument("--seconds", type=float, default=60)
    ap.add_argument("--rounds", type=int, default=2, help="guided mode: recordings per activity")
    args = ap.parse_args()

    stream = IMUStream().start()
    print(f"Waiting for the wearable on '{cfg.IMU_TOPIC}'...")
    if not stream.wait_for_data():
        sys.exit("No IMU data. Is the Steps-UnoQ app running? "
                 "(python ../tools/deploy.py Steps-UnoQ)")
    print("Wearable connected.\n")

    try:
        if args.activity:
            record_one(stream, args.activity, args.seconds)
        else:
            plan = [(r, a) for r in range(1, args.rounds + 1) for a in cfg.ACTIVITIES]
            for i, (r, activity) in enumerate(plan, 1):
                print(f"[{i}/{len(plan)}] Round {r}: {HOW[activity]} for {args.seconds:.0f} s.")
                answer = input("  Press Enter to start (s = skip, q = quit): ").strip().lower()
                if answer == "q":
                    break
                if answer == "s":
                    continue
                record_one(stream, activity, args.seconds)
                print()
    except (KeyboardInterrupt, EOFError):
        print()
    finally:
        stream.stop()

    print("Recordings so far: " + ", ".join(f"{a} {n}" for a, n in counts().items()))


if __name__ == "__main__":
    main()
