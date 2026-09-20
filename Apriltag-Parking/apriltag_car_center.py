import cv2
import numpy as np
import legoeducation as le

# --- LEGO connection info: match these to your Connection Card ---
card_color = le.LEGO_COLOR_PURPLE
card_serial = '6235'  # <-- update to match your Double Motor's card

# --- AprilTag setup ---
TAG_FAMILY = cv2.aruco.DICT_APRILTAG_36h11
dictionary = cv2.aruco.getPredefinedDictionary(TAG_FAMILY)
detector_params = cv2.aruco.DetectorParameters()
detector = cv2.aruco.ArucoDetector(dictionary, detector_params)

# --- Control tuning ---
# The car drives on a track parallel to the screen (left/right), so distance
# to the target is the tag's horizontal pixel offset from the frame's center.
MAX_SPEED = 40           # top motor speed (%), keep modest so it doesn't overshoot the center
DEADBAND_PX = 15         # stop once the tag is within this many pixels of the frame's center
KP = 0.15                # proportional gain: motor speed (%) per pixel of error
DIRECTION_SIGN = -1      # flip to 1 if the car drives toward the wrong side
MAX_MISSED_FRAMES = 10   # stop the motor if the tag goes undetected for this many frames

# The Double Motor's two sides are mounted as mirror images of each other,
# so sending them identical commands spins the car in place instead of
# driving it straight. These flip one side so they turn in opposite
# real-world directions together. If it still spins (or drives straight but
# backwards), try flipping the sign of one or both of these.
LEFT_SIGN = 1
RIGHT_SIGN = -1

# Connect to the Double Motor
motor = le.DoubleMotor()
motor.connect(card_color=card_color, card_serial=card_serial)
if not motor.connected:
    print('Error connecting to Double Motor.')
    exit(1)

cap = cv2.VideoCapture(0)  # change index if you have multiple cameras
if not cap.isOpened():
    print("Error: could not open video stream.")
    motor.disconnect()
    exit(1)

current_speed = 0
missed_frames = 0


def set_speed(speed):
    """Send a motor command only when the speed actually changes."""
    global current_speed
    speed = int(np.clip(speed, -MAX_SPEED, MAX_SPEED))
    if speed == current_speed:
        return
    current_speed = speed
    if speed == 0:
        motor.motor_stop(motor=le.MOTOR_BOTH)
    else:
        motor.motor_run(motor=le.MOTOR_LEFT, speed=LEFT_SIGN * speed)
        motor.motor_run(motor=le.MOTOR_RIGHT, speed=RIGHT_SIGN * speed)


try:
    while True:
        ok, frame = cap.read()
        if not ok:
            print("Error: could not read frame.")
            break

        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        corners, ids, _ = detector.detectMarkers(gray)
        frame_center_x = frame.shape[1] // 2

        if ids is not None and len(ids) > 0:
            missed_frames = 0
            tag_corners = corners[0][0]
            cx = int(tag_corners[:, 0].mean())
            error = cx - frame_center_x

            if abs(error) <= DEADBAND_PX:
                set_speed(0)
            else:
                set_speed(DIRECTION_SIGN * KP * error)

            cv2.polylines(frame, [tag_corners.astype(np.int32)], True, (0, 0, 255), 2)
            cv2.putText(frame, f"error={error}px speed={current_speed}%", (10, 30),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 255), 2)
        else:
            missed_frames += 1
            if missed_frames > MAX_MISSED_FRAMES:
                set_speed(0)  # lost the tag -- stop for safety

        cv2.line(frame, (frame_center_x, 0), (frame_center_x, frame.shape[0]), (255, 0, 0), 1)
        cv2.imshow("Center on AprilTag (ESC to quit)", frame)
        if cv2.waitKey(1) & 0xFF == 27:  # ESC key
            break
finally:
    motor.motor_stop(motor=le.MOTOR_BOTH)
    cap.release()
    cv2.destroyAllWindows()
    motor.disconnect()
