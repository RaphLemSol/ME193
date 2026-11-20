"""Train the lookup-table policy from the cleaned walks, print it, and save it for the board.

Usage:  python train_policy.py [--cleaned ../data/cleaned] [--out ../uno_q/python/policy.json]

1. Reads every cleaned walk (training/clean_labels.py writes them; both walkers, demo and
   correction walks).
2. Builds the table with uno_q/python/policy.py (the same code the board runs): per
   situation (left turns, right turns, stairs, steps since the last turn in buckets of 4),
   how often each action was chosen; correction rows count 3 times.
3. Tests it fairly, leaving one walk out at a time: trained on the other walks, how often
   does the table give that walk's cleaned label? (Only with 2 or more demo walks.)
4. Prints the table, one line per stretch of the route (after how many left/right turns),
   writes the same text to training/policy_report.md, and saves policy.json.
"""
import argparse
import csv
import os
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "uno_q" / "python"))
import policy as pol  # noqa: E402

SHORT = {"Straight": "S", "Left": "L", "Right": "R", "Stairs": "St", "Arrived": "A"}


def load_walks(folder):
    """{file name: rows} for every cleaned walk CSV."""
    walks = {}
    for name in sorted(os.listdir(folder)):
        if name.endswith(".csv"):
            with open(os.path.join(folder, name), newline="") as f:
                rows = list(csv.DictReader(f))
            if rows:
                walks[name] = rows
    return walks


def table_text(table, bucket):
    """The table, readable: one line per stretch, each bucket as "steps a-b: action (votes)"."""
    lines = []
    for stretch in sorted({k[:3] for k in table}, key=lambda s: (s[0] + s[1], s)):
        left, right, stairs = stretch
        cells = []
        for k in sorted(k for k in table if k[:3] == stretch):
            c = table[k]
            votes = " ".join(f"{SHORT[a]}{n}" for a, n in sorted(c.items(), key=lambda x: -x[1]))
            cells.append(f"{k[3] * bucket}-{k[3] * bucket + bucket - 1}: {pol.best(c)} ({votes})")
        lines.append(f"After {left} left, {right} right{', on stairs' if stairs else ''} turns:\n    "
                     + "\n    ".join(cells))
    return "\n".join(lines)


def leave_one_out(walks, bucket):
    """For each demo walk: train on all the others, predict its rows. Returns lines of text."""
    demos = [n for n, rows in walks.items() if rows[0]["kind"] == "demo"]
    if len(demos) < 2:
        return ["Leave-one-walk-out test: needs at least 2 demo walks."]
    lines, total_ok, total = [], 0, 0
    for name in demos:
        others = [r for n, rows in walks.items() if n != name for r in rows]
        table = pol.build_table(others, bucket)
        ok = sum(pol.predict_from(table, r, bucket)["action"] == r["label"] for r in walks[name])
        turn_rows = [r for r in walks[name] if r["label"] in ("Left", "Right")]
        turn_ok = sum(pol.predict_from(table, r, bucket)["action"] == r["label"] for r in turn_rows)
        lines.append(f"  {name}: {ok}/{len(walks[name])} rows agree; turn rows {turn_ok}/{len(turn_rows)}")
        total_ok, total = total_ok + ok, total + len(walks[name])
    lines.insert(0, f"Leave-one-walk-out test: {total_ok}/{total} rows agree ({100 * total_ok / total:.0f}%)")
    return lines


def train(cleaned, out, bucket=pol.BUCKET, quiet=False, report=HERE / "policy_report.md"):
    walks = load_walks(cleaned)
    if not walks:
        raise SystemExit(f"No cleaned walks in {cleaned}: run clean_labels.py first (and check data/walks/).")
    rows = [r for rs in walks.values() for r in rs]
    table = pol.build_table(rows, bucket)
    info = {"trained": time.strftime("%Y-%m-%d %H:%M"), "walks": list(walks), "bucket": bucket,
            "rows": len(rows), "dagger_weight": pol.DAGGER_WEIGHT}
    pol.save(table, out, info)
    text = "\n".join([
        f"# Policy table ({info['trained']})",
        "",
        f"From {len(walks)} walks ({len(rows)} rows): " + ", ".join(walks),
        f"Steps since the last turn in buckets of {bucket}; votes per action (correction rows count {pol.DAGGER_WEIGHT}).",
        "S = Straight, L = Left, R = Right, St = Stairs, A = Arrived. A situation not in the table "
        "uses the nearest one (same stretch first).",
        "",
        "```",
        table_text(table, bucket),
        "```",
        "",
        *leave_one_out(walks, bucket),
    ])
    Path(report).write_text(text + "\n")
    if not quiet:
        print(text)
        print(f"\nSaved {out} ({len(table)} situations) and {report}")
    return table


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--cleaned", default=str(HERE.parent / "data" / "cleaned"))
    p.add_argument("--out", default=str(HERE.parent / "uno_q" / "python" / "policy.json"))
    p.add_argument("--bucket", type=int, default=pol.BUCKET)
    a = p.parse_args()
    train(a.cleaned, a.out, a.bucket)
