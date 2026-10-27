"""
Receives the wearable's IMU samples over MQTT (sent by Gait-UnoQ) and keeps
them in a buffer for record.py and live.py.
"""

import json
import threading
import time

import numpy as np
import paho.mqtt.client as mqtt

import gait_config as cfg

SCALE = np.array([cfg.ACCEL_LSB_PER_G] * 3 + [cfg.GYRO_LSB_PER_DPS] * 3)


class IMUStream:
    def __init__(self, keep_s=None):
        """keep_s: only keep the newest keep_s seconds (live.py). None keeps
        everything until take() is called (record.py)."""
        self.keep = int(keep_s * cfg.SAMPLE_HZ) if keep_s else None
        self.lock = threading.Lock()
        self.times = []          # board's millis() for each sample
        self.rows = []           # ax, ay, az in g; gx, gy, gz in deg/s
        self.last_msg = 0.0
        self.total = 0
        self.client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
        self.client.on_connect = self._on_connect
        self.client.on_message = self._on_message

    def start(self):
        self.client.connect_async(cfg.MQTT_BROKER, 1883)
        self.client.loop_start()
        return self

    def stop(self):
        self.client.loop_stop()
        self.client.disconnect()

    def _on_connect(self, client, userdata, flags, reason_code, properties):
        if reason_code.is_failure:
            print(f"MQTT: could not connect to {cfg.MQTT_BROKER}: {reason_code}")
            return
        client.subscribe(cfg.IMU_TOPIC)

    def _on_message(self, client, userdata, msg):
        try:
            raw = np.array(json.loads(msg.payload)["s"], dtype=float)
        except (ValueError, KeyError, TypeError):
            return
        if raw.ndim != 2 or raw.shape[1] != 7:
            return
        with self.lock:
            self.times.extend(raw[:, 0].astype(int).tolist())
            self.rows.extend((raw[:, 1:] / SCALE).tolist())
            if self.keep and len(self.rows) > self.keep:
                del self.times[:-self.keep]
                del self.rows[:-self.keep]
            self.last_msg = time.time()
            self.total += len(raw)

    def connected(self):
        """True if samples arrived in the last second."""
        return time.time() - self.last_msg < 1.0

    def latest(self, n):
        """The newest n samples as an (n, 6) array, or None if there aren't n yet."""
        with self.lock:
            if len(self.rows) < n:
                return None
            return np.array(self.rows[-n:])

    def take(self):
        """Everything received since the last take(): (times, (N, 6) samples)."""
        with self.lock:
            times, rows = self.times, self.rows
            self.times, self.rows = [], []
        return np.array(times, dtype=int), np.array(rows).reshape(-1, 6)

    def wait_for_data(self, timeout=15.0):
        start = time.time()
        while not self.connected():
            if time.time() - start > timeout:
                return False
            time.sleep(0.1)
        return True
