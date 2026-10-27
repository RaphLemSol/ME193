"""
Settings shared by record.py, train.py and live.py. Edit this file, not the scripts.
"""

from pathlib import Path

# --- MQTT (must match Gait-UnoQ/python/main.py) -----------------------------
MQTT_BROKER = "broker.hivemq.com"
PLAYER_NAME = "Raphael"
IMU_TOPIC = f"ME193_{PLAYER_NAME}_gait/imu"
ACTIVITY_TOPIC = f"ME193_{PLAYER_NAME}_gait/activity"

# --- MPU6050 (must match the ranges set in Gait-UnoQ/sketch/sketch.ino) -----
SAMPLE_HZ = 100
ACCEL_LSB_PER_G = 2048.0      # +-16 g
GYRO_LSB_PER_DPS = 16.4       # +-2000 deg/s
CHANNELS = ["ax", "ay", "az", "gx", "gy", "gz"]   # ax..az in g, gx..gz in deg/s

# --- Activities --------------------------------------------------------------
# The order sets the code sent to the UNO Q's LED matrix: S, W, R, B.
ACTIVITIES = ["still", "walk", "run", "bike"]

# --- Windows -----------------------------------------------------------------
# Each prediction looks at the last WINDOW_S seconds. 2 s holds at least one
# full stride even for slow walking.
WINDOW_S = 2.0
STEP_S = 0.5                  # make a new window (and prediction) this often

# --- Model 1: peak acceleration in one direction -----------------------------
# "auto" tries ax, ay and az and keeps whichever classifies best.
# Or force one, e.g. "az" for the axis that runs along your shin.
PEAK_AXIS = "auto"

# --- Files -------------------------------------------------------------------
HERE = Path(__file__).resolve().parent
DATA_DIR = HERE / "data"
MODEL_PATH = HERE / "models" / "gait_models.joblib"
