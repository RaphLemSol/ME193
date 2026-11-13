import functools
import glob
import time

import cv2
import numpy as np
from arduino.app_utils import *

# Docker gives print() a pipe, which holds output in a buffer; send each line right away
print = functools.partial(print, flush=True)

CAMERA_EVERY_S = 5.0      # how often to re-check the camera
ASCII = " .:-=+*#%@"      # dark -> bright, for the text picture in the log


def open_camera():
    """Same search as the safe (vision.open_camera): first /dev/video that gives a frame."""
    devices = sorted(glob.glob("/dev/video*"))
    print(f"camera devices: {devices or 'NONE - is the webcam plugged into the hub?'}")
    for i in range(10):
        cap = cv2.VideoCapture(i)
        if not cap.isOpened():
            continue
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1280)      # same as the safe (vision.py)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 720)
        cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))   # after the size
        ok, frame = cap.read()
        if ok and frame is not None:
            print(f"camera {i} OPEN: {frame.shape[1]}x{frame.shape[0]}")
            return cap
        cap.release()
    print("camera: could not open any (if devices are listed above, the app can't access them)")
    return None


def text_picture(frame, cols=48, rows=16):
    """The camera view as characters, so you can see it in the log. The
    contrast is stretched so a dim view still shows shapes."""
    gray = cv2.resize(cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY), (cols, rows), interpolation=cv2.INTER_AREA)
    gray = cv2.normalize(gray, None, 0, 255, cv2.NORM_MINMAX)
    return "\n".join("    |" + "".join(ASCII[int(v) * len(ASCII) // 256] for v in row) + "|" for row in gray)


cap = open_camera()
last_presses = 0
last_held = 0
last_camera = 0.0


def loop():
    global cap, last_presses, last_held, last_camera
    presses = Bridge.call("presses")
    held = Bridge.call("held")
    if presses != last_presses:
        print(f"BUTTON pressed (total {presses})")
        last_presses = presses
    if held != last_held:
        print("  button down" if held else "  button up")
        last_held = held

    now = time.monotonic()
    if now - last_camera > CAMERA_EVERY_S:
        last_camera = now
        if cap is None:
            cap = open_camera()
        else:
            t0 = time.monotonic()
            frames = [cap.read()[1] for _ in range(10)]
            frames = [f for f in frames if f is not None]
            if not frames:
                print("camera stopped giving frames; reopening")
                cap.release()
                cap = None
            else:
                fps = len(frames) / (time.monotonic() - t0)
                frame = frames[-1]
                print(f"camera OK: {fps:.1f} fps, brightness {frame.mean():.0f}/255")
                print(text_picture(frame))
    time.sleep(0.02)


print("Press the button: the matrix lights while held, then shows the count; the RGB LED changes color.")
App.run(user_loop=loop)
