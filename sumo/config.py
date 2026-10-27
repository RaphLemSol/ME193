"""
All the knobs for the sumo robot in one place. Edit this file, not the
robot code, to match your hardware and tune how it fights.
"""

import legoeducation as le

# --- LEGO hardware (connection cards) --------------------------------------
# Drive base: Double Motor, left wheel on motor A, right wheel on motor B.
MOTOR_CARD_COLOR = le.LEGO_COLOR_RED    # Change to your card's color
MOTOR_CARD_SERIAL = '1131'              # Change to your card's 4-digit serial

# Light sensor: the LEGO Color Sensor, mounted pointing straight down at the
# floor, a few mm above it.
SENSOR_CARD_COLOR = le.LEGO_COLOR_RED   # Change to your card's color
SENSOR_CARD_SERIAL = '1131'             # Change to your card's 4-digit serial

# If "forward" drives the robot backward, flip this to -1.
FORWARD_SIGN = -1
# If the robot spins the wrong way when it should go straight, the wheels are
# on swapped ports; flip this to True.
SWAP_SIDES = False

# --- Tape detection ---------------------------------------------------------
# Color names (from colorSensor.detect_color()) that count as "on the tape".
# Run `python sumo.py --check` over the floor and over the tape to see what
# your sensor actually reports, then edit this.
TAPE_COLORS = {"Blue", "Azure"}

# --- MQTT -------------------------------------------------------------------
MQTT_BROKER = "test.mosquitto.org"
MQTT_PORT = 1883
MQTT_BASE = "ME193/Rogers/Fiona/sumo"
TOPIC_DISTANCE = MQTT_BASE + "/distance"   # UNO Q -> robot: cm, as a float
TOPIC_CMD = MQTT_BASE + "/cmd"             # teleop -> robot: "charge" / "out" / "reset"
TOPIC_STATE = MQTT_BASE + "/state"         # robot -> anyone: which branch is running

# --- Behavior tree tuning ---------------------------------------------------
LOOP_HZ = 20                  # how often the tree is ticked

OPPONENT_CM = 30.0            # opponent closer than this -> charge
DISTANCE_STALE_S = 1.0        # ignore distance readings older than this

CHARGE_SPEED = 100            # full speed forward
CHARGE_HOLD_S = 1.5           # one "charge" press drives forward this long

BACKUP_SPEED = 70
BACKUP_S = 0.6                # back away from the tape this long...
TURN_SPEED = 60
TURN_S = 0.5                  # ...then turn this long

SEARCH_SPEED = 25             # slow spin while looking for the opponent
