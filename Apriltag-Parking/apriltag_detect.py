import cv2
import numpy as np

# Which AprilTag family to look for. Change this to match the tags you printed.
# Options include: DICT_APRILTAG_16h5, DICT_APRILTAG_25h9,
#                   DICT_APRILTAG_36h10, DICT_APRILTAG_36h11
TAG_FAMILY = cv2.aruco.DICT_APRILTAG_36h11

dictionary = cv2.aruco.getPredefinedDictionary(TAG_FAMILY)
detector_params = cv2.aruco.DetectorParameters()
detector = cv2.aruco.ArucoDetector(dictionary, detector_params)

cap = cv2.VideoCapture(0)  # change index if you have multiple cameras
if not cap.isOpened():
    print("Error: could not open video stream.")
    exit(1)

sharpen_kernel = np.array([[0, -1, 0], [-1, 5, -1], [0, -1, 0]], dtype=np.float32)

# Bridge brief detection gaps (e.g. a blurry frame while the tag moves fast):
# when a tag isn't re-detected, track its corners forward with optical flow
# instead of freezing the box, so it keeps moving with the tag.
MAX_MISSED_FRAMES = 10
LK_PARAMS = dict(winSize=(21, 21), maxLevel=3,
                  criteria=(cv2.TERM_CRITERIA_EPS | cv2.TERM_CRITERIA_COUNT, 30, 0.01))
last_seen = {}  # tag_id -> {"corners": ndarray, "missed": int}
prev_gray = None

while True:
    ok, frame = cap.read()
    if not ok:
        print("Error: could not read frame.")
        break

    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    corners, ids, rejected = detector.detectMarkers(gray)

    # Sharpen for display so the tag's edges stand out more.
    # Detection runs on the original grayscale frame above; this is just for display.
    sharpened = cv2.filter2D(gray, -1, sharpen_kernel)
    display = cv2.cvtColor(sharpened, cv2.COLOR_GRAY2BGR)

    seen_ids = set()
    if ids is not None:
        for tag_corners, tag_id in zip(corners, ids.flatten()):
            tag_id = int(tag_id)
            seen_ids.add(tag_id)
            last_seen[tag_id] = {"corners": tag_corners[0], "missed": 0}
            print(f"Detected tag {tag_id}")

    # For tags not re-detected this frame, carry them forward with optical
    # flow so the box tracks the tag's actual motion instead of sitting still.
    if prev_gray is not None:
        for tag_id in list(last_seen.keys()):
            if tag_id in seen_ids:
                continue
            entry = last_seen[tag_id]
            p0 = entry["corners"].reshape(-1, 1, 2).astype(np.float32)
            p1, status, _ = cv2.calcOpticalFlowPyrLK(prev_gray, gray, p0, None, **LK_PARAMS)
            if p1 is not None and status.all():
                entry["corners"] = p1.reshape(-1, 2)

    # Draw every tracked tag: solid red if seen this frame, fading orange
    # while coasting on optical-flow tracking during a brief miss.
    for tag_id in list(last_seen.keys()):
        entry = last_seen[tag_id]
        if tag_id not in seen_ids:
            entry["missed"] += 1
            if entry["missed"] > MAX_MISSED_FRAMES:
                del last_seen[tag_id]
                continue

        box = entry["corners"].astype(np.int32)
        color = (0, 0, 255) if entry["missed"] == 0 else (0, 140, 255)
        cv2.polylines(display, [box], isClosed=True, color=color, thickness=2)

        cx, cy = entry["corners"].mean(axis=0).astype(int)
        cv2.circle(display, (cx, cy), 4, color, -1)
        label = f"ID {tag_id} ({cx}, {cy})"
        if entry["missed"] > 0:
            label += " (lost)"
        cv2.putText(display, label, (cx - 40, cy - 20),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, color, 2)

    prev_gray = gray

    cv2.imshow("AprilTag Detection (ESC to quit)", display)
    if cv2.waitKey(1) & 0xFF == 27:  # ESC key
        break

cap.release()
cv2.destroyAllWindows()
