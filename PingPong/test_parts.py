"""
Test each part of the ping-pong setup on its own.

    python test_parts.py tags     # AprilTag 27: distance -> level, hold still -> start
    python test_parts.py pose     # MediaPipe Pose: tracks your paddle wrist
    python test_parts.py mqtt     # MQTT: is the paddle sending data? posts a test score
    python test_parts.py light    # light sensor: live reading, cover / uncover check
    python test_parts.py mpu      # MPU6050: live gyro / accel, counts swings
    python test_parts.py motors   # motors: runs each motor forward and backward

tags and pose only need the webcam. mqtt, light, mpu and motors need the
PingPong-UnoQ app running on the board (python tools/deploy.py PingPong-UnoQ).

Press q or Esc in a camera window, or Ctrl+C in the terminal, to stop.
"""

import argparse
import json
import queue
import time
import uuid

import cv2
import mediapipe as mp
import paho.mqtt.client as mqtt

import ping_pong as pp


# ----------------------------------------------------------------------------
# Camera tests
# ----------------------------------------------------------------------------

def open_camera():
    cap = cv2.VideoCapture(pp.CAMERA_INDEX, cv2.CAP_DSHOW)
    if not cap.isOpened():
        raise RuntimeError(f"Could not open camera index {pp.CAMERA_INDEX}")
    return cap


def test_tags():
    print(f"Hold tag {pp.GAME_TAG} up to the camera at different distances. The size number "
          f"sets the level (EASY below {pp.LEVEL_SIZES[0]}, HARD above {pp.LEVEL_SIZES[1]}; "
          "change LEVEL_SIZES in ping_pong.py). Hold it still to fill the START ring.")
    tag = pp.GameTag()
    cap = open_camera()
    detected_other = set()
    try:
        while True:
            ok, frame = cap.read()
            if not ok:
                break
            if tag.read(frame):   # read before mirroring
                print(f"START at level {tag.level} ({pp.LEVEL_NAMES[tag.level]}), "
                      f"size {tag.size:.2f}")
            # Point out other tags too, in case the wrong one is printed
            _, ids, _ = tag.detector.detectMarkers(cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY))
            for tag_id in (ids.flatten() if ids is not None else []):
                if int(tag_id) != pp.GAME_TAG and int(tag_id) not in detected_other:
                    detected_other.add(int(tag_id))
                    print(f"Saw tag {int(tag_id)}, but the game only uses tag {pp.GAME_TAG}.")
            frame = cv2.flip(frame, 1)
            pp.draw_tag(frame, tag)
            if tag.corners is None:
                pp.put(frame, f"Tag {pp.GAME_TAG} not in view", (10, 30), color=(0, 0, 255))
            else:
                pp.put(frame, f"size {tag.size:.3f} -> level {tag.level} "
                              f"{pp.LEVEL_NAMES[tag.level]}", (10, 30), color=(0, 220, 0))
            cv2.imshow("Test: AprilTag", frame)
            if cv2.waitKey(1) & 0xFF in (ord("q"), 27):
                break
    finally:
        cap.release()
        cv2.destroyAllWindows()


def test_pose():
    print(f"Move your {pp.PADDLE_HAND} hand around. The circle should follow your wrist.")
    landmarker = pp.make_pose_landmarker()
    cap = open_camera()
    start = time.perf_counter()
    last_ms = -1
    try:
        while True:
            ok, frame = cap.read()
            if not ok:
                break
            rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            ms = max(int((time.perf_counter() - start) * 1000), last_ms + 1)
            last_ms = ms
            result = landmarker.detect_for_video(
                mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb), ms)
            wrist = pp.paddle_wrist(result)
            frame = cv2.flip(frame, 1)
            height, width = frame.shape[:2]
            if wrist is None:
                pp.put(frame, f"{pp.PADDLE_HAND} wrist NOT visible", (10, 30), color=(0, 0, 255))
            else:
                cv2.circle(frame, (int(wrist[0] * width), int(wrist[1] * height)), 25,
                           (0, 220, 0), 3)
                pp.put(frame, f"{pp.PADDLE_HAND} wrist x={wrist[0]:.2f} y={wrist[1]:.2f}",
                       (10, 30), color=(0, 220, 0))
            cv2.imshow("Test: Pose", frame)
            if cv2.waitKey(1) & 0xFF in (ord("q"), 27):
                break
    finally:
        landmarker.close()
        cap.release()
        cv2.destroyAllWindows()


# ----------------------------------------------------------------------------
# Paddle tests (over MQTT, through the PingPong-UnoQ app)
# ----------------------------------------------------------------------------

def connect(readings=None):
    """Connect to the broker; put paddle messages in `readings` if given."""
    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2,
                         client_id=f"pingpong-test-{uuid.uuid4().hex[:8]}")

    def on_connect(c, userdata, flags, reason_code, properties):
        if readings is not None:
            c.subscribe(pp.PADDLE_TOPIC)
        print(f"Connected to {pp.MQTT_BROKER}")

    def on_message(c, userdata, msg):
        try:
            readings.put(json.loads(msg.payload.decode()))
        except ValueError:
            print(f"Bad paddle message: {msg.payload!r}")

    client.on_connect = on_connect
    client.on_message = on_message
    client.connect(pp.MQTT_BROKER, pp.MQTT_PORT, keepalive=60)
    client.loop_start()
    return client


def next_reading(readings):
    try:
        return readings.get(timeout=2.0)
    except queue.Empty:
        print(f"No paddle data on '{pp.PADDLE_TOPIC}' for 2 s. Is the PingPong-UnoQ app "
              "running and online? Check its console.")
        return None


def bar(value, full, width=30):
    filled = int(max(0.0, min(1.0, value / full)) * width)
    return "#" * filled + "-" * (width - filled)


def test_mqtt():
    readings = queue.Queue()
    client = connect(readings)
    try:
        print(f"Waiting for paddle data on '{pp.PADDLE_TOPIC}'...")
        count, start = 0, time.time()
        while time.time() - start < 5:
            if next_reading(readings) is not None:
                count += 1
        print(f"Got {count} paddle messages in 5 s (about {count / 5:.0f}/s; ~30/s is normal).")
        # Round trip through the broker on a private topic, so the real score isn't touched
        echo = queue.Queue()
        test_topic = f"{pp.PADDLE_TOPIC}/selftest"
        client.message_callback_add(test_topic, lambda c, u, msg: echo.put(msg.payload.decode()))
        client.subscribe(test_topic)
        time.sleep(0.5)
        client.publish(test_topic, "ping", qos=1)
        try:
            echo.get(timeout=3)
            print("Publishing works: a test message went to the broker and came back.")
        except queue.Empty:
            print("Publishing FAILED: the test message never came back from the broker.")
    finally:
        client.loop_stop()
        client.disconnect()


def test_light():
    readings = queue.Queue()
    client = connect(readings)
    print("Leave the light sensor UNCOVERED for a moment...")
    baseline = lo = hi = None
    try:
        samples = []
        while len(samples) < pp.BASELINE_SAMPLES:
            r = next_reading(readings)
            if r is not None:
                samples.append(float(r["light"]))
        baseline = sorted(samples)[len(samples) // 2]
        print(f"Uncovered baseline: {baseline:.0f}. Now cover and uncover it with your hand. "
              "Ctrl+C to stop.")
        lo, hi = baseline, baseline
        while True:
            r = next_reading(readings)
            if r is None:
                continue
            light = float(r["light"])
            lo, hi = min(lo, light), max(hi, light)
            change = abs(light - baseline) / baseline if baseline else 0.0
            held = "HELD" if change >= pp.GRIP_CHANGE else "open"
            print(f"\rlight {light:5.0f} [{bar(light, 1023)}] change {change:4.0%} {held:4}  "
                  f"(min {lo:.0f}, max {hi:.0f})", end="", flush=True)
    except KeyboardInterrupt:
        print()
        if baseline and lo is not None and max(baseline - lo, hi - baseline) / baseline < pp.GRIP_CHANGE:
            print(f"Covering never changed the reading by {pp.GRIP_CHANGE:.0%}. Check the "
                  "divider wiring, or lower GRIP_CHANGE in ping_pong.py.")
    finally:
        client.loop_stop()
        client.disconnect()


def test_mpu():
    readings = queue.Queue()
    client = connect(readings)
    print(f"Hold the paddle still (accel should be ~1.00 g), then swing it. A swing is "
          f"gyro over {pp.SWING_GYRO_DPS} deg/s. Ctrl+C to stop.")
    swings, last_swing, top = 0, 0.0, 0.0
    try:
        while True:
            r = next_reading(readings)
            if r is None:
                continue
            gyro, accel = float(r["gyro"]), float(r["accel"])
            if not r.get("imu", True):
                print("\rMPU6050 NOT ANSWERING - check its VCC, GND, SDA and SCL wires"
                      + " " * 30, end="", flush=True)
                continue
            top = max(top, gyro)
            now = time.time()
            if gyro >= pp.SWING_GYRO_DPS and now - last_swing >= pp.SWING_COOLDOWN_S:
                swings, last_swing = swings + 1, now
                print(f"\nSWING #{swings}: {gyro:.0f} deg/s")
            print(f"\rgyro {gyro:6.0f} deg/s [{bar(gyro, pp.HARD_SWING_GYRO_DPS)}] "
                  f"accel {accel:4.2f} g  (fastest {top:.0f})", end="", flush=True)
    except KeyboardInterrupt:
        print(f"\n{swings} swings. Fastest: {top:.0f} deg/s.")
    finally:
        client.loop_stop()
        client.disconnect()


def test_motors():
    client = connect()
    time.sleep(1.0)   # let the connection come up
    steps = [
        ("Motor 1 forward", 150, 0),
        ("Motor 1 backward", -150, 0),
        ("Motor 2 forward", 0, 150),
        ("Motor 2 backward", 0, -150),
        ("Both, opposite ways (the paddle buzz)", 200, -200),
    ]
    try:
        for name, m1, m2 in steps:
            input(f"Press Enter to run: {name} (1 s)...")
            client.publish(pp.FEEDBACK_TOPIC,
                           json.dumps({"event": "motor", "m1": m1, "m2": m2, "seconds": 1.0}))
        input("Press Enter to play the game's 'hit' buzz and show 7 on the LED matrix...")
        client.publish(pp.FEEDBACK_TOPIC, json.dumps({"event": "hit", "streak": 7}))
        input("Press Enter to play the 'miss' buzz and reset the LED matrix to 0...")
        client.publish(pp.FEEDBACK_TOPIC, json.dumps({"event": "miss", "streak": 0}))
        time.sleep(1.0)
        print("Done. If a motor spun the wrong way or not at all, check its M_A / M_B wires.")
    finally:
        client.loop_stop()
        client.disconnect()


TESTS = {
    "tags": test_tags,
    "pose": test_pose,
    "mqtt": test_mqtt,
    "light": test_light,
    "mpu": test_mpu,
    "motors": test_motors,
}


def pick_test():
    """Menu for when the script is started with no part named (e.g. VS Code's Run button)."""
    names = list(TESTS)
    for i, name in enumerate(names, 1):
        print(f"  {i}. {name}")
    while True:
        choice = input("Which part do you want to test? Type a number or name: ").strip().lower()
        if choice in TESTS:
            return choice
        if choice.isdigit() and 1 <= int(choice) <= len(names):
            return names[int(choice) - 1]
        print("Not one of the choices, try again.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Test one part of the ping-pong setup")
    parser.add_argument("part", nargs="?", choices=TESTS, help="leave out to pick from a menu")
    part = parser.parse_args().part or pick_test()
    TESTS[part]()
