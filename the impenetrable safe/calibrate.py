"""
Find the black-tape square on the carpet and save where it is
(Safe-UnoQ/python/roi.json). Run it once the camera is on its stand, with
nothing in the square.

    python calibrate.py --list       # which camera number is the USB webcam?
    python calibrate.py              # s = save, m = click the 4 corners yourself, q = quit

The square is found as a dark outline that is darker than the carpet around
it. On a dark or busy carpet it may not be found: press m and click its
4 corners instead (you only do this once; the stand keeps the camera still).
"""

import argparse

import cv2
import numpy as np

import safe_config as cfg
import vision


def list_cameras():
    for i in range(6):
        cap, _ = vision.open_camera(i)
        if cap is None:
            continue
        frame = vision.read_frame(cap)
        cap.release()
        cv2.imshow(f"camera {i} (any key = next)", frame)
        cv2.waitKey(0)
        cv2.destroyAllWindows()
        print(f"camera {i} works")
    print("Put the webcam's number in CAMERA_INDEX in safe_config.py")


def main():
    ap = argparse.ArgumentParser(description="Find and save the taped square")
    ap.add_argument("--camera", type=int, default=cfg.CAMERA_INDEX)
    ap.add_argument("--list", action="store_true", help="show each camera so you can pick the webcam")
    args = ap.parse_args()
    if args.list:
        return list_cameras()

    cap, _ = vision.open_camera(args.camera)
    if cap is None:
        raise SystemExit(f"Camera {args.camera} didn't open. Try: python calibrate.py --list")

    clicks = []
    manual = False
    cv2.namedWindow("calibrate")
    cv2.setMouseCallback("calibrate", lambda ev, x, y, *_: clicks.append((x, y))
                         if ev == cv2.EVENT_LBUTTONDOWN and manual and len(clicks) < 4 else None)

    print("s = save   m = click corners yourself   q = quit")
    while True:
        frame = vision.read_frame(cap)
        if frame is None:
            continue
        corners = (vision.order_corners(clicks) if len(clicks) == 4 else None) if manual \
            else vision.find_square(frame)
        view = frame.copy()
        for x, y in clicks:
            cv2.circle(view, (x, y), 5, (0, 255, 255), -1)
        if corners is not None:
            cv2.polylines(view, [corners.astype(np.int32)], True, (0, 255, 0), 2)
            crop = vision.crop_square(frame, corners)
            view[10:10 + vision.CROP, -10 - vision.CROP:-10] = crop
        msg = "MANUAL: click 4 corners" if manual else ("found - press s" if corners is not None else "no taped square found")
        cv2.putText(view, msg, (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 255, 0), 2)
        cv2.imshow("calibrate", view)

        key = cv2.waitKey(1) & 0xFF
        if key == ord("q"):
            break
        if key == ord("m"):
            manual, clicks[:] = True, []
        if key == ord("s") and corners is not None:
            vision.save_roi(corners)
            print(f"Saved {vision.ROI_PATH}")
            break
    cap.release()
    cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
