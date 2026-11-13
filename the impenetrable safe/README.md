# The Impenetrable Safe

A safe that opens with a finger code. Walk up, press the button, and the
LEDs light up. Hold up three numbers (1-5) with your fingers in the taped
square under the webcam. A convolutional neural net I built in PyTorch counts
the fingers, and if the three numbers are the code, a gear motor opens the latch.

```
 button ─> UNO Q sketch ─> status LED blue + LED matrix shows 3 empty boxes
 webcam ─> crop the taped square ─> FingerNet (CNN) ─> 0-5 fingers, 30x a second
        ─> lock policy (hold steady 1 s = 1 digit, 3 digits = check code)
        ─> gear-motor latch + green/red status LED + LED matrix
```

Step 1 (computer): the webcam is on the laptop, `safe_laptop.py` runs the
net and the policy, and the UNO Q (in `"laptop"` mode) runs the box over MQTT.
Step 2 (UNO Q): the same webcam plugs into the UNO Q, which runs the same
trained model by itself (`"board"` mode). It isn't trained on the board.

## Folder

| | |
|---|---|
| `v_data/` | Anna's V data: gradient descent math (`MATH.md`), Excel with 5 iterations on m & b, Python fit + plots |
| `calibrate.py` | finds the taped square on the carpet (or you click its corners) and saves where it is |
| `test_camera.py` | live webcam check: fps, brightness, sharpness, whether it sees the square |
| `SafeTest-UnoQ/` | board test app: the button (matrix, RGB LED, log) and the webcam on the UNO Q |
| `collect.py` | records labeled pictures of hands (0-5 fingers) |
| `finger_net.py` | the CNN (PyTorch) and the data augmentation |
| `train.py` | trains + tests it, exports the weights for the UNO Q |
| `safe_laptop.py` | the whole lock on the laptop (step 1) |
| `visualize.py` | a picture of every layer, for the stop-action movie |
| `set_code.py` | sets the code (saved only as a hash) |
| `Safe-UnoQ/` | the UNO Q app (step 2). `python/vision.py`, `lock_policy.py` and `numpy_net.py` are used by the laptop scripts too, so both run the same code |
| `NOTION.md`, `MOVIE_SCRIPT.md` | drafts for the Notion page and the movie |

## The neural net (FingerNet)

```
(3, 64, 64) color picture of the taped square, standardized
conv1 16 filters 5x5 -> ReLU -> max pool 2x2   (16, 32, 32)
conv2 32 filters 3x3 -> ReLU -> max pool 2x2   (32, 16, 16)
conv3 64 filters 3x3 -> ReLU -> max pool 2x2   (64,  8,  8)
flatten 4096 -> dropout 30% -> linear -> 6 scores -> softmax -> 0-5 fingers
```

About 49,000 weights. Trained with cross-entropy loss (it picks a category,
not a number) and Adam (gradient descent with a step size per weight). Every
training picture is randomly turned (±25°), shifted, zoomed, mirrored (left
vs right hand), and given different brightness and color each epoch
(augmentation). `train.py` tests on whole recording bursts it never trained
on (or, with `--holdout-person`, a person it never saw), because the frames
within one burst are nearly identical.

**Something new (not done in class):**
- **The CNN written from scratch in numpy** (`numpy_net.py`): convolution
  (im2col), ReLU, max pooling, linear, softmax. The UNO Q runs this instead
  of PyTorch, so it doesn't need a ~1 GB install. `train.py` checks that it
  matches PyTorch (difference ~1e-7) after every training run.
- **Intruder snapshots**: a wrong code saves what the camera saw for each
  digit, plus the whole view, to `intruders/`.
- **Real lock security**: the code is stored only as a salted SHA-256 hash;
  a wrong entry never says which digit was wrong; 3 wrong codes lock it out
  for 30 s, then 60 s, then 120 s.
- **A look inside the net** (`visualize.py`): every filter and feature map,
  for the movie.

## Hardware

- Arduino UNO Q, USB webcam (the same one for both steps), and a USB-C hub
  with power passthrough so the webcam can plug into the UNO Q
- A camera stand at a fixed height over the carpet, and a square of black
  tape (~15-20 cm) on the carpet under it
- Push button (COM to GND, NO to D2)
- Yellow plastic gear motor (TT motor) for the latch, driven by a Cytron
  Maker Drive powered from the UNO Q's 5V (no battery)
- No extra LEDs: the status light is the UNO Q's own RGB LED (blue =
  watching, green = open, red = wrong / locked out), plus its LED matrix

| UNO Q pin | Part |
|---|---|
| D2 | button NO (button COM to GND; NC unused; internal pull-up) |
| D5, D6 | Maker Drive M1A, M1B; gear motor on the M1 outputs |
| 5V, GND | Maker Drive VB+, VB- (powers the motor; optional 470-1000 µF capacitor across them) |

If the UNO Q resets when the motor starts, the 5V pin can't supply the
motor's surge: give the Maker Drive its own 5 V source on VB+ / VB-.

The gear motor can't tell where it is, so the sketch runs it for a set time:
`OPEN_MS` one way to open, `CLOSE_MS` the other way to close (top of
`Safe-UnoQ/sketch/sketch.ino`). Tune them so the latch fully opens and
closes. Build the latch with a hard stop at each end, so running a little too
long is harmless. If it turns the wrong way, set `MOTOR_REVERSED = true`.
At power-up it doesn't know where the latch is, so it runs the close
direction once (it may push against the stop for a moment).

## Steps

From this folder (needs `torch`, `opencv-python`, `matplotlib`, `paho-mqtt`):

```
python calibrate.py --list              # find the webcam's number -> CAMERA_INDEX in safe_config.py
python calibrate.py                     # nothing in the square, press s
python set_code.py 4 1 3                # YOUR code: three different numbers, 1-5
python collect.py --person raphael      # 0-5 = record that many fingers
python train.py                         # ~5 min on a laptop CPU
python safe_laptop.py --no-board        # try it: space = button
```

**Collecting data.** Aim for 300+ pictures per number from at least 5-6
short bursts each. Move your hand around the whole square while it records,
tilt it, use both hands, and vary which fingers make each number. **0 = a fist
and also the empty square.** There's no lamp over the square, so record in
different light (daytime, evening, desk lamp on and off). Then get 2-3
friends to do a few bursts each (`--person anna`). 3 tends to be the
hardest, so give it extra.

**Step 1, the box from the laptop.** In `Safe-UnoQ/python/main.py`, set
`MODE = "laptop"`, then from the `ME193` folder:

```
python tools/deploy.py Safe-UnoQ
```

and from this folder `python safe_laptop.py`.

**Step 2, all on the UNO Q.** Plug the webcam into the UNO Q's hub, set
`MODE = "board"`, and deploy again. Everything it needs is in the app folder
(`finger_net.npz`, `roi.json`, `code.json`). Keep the camera on the same
stand; if the stand moved, run `calibrate.py` again on the laptop and
redeploy. The log prints frames per second and ms per frame, for comparing
with the laptop (`safe_laptop.py` shows the same numbers;
`python safe_laptop.py --numpy` runs the board's numpy net on the laptop).

## Results

Fill in after training: `models/training.png`, `models/report.json`, and
`models/training_holdout-<name>.png` for each friend held out.
