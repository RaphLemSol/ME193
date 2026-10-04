from pathlib import Path

import cv2
import paho.mqtt.client as mqtt
from ultralytics import YOLO

BROKER = "test.mosquitto.org"
TOPIC = "Minifig_Julian"

# Weights produced by train_yolo.py (RUNS_DIR / RUN_NAME / "weights" / "best.pt").
# Update this if you retrain - ultralytics auto-increments the run folder
# name (minifig_detector-2, -3, ...) rather than overwriting it.
WEIGHTS_PATH = Path(__file__).parent / "runs" / "minifig_detector-3" / "weights" / "best.pt"

CAMERA_INDEX = 0

# Minimum detection confidence (0-1) to count as "found". Edit this to
# tune sensitivity.
CONFIDENCE_THRESHOLD = 0.1


def to_coordinate(box, frame_width, frame_height):
    """Map a detection's center to (x, y) in [-1, 1].

    (0, 0) is the center of the frame. x increases to the right, y
    increases downward (standard image coordinate convention).
    """
    x1, y1, x2, y2 = box
    cx = (x1 + x2) / 2
    cy = (y1 + y2) / 2
    x = (cx - frame_width / 2) / (frame_width / 2)
    y = (cy - frame_height / 2) / (frame_height / 2)
    return x, y


def best_detection(results, confidence_threshold):
    """Return the highest-confidence box above threshold, or None."""
    best_box = None
    best_confidence = confidence_threshold
    boxes = results.boxes.xyxy.tolist()
    confidences = results.boxes.conf.tolist()
    for box, confidence in zip(boxes, confidences):
        if confidence > best_confidence:
            best_confidence = confidence
            best_box = box
    return best_box, best_confidence


def main():
    if not WEIGHTS_PATH.exists():
        raise FileNotFoundError(
            f"Couldn't find trained weights at {WEIGHTS_PATH}. "
            "Run train_yolo.py first, or update WEIGHTS_PATH."
        )

    model = YOLO(str(WEIGHTS_PATH))

    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
    client.connect(BROKER)
    client.loop_start()

    camera = cv2.VideoCapture(CAMERA_INDEX)
    if not camera.isOpened():
        raise RuntimeError(f"Could not open camera index {CAMERA_INDEX}")

    print(f"Tracking minifig, publishing to '{TOPIC}'. Press 'q' in the preview window to quit.")

    try:
        while True:
            ok, frame = camera.read()
            if not ok:
                print("Failed to read from camera.")
                continue

            frame_height, frame_width = frame.shape[:2]
            results = model.predict(frame, verbose=False)[0]
            box, confidence = best_detection(results, CONFIDENCE_THRESHOLD)

            if box is not None:
                x, y = to_coordinate(box, frame_width, frame_height)
                payload = f"({x:.2f}, {y:.2f})"
                client.publish(TOPIC, payload)
                print(f"Minifig at {payload}  (confidence={confidence:.2f})")

                x1, y1, x2, y2 = (int(v) for v in box)
                cv2.rectangle(frame, (x1, y1), (x2, y2), (0, 255, 0), 2)
            else:
                print("No minifig detected.")

            cv2.imshow("Minifig Tracker", frame)
            if cv2.waitKey(1) & 0xFF == ord("q"):
                break
    finally:
        camera.release()
        cv2.destroyAllWindows()
        client.loop_stop()
        client.disconnect()


if __name__ == "__main__":
    main()
