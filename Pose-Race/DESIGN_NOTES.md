# Design Notes

This is a record of the reasoning behind `steering_control.py` — what was
decided, why, and (since it came up as a class question) how the hand-tracking
model it relies on was actually trained.

## How is the MediaPipe hand detection trained?

**Short answer: it isn't trained by this project at all.** `steering_control.py`
only runs *inference* on a pre-trained model that Google's MediaPipe team
published; nothing here does any training or fine-tuning.

The model in use is MediaPipe's **HandLandmarker**, downloaded once as
`models/hand_landmarker.task` from Google's model repository and loaded via
the MediaPipe Tasks API (`mediapipe.tasks.python.vision.HandLandmarker`).
Internally it's a two-stage pipeline, both stages trained with supervised
learning on labeled image datasets, offline, well before this project existed:

1. **Palm detector** — a single-shot detector (SSD-style) that finds an
   oriented bounding box around each palm in the frame. Detecting the palm
   first (rather than the whole hand or individual fingers) is a deliberate
   choice from the original MediaPipe Hands research: palms are roughly
   rigid and square, so a single anchor-based detector generalizes well
   across hand poses, whereas fingers vary too much in relative position and
   self-occlude constantly.
2. **Hand landmark model** — given the cropped palm region, a CNN regresses
   21 3D landmark coordinates (fingertips, knuckles, wrist, etc.), plus a
   handedness label (left/right) and a presence confidence score.

Both stages were trained on a mix of:

- **Real-world photos** — tens of thousands of images with hands in varied
  poses, lighting, and skin tones, manually annotated with landmark
  positions.
- **Synthetic (rendered) hand data** — a 3D hand model rendered over varied
  backgrounds/poses/lighting to generate additional images with perfect
  ground-truth landmark labels, cheaply, at a scale and precision that's
  hard to get from manual annotation alone. This synthetic-plus-real mix is
  the specific technique the MediaPipe Hands paper (Zhang et al., 2020,
  "MediaPipe Hands: On-device Real-time Hand Tracking") highlights as key to
  the model's robustness.

The trained network is then quantized/converted to TensorFlow Lite so it can
run in real time on a CPU (as it does here, via the XNNPACK delegate — see
the "Created TensorFlow Lite XNNPACK delegate for CPU" line printed at
startup) or GPU, with no retraining needed for a new use case like this one.

This project's only involvement with the model is calling
`HandLandmarker.detect_for_video(...)` once per camera frame and reading the
21 landmarks it returns back out — the same pre-trained weights work
regardless of whose hands are in frame.

## Why the MediaPipe Tasks API instead of `mp.solutions.hands`

The installed `mediapipe` version (1.0.1) dropped the older
`mediapipe.solutions.hands` API entirely — it only ships the newer Tasks API
now. That's why the code goes through `HandLandmarker`/`HandLandmarkerOptions`
and needs the `.task` model file downloaded separately, rather than the
simpler one-line setup older tutorials show.

## Steering algorithm

The control scheme is a **two-hand virtual wheel**, chosen over a one-hand
gesture because it maps directly onto how a real steering wheel is held and
turned, and because two tracked points give both a rotation (angle between
them) and a position (their midpoint) for free — exactly the two inputs
needed (steer, and forward/back).

- **Steering**: the angle between the two palm centers, relative to
  horizontal. Near-level hands (within `ANGLE_DEADZONE_DEG`) count as
  "straight" so small natural hand jitter doesn't cause drift. The angle is
  normalized against `MAX_WHEEL_ANGLE_DEG` (how far you must rotate for full
  lock) and scaled to a max differential (`MAX_STEER_DIFF`) added to one side
  and subtracted from the other (`movement_move_tank`).
- **Forward/back**: the vertical position of the midpoint between the hands,
  relative to a neutral line. Initially this was a straight top-half/
  bottom-half split of the frame, but forward driving is the priority use
  case, so the neutral line was moved down (`FORWARD_ZONE_FRACTION`) so the
  forward zone claims most of the frame height and backward gets a smaller
  band near the bottom.
- **Speed saturation**: within each zone (forward or backward), the outer
  `1 - SPEED_SATURATION_FRACTION` of the zone is clamped to 100%, with a
  linear ramp through the inner portion. This was added because requiring a
  hand at the *exact* edge of the frame to reach full speed was impractical
  — the saturation band makes 100% speed easy to reach without needing
  pixel-perfect hand placement.
- **Safety cutout**: fewer than two hands detected → speed is forced to zero
  every frame. Letting go of the "wheel" always stops the robot.
- **Smoothing**: both steering and forward/back targets are passed through
  an exponential moving average (`SMOOTHING_ALPHA`) before being sent, to
  damp frame-to-frame landmark jitter without adding much input lag.
- **BLE throttling**: commands are rate-limited (`SEND_INTERVAL_S`) and only
  resent when the values change meaningfully (`CHANGE_THRESHOLD`), since the
  camera loop runs faster than BLE writes need to be issued.

## Hardware: the Connection Card and two motors

LEGO Education's Python API identifies a specific physical device over BLE by
a **Connection Card** — a color + serial number pair, e.g. purple/5164 — so
you can pick one particular hub out of several broadcasting nearby. On this
robot, the *same* physical card is attached to both the Double Motor and the
Single Motor, so each device type's own `connect(card_color=, card_serial=)`
call finds its matching hardware using the same identity, even though they're
two separate BLE peripherals.

The Single Motor was added purely to spin something (e.g. an attachment)
continuously at full speed, with no relationship to driving. It's connected
as an independent `SingleMotor` object; `motor_run()` is a "keep going until
told otherwise" command, so it's issued once at connect time and then
re-issued every couple of seconds as a cheap safety net — nothing in the
steering/driving code path touches this object at all, so it can't be
affected by whatever the Double Motor is doing.

## Tuning history

Through testing, two rounds of tuning were made from the initial values:

1. **Steering was too sensitive** — small, natural hand tilt was reading as a
   hard turn. Fixed by roughly doubling `MAX_WHEEL_ANGLE_DEG` (more rotation
   required for full lock), lowering `MAX_STEER_DIFF` (softer turns even at
   full lock), and widening `ANGLE_DEADZONE_DEG`.
2. **Forward driving needed priority** — the original symmetric top-half/
   bottom-half split gave forward and backward equal, and fairly coarse,
   ranges. `FORWARD_ZONE_FRACTION` was introduced to give forward most of the
   frame height for finer control, and `SPEED_SATURATION_FRACTION` was added
   so full speed doesn't require reaching the literal edge of the frame.
