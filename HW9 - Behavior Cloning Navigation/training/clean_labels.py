"""Clean the walk labels before training. Raw walk files are never changed.

Usage:  python clean_labels.py [--lead 6] [--walks ../data/walks] [--out ../data/cleaned]

Reads every walk CSV in --walks (the board's files, columns in data/README.md), skips the
ones listed in ../data/walks_excluded.txt, and writes a cleaned copy of each to --out with
two more columns: raw_label (what was tapped) and note (why a label changed). Prints a
report per walk.

Why clean: labeling while walking is hard. Turn taps come early, late or not at all, and a
Left can stay on after the turn. The board's turn counter (the ankle gyro, checked in
Step 0) knows exactly at which step each turn was counted, so it places the turn labels,
and the taps are only used to check it.

Demo walks (kind = demo):
1. Merge rows that describe the same moment (same steps, turns and stairs; a tap and a step
   at the same step count): the last one's label wins (the walker's latest decision).
2. Find each counted turn: the row where turns_left or turns_right goes up. It was counted
   at step S = steps - steps_since_turn of that row, in that direction.
3. Label: Left/Right on the rows from LEAD steps before S up to S (steps S-LEAD .. S, still
   before the turn was counted; this also wins over a Stairs tap): the instruction comes LEAD steps ahead. Every other row is
   Straight, except rows tapped Stairs or Arrived, which keep their tap. This also fixes a
   Left/Right left on after the turn: after S it is Straight.
4. Check the taps: every Left/Right tap (where a Left/Right run of rows starts) is matched to
   the nearest counted turn in the same direction, from TAP_EARLY steps before it to
   TAP_LATE steps after it. Reported: on-time taps (with how many steps early), late taps
   (just after the turn was counted), turns with no tap, taps the other way, and taps with
   no counted turn nearby (the board missed a turn, or a mis-tap: that walk deserves a
   look).

DAgger walks (kind = dagger) hold only the correction taps: each is kept as it is (the
walker's correct action at that moment), since there is no step-by-step series to place.
"""
import argparse
import csv
import os
from pathlib import Path

HERE = Path(__file__).resolve().parent
TAP_EARLY = 20      # a turn tap this many steps before the counted turn still belongs to it
TAP_LATE = 4        # ... or this many steps after it (a late tap)
TURNS = ("Left", "Right")


def num(row, col):
    """A numeric column as a number (the CSV holds text)."""
    v = row.get(col, "")
    return float(v) if v not in ("", None) else 0.0


def merge_moments(rows):
    """Step 1: one row per moment (same steps, turns_left, turns_right, on_stairs in a row);
    the last row's label wins."""
    out = []
    for row in rows:
        key = tuple(num(row, c) for c in ("steps", "turns_left", "turns_right", "on_stairs"))
        if out and out[-1][0] == key:
            out[-1] = (key, dict(row))      # copies: the raw rows are never changed
        else:
            out.append((key, dict(row)))
    return [r for _, r in out]


def counted_turns(rows):
    """Step 2: [(row index, step S at which it was counted, "Left"/"Right", turn number)]."""
    turns, prev = [], (0.0, 0.0)
    for i, row in enumerate(rows):
        cur = (num(row, "turns_left"), num(row, "turns_right"))
        for _ in range(int(cur[0] - prev[0])):
            turns.append((i, num(row, "steps") - num(row, "steps_since_turn"), "Left", len(turns) + 1))
        for _ in range(int(cur[1] - prev[1])):
            turns.append((i, num(row, "steps") - num(row, "steps_since_turn"), "Right", len(turns) + 1))
        prev = cur
    return turns


def turn_taps(raw_rows):
    """Where each Left/Right run of rows starts in the raw rows (a tap): [(steps, label)]."""
    taps, prev_label = [], None
    for row in raw_rows:
        label = row["label"]
        if label in TURNS and label != prev_label:
            taps.append((num(row, "steps"), label))
        prev_label = label
    return taps


def clean_demo(raw_rows, lead):
    """Steps 1-4 for one demo walk. Returns (cleaned rows, report lines, counts)."""
    rows = merge_moments(raw_rows)
    turns = counted_turns(rows)
    # Step 3: labels
    # Rule chosen 2026-11-19 (Route B, see docs/process_log.md): the turn warning runs from LEAD
    # steps before each counted turn up to AND INCLUDING the step at which it was counted, as
    # long as the row doesn't show the turn yet (n-1 turns done), and it wins over a Stairs tap.
    # Before, the window stopped one step short (steps < S), so the row saved at the turn step
    # just before the count arrived said Straight; those rows made Straight win or tie at the end
    # of a stretch. And Stairs taps that ran up to a corner (bottom of the stairs, then Left) hid
    # the Left warning completely. Arrived taps are always kept.
    for row in rows:
        row["raw_label"] = row["label"]
        row["note"] = ""
        steps = num(row, "steps")
        done = num(row, "turns_left") + num(row, "turns_right")
        warning = None
        for _, s, direction, n in turns:
            # turn n's warning: LEAD steps before it up to its step S, while n-1 turns are done
            if done == n - 1 and s - lead <= steps <= s:
                warning = direction
        if row["label"] == "Arrived" or (row["label"] == "Stairs" and warning is None):
            continue                                    # keep the tap
        new = warning or "Straight"
        if new != row["label"]:
            row["note"] = (("turn warning wins over the Stairs tap" if row["label"] == "Stairs"
                            else f"turn label {lead} steps ahead of the counted turn") if new in TURNS
                           else "after the counted turn" if row["label"] in TURNS else "not a turn")
            row["label"] = new
    # Step 4: check the taps against the counted turns
    report, counts = [], {"turns": len(turns), "on_time": 0, "late": 0, "untapped": 0,
                          "other_way": 0, "no_turn": 0, "early_by": []}
    taps = turn_taps(raw_rows)
    used, other_used = set(), set()     # turns matched by a tap the same way / the other way
    for steps, label in taps:
        near = [(abs(s - steps), k) for k, (_, s, d, _) in enumerate(turns)
                if k not in used and s - TAP_EARLY <= steps <= s + TAP_LATE]
        same = [(dist, k) for dist, k in near if turns[k][2] == label]
        if same:
            k = min(same)[1]
            used.add(k)
            s = turns[k][1]
            if steps < s:
                counts["on_time"] += 1
                counts["early_by"].append(s - steps)
            else:
                counts["late"] += 1
                report.append(f"  late tap: {label} at step {steps:.0f}, the turn was counted at step {s:.0f}")
        elif near:
            counts["other_way"] += 1
            k = min(near)[1]
            other_used.add(k)
            report.append(f"  tap the other way: {label} at step {steps:.0f}, the board counted "
                          f"{turns[k][2]} at step {turns[k][1]:.0f} (label follows the board)")
        else:
            counts["no_turn"] += 1
            report.append(f"  CHECK: {label} tapped at step {steps:.0f} but no turn counted nearby "
                          f"(the board missed a turn, or a mis-tap); labeled Straight")
    for k, (_, s, d, n) in enumerate(turns):
        if k not in used and k not in other_used:
            counts["untapped"] += 1
            report.append(f"  no tap for turn {n} ({d}, counted at step {s:.0f}); labeled from the board")
    return rows, report, counts


def clean_dagger(raw_rows):
    """Correction taps are kept as they are."""
    for row in raw_rows:
        row["raw_label"], row["note"] = row["label"], "correction"
    return raw_rows, [], {"corrections": len(raw_rows),
                          "changed": sum(r["label"] != r.get("predicted", "") for r in raw_rows)}


def excluded(walks_dir):
    """Walk files listed in data/walks_excluded.txt (one per line, # comments), e.g. test walks.
    Only for the board's walks (a folder named walks/, next to the list); other folders, such
    as data/live_test/, are cleaned whole."""
    path = Path(walks_dir).parent / "walks_excluded.txt"
    if Path(walks_dir).name != "walks" or not path.exists():
        return set()
    return {line.split("#")[0].strip() for line in path.read_text().splitlines() if line.split("#")[0].strip()}


def trims(walks_dir):
    """Walks used only in part, from data/walks_trim.txt (next to walks_excluded.txt): one walk
    per line, the file name, then which rows to keep by step count ("<40" = steps below 40,
    "<=36" = up to 36), then # and why. Labels are worked out on the WHOLE walk first (so a
    turn warning before the cut still knows about the turn after it); only then are the later
    rows dropped. Raw files are never changed. Returns {file name: (operator, step)}."""
    path = Path(walks_dir).parent / "walks_trim.txt"
    if Path(walks_dir).name != "walks" or not path.exists():
        return {}
    out = {}
    for line in path.read_text().splitlines():
        parts = line.split("#")[0].split()
        if not parts:
            continue
        if len(parts) != 2 or not parts[1].startswith(("<=", "<")):
            raise ValueError(f"walks_trim.txt: can't read {line!r} (expected: name.csv <40)")
        op = "<=" if parts[1].startswith("<=") else "<"
        out[parts[0]] = (op, float(parts[1][len(op):]))
    return out


def keep_row(row, trim):
    """Whether a cleaned row stays, given the walk's trim (None = keep everything)."""
    if trim is None:
        return True
    op, limit = trim
    steps = num(row, "steps")
    return steps <= limit if op == "<=" else steps < limit


def clean_all(walks_dir, out_dir, lead, quiet=False):
    """Clean every walk in walks_dir into out_dir. Returns {file name: counts}."""
    os.makedirs(out_dir, exist_ok=True)
    for old in os.listdir(out_dir):       # start empty: a walk excluded since the last run must
        if old.endswith(".csv"):          # not keep training the policy from an old cleaned copy
            os.remove(os.path.join(out_dir, old))
    skip = excluded(walks_dir)
    cuts = trims(walks_dir)
    results = {}
    for name in sorted(os.listdir(walks_dir)):
        if not name.endswith(".csv"):
            continue
        if name in skip:
            if not quiet:
                print(f"{name}: skipped (in walks_excluded.txt)")
            continue
        with open(os.path.join(walks_dir, name), newline="") as f:
            reader = csv.DictReader(f)
            columns, raw = reader.fieldnames, list(reader)
        if not raw:
            if not quiet:
                print(f"{name}: empty, skipped")
            continue
        kind = raw[0]["kind"]
        rows, report, counts = clean_demo([dict(r) for r in raw], lead) if kind == "demo" else clean_dagger([dict(r) for r in raw])
        if name in cuts:                      # partly used: labels from the whole walk, then cut
            before = len(rows)
            rows = [r for r in rows if keep_row(r, cuts[name])]
            op, limit = cuts[name]
            report.append(f"  trimmed (walks_trim.txt): kept rows with steps {op} {limit:g}, "
                          f"dropped {before - len(rows)} of {before}")
        with open(os.path.join(out_dir, name), "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=list(columns) + ["raw_label", "note"], lineterminator="\n")
            w.writeheader()
            w.writerows(rows)
        changed = sum(r["label"] != r["raw_label"] for r in rows)
        results[name] = dict(counts, rows=len(rows), changed=changed, kind=kind)
        if not quiet:
            if kind == "demo":
                early = counts["early_by"]
                print(f"{name}: {len(raw)} rows -> {len(rows)} moments, {changed} labels changed; "
                      f"{counts['turns']} turns counted, taps on time {counts['on_time']}"
                      f"{f' (median {sorted(early)[len(early) // 2]:.0f} steps early)' if early else ''}, "
                      f"late {counts['late']}, untapped {counts['untapped']}, other way {counts['other_way']}, "
                      f"no turn {counts['no_turn']}")
                for line in report:
                    print(line)
            else:
                print(f"{name}: {counts['corrections']} corrections kept ({counts['changed']} differ from the policy)")
                for line in report:
                    print(line)
    return results


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--lead", type=float, default=6, help="steps of warning before a counted turn (default 6)")
    p.add_argument("--walks", default=str(HERE.parent / "data" / "walks"))
    p.add_argument("--out", default=str(HERE.parent / "data" / "cleaned"))
    a = p.parse_args()
    clean_all(a.walks, a.out, a.lead)
