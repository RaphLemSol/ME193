import json
import threading
from pathlib import Path

import cv2
import paho.mqtt.client as mqtt
from ultralytics import YOLO

BROKER = "test.mosquitto.org"
TOPIC = "ME193_Raphael_minifig"  # must match TOPIC on the UnoQ

# Weights produced by train_yolo.py (RUNS_DIR / RUN_NAME / "weights" / "best.pt").
# Update this if you retrain - ultralytics auto-increments the run folder
# name (blue_detector-2, -3, ...) rather than overwriting it.
WEIGHTS_PATH = Path(__file__).parent / "runs" / "blue_detector-4" / "weights" / "best.pt"

CAMERA_INDEX = 0

# Minimum detection confidence (0-1) to count as "found". Edit this to
# tune sensitivity.
CONFIDENCE_THRESHOLD = 0.5

# Ignore boxes covering more than this fraction of the frame (0-1). A
# minifig is small, so huge boxes are usually a blue shirt or background.
MAX_BOX_AREA = 0.35


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


def to_message(box, frame_width, frame_height):
    """Build the JSON MQTT message for a detection.

    x, y: box center in [-1, 1], (0, 0) = frame center (see to_coordinate).
    width, height: box size as a fraction of the frame, in [0, 1].
    """
    x, y = to_coordinate(box, frame_width, frame_height)
    x1, y1, x2, y2 = box
    return json.dumps({
        "x": round(x, 3),
        "y": round(y, 3),
        "width": round((x2 - x1) / frame_width, 3),
        "height": round((y2 - y1) / frame_height, 3),
    })


def best_detection(results, confidence_threshold, frame_width, frame_height):
    """Return the highest-confidence box above threshold that isn't too
    large to be a minifig, or None."""
    best_box = None
    best_confidence = confidence_threshold
    boxes = results.boxes.xyxy.tolist()
    confidences = results.boxes.conf.tolist()
    max_area = MAX_BOX_AREA * frame_width * frame_height
    for box, confidence in zip(boxes, confidences):
        x1, y1, x2, y2 = box
        if (x2 - x1) * (y2 - y1) > max_area:
            continue
        if confidence > best_confidence:
            best_confidence = confidence
            best_box = box
    return best_box, best_confidence


class LatestFrame:
    """Reads the camera on a background thread and keeps only the newest
    frame, so slow YOLO inference never works on old, buffered frames."""

    def __init__(self, camera):
        self.camera = camera
        self.frame = None
        self.lock = threading.Lock()
        self.running = True
        threading.Thread(target=self._reader, daemon=True).start()

    def _reader(self):
        while self.running:
            ok, frame = self.camera.read()
            if ok:
                with self.lock:
                    self.frame = frame

    def read(self):
        with self.lock:
            frame, self.frame = self.frame, None
        return frame

    def stop(self):
        self.running = False


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

    latest = LatestFrame(camera)

    print(f"Tracking minifig, publishing to '{TOPIC}'. Press 'q' in the preview window to quit.")

    try:
        while True:
            frame = latest.read()
            if frame is None:
                cv2.waitKey(1)
                continue

            frame_height, frame_width = frame.shape[:2]
            results = model.predict(frame, verbose=False)[0]
            box, confidence = best_detection(
                results, CONFIDENCE_THRESHOLD, frame_width, frame_height
            )

            if box is not None:
                payload = to_message(box, frame_width, frame_height)
                client.publish(TOPIC, payload)
                print(f"Minifig at {payload}  (confidence={confidence:.2f})")

                x1, y1, x2, y2 = (int(v) for v in box)
                cv2.rectangle(frame, (x1, y1), (x2, y2), (0, 255, 0), 2)
            else:
                # Tell the UnoQ right away so it stops instead of using the
                # last position.
                client.publish(TOPIC, json.dumps({"found": False}))
                print("No minifig detected.")

            cv2.imshow("Minifig Tracker", frame)
            if cv2.waitKey(1) & 0xFF == ord("q"):
                break
    finally:
        latest.stop()
        camera.release()
        cv2.destroyAllWindows()
        client.loop_stop()
        client.disconnect()


if __name__ == "__main__":
    main()
