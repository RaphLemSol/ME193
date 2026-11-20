# Behavior Cloning Navigation (HW9)

A wearable guide that walks someone to Nolop without ever finding out where they are.
It doesn't use GPS or Wi-Fi to find its position. It only knows two things about the
walk so far: how many steps the person has taken since the last turn, and how many turns
they have made. A trained step counter and the gyroscope of the same sensor on the ankle
measure these, on an Arduino UNO Q. The navigation itself isn't programmed by hand. It is learned
by **behavior cloning**: we walk the route ourselves, press what we are doing on a phone
("straight", "left", "right", "stairs", "arrived"), and a policy learns to give the same
instruction in the same situation. The interesting part is doing this with very little
data. We are allowed at most 10 full walks in total, for both partners together, including
correction walks. That means cleaning the labels before training matters as much as the
model. For example, people press "turn" a moment after they start turning, so the label
lands late. The board runs everything and serves the phone page itself, so no laptop or
internet is needed on the walk.

> **Status (2026-11-17):** folder and plan set up. No board code, data or policy yet.
> Sections below describe the planned design; [docs/process_log.md](docs/process_log.md)
> records what changes as we build it.

## How it works

**Sensing (on the UNO Q)**
- **Steps:** an MPU-6050 on the right lower leg, near the ankle, counted by Raph's CNN
  step counter (see Credits), ported to plain numpy so it runs on the board
  (`uno_q/python/stride_counter.py`). Five small 1-D convolutional nets look at the last
  4 s and score how likely the strapped leg is at mid-swing; each peak of their average
  is one stride = 2 steps. Our strap holds the sensor turned differently from Raph's, so
  the x and y axes are swapped to his layout first. Steps go up 2 at a time, about
  0.6-0.85 s after the stride. Distance is his fitted 0.41 m per step, the same for
  everyone. On all of Step 0's walks it was within 2 steps for both walkers; the HW7
  counter undercounted Mohammed by up to a third.
- **Turns:** the gyroscope of the same ankle sensor. It has no compass, so a turn is found
  by adding up the gyro's turning rate over time. The rotation is measured around "up",
  found from the accelerometer averaged over 1 s (the leg's swing averages out), so it
  works however the sensor sits on the leg. The gyro's bias (a false turning rate when
  still) is measured while the walker stands still for 5 s at the start of every walk. A
  turn is counted when the heading changes by more than 60° within 3 s. The heading
  itself slowly drifts over a long walk, so the policy never uses it directly. It only
  uses the number of turns. A first test on Raph's recorded walk showed every turnaround
  clearly ([`media/ankle_turns_raph.png`](media/ankle_turns_raph.png)); 90° corners are
  tested next. **Backup:** a second MPU-6050 at the waist, if the ankle can't count
  corners.
- **Stairs (optional):** a small classifier that says "on stairs" or not.

**What the policy sees and does**

| Observation (input) | Action (output) |
|---|---|
| steps since the last turn (or meters since the last turn: both are saved, to be compared) | Straight |
| turns so far (left, right) | Left |
| on stairs (yes / no) | Right |
| | Stairs |
| | Arrived |

**The policy: a lookup table first.** This follows the
[AnnaCode Table Cloner](https://chrisbuerginrogers.github.io/ME193-Robotics/Public%20stuff/AnnaCode/cloner.html).
During demonstrations, every situation the walker is in gets a tally of the actions they
chose there. When navigating, the board gives the most common action for the current
situation. If that exact situation never came up, it uses the closest one that did. The
whole policy is a table you can read, so it is easy to check what it learned. We'll try a
small neural net only if the table isn't good enough.

**Cleaning the labels before training**
- Shift each turn label a few steps earlier, to undo the walker's reaction delay.
- Choose how many steps before a turn the instruction should appear, so a new walker has
  time to react.
- Fix the label that stays on for a step after a turn ends (a known bug in the page).

**Corrections (DAgger)**
- On a correction walk, the policy guides. When it gives a wrong instruction, the walker
  presses the right one.
- The corrected moments are added to the training data, and the table is rebuilt. This
  teaches the policy situations the demonstrations never showed, such as a missed turn.

**The phone page**
- The board serves the page itself (the App Lab `web_ui` brick, port 7000), as in HW7.
- The phone joins the board over a phone hotspot. Wi-Fi is only the link between phone
  and board; it is never used to find where the walker is.
- Two tabs: **Record demo** (label a demonstration) and **Navigate + correct** (follow
  the policy; with "Save my corrections" ticked, every correction tap is saved for DAgger).
- It reads the board's state from `GET /api/state`: `steps`, `distance_m`, `turns_left`,
  `turns_right`, `steps_at_last_turn`, `distance_at_last_turn`, `heading_deg`,
  `on_stairs`.
- Before every walk it calls `GET /api/reset` (with who is walking and which kind of
  walk), and the walk only starts once the board answers `{"ok": true}` with its walk
  number, so each walk's counts start at 0.
- It sends every saved row to the board (`POST /api/rows`). If the board doesn't answer,
  the rows wait on the phone, even through a page reload, and go out in order when it
  answers again.
- If the board stops answering, a warning appears on both tabs and the instruction is
  greyed out until it answers again.
- The board saves each walk as one CSV; the phone's download is a backup. The columns are
  explained in [data/README.md](data/README.md).

## Hardware

- Arduino UNO Q, on a USB power bank
- 1 × MPU-6050 at 0x68 with the board on the right lower leg, near the ankle: exactly
  HW7's setup, short wire. It gives both the steps and the turns.
- Backup only, if the ankle can't count corners: a second MPU-6050 at the waist (0x69, AD0
  tied to 3.3 V) on a long wire
- A phone for the page and the hotspot
- The route: start point still to be decided, ending at Nolop

## Files

```
HW9 - Behavior Cloning Navigation/
├── README.md
├── uno_q/          the board app: sensing, policy and the phone page (own README)
│   └── assets/     the phone page
├── training/       label cleanup and policy training (laptop)
├── data/           recorded walks, their log and the recording checklist
├── docs/           process log: what we tried, what failed, what we figured out
└── media/          plots and images
```

| File | What it does |
|---|---|
| [uno_q/README.md](uno_q/README.md) | What the board app does and how to deploy it |
| [uno_q/app.yaml](uno_q/app.yaml) | App Lab settings: name, port 7000, web page brick |
| [uno_q/python/main.py](uno_q/python/main.py) | The board app: reads the sensor, counts steps and turns, answers the page (`/api/state`, `/api/reset`, `/api/rows`) |
| [uno_q/python/sensor.py](uno_q/python/sensor.py) | Collects and checks the sensor readings from the sketch (lost and bad readings) |
| [uno_q/python/turns.py](uno_q/python/turns.py) | Counts turns live from the ankle gyro (offset per axis, heading around "up", 60° within 3 s) |
| [uno_q/python/walks.py](uno_q/python/walks.py) | Saves each walk's rows to a CSV on the board (tickets, undo, safe rewrites) |
| [uno_q/sketch/sketch.ino](uno_q/sketch/sketch.ino) | HW7's sketch: reads the MPU-6050 100 times a second |
| [uno_q/python/stride_counter.py](uno_q/python/stride_counter.py) | Raph's step counter in plain numpy, with a live counter for the board app |
| `uno_q/python/raph_step_model.npz` | Raph's 5 trained nets and counting settings, exported for the board |
| [training/export_raph_cnn.py](training/export_raph_cnn.py) | Exports Raph's PyTorch model to that file (weights unchanged) |
| [training/check_numpy_port.py](training/check_numpy_port.py) | Checks the numpy port gives the same scores, peaks and counts as his PyTorch version |
| [training/compare_raph_cnn.py](training/compare_raph_cnn.py) | Runs Raph's counter on our recordings (with and without the axis swap) |
| [training/ankle_turn_check.py](training/ankle_turn_check.py) | Heading from the ankle gyro, to check turns (Step 0) |
| [training/check_turns.py](training/check_turns.py) | Runs the board's turn counter on the 8 Step 0 recordings with known turns |
| [training/update_policy.py](training/update_policy.py) | One command between walks: pull the walks, clean, train, put the policy on the board, check it |
| [training/clean_labels.py](training/clean_labels.py) | Places the turn labels from the board's counted turns (6 steps ahead), checks the taps, never edits raw files |
| [training/train_policy.py](training/train_policy.py) | Builds the lookup-table policy, prints it, tests it leaving one walk out |
| [training/tests/](training/tests/) | Fake walks with known answers (`fake_walks.py`) and the test (`test_pipeline.py`) |
| [uno_q/python/policy.py](uno_q/python/policy.py) | The lookup-table policy, shared by the board (`/api/predict`) and training |
| [training/requirements.txt](training/requirements.txt) | Laptop packages for label cleanup, training and the checks |
| `data/step0/`, `data/sensor_swap/` | Raw ankle recordings from Step 0 and the sensor-swap experiment |
| `data/live_test/` | Test walks saved by the board during the Live-mode test, and the page's download of walk 2 |
| [data/README.md](data/README.md) | Walk file naming, CSV columns and the 10-walk log |
| [data/RECORDING_CHECKLIST.md](data/RECORDING_CHECKLIST.md) | Step-by-step for testing the counter and recording each walk |
| [docs/process_log.md](docs/process_log.md) | Dated record of decisions and results |

## Setup and run

1. Laptop packages, in the repo's `.venv`:
   `pip install -r "Mohammed's Projects/HW9 - Behavior Cloning Navigation/training/requirements.txt"`
2. The board app is deployed from the terminal (`uno_q/README.md`, "How to deploy"). On walking
   days the board makes its own Wi-Fi network, NolopNav, and the phone opens
   http://10.42.0.1:7000 ("Walking days").
3. Walk and label with the page (`data/RECORDING_CHECKLIST.md`).
4. **Between walks, one command** pulls the walks from the board, cleans the labels, trains
   the policy and puts it on the board (no restart needed):

   ```
   .venv/bin/python "Mohammed's Projects/HW9 - Behavior Cloning Navigation/training/update_policy.py" --via usb
   ```

   (`--via nolop` with the laptop on NolopNav; `--no-deploy` to look at the table first;
   `--check-only` to check the board; `--with-code` after changing the app's code;
   `--code-only` to put the app on the board before the first walk, when there is nothing
   to train yet.) It prints
   the cleanup report, the table and a leave-one-walk-out test, and writes the table to
   `training/policy_report.md`. If the sensor readings have stopped, it prints the power-off
   steps.
5. Tests without the board: `python training/tests/test_pipeline.py` (fake walks with known
   answers, and the Live-test walks).

## Tuning and notes

- **Walk budget:** 10 full walks at most, both partners together, corrections included.
  The table in `data/README.md` is the official count, not the page's counter.
  Short counted test walks of the step counter aren't full route walks, so they don't
  use up the budget. The log is in [data/README.md](data/README.md).
- **Step counter:** Raph's CNN counter, not the HW7 counter: on Step 0's loops it was
  within 2 steps for both walkers and both sensors, while the HW7 counter undercounted
  Mohammed by 21-34% on either sensor. It is judged further from the route demos (both
  walkers on the same route). The numpy port matches his PyTorch version to within
  0.000001 per score, with the same strides on every recording. A numpy test with the
  same layer sizes ran 5 nets on one window in about 35 ms on the UNO Q (one window every
  250 ms); the port itself is timed on the board in build step 4.
- **Turns from the ankle:** Step 0 passed for both walkers: every 90° corner changed the
  heading by more than 60° within 2 s (lowest 71°), straight walking stayed under 23°.
  Walking corners read about 12% short (spot turns read the full angle); turns are only
  compared with 60°, so this isn't corrected. The waist sensor and long wire are dropped.
- **Gyro bias:** Raph's sensor reads about +34°/s on gx when still (Mohammed's: about 3°/s).
  It is measured for each axis while standing still for 5 s at the start of every walk
  and subtracted before taking the turn around "up"; measured as one number around "up",
  it depends on the leg's tilt and the loops came out 74° apart.
- **Board as its own Wi-Fi network:** possible, but while it is on, the laptop can't reach
  the board to deploy. The phone hotspot (already set up on the board) is the plan.
- **Still to decide:** start point, the exact route, and whether it stays inside a
  building or crosses campus.

## Credits

- **Raph's step counter**
  ([How many steps](https://github.com/RaphLemSol/ME193/tree/main/How%20many%20steps)):
  an ensemble of 1-D CNNs that finds each stride in the ankle data. **This is the step
  counter HW9 uses:** his network design, his trained weights and his counting rule,
  unchanged; here it is ported from PyTorch to plain numpy so it runs on the board
  (`uno_q/python/stride_counter.py`), with the axes swapped for our strap. Raph reviews
  the port.
- **Mohammed Almheiri:** the HW7 Step Recorder app and board setup this builds on (Step 0
  was recorded with it), the HW9 setup, Step 0 and the sensor-swap experiment.
- **Both partners** walk and label the route; the policy is trained on both partners' walks.
- The lookup-table policy follows the course's AnnaCode Table Cloner example (linked above).
