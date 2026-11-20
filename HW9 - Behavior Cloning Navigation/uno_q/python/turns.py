"""Counting turns from the ankle gyro, live (build step 9).

The method of training/ankle_turn_check.py (checked in Step 0), one reading at a time:

1. Gyro offset: for the first 5 s after a reset (the walker stands still after Start), the
   average of each gyro axis (gx, gy, gz) is measured; from then on it is subtracted from
   every reading. Measured per axis, not as one number around "up": Step 0 showed the one
   number depends on how the leg is tilted. No turns are counted until it is measured.
2. "Up": the accelerometer averaged over the last 1 s (the leg's swing averages out). Live,
   only the past second can be averaged (the script averaged half a second either side).
3. Heading: the turning rate around "up" (the offset-free gyro reading along "up", deg/s)
   added up reading by reading, 10 ms each. A reading that isn't real (lost or bad) adds
   nothing but still counts as 10 ms of time. Left turns are positive (as in Step 0).
4. A turn: the heading has changed by more than TURN_DEG (60°) within the last WINDOW_S
   (3 s), measured from the heading 3 s ago. Right after a turn, it is measured from that
   turn instead, as quarter turns: a turn is counted at 60° but a corner goes on to about
   90°, so another turn in the SAME direction needs 60° more beyond 30° past where the last
   one was counted; a turn the OTHER way is measured from where the last one was counted.
   So the rest of a corner isn't counted again, the next corner can be (even 1 s later:
   corners came 1-1.5 s apart in Step 0), and a 180° turn counts as two turns in the same
   direction (a U-turn = two lefts or two rights).

Why 3 s, not 2 s: one of Mohammed's corners took about 4 s (49° -> 119° with a pause), so no
2 s stretch reached 60°; widening the window catches it without lowering the 60° (the
walking wobble stays far below it). Checked on the 8 Step 0 recordings
(training/check_turns.py).
"""
from collections import deque

import numpy as np

RATE_HZ = 100
BIAS_S = 5.0            # stand still this long after a reset
UP_S = 1.0              # average the accelerometer over the last 1 s for "up"
WINDOW_S = 3.0          # a turn = more than TURN_DEG within this long
QUARTER_REST_DEG = 30.0 # a corner goes on about this far past the point where it is counted (60° -> 90°)
TURN_DEG = 60.0


class TurnCounter:
    def __init__(self):
        self.up_n = int(UP_S * RATE_HZ)
        self.window_n = int(WINDOW_S * RATE_HZ)
        self.reset()

    def reset(self):
        """A new walk: measure the offset again, heading and counts back to 0."""
        self.bias_sum = np.zeros(3)
        self.bias_n = 0
        self.bias_acc = []              # accelerometer while measuring, to check stillness
        self.bias = None                # per-axis gyro offset, once measured
        self.still_spread = None        # accelerometer spread (g) while it was measured
        self.acc = deque(maxlen=self.up_n)
        self.heading = 0.0
        self.history = deque(maxlen=self.window_n + 1)   # heading at each reading, last 3 s
        self.index = 0                  # readings since the reset
        self.turn_index = None          # reading at which the last turn was counted
        self.turn_heading = 0.0         # heading then
        self.turn_dir = 0               # +1 left, -1 right (the last turn)
        self.left = self.right = 0
        self.events = []                # (reading index, "L"/"R", heading change) for the log

    def add(self, values, ok=True):
        """One reading (ax ay az in g, gx gy gz in deg/s). Returns "L", "R" or None."""
        self.index += 1
        new_turn = None
        if ok:
            acc, gyro = np.asarray(values[:3], float), np.asarray(values[3:6], float)
            self.acc.append(acc)
            if self.bias is None:
                # 1. still measuring the gyro's offset
                self.bias_sum += gyro
                self.bias_n += 1
                self.bias_acc.append(acc)
                if self.bias_n >= BIAS_S * RATE_HZ:
                    self.bias = self.bias_sum / self.bias_n
                    self.still_spread = float(np.std(self.bias_acc, axis=0).max())
                    self.bias_acc = []
            else:
                # 2-3. "up" from the last 1 s, turning rate around it, added up
                up = np.mean(self.acc, axis=0)
                norm = np.linalg.norm(up)
                if norm > 0:
                    self.heading += float((gyro - self.bias) @ (up / norm)) / RATE_HZ
        self.history.append((self.index, self.heading))
        if self.bias is not None and len(self.history) > 1:
            # 4. measured from the heading 3 s ago, or from the last turn if it was more recent
            start_index, start_heading = self.history[0]
            direction, change = 0, 0.0
            if self.turn_index is not None and self.turn_index > start_index:
                d = self.turn_dir
                same = d * (self.heading - (self.turn_heading + QUARTER_REST_DEG * d))
                other = -d * (self.heading - self.turn_heading)
                if same > TURN_DEG:
                    direction, change = d, same
                elif other > TURN_DEG:
                    direction, change = -d, other
            else:
                change = self.heading - start_heading
                if abs(change) > TURN_DEG:
                    direction, change = (1 if change > 0 else -1), abs(change)
            if direction:
                new_turn = "L" if direction > 0 else "R"
                if new_turn == "L":
                    self.left += 1
                else:
                    self.right += 1
                self.turn_index, self.turn_heading, self.turn_dir = self.index, self.heading, direction
                self.events.append((self.index, new_turn, round(direction * change)))
        return new_turn

    @property
    def ready(self):
        """True once the gyro's offset is measured (turns can be counted)."""
        return self.bias is not None
