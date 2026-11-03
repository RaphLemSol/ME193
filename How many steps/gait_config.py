"""
Settings shared by record.py, train.py and live.py. Edit this file, not the scripts.
"""

from pathlib import Path

# --- MQTT (must match Steps-UnoQ/python/main.py) ----------------------------
MQTT_BROKER = "broker.hivemq.com"
PLAYER_NAME = "Raphael"
IMU_TOPIC = f"ME193_{PLAYER_NAME}_steps/imu"
ACTIVITY_TOPIC = f"ME193_{PLAYER_NAME}_steps/display"   # what the LED matrix shows

# --- MPU6050 (must match the ranges set in Steps-UnoQ/sketch/sketch.ino) ----
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

# --- Step counter (step_net.py, train_steps.py, live_steps.py) ---------------
# The sensor is on ONE ankle, so the net finds that leg's strides (one swing
# of the strapped leg). Every stride is 2 steps: one per foot.
STEP_ACTIVITIES = ["walk", "run"]   # recordings of anything else have 0 steps
NET_WINDOW_S = 4.0            # the net looks at the last 4 s (2+ walking strides)
NET_HOP_S = 0.25              # live: run the net this often
COUNT_DELAY_S = 0.6           # a stride is counted once it's this old, so the
                              # net has seen what comes after it too
MIN_STRIDE_S = 0.4            # two strides of the same leg can't be closer than this
ENSEMBLE = 5                  # nets trained with different seeds; their spread
                              # shows how sure the counter is

# --- Distance (train_steps.py fits it from recordings of a known distance) ---
# Used only until you have recordings with a measured distance.
HEIGHT_M = 1.75

# --- Files -------------------------------------------------------------------
HERE = Path(__file__).resolve().parent
DATA_DIR = HERE / "data"
LABELS_PATH = DATA_DIR / "labels.json"     # your step counts and distances, per recording
MODEL_PATH = HERE / "models" / "gait_models.joblib"
STEP_MODEL_PATH = HERE / "models" / "step_net.pt"
