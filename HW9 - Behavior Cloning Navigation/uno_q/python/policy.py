"""The navigation policy: a lookup table, like the AnnaCode Table Cloner.

Used in two places, so they always agree:
- on the board, by GET /api/predict (main.py): what should the walker do now?
- on the laptop, by training/train_policy.py, which builds the table from the cleaned walks
  and writes policy.json next to this file.

A situation is (turns_left, turns_right, on_stairs, bucket), where bucket groups the steps
since the last turn: bucket = steps_since_turn // BUCKET (BUCKET = 4: steps 0-3, 4-7, ...).
Training counts, per situation, which action the cleaned labels chose (demo rows count 1,
correction rows count DAGGER_WEIGHT); the answer is the most common action.

A situation never seen borrows from the nearest one that was: distance = 100 x the
difference in turns (being on the wrong stretch of the route matters most) + 50 if stairs
differ + the difference in buckets. So it looks along the same stretch first; a walker who
walks past the end of a stretch keeps getting that stretch's last answer (usually the turn).
"""
import json
import os
from collections import Counter

BUCKET = 4              # steps per bucket of "steps since the last turn"
DAGGER_WEIGHT = 3       # a correction counts like this many demo rows
ACTIONS = ["Straight", "Left", "Right", "Stairs", "Arrived"]


def situation(obs, bucket=BUCKET):
    """The table key for an observation (dict with steps_since_turn, turns_left, turns_right,
    on_stairs; numbers or numeric text)."""
    f = lambda k: float(obs.get(k, 0) or 0)
    return (int(f("turns_left")), int(f("turns_right")), int(f("on_stairs")),
            int(max(f("steps_since_turn"), 0) // bucket))


def key_text(s):
    """(1, 0, 0, 5) -> "1,0,0,5" (JSON keys must be text)."""
    return ",".join(str(v) for v in s)


def distance(a, b):
    """How far apart two situations are (see the module docstring)."""
    return 100 * (abs(a[0] - b[0]) + abs(a[1] - b[1])) + 50 * abs(a[2] - b[2]) + abs(a[3] - b[3])


def build_table(rows, bucket=BUCKET, dagger_weight=DAGGER_WEIGHT):
    """rows: cleaned rows (dicts with the observation columns, label and kind). Returns
    {situation: Counter(action -> weight)}."""
    table = {}
    for row in rows:
        if row["label"] not in ACTIONS:
            continue
        w = dagger_weight if row.get("kind") == "dagger" else 1
        table.setdefault(situation(row, bucket), Counter())[row["label"]] += w
    return table


def best(counter):
    """The most common action; ties go to the earlier action in ACTIONS (Straight first)."""
    return max(ACTIONS, key=lambda a: (counter.get(a, 0), -ACTIONS.index(a)))


def predict_from(table, obs, bucket=BUCKET):
    """The table's answer for an observation: {"action", "how" (exact / nearest / none),
    "situation", "used" (the situation answered from), "counts"}."""
    s = situation(obs, bucket)
    if not table:
        return {"action": None, "how": "none", "situation": key_text(s), "used": None, "counts": {}}
    if s in table:
        used, how = s, "exact"
    else:
        used, how = min(table, key=lambda k: (distance(s, k), k)), "nearest"
    return {"action": best(table[used]), "how": how, "situation": key_text(s),
            "used": key_text(used), "counts": dict(table[used])}


def save(table, path, info):
    """Write the table (and how it was trained) to policy.json."""
    data = {"bucket": info.get("bucket", BUCKET), "info": info,
            "table": {key_text(k): dict(v) for k, v in sorted(table.items())}}
    tmp = str(path) + ".tmp"
    with open(tmp, "w") as f:
        json.dump(data, f, indent=1)
    os.replace(tmp, path)


class Policy:
    """policy.json on the board. It is read again whenever the file changes, so a new policy
    can be copied over without restarting the app (no reflash, no power-off)."""

    def __init__(self, path, logger=None):
        self.path, self.logger = path, logger
        self.mtime, self.table, self.bucket, self.info = None, {}, BUCKET, {}

    def refresh(self):
        try:
            mtime = os.path.getmtime(self.path)
        except OSError:
            self.table, self.mtime = {}, None            # no policy yet
            return
        if mtime == self.mtime:
            return
        with open(self.path) as f:
            data = json.load(f)
        self.bucket = int(data.get("bucket", BUCKET))
        self.info = data.get("info", {})
        self.table = {tuple(int(v) for v in k.split(",")): Counter(c) for k, c in data["table"].items()}
        self.mtime = mtime
        if self.logger:
            self.logger.info(f"Policy loaded: {len(self.table)} situations, trained "
                             f"{self.info.get('trained', '?')} on {len(self.info.get('walks', []))} walks")

    def predict(self, obs):
        self.refresh()
        return predict_from(self.table, obs, self.bucket)
