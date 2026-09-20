# Pose Race

A hand-tracked virtual steering wheel that drives a LEGO Education robot. A webcam
watches your hands via MediaPipe's HandLandmarker; the position and rotation of
your two-hand "wheel" is translated into differential-drive motor commands sent
over Bluetooth Low Energy (BLE) to a LEGO Education Double Motor. A separate
Single Motor on the same robot just runs continuously at full speed (e.g. for a
spinning attachment), independent of the driving controls.

See [DESIGN_NOTES.md](DESIGN_NOTES.md) for the reasoning behind the control
scheme, how the MediaPipe hand-tracking model is trained, and the history of
tuning decisions made while building this.

## Hardware

- A LEGO Education Double Motor and Single Motor, both wearing the same
  Connection Card (color + serial number identify one physical robot; each
  device type's own `connect()` call finds its matching hardware by that card).
- A webcam.
- Windows with Bluetooth LE support.

## Setup

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

The MediaPipe hand-landmark model (`models/hand_landmarker.task`) is already
checked into this repo, so no separate model download is needed.

Update the Connection Card identity at the top of `steering_control.py`
(`CARD_COLOR`, `CARD_SERIAL`) to match your own hardware.

## Running it

```powershell
python steering_control.py
```

Power on the robot (broadcasting) first. A camera window opens once connected.

## Controls

Hold up **both hands** like you're gripping a steering wheel:

- **Rotate** your hands (one up, one down) to steer left/right.
- **Raise** the whole "wheel" toward the top of the frame to drive forward —
  the higher, the faster. The forward zone covers most of the frame (see
  `FORWARD_ZONE_FRACTION` in the script), since forward driving is the
  priority.
- **Lower** the wheel toward the bottom of the frame to drive backward.
- The outer portion of each zone already means 100% speed, so you don't need
  to pin your hand at the very edge of the frame to reach full speed.
- Show **fewer than two hands** and the robot stops immediately — a safety
  cutout.

Press `q` or `Esc` in the video window to quit; the robot brakes and both
motors disconnect cleanly.

## Tuning

All control constants live at the top of `steering_control.py`:

| Constant | Effect |
|---|---|
| `MAX_SPEED` | Top forward/backward speed (%) |
| `MAX_WHEEL_ANGLE_DEG` | Hand rotation needed for full steering lock (higher = less sensitive) |
| `MAX_STEER_DIFF` | Max speed difference between the two sides while turning |
| `ANGLE_DEADZONE_DEG` | Rotation tolerance before steering registers at all |
| `FORWARD_ZONE_FRACTION` | Fraction of the frame (from the top) mapped to forward |
| `SPEED_SATURATION_FRACTION` | How far into a zone before it's already 100% speed |
| `SINGLE_MOTOR_SPEED` | Constant speed for the always-on Single Motor |
