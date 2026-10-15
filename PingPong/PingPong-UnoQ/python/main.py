import json
import threading
import time

import paho.mqtt.client as mqtt
from arduino.app_utils import *

# Must match MQTT_BROKER, PADDLE_TOPIC and FEEDBACK_TOPIC in PingPong/ping_pong.py.
BROKER = "broker.hivemq.com"
PLAYER_NAME = "Raphael"
PADDLE_TOPIC = f"ME193_{PLAYER_NAME}_paddle"
FEEDBACK_TOPIC = f"ME193_{PLAYER_NAME}_paddle/feedback"

SEND_INTERVAL = 1 / 30   # send IMU + light ~30x a second

# Motor "buzz" patterns: list of (motor speed -255..255, seconds).
# Both motors spin opposite ways so the paddle shakes instead of driving.
BUZZ = {
    "hit": [(200, 0.08)],
    "miss": [(160, 0.4)],
    "start": [(150, 0.1), (0, 0.1), (150, 0.1)],
    "gameover": [(180, 0.25), (0, 0.15), (180, 0.25), (0, 0.15), (180, 0.5)],
}

events = []                # feedback events waiting to be played
events_lock = threading.Lock()


def on_connect(client, userdata, flags, reason_code, properties):
    client.subscribe(FEEDBACK_TOPIC)
    print(f"Connected to {BROKER}; sending on '{PADDLE_TOPIC}', listening on '{FEEDBACK_TOPIC}'")


def on_message(client, userdata, msg):
    try:
        data = json.loads(msg.payload.decode())
        if not isinstance(data, dict):
            raise ValueError
        with events_lock:
            events.append(data)
    except ValueError:
        print(f"Ignoring bad feedback: {msg.payload!r}")


def play_events():
    """Buzz the motors and update the LED streak counter for each game event."""
    with events_lock:
        pending = events[:]
        events.clear()
    for data in pending:
        event = data.get("event")
        if event == "motor":
            # Test command from PingPong/test_parts.py: run each motor on its own
            m1, m2, seconds = int(data["m1"]), int(data["m2"]), float(data["seconds"])
            print(f"motor test: m1={m1} m2={m2} for {seconds:.1f} s")
            Bridge.call("set_motors", m1, m2)
            time.sleep(min(seconds, 3.0))
            Bridge.call("set_motors", 0, 0)
            continue
        streak = int(data.get("streak", 0))
        print(f"{event} (streak {streak})")
        Bridge.call("show_number", streak)
        for speed, seconds in BUZZ.get(event, []):
            Bridge.call("set_motors", speed, -speed)
            time.sleep(seconds)
        Bridge.call("set_motors", 0, 0)


client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
client.on_connect = on_connect
client.on_message = on_message
client.connect(BROKER, 1883)
client.loop_start()

last_print = 0.0


def loop():
    global last_print
    gyro = Bridge.call("gyro_peak")
    accel = Bridge.call("accel_g")
    light = Bridge.call("light")
    imu_ok = gyro >= 0
    # Keep sending even when the MPU6050 is down, so the light sensor still works
    client.publish(PADDLE_TOPIC, json.dumps({
        "gyro": round(gyro, 1) if imu_ok else 0.0,
        "accel": round(accel, 2) if imu_ok else 0.0,
        "light": light,
        "imu": imu_ok,
    }))

    now = time.time()
    if now - last_print > 1.0:
        if imu_ok:
            print(f"gyro {gyro:.0f} deg/s  accel {accel:.2f} g  light {light}")
        else:
            print(f"MPU6050 not answering (retrying) - check its VCC/GND/SDA/SCL wires. light {light}")
        last_print = now

    play_events()
    time.sleep(SEND_INTERVAL)


App.run(user_loop=loop)
