# How Many Steps?

The [GaitIdentifier](../GaitIdentifier) wearable (an Arduino UNO Q and an MPU6050 on the
ankle), extended to **count steps with a neural net in PyTorch** and **estimate how
far you walked**. The live count shows on the laptop and on the UNO Q's LED matrix.

```
 ankle: MPU6050 ──I2C──> UNO Q sketch (100 Hz)
                           │ Bridge
                         UNO Q Python ──MQTT imu──> laptop: live_steps.py (PyTorch)
                           ▲                                   │
                           └────── MQTT step count ────────────┘
                         LED matrix shows the count
```

## Sensors used

Every MPU6050 output goes into the net: **3 accelerometer axes, 3 gyro axes**,
plus the total acceleration and total rotation rate (these two don't change if
the sensor is rotated on your leg). The MPU6050's temperature reading doesn't
help with steps, so it isn't used.

I left out the light sensor, distance sensor and servos, as you suggested.
None of them measures your leg moving. The one other sensor that would help is
**a second MPU6050 on the other ankle** (same I2C bus with its AD0 pin wired to
3.3 V, address 0x69). Then both feet would be measured directly instead of
doubling one leg's strides (see the limitations below).

## How the step counter works

1. **One stride = 2 steps.** The sensor is on one ankle, so it feels that
   leg's swings. Every swing of the strapped leg means the other foot has
   taken one step too.
2. **Training targets.** In walk/run recordings the shin's rotation rate has
   one big peak per stride, at mid-swing. `label_strides()` finds them. If you
   counted your steps, it picks the threshold that matches your count. Still
   and bike recordings have no strides. They teach the net that pedaling is
   *not* walking, even though it is also a big, regular leg rotation.
3. **The net** (`StepNet` in `step_net.py`) is a 1-D convolutional network.
   It reads 4 s of the 8 signals and outputs, for every sample, how likely the
   leg is at mid-swing. Dilated convolutions let each output see about 2.5 s
   around it, so it judges the whole stride pattern and not just one peak. It
   is trained with augmentation (random sensor tilt or flipped mounting,
   faster/slower cadence, louder/softer motion, noise), so it holds up when the
   strap moves a little.
4. **Counting.** Live, the net runs every 0.25 s on the last 4 s. A stride is
   counted once it's 0.6 s old, so the net has seen what came after it and no
   stride is counted twice. Testing uses this exact same code.
5. **An ensemble of 5 nets** (different random seeds) runs live. Their output
   is averaged for the count. How much they disagree goes into the ± shown
   next to the count.

## Steps to run

From the `ME193` folder, put the board app on the UNO Q:

```
python tools/deploy.py Steps-UnoQ
```

Then from `ME193/How many steps` (needs `torch`, `scipy`, `matplotlib`, `opencv-python`, `paho-mqtt`):

```
python record.py walk --seconds 60     # record + type in your step count / distance
python record.py run --seconds 45
python record.py still                 # 0 steps: teaches it what not to count
python record.py bike
python train_steps.py                  # train, test, fit distance (~15 min)
python live_steps.py                   # live demo: r = reset, q = quit
```

The 8 recordings you made for GaitIdentifier are already in `data/`. They
work for training, but nobody counted the steps in them, so they can't measure
accuracy. **You need recordings where you counted the steps.**

### Recording counted walks (the ground truth)

- Start standing still. When it says RECORDING, walk and **count every
  footfall out loud** (both feet). Stop and stand still before the time runs
  out, or press Ctrl+C. Type in the count when it asks.
- Counting out loud is good to about ±1-2 steps. To do better, film your feet
  and count from the video later. You can enter the numbers by editing
  `data/labels.json` yourself.
- Do **at least 5 counted walks and 3 counted runs**: slow, normal and fast,
  some short (20 steps) and some long (100+), some with turns. More counted
  recordings make the uncertainty estimate itself more trustworthy.

### Recording known distances (for the distance estimate)

When `record.py` asks *how far did you go*, enter the measured distance. A
running track works well: one lap in lane 1 is 400 m, or use the 100 m
straight. A tape-measured hallway also works. Do at least 3 walks and 2 runs at
different speeds. `train_steps.py` needs at least 2 of them to test the
distance estimate, and at least 3 to try the stride-length models that adjust
for speed.

## The video demonstration

1. `python live_steps.py`, then press `r` to zero the count.
2. Film yourself (or someone films you) walking about 50 counted steps.
   Keep the laptop screen or the UNO Q's LED matrix in view. The count lags
   you by about half a second, so stop and wait a moment.
3. Say your own count out loud at the end and compare. Then do a run, and
   show standing still and air-biking **not** adding steps (the part a simple
   pedometer gets wrong).

## Uncertainty analysis: how good is it?

`train_steps.py` tests every recording with a net that **never trained on
that recording** (cross-validation by recording). It counts each one with the
live counter and prints:

| What | Meaning |
|---|---|
| **Count error vs your count** | Average error (bias), average size of the error (MAE, %), the 95% confidence range of that % (bootstrap), and the **95% limits of agreement**: the range 95% of counts land in |
| **Stride by stride** | Of the labeled strides, how many it found (recall) and how many it made up (precision), within ±150 ms, plus the timing error |
| **Fake steps** | Steps per minute counted while standing still or biking. Should be 0 |
| **No-AI comparison** | The same tests for a plain peak counter (count the big gyro peaks) |

It saves `models/steps_results.png` (example net output, counted vs true,
error plot, distance) and `models/step_report.json`. The live ± uses the error
spread measured here plus the ensemble's disagreement.

**What limits the accuracy:**

- **Doubling strides.** The count is always even, so it can be off by 1 at
  the start or end of a walk (which foot moved first). Shuffling one foot,
  pivoting, or a half step with the unstrapped foot is invisible to it.
- **Turning steps are under-counted.** When you pivot to turn around, the
  steps are small shuffles and the strapped shin barely swings, so there's no
  clear stride to find. In a counted walk back and forth over 2 m (10
  lengths, 9 turns), the true count was 61, the net counted 48 and the gyro
  peaks only support 52: about 1 missed step per turn. On a straight walk this
  hardly happens, so test on a straight path, or report the turn count with
  the error.
- **Your own count is uncertain too** (±1-2 steps when counting out loud), so
  errors that small can't be told apart from counting mistakes.
- **The labels come from the gyro peaks.** In recordings you didn't count, the
  net learns to copy a peak detector. The counted recordings are the only real
  ground truth. Without them, the "error" printed is only agreement with the
  auto labels, and the script says so.
- **One person, one placement.** It is trained on you, with the sensor on the
  outside of the shin. Another person, a loose strap, or the sensor on the
  other leg will be worse. The tilt/flip augmentation helps, but don't count on it.
- **Untested movements:** stairs, hills, very slow shuffling, jumping and
  dancing aren't in the training data.
- **Small test set.** With about 10 recordings, the error numbers themselves
  are rough. The bootstrap confidence range shows how rough.

## Distance estimate: limitations and accuracy

Distance = sum of every stride's length. Each stride's length is fitted from
your known-distance recordings: **stride length = a + b × feature**, where the
feature is one of:

| Model | Feature | Idea |
|---|---|---|
| `constant` | none | every stride is the same length |
| `cadence` | strides per second | faster cadence goes with longer strides |
| `swing` | peak shin rotation rate × stride time | the faster the leg swings, the further it goes |
| `weinberg` | (accel range in the stride)^¼ | Weinberg's (2002) pedometer rule: more bounce = longer stride |

`train_steps.py` tests each model on recordings it wasn't fitted to, prints
each one's error, and uses the best. **Before you record any known
distances**, it uses a rule of thumb from your height (`HEIGHT_M` in
`gait_config.py`): step = 0.415 × height walking, 0.65 × height running. That
is roughly ±20% for walking and worse for running.

**Limitations:**

- **It doesn't measure distance directly.** It's strides × estimated stride
  length, so any step-count error adds to the distance error.
- **Stride length varies.** It changes with speed, slope, tiredness and
  shoes. Fitted models typically get within about 5-10% on a walk like the
  ones they were fitted on. A different kind of walk (stairs, a crowd, hills)
  can be much worse.
- **Running is harder.** Running stride length varies much more with speed
  than walking stride length does, so it needs its own known-distance runs.
- **No direction.** It can't tell walking in a straight line from walking in
  a circle, or going backwards. A loop of 400 m counts the same as 400 m away.
- **Why not integrate the accelerometer twice?** That would measure position
  directly, but the MPU6050's noise and bias make the error grow with the
  square of time. Within seconds it's off by meters. Foot-mounted trackers
  fix this by resetting the velocity to zero every time the foot is flat on
  the ground. On the shin the sensor never fully stops, so that doesn't work
  well here.

## Files

| File | What it does |
|---|---|
| `step_net.py` | The net, labels, training, the live/test counter, the distance models |
| `train_steps.py` | Train + cross-validate + uncertainty analysis + distance fit |
| `live_steps.py` | Live count, ±, distance, cadence. Sends the count to the LED matrix |
| `record.py` | Records labeled data and asks for your step count / distance |
| `gait_config.py` | All settings |
| `gait_stream.py` | Receives the MQTT data |
| `Steps-UnoQ/` | Board app. The sketch reads the MPU6050 at 100 Hz and draws the count |
| `train.py`, `live.py`, `gait_features.py` | The GaitIdentifier activity classifier, still working |
