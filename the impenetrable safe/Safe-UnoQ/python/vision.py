"""
Camera + image preparation, shared by the laptop scripts and the UNO Q app
so both feed the net exactly the same thing.

    camera (1280x720) --shrink--> frame (640x360) --crop the taped square-->
        128x128 color image --shrink + standardize--> (3, 64, 64) net input

The webcam is asked for 1280x720 because at 640x480 it crops the sides of
its view (zoomed in); 1280x720 is its widest view. The frame is shrunk to
640x360 right away so the rest is fast on the UNO Q.

The taped square's corners are found once (calibrate.py) and saved in roi.json
next to this file. The camera stand keeps it in the same place after that.
"""

import json
import sys
from pathlib import Path

import cv2
import numpy as np

HERE = Path(__file__).resolve().parent
ROI_PATH = HERE / "roi.json"

CAMERA_W, CAMERA_H = 1280, 720   # asked of the webcam (its widest view)
FRAME_W, FRAME_H = 640, 360      # what everything else uses, same on laptop and board
CROP = 128                       # saved training images are CROP x CROP
IMG = 64                         # the net sees IMG x IMG


def open_camera(index=None):
    """Open a USB camera at CAMERA_W x CAMERA_H. index=None tries 0-9 and
    takes the first one that gives a frame (the UNO Q has only the webcam)."""
    # On the UNO Q, OpenCV would pick GStreamer, which ignores the size
    # request; V4L2 (the Linux camera driver) honors it.
    backend = cv2.CAP_DSHOW if sys.platform == "win32" else cv2.CAP_V4L2
    for i in ([index] if index is not None else range(10)):
        cap = cv2.VideoCapture(i, backend)
        if not cap.isOpened():
            continue
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, CAMERA_W)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, CAMERA_H)
        # Compressed frames: uncompressed 1280x720 only comes at 5 fps over USB.
        # Has to be set after the size, or the camera ignores it.
        cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))
        cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        ok, frame = cap.read()
        if ok and frame is not None:
            return cap, i
        cap.release()
    return None, None


def read_frame(cap):
    """One frame, shrunk to FRAME_W x FRAME_H."""
    ok, frame = cap.read()
    if not ok or frame is None:
        return None
    if frame.shape[1] != FRAME_W or frame.shape[0] != FRAME_H:
        frame = cv2.resize(frame, (FRAME_W, FRAME_H), interpolation=cv2.INTER_AREA)
    return frame


def order_corners(pts):
    """4 points -> top-left, top-right, bottom-right, bottom-left."""
    pts = np.asarray(pts, np.float32).reshape(4, 2)
    s, d = pts.sum(axis=1), pts[:, 1] - pts[:, 0]
    return np.array([pts[np.argmin(s)], pts[np.argmin(d)], pts[np.argmax(s)], pts[np.argmax(d)]], np.float32)


def find_square(frame):
    """Outer corners (pixels) of the black-tape square on the carpet, or None.

    Tape = the darkest ~12% of the picture. Shiny tape reflects light in
    spots, which breaks the outline into pieces, so instead of following the
    outline, a hull is wrapped around all the big dark pieces and simplified
    to 4 corners. Check the green outline before saving; if it's wrong
    (a dark carpet, other dark things in view), click the corners by hand
    in calibrate.py."""
    gray = cv2.GaussianBlur(cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY), (5, 5), 0)
    tape = (gray < np.percentile(gray, 12) + 5).astype(np.uint8)
    tape = cv2.morphologyEx(tape, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))
    n, labels, stats, _ = cv2.connectedComponentsWithStats(tape)
    area = frame.shape[0] * frame.shape[1]
    pieces = [i for i in range(1, n) if stats[i, cv2.CC_STAT_AREA] > 0.004 * area]
    if not pieces:
        return None
    pts = np.column_stack(np.where(np.isin(labels, pieces)))[:, ::-1].astype(np.int32)
    hull = cv2.convexHull(pts)
    if cv2.contourArea(hull) < 0.1 * area:
        return None
    for eps in np.linspace(0.01, 0.1, 30):
        approx = cv2.approxPolyDP(hull, eps * cv2.arcLength(hull, True), True)
        if len(approx) == 4:
            return order_corners(approx)
    return None


def save_roi(corners):
    """Corners are saved as fractions of the frame, so a camera that gives a
    different resolution still lines up."""
    norm = (np.asarray(corners) / [FRAME_W, FRAME_H]).round(5).tolist()
    ROI_PATH.write_text(json.dumps({"corners": norm}, indent=2))


def load_roi():
    if not ROI_PATH.exists():
        return None
    norm = np.array(json.loads(ROI_PATH.read_text())["corners"], np.float32)
    return norm * [FRAME_W, FRAME_H]


def crop_square(frame, corners):
    """The inside of the taped square, warped flat to CROP x CROP."""
    dst = np.array([[0, 0], [CROP - 1, 0], [CROP - 1, CROP - 1], [0, CROP - 1]], np.float32)
    m = cv2.getPerspectiveTransform(np.asarray(corners, np.float32), dst)
    return cv2.warpPerspective(frame, m, (CROP, CROP), flags=cv2.INTER_AREA)


def to_input(crop):
    """CROP x CROP BGR image -> (3, IMG, IMG) float32 for the net. Each image
    is shifted/scaled to mean 0, std 1, so a brighter or darker room matters less."""
    small = cv2.resize(crop, (IMG, IMG), interpolation=cv2.INTER_AREA)
    x = cv2.cvtColor(small, cv2.COLOR_BGR2RGB).astype(np.float32) / 255.0
    x = (x - x.mean()) / (x.std() + 1e-6)
    return np.ascontiguousarray(x.transpose(2, 0, 1))
