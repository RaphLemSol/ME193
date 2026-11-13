"""
Record training pictures of hands in the taped square.

    python collect.py --person raphael

Keys:  0-5 = start recording that many fingers (press again or space to stop)
       x   = delete the last burst (if you showed the wrong number)
       q   = quit

While a burst records (10 pictures a second), MOVE: slide your hand around
the square, tilt it, use the other hand, and use different fingers for the
same number (2 = index+middle, but also thumb+index). 0 = a fist AND an
empty square. Record each number in a few short bursts rather than one long
one; train.py tests on whole bursts it didn't train on.
"""

import argparse
import time

import cv2
import numpy as np

import safe_config as cfg
import vision

EVERY_S = 0.1


def counts():
    return [len(list((cfg.DATA_DIR / str(c)).glob("*.png"))) for c in range(cfg.CLASSES)]


def main():
    ap = argparse.ArgumentParser(description="Record labeled finger pictures")
    ap.add_argument("--person", required=True, help="whose hand (used to test on people it never saw)")
    ap.add_argument("--camera", type=int, default=cfg.CAMERA_INDEX)
    args = ap.parse_args()
    person = args.person.lower().replace("_", "-")

    roi = vision.load_roi()
    if roi is None:
        raise SystemExit("Run calibrate.py first")
    cap, _ = vision.open_camera(args.camera)
    if cap is None:
        raise SystemExit(f"Camera {args.camera} didn't open. Try: python calibrate.py --list")

    label, session, saved, last_save = None, None, [], 0.0
    bursts = []                                  # files of each burst, for undo
    n = counts()
    while True:
        frame = vision.read_frame(cap)
        if frame is None:
            continue
        crop = vision.crop_square(frame, roi)
        now = time.monotonic()
        if label is not None and now - last_save >= EVERY_S:
            folder = cfg.DATA_DIR / str(label)
            folder.mkdir(parents=True, exist_ok=True)
            path = folder / f"{person}_{session}_{len(saved):03d}.png"
            cv2.imwrite(str(path), crop)
            saved.append(path)
            n[label] += 1
            last_save = now

        view = frame.copy()
        cv2.polylines(view, [roi.astype(np.int32)], True, (0, 0, 255) if label is not None else (0, 255, 0), 2)
        big = cv2.resize(crop, (256, 256), interpolation=cv2.INTER_NEAREST)
        view[10:266, -266:-10] = big
        status = f"RECORDING {label} fingers: {len(saved)}" if label is not None else "0-5 = record, x = undo, q = quit"
        cv2.putText(view, status, (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 255) if label is not None else (0, 255, 0), 2)
        cv2.putText(view, "  ".join(f"{c}:{n[c]}" for c in range(cfg.CLASSES)), (10, vision.FRAME_H - 15),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 2)
        cv2.imshow("collect", view)

        key = cv2.waitKey(1) & 0xFF
        if key == ord("q"):
            break
        pressed = key - ord("0") if ord("0") <= key <= ord("5") else None
        if label is not None and (key == ord(" ") or pressed is not None):
            print(f"  {label} fingers: {len(saved)} pictures")
            bursts.append(saved)
            label = None
        elif pressed is not None:
            label, session, saved = pressed, time.strftime("%m%d%H%M%S"), []
        elif key == ord("x") and label is None and bursts:
            gone = bursts.pop()
            for p in gone:
                p.unlink(missing_ok=True)
            n = counts()
            print(f"  deleted the last burst ({len(gone)} pictures)")

    cap.release()
    cv2.destroyAllWindows()
    print("Pictures per number:", dict(enumerate(counts())))


if __name__ == "__main__":
    main()
