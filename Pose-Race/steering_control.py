"""
Hand-tracked virtual steering wheel that drives a LEGO Education Double Motor.

Hold up BOTH hands like you're gripping a steering wheel:
  - Rotate your hands (one up, one down) to STEER left/right.
  - Raise the whole "wheel" up the frame to drive FORWARD (higher = faster).
  - Lower the whole "wheel" down the frame to drive BACKWARD (lower = faster).
  - Keep hands level and centered to stop.

Show fewer than two hands and the robot stops, as a safety cutout.

Press 'q' or Esc in the video window to quit.
"""

import math
import os
import time

import cv2
import mediapipe as mp
from mediapipe.tasks.python import vision, BaseOptions
from mediapipe.tasks.python.vision.core.vision_task_running_mode import VisionTaskRunningMode

import legoeducation as le

# --- Hardware identity (Connection Card shared by the Double Motor and Single Motor) ---
CARD_COLOR = le.LEGO_COLOR_PURPLE
CARD_SERIAL = "5164"

# The Single Motor just runs flat-out the whole time, independent of steering/driving.
SINGLE_MOTOR_SPEED = 100
SINGLE_MOTOR_REASSERT_INTERVAL_S = 2.0  # periodically re-issue the run command as a safety net

# --- Camera / model ---
CAMERA_INDEX = 0
MODEL_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "models", "hand_landmarker.task")

# --- Control tuning ---
MAX_SPEED = 100            # top forward/backward speed, percent
MAX_WHEEL_ANGLE_DEG = 100  # hand rotation (degrees) that maps to full steering lock (higher = less sensitive)
MAX_STEER_DIFF = 55        # max percentage points added/subtracted between wheels
SPEED_DEADZONE = 0.08      # fraction of each zone's span near neutral that counts as "stopped"
ANGLE_DEADZONE_DEG = 10    # degrees near level that counts as "straight"
SMOOTHING_ALPHA = 0.4      # 0..1, higher = more responsive/less smooth
FORWARD_ZONE_FRACTION = 0.7  # fraction of frame height (from the top) mapped to forward; rest is backward
SPEED_SATURATION_FRACTION = 0.75  # reaching this fraction of the way through a zone already means 100% speed
SEND_INTERVAL_S = 1 / 15   # throttle BLE commands to ~15 Hz
CHANGE_THRESHOLD = 3       # only resend if speed changed by more than this many percent

# Landmarks used to estimate a stable palm-center point per hand
PALM_LANDMARKS = (0, 5, 9, 13, 17)


def clamp(value, lo, hi):
    return max(lo, min(hi, value))


def palm_center_px(hand_landmarks, width, height):
    xs = [hand_landmarks[i].x for i in PALM_LANDMARKS]
    ys = [hand_landmarks[i].y for i in PALM_LANDMARKS]
    cx = sum(xs) / len(xs) * width
    cy = sum(ys) / len(ys) * height
    return cx, cy


def make_landmarker():
    options = vision.HandLandmarkerOptions(
        base_options=BaseOptions(model_asset_path=MODEL_PATH),
        running_mode=VisionTaskRunningMode.VIDEO,
        num_hands=2,
        min_hand_detection_confidence=0.6,
        min_tracking_confidence=0.5,
    )
    return vision.HandLandmarker.create_from_options(options)


def connect_double_motor():
    print(f"Connecting to Double Motor (card color=purple, serial={CARD_SERIAL})...")
    motor = le.DoubleMotor()
    motor.connect(card_color=CARD_COLOR, card_serial=CARD_SERIAL)
    if not motor.connected:
        raise RuntimeError(
            "Could not connect to the Double Motor. Make sure it is powered on, "
            "broadcasting, and the purple Connection Card numbered 5164 is attached."
        )
    print("Connected.")
    motor.movement_set_end_state(le.MOTOR_END_STATE_BRAKE)
    return motor


def connect_single_motor():
    print(f"Connecting to Single Motor (card color=purple, serial={CARD_SERIAL})...")
    motor = le.SingleMotor()
    motor.connect(card_color=CARD_COLOR, card_serial=CARD_SERIAL)
    if not motor.connected:
        raise RuntimeError(
            "Could not connect to the Single Motor. Make sure it is powered on, "
            "broadcasting, and the purple Connection Card numbered 5164 is attached."
        )
    print("Connected.")
    motor.motor_run(speed=SINGLE_MOTOR_SPEED, blocking=False)
    return motor


def draw_wheel(frame, left_pt, right_pt, angle_deg, forward_pct, steer_pct):
    height, width = frame.shape[:2]

    # Neutral reference line: above it is the (larger) forward zone, below is backward
    neutral_y = int(height * FORWARD_ZONE_FRACTION)
    cv2.line(frame, (0, neutral_y), (width, neutral_y), (60, 60, 60), 1)

    mx = int((left_pt[0] + right_pt[0]) / 2)
    my = int((left_pt[1] + right_pt[1]) / 2)
    radius = int(max(30, math.hypot(right_pt[0] - left_pt[0], right_pt[1] - left_pt[1]) / 2))

    cv2.circle(frame, (mx, my), radius, (0, 200, 0), 2)
    cv2.line(frame, (int(left_pt[0]), int(left_pt[1])), (int(right_pt[0]), int(right_pt[1])), (0, 200, 0), 4)
    # perpendicular spoke so the wheel graphic visibly "rotates"
    ang = math.radians(angle_deg + 90)
    sx = int(mx - radius * math.cos(ang))
    sy = int(my - radius * math.sin(ang))
    ex = int(mx + radius * math.cos(ang))
    ey = int(my + radius * math.sin(ang))
    cv2.line(frame, (sx, sy), (ex, ey), (0, 200, 0), 2)

    for pt in (left_pt, right_pt):
        cv2.circle(frame, (int(pt[0]), int(pt[1])), 10, (0, 120, 255), -1)

    cv2.putText(frame, f"Forward: {forward_pct:+.0f}%", (10, 30),
                cv2.FONT_HERSHEY_SIMPLEX, 0.8, (255, 255, 255), 2)
    cv2.putText(frame, f"Steer:   {steer_pct:+.0f}", (10, 60),
                cv2.FONT_HERSHEY_SIMPLEX, 0.8, (255, 255, 255), 2)


def main():
    motor = connect_double_motor()
    single_motor = connect_single_motor()
    landmarker = make_landmarker()

    cap = cv2.VideoCapture(CAMERA_INDEX, cv2.CAP_DSHOW)
    if not cap.isOpened():
        raise RuntimeError(f"Could not open camera index {CAMERA_INDEX}")

    smoothed_forward = 0.0
    smoothed_steer = 0.0
    last_sent_left = None
    last_sent_right = None
    last_send_time = 0.0
    last_single_motor_assert_time = 0.0
    start_time = time.perf_counter()
    last_timestamp_ms = -1

    print("Show both hands to the camera to drive. Press 'q' or Esc to quit.")

    try:
        while True:
            ok, frame = cap.read()
            if not ok:
                break
            frame = cv2.flip(frame, 1)
            height, width = frame.shape[:2]

            rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb)

            timestamp_ms = int((time.perf_counter() - start_time) * 1000)
            if timestamp_ms <= last_timestamp_ms:
                timestamp_ms = last_timestamp_ms + 1
            last_timestamp_ms = timestamp_ms

            result = landmarker.detect_for_video(mp_image, timestamp_ms)

            driving = False
            if len(result.hand_landmarks) == 2:
                centers = [palm_center_px(hl, width, height) for hl in result.hand_landmarks]
                centers.sort(key=lambda p: p[0])  # left-on-screen first
                left_pt, right_pt = centers

                dx = right_pt[0] - left_pt[0]
                dy = right_pt[1] - left_pt[1]
                angle_deg = math.degrees(math.atan2(dy, dx))
                if abs(angle_deg) < ANGLE_DEADZONE_DEG:
                    angle_deg = 0.0

                steer_target = clamp(angle_deg / MAX_WHEEL_ANGLE_DEG, -1.0, 1.0) * MAX_STEER_DIFF

                # Neutral line sits low in the frame so the forward zone (above it)
                # spans most of the screen, and backward (below it) is a smaller zone.
                mid_y = (left_pt[1] + right_pt[1]) / 2
                neutral_y = height * FORWARD_ZONE_FRACTION
                if mid_y <= neutral_y:
                    vertical_offset = (neutral_y - mid_y) / neutral_y
                else:
                    vertical_offset = -(mid_y - neutral_y) / (height - neutral_y)
                if abs(vertical_offset) < SPEED_DEADZONE:
                    vertical_offset = 0.0

                # The outer fraction of each zone (e.g. the top 25% of the forward
                # zone, or the bottom 25% of the backward zone) already means 100%,
                # so full speed is easy to reach without pinning your hand at the edge.
                sign = 1.0 if vertical_offset >= 0 else -1.0
                magnitude = clamp(abs(vertical_offset) / SPEED_SATURATION_FRACTION, 0.0, 1.0)
                vertical_offset = sign * magnitude

                forward_target = vertical_offset * MAX_SPEED

                smoothed_forward += SMOOTHING_ALPHA * (forward_target - smoothed_forward)
                smoothed_steer += SMOOTHING_ALPHA * (steer_target - smoothed_steer)

                speed_left = clamp(round(smoothed_forward + smoothed_steer), -100, 100)
                speed_right = clamp(round(smoothed_forward - smoothed_steer), -100, 100)

                draw_wheel(frame, left_pt, right_pt, angle_deg, smoothed_forward, smoothed_steer)
                driving = True
            else:
                smoothed_forward = 0.0
                smoothed_steer = 0.0
                speed_left = 0
                speed_right = 0
                cv2.putText(frame, "Show BOTH hands to drive", (10, 30),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 0, 255), 2)

            now = time.perf_counter()
            changed = (
                last_sent_left is None
                or abs(speed_left - last_sent_left) > CHANGE_THRESHOLD
                or abs(speed_right - last_sent_right) > CHANGE_THRESHOLD
            )
            if now - last_send_time >= SEND_INTERVAL_S and (changed or not driving):
                motor.movement_move_tank(speed_left, speed_right, blocking=False)
                last_sent_left, last_sent_right = speed_left, speed_right
                last_send_time = now

            # Keep the Single Motor pinned at full speed regardless of driving state.
            if now - last_single_motor_assert_time >= SINGLE_MOTOR_REASSERT_INTERVAL_S:
                single_motor.motor_run(speed=SINGLE_MOTOR_SPEED, blocking=False)
                last_single_motor_assert_time = now

            cv2.imshow("Steering Wheel Control", frame)
            key = cv2.waitKey(1) & 0xFF
            if key in (ord("q"), 27):  # 'q' or Esc
                break
    finally:
        print("Stopping motors and disconnecting...")
        try:
            motor.movement_stop(blocking=True)
        except Exception as e:
            print(f"Warning: error while stopping Double Motor: {e}")
        try:
            motor.disconnect()
        except Exception as e:
            print(f"Warning: error while disconnecting Double Motor: {e}")
        try:
            single_motor.motor_stop(blocking=True)
        except Exception as e:
            print(f"Warning: error while stopping Single Motor: {e}")
        try:
            single_motor.disconnect()
        except Exception as e:
            print(f"Warning: error while disconnecting Single Motor: {e}")
        landmarker.close()
        cap.release()
        cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
