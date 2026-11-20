"""Check the board's live turn counter (uno_q/python/turns.py) on the 8 recordings with known
turns from Step 0 and the sensor swap.

Usage:  python check_turns.py        (from anywhere; needs numpy)

Each recording starts with 5 s of standing still, like a walk after Start, and is fed to
TurnCounter one reading at a time, exactly as on the board. Reported per recording:
- the turns counted, in order, against the turns walked (a 180° spot turn = two turns);
- when each was counted and how far the heading had changed then;
- how still the walker stood while the gyro's offset was measured;
- the biggest heading change within one window (3 s) on the straight stretches (read off
  the Step 0 heading plots), against the 60° a turn needs: the room left before walking
  could look like a turn.
"""
import os
import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "uno_q" / "python"))
import turns  # noqa: E402

DATA = HERE.parent / "data"
CASES = [  # file, turns walked (in order), straight stretches (s)
    ("step0/Raph_LoopLeft.csv", "LLLL", [[6, 14.2], [19.0, 23.5]]),
    ("step0/Raph_LoopRight.csv", "RRRR", [[6, 13.5], [21.5, 28]]),
    ("step0/Raph_SpotTurns.csv", "LLRR", []),
    ("step0/Mohammed_LoopLeft.csv", "LLLL", [[7, 12.8], [20, 24.6]]),
    ("step0/Mohammed_LoopRight.csv", "RRRR", [[7, 13.2], [20, 26.4]]),
    ("step0/Mohammed_SpotTurns.csv", "RRLL", []),
    ("sensor_swap/Raph_LoopLeft_MohammedSensor.csv", "LLLL", []),
    ("sensor_swap/Mohammed_LoopLeft_MohammedSensor.csv", "LLLL", []),
]

all_ok = True
window = int(turns.WINDOW_S * turns.RATE_HZ)
print(f"window {turns.WINDOW_S} s, turn = more than {turns.TURN_DEG}°")
for f, walked, straights in CASES:
    d = np.genfromtxt(DATA / f, delimiter=",", names=True, dtype=None, encoding="utf-8")
    tc = turns.TurnCounter()
    heading = []
    for row in np.c_[d["ax"], d["ay"], d["az"], d["gx"], d["gy"], d["gz"]]:
        tc.add(row)
        heading.append(tc.heading)
    heading = np.array(heading)
    got = "".join(e[1] for e in tc.events)
    ok = got == walked
    all_ok &= ok
    room = ""
    if straights:
        biggest = max(abs(heading[i + window] - heading[i])
                      for a, b in straights for i in range(int(a * 100), int(b * 100) - window))
        room = f" | straights: at most {biggest:.0f}° within {turns.WINDOW_S:.0f} s"
    when = ", ".join(f"{e[1]} at {e[0] / 100:.1f} s ({e[2]:+d}°)" for e in tc.events)
    print(f"{'OK  ' if ok else 'MISS'} {os.path.basename(f):38s} walked {walked}, counted {got or '-'}"
          f" | stood still: {tc.still_spread:.3f} g{room}\n       {when}")
print("ALL MATCH" if all_ok else "SOMETHING DIFFERS")
sys.exit(0 if all_ok else 1)
