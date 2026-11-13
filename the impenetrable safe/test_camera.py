"""
Check the USB webcam on the laptop before collecting data.

    python test_camera.py              # the camera in safe_config.py (CAMERA_INDEX)
    python test_camera.py --camera 2
    python test_camera.py --size 1280x720   # ask the webcam for this size instead (wider view?)

Shows the live view with the frame rate, resolution and brightness, and
outlines the taped square in green if it can find it. Keys: s = save a
snapshot (camera_test.png), q = quit.

Things to check:
  - It's the USB webcam, not the laptop's camera (try other --camera numbers)
  - ~15-30 fps (a dark room makes the webcam slow down to expose longer)
  - The whole taped square is in view, with some margin, and gets outlined
  - A hand in the square is sharp, not blurry
"""

import argparse
import time

import cv2
import numpy as np

import safe_config as cfg
import vision


def main():
    ap = argparse.ArgumentParser(description="Live webcam check")
    ap.add_argument("--camera", type=int, default=cfg.CAMERA_INDEX)
    ap.add_argument("--size", help="e.g. 1280x720: show the webcam's own picture at this size, to "
                                   "compare with what the safe uses")
    args = ap.parse_args()

    cap, _ = vision.open_camera(args.camera)
    if cap is None:
        raise SystemExit(f"Camera {args.camera} didn't open. Try: python calibrate.py --list")
    if args.size:
        w, h = (int(v) for v in args.size.lower().split("x"))
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, w)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, h)
    ok, raw = cap.read()
    print(f"camera {args.camera} open, it gives {raw.shape[1]}x{raw.shape[0]} "
          f"(the safe uses {vision.FRAME_W}x{vision.FRAME_H})")

    fps, last = 0.0, time.monotonic()
    while True:
        if args.size:                       # the camera's own picture, not resized
            ok, frame = cap.read()
            frame = frame if ok else None
        else:
            frame = vision.read_frame(cap)
        if frame is None:
            print("no frame")
            continue
        now = time.monotonic()
        fps = 0.9 * fps + 0.1 / max(now - last, 1e-3)
        last = now

        view = frame.copy()
        square = vision.find_square(frame)
        if square is not None:
            cv2.polylines(view, [square.astype(np.int32)], True, (0, 255, 0), 2)
            view[10:10 + vision.CROP, -10 - vision.CROP:-10] = vision.crop_square(frame, square)
        sharp = cv2.Laplacian(cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY), cv2.CV_64F).var()
        lines = [f"{fps:.0f} fps   brightness {frame.mean():.0f}/255   sharpness {sharp:.0f}",
                 "square: " + ("FOUND" if square is not None else "not found"),
                 "s = snapshot   q = quit"]
        for k, text in enumerate(lines):
            cv2.putText(view, text, (10, 30 + 28 * k), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 0), 2)
        cv2.imshow("camera test", view)

        key = cv2.waitKey(1) & 0xFF
        if key == ord("q"):
            break
        if key == ord("s"):
            cv2.imwrite(str(cfg.HERE / "camera_test.png"), frame)
            print(f"saved {cfg.HERE / 'camera_test.png'}")
    cap.release()
    cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
