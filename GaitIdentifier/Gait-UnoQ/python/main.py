import functools
import json
import time

import paho.mqtt.client as mqtt
from arduino.app_utils import *

# Docker gives print() a pipe, which holds output in a buffer; send each line right away
print = functools.partial(print, flush=True)

# Must match MQTT_BROKER, IMU_TOPIC and ACTIVITY_TOPIC in GaitIdentifier/gait_config.py.
BROKER = "broker.hivemq.com"
PLAYER_NAME = "Raphael"
IMU_TOPIC = f"ME193_{PLAYER_NAME}_gait/imu"
ACTIVITY_TOPIC = f"ME193_{PLAYER_NAME}_gait/activity"

READ_INTERVAL = 0.1   # ask the sketch for its buffered samples 10x a second

activity = None       # latest code from the laptop (0-3), shown on the LED matrix


def on_connect(client, userdata, flags, reason_code, properties):
    client.subscribe(ACTIVITY_TOPIC)
    print(f"Connected to {BROKER}; sending IMU on '{IMU_TOPIC}'")


def on_message(client, userdata, msg):
    global activity
    try:
        activity = int(json.loads(msg.payload.decode())["code"])
    except (ValueError, KeyError, TypeError):
        print(f"Ignoring bad activity message: {msg.payload!r}")


client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
client.on_connect = on_connect
client.on_message = on_message
client.connect_async(BROKER, 1883)
client.loop_start()

shown = None
sent = 0
last_print = time.time()


def loop():
    global shown, sent, last_print
    text = Bridge.call("imu_batch")

    if text == "ERR":
        if time.time() - last_print > 1.0:
            print("MPU6050 not answering (retrying) - check its VCC/GND/SDA/SCL wires")
            last_print = time.time()
    elif text:
        samples = [[int(x) for x in row.split(",")] for row in text.split(";") if row]
        client.publish(IMU_TOPIC, json.dumps({"s": samples}, separators=(",", ":")))
        sent += len(samples)

    if activity != shown:
        Bridge.call("show_activity", activity)
        shown = activity

    if time.time() - last_print > 5.0:
        print(f"{sent / (time.time() - last_print):.0f} samples/s sent")
        sent = 0
        last_print = time.time()

    time.sleep(READ_INTERVAL)


Bridge.call("show_activity", -1)
App.run(user_loop=loop)
