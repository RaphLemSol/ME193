# Gait Identifier

A wearable made from the Arduino UNO Q and an MPU6050 that tells apart
**standing still, walking, running and biking** (or lying on your back and
air-biking). There are two models, neither of them a neural net:

| | Input | Classifier |
|---|---|---|
| **Model 1** | Only the **peak acceleration along one axis** in each 2 s window | Decision tree, depth 3. It just learns thresholds, which `train.py` prints as rules |
| **Model 2** | **All IMU outputs**: ax, ay, az, gx, gy, gz plus total accel and total rotation. For each one: mean, spread, min, max, range and jerkiness. Plus the stride/pedal frequency | Random forest, 300 trees |

## How it fits together

```
 ankle: MPU6050 ──I2C──> UNO Q sketch (samples at 100 Hz)
                           │ Bridge
                         UNO Q Python ──MQTT imu──> laptop: record.py / live.py
                           ▲                                   │
                           └──────── MQTT activity ────────────┘
                         LED matrix shows S / W / R / B
```

- `Gait-UnoQ/` is the board app. The sketch reads the MPU6050 at 100 Hz
  (±16 g, ±2000 °/s, so running impacts don't clip). The Python side sends
  the samples to the laptop 10 times a second and shows the predicted
  activity on the LED matrix.
- `record.py` saves labeled recordings to `data/`.
- `train.py` trains and tests both models and saves them to `models/`.
- `live.py` runs both models side by side in real time.
- `gait_config.py` holds all settings. `gait_features.py` has the features,
  and `gait_stream.py` receives the MQTT data.

## Hardware

| MPU6050 | UNO Q |
|---|---|
| VCC | 3.3V |
| GND | GND |
| SDA | SDA |
| SCL | SCL |

**Placement: the ankle.** Strap the MPU6050 flat against the outside of your
shin just above the ankle bone, so it can't wobble. Every recording and every
demo must use the same position and orientation. At the hip, walking, running
and biking all look much more alike, which is why the ankle is easier.

**Power:** run the UNO Q from a USB-C power bank in a pocket or on a belt.
It sends over Wi-Fi, so the laptop just needs internet access.

## Steps

From the `ME193` folder:

```
python tools/deploy.py Gait-UnoQ       # 1. put the app on the board
```

Then from `ME193/GaitIdentifier`:

```
python record.py still                 # 2. record each activity 2-3 times
python record.py walk                  #    (60 s each by default; --seconds 45)
python record.py run
python record.py bike                  #    or lie on your back and air-bike
python train.py                        # 3. train + test both models
python live.py                         # 4. live demo (q or Esc to quit)
```

- **Record each activity at least twice,** ideally on different days or
  routes. `train.py` tests each model on whole recordings it never trained
  on. With only one recording per activity it falls back to mixing windows,
  and the accuracy it reports will be too optimistic.
- `train.py` prints both models' accuracy and confusion matrices, model 1's
  learned thresholds, and model 2's most useful features. It also saves
  `models/results.png` for your presentation.
- Model 1's axis is picked automatically: whichever of ax, ay, az works
  best. To force one, set `PEAK_AXIS` in `gait_config.py`.
- `live.py --led 1` shows model 1 on the LED matrix instead of model 2.

## What to expect

Model 1 only sees how hard the hardest jolt in the window was, so it should
separate **still < walk < run** well. It will mix up **biking** with walking
or standing, because pedaling has smooth, low peaks. Model 2 also sees
rotation, how regular the motion is, and its frequency: about 1 Hz per foot
for walking, about 1.4 Hz for running, and a smooth circle for biking. That
is the comparison to show.
