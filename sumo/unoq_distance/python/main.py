"""
Runs on the UNO Q's Linux side. Asks the sketch for the HC-SR04 distance and
publishes it over MQTT for the sumo robot (sumo.py on the laptop).

Publishes the median of the last 3 readings (in cm, e.g. "23.4") to
ME193/Rogers/Fiona/sumo/distance about 20 times a second. "-1" means nothing
in range.
"""

import time
from collections import deque
from statistics import median

import paho.mqtt.client as mqtt
from arduino.app_utils import App, Bridge

# Keep these the same as sumo/config.py.
MQTT_BROKER = "test.mosquitto.org"
MQTT_PORT = 1883
TOPIC_DISTANCE = "ME193/Rogers/Fiona/sumo/distance"

PERIOD_S = 0.05

client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
client.connect_async(MQTT_BROKER, MQTT_PORT, keepalive=30)
client.loop_start()

recent = deque(maxlen=3)   # median of 3 throws out single bad echoes


def loop():
    try:
        d = float(Bridge.call("distance_cm"))
    except Exception as e:
        print(f"bridge: {e}")
        time.sleep(0.5)
        return
    recent.append(d)
    good = [x for x in recent if x > 0]
    value = median(good) if good else -1.0
    client.publish(TOPIC_DISTANCE, f"{value:.1f}")
    time.sleep(PERIOD_S)


App.run(user_loop=loop)
