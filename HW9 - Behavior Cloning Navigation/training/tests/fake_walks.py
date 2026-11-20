"""Fake walk files, made the way the page and the board make real ones, for testing the
label cleanup and the policy without walking.

simulate() walks a route stride by stride (the step counter goes up 2 at a time) and
writes the rows the page would save:
- the board counts each turn one stride into the corner (2 steps past the end of the
  stretch), and sets steps_at_last_turn there;
- each tick the page ends a Left/Right label once the turn count goes up (or after 10 steps
  with no turn), then saves a row if the steps changed;
- a tap saves a row at that moment with the tapped label and becomes the current label.
Columns and file names as the board writes them (uno_q/python/walks.py).
"""
import csv
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "uno_q" / "python"))
from walks import COLUMNS  # noqa: E402

STEP_M = 0.41
TURN_GIVE_UP_STEPS = 10      # as in the page


def simulate(walk, walker, segments, turn_dirs, taps, t0=1795030000000):
    """segments: steps in each stretch; turn_dirs: "Left"/"Right" between stretches;
    taps: {step: [labels tapped at that step, in order]}. Returns the rows."""
    ends = [sum(segments[:j + 1]) for j in range(len(segments))]
    counted_at = [ends[j] + 2 for j in range(len(turn_dirs))]
    rows, steps, left, right, at_turn = [], 0, 0, 0, 0
    label, turns_at_tap, steps_at_tap = "Straight", 0, 0

    def row(lbl):
        rows.append({"walk": walk, "walker": walker, "kind": "demo", "t_ms": t0 + len(rows) * 600,
                     "steps": steps, "distance_m": round(steps * STEP_M, 1),
                     "steps_since_turn": steps - at_turn, "distance_since_turn": round((steps - at_turn) * STEP_M, 1),
                     "turns": left + right, "turns_left": left, "turns_right": right,
                     "heading_deg": 0, "on_stairs": 0, "label": lbl, "predicted": ""})

    for _ in range(ends[-1] // 2 + 2):
        steps += 2
        for j, s in enumerate(counted_at):                      # the board counts a turn
            if steps == s:
                left, right = left + (turn_dirs[j] == "Left"), right + (turn_dirs[j] == "Right")
                at_turn = steps
        if label in ("Left", "Right") and (left + right > turns_at_tap or steps - steps_at_tap >= TURN_GIVE_UP_STEPS):
            label = "Straight"                                  # the page ends the turn label
        row(label)                                              # a new step: a row
        for tapped in taps.get(steps, []):                      # taps at this step
            label, turns_at_tap, steps_at_tap = tapped, left + right, steps
            row(tapped)
    return rows


def dagger(walk, walker, corrections, t0=1795040000000):
    """Correction rows: [(turns_left, turns_right, steps_since_turn, label, predicted)]."""
    return [{"walk": walk, "walker": walker, "kind": "dagger", "t_ms": t0 + i * 5000, "steps": 0,
             "distance_m": 0, "steps_since_turn": s, "distance_since_turn": round(s * STEP_M, 1),
             "turns": l + r, "turns_left": l, "turns_right": r, "heading_deg": 0, "on_stairs": 0,
             "label": lbl, "predicted": pred} for i, (l, r, s, lbl, pred) in enumerate(corrections)]


def write(folder, name, rows):
    os.makedirs(folder, exist_ok=True)
    with open(os.path.join(folder, name), "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=COLUMNS, lineterminator="\n")
        w.writeheader()
        w.writerows(rows)


def make_all(walks_dir):
    """The test walks (see test_pipeline.py for what each one checks)."""
    # Mohammed: stretches of 24, 14, 30 steps; turns Left then Right
    m = [24, 14, 30]
    write(walks_dir, "Mohammed_demo_W04.csv", simulate(4, "Mohammed", m, ["Left", "Right"], {
        20: ["Left"],                      # on time: 6 steps before the turn is counted (26)
        42: ["Right"],                     # late: turn 2 was counted at 40; stays on (page) until 52
        50: ["Stairs"], 56: ["Straight"],  # stairs, then back to straight
        68: ["Arrived"],                   # at the end
    }))
    # Raph: more steps per stretch (26, 16, 32); turns counted at 28 and 44
    r = [26, 16, 32]
    write(walks_dir, "Raph_demo_W05.csv", simulate(5, "Raph", r, ["Left", "Right"], {
        40: ["Left"],                      # turn 2 is a Right (counted at 44): tapped the other way
        54: ["Stairs"], 60: ["Straight"],  # the same stairs as Mohammed (10-15 steps into stretch 3)
        66: ["Left"], 68: ["Straight"],    # a mis-tap: no turn there
        74: ["Arrived"],
    }))                                    # and no tap at all for turn 1 (counted at 28)
    write(walks_dir, "Mohammed_dagger_W06.csv", dagger(6, "Mohammed", [
        (0, 0, 20, "Left", "Straight"),    # "turn now" where the policy said straight
        (1, 1, 30, "Arrived", "Straight"),
    ]))
    write(walks_dir, "Mohammed_demo_W07.csv", [])                 # started, no rows
    write(walks_dir, "Mohammed_demo_W01.csv", simulate(1, "Mohammed", [6], [], {2: ["Left"]}))  # a test walk
    Path(walks_dir).parent.joinpath("walks_excluded.txt").write_text(
        "# test walks, not route walks\nMohammed_demo_W01.csv  # live test\n")
