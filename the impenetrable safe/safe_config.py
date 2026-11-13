"""
Settings for the laptop scripts. The image code (vision.py), the lock policy
and the numpy net live in Safe-UnoQ/python so the laptop and the UNO Q run
exactly the same code; importing this file makes them importable here.
"""

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
APP_PY = HERE / "Safe-UnoQ" / "python"
sys.path.insert(0, str(APP_PY))

# The USB webcam, NOT the laptop's built-in camera (that's usually 0).
# `python calibrate.py --list` shows which number is which.
CAMERA_INDEX = 1

DATA_DIR = HERE / "data"              # data/<0-5>/<person>_<session>_<n>.png
MODEL_DIR = HERE / "models"
MODEL_PATH = MODEL_DIR / "finger_net.pt"
NPZ_PATH = APP_PY / "finger_net.npz"  # the same weights, for the UNO Q
INTRUDER_DIR = HERE / "intruders"

CLASSES = 6                           # 0-5 fingers; 0 = fist or no hand

# Must match the topics in Safe-UnoQ/python/main.py.
MQTT_BROKER = "broker.hivemq.com"
PLAYER_NAME = "Raphael"
BUTTON_TOPIC = f"ME193_{PLAYER_NAME}_safe/button"
EVENT_TOPIC = f"ME193_{PLAYER_NAME}_safe/event"
PREVIEW_TOPIC = f"ME193_{PLAYER_NAME}_safe/preview"
