"""Test the label cleanup and the policy on fake walks with known answers, then on the real
Live-test walks. Run:  python training/tests/test_pipeline.py   (needs only numpy-free Python)

Fake walks (fake_walks.py): Mohammed's demo (on-time tap, late tap left on after the turn,
stairs, arrived), Raph's demo (more steps per stretch, an untapped turn, a tap the other
way, a mis-tap), a correction walk, an empty walk and an excluded test walk.
"""
import csv
import hashlib
import os
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE.parents[1] / "uno_q" / "python"))
import clean_labels  # noqa: E402
import train_policy  # noqa: E402
import policy as pol  # noqa: E402
import fake_walks  # noqa: E402

fails = 0


def check(name, ok, detail=""):
    global fails
    print(("PASS " if ok else "FAIL ") + name + (f"  [{detail}]" if not ok and detail else ""))
    fails += not ok


def labels(folder, name):
    with open(os.path.join(folder, name), newline="") as f:
        return {(int(float(r["steps"])), r["label"], r["raw_label"]) for r in csv.DictReader(f)}


def by_step(folder, name):
    with open(os.path.join(folder, name), newline="") as f:
        return {int(float(r["steps"])): r["label"] for r in csv.DictReader(f)}


with tempfile.TemporaryDirectory() as tmp:
    walks, cleaned = os.path.join(tmp, "data", "walks"), os.path.join(tmp, "data", "cleaned")
    fake_walks.make_all(walks)
    fingerprint = lambda: {n: hashlib.sha256(open(os.path.join(walks, n), "rb").read()).hexdigest() for n in os.listdir(walks)}
    before = fingerprint()
    res = clean_labels.clean_all(walks, cleaned, lead=6, quiet=True)

    # --- what gets cleaned ---
    check("test walk in walks_excluded.txt skipped, empty walk skipped",
          "Mohammed_demo_W01.csv" not in res and "Mohammed_demo_W07.csv" not in res, str(list(res)))
    check("raw files untouched (same fingerprints before and after)", fingerprint() == before)

    # --- Mohammed W04: turns counted at 26 (Left) and 40 (Right) ---
    m = by_step(cleaned, "Mohammed_demo_W04.csv")
    check("W04: Left on the 6 steps before turn 1 (20, 22, 24), Straight before",
          [m[s] for s in (18, 20, 22, 24, 26)] == ["Straight", "Left", "Left", "Left", "Straight"], str(m))
    check("W04: Right on the 6 steps before turn 2 (34, 36, 38)",
          [m[s] for s in (32, 34, 36, 38, 40)] == ["Straight", "Right", "Right", "Right", "Straight"], str(m))
    check("W04: the late Right left on after the turn (42-48) -> Straight",
          all(m[s] == "Straight" for s in (42, 44, 46, 48)), str(m))
    check("W04: Stairs kept (50-54), then Straight; Arrived kept at the end",
          [m[s] for s in (50, 52, 54, 56)] == ["Stairs"] * 3 + ["Straight"] and m[70] == "Arrived", str(m))
    c = res["Mohammed_demo_W04.csv"]
    check("W04 report: 2 turns, 1 on time (6 steps early), 1 late",
          (c["turns"], c["on_time"], c["early_by"], c["late"], c["untapped"]) == (2, 1, [6.0], 1, 0), str(c))
    check("W04: a tap and a step at the same moment merged into one row",
          sum(1 for s, l, raw in labels(cleaned, "Mohammed_demo_W04.csv") if s == 20) == 1)

    # --- Raph W05: turns counted at 28 (Left) and 44 (Right) ---
    r = by_step(cleaned, "Raph_demo_W05.csv")
    check("W05: untapped turn 1 still labeled Left (22-26)", [r[s] for s in (20, 22, 24, 26)] == ["Straight", "Left", "Left", "Left"], str(r))
    check("W05: turn 2 tapped Left, labeled Right from the board (38-42)", [r[s] for s in (36, 38, 40, 42, 44)] == ["Straight"] + ["Right"] * 3 + ["Straight"], str(r))
    check("W05: the mis-tap Left at 66 (no turn) -> Straight", r[66] == "Straight", str(r))
    c = res["Raph_demo_W05.csv"]
    check("W05 report: 1 untapped, 1 the other way, 1 with no turn",
          (c["untapped"], c["other_way"], c["no_turn"]) == (1, 1, 1), str(c))

    # --- excluding a walk later removes its old cleaned copy ---
    with open(os.path.join(os.path.dirname(walks), "walks_excluded.txt"), "a") as f:
        f.write("Raph_demo_W05.csv  # excluded after a first run\n")
    res2 = clean_labels.clean_all(walks, cleaned, lead=6, quiet=True)
    check("a walk excluded after a first run: its old cleaned copy is gone",
          "Raph_demo_W05.csv" not in os.listdir(cleaned) and "Raph_demo_W05.csv" not in res2)
    res = clean_labels.clean_all(walks, cleaned, lead=6, quiet=True)   # (W05 stays excluded below)
    with open(os.path.join(os.path.dirname(walks), "walks_excluded.txt"), "w") as f:
        f.write("Mohammed_demo_W01.csv\n")
    res = clean_labels.clean_all(walks, cleaned, lead=6, quiet=True)   # back to the full set

    # --- DAgger W06: kept as they are ---
    check("W06: corrections kept", res["Mohammed_dagger_W06.csv"]["corrections"] == 2)

    # --- the policy ---
    out = os.path.join(tmp, "policy.json")
    report = os.path.join(tmp, "policy_report.md")
    table = train_policy.train(cleaned, out, quiet=True, report=report)
    p = pol.Policy(out)
    ask = lambda l, r, s: p.predict({"turns_left": l, "turns_right": r, "on_stairs": 0, "steps_since_turn": s})
    check("policy: start of the walk -> Straight", ask(0, 0, 4)["action"] == "Straight")
    check("policy: near the end of stretch 1 -> Left", ask(0, 0, 24)["action"] == "Left", str(ask(0, 0, 24)))
    check("policy: near the end of stretch 2 -> Right", ask(1, 0, 12)["action"] == "Right", str(ask(1, 0, 12)))
    check("policy: on stretch 3 at the stairs -> Stairs", ask(1, 1, 12)["action"] == "Stairs", str(ask(1, 1, 12)))
    check("policy: end of stretch 3 -> Arrived", ask(1, 1, 30)["action"] == "Arrived", str(ask(1, 1, 30)))
    over = ask(0, 0, 80)
    check("policy: walked past the end of stretch 1 -> nearest known (Left)",
          over["how"] == "nearest" and over["action"] == "Left", str(over))
    check("policy: a correction (counted 3x) outvotes demos in its situation",
          table[(0, 0, 0, 5)]["Left"] >= 3)
    check("policy.json and the report written", os.path.exists(out) and os.path.exists(report))

# --- the real Live-test walks (steps from swinging the board, turns from rotating it) ---
with tempfile.TemporaryDirectory() as tmp:
    live = HERE.parents[1] / "data" / "live_test"
    res = clean_labels.clean_all(str(live), tmp, lead=6, quiet=True)
    check("real Live-test walks clean without errors",
          "Mohammed_demo_W02.csv" in res and "Mohammed_demo_W03.csv" in res, str(res))
    check("W02 (Left tapped, no turn counted): flagged, labeled Straight",
          res["Mohammed_demo_W02.csv"]["no_turn"] == 1, str(res["Mohammed_demo_W02.csv"]))
    check("W03 (table rotation: L then R counted at 0 steps): 2 turns found",
          res["Mohammed_demo_W03.csv"]["turns"] == 2, str(res["Mohammed_demo_W03.csv"]))

# --- The 2026-11-19 warning rule (Route B): Stairs tapped right up to a corner, and a row saved
# at the turn step just before the count arrived. Both must say Left (lead 6, turn counted at 30).
def row(steps, turns_left, label, since=None):
    since = steps if since is None else since
    return {"walk": "9", "walker": "Raph", "kind": "demo", "t_ms": str(steps), "steps": str(steps),
            "distance_m": "0", "steps_since_turn": str(since), "distance_since_turn": "0",
            "turns": str(turns_left), "turns_left": str(turns_left), "turns_right": "0",
            "heading_deg": "0", "on_stairs": "0", "label": label, "predicted": ""}

raw_rule = ([row(s, 0, "Straight") for s in (2, 4)] + [row(s, 0, "Stairs") for s in range(6, 30, 2)]
            + [row(30, 0, "Stairs"), row(32, 1, "Straight", since=2), row(34, 1, "Arrived", since=4)])
got = {int(r["steps"]): r["label"] for r in clean_labels.clean_demo(raw_rule, 6)[0]}
check("rule: Stairs kept before the warning (6-22)", all(got[s] == "Stairs" for s in range(6, 24, 2)), str(got))
check("rule: the Left warning wins over Stairs taps (24-28)", [got[s] for s in (24, 26, 28)] == ["Left"] * 3, str(got))
check("rule: the row at the turn step before the count says Left (30)", got[30] == "Left", str(got))
check("rule: after the counted turn Straight, Arrived kept", got[32] == "Straight" and got[34] == "Arrived", str(got))

# --- walks_trim.txt (2026-11-19): use only the first part of a walk. Labels come from the whole
# walk (the Left warning before the cut still knows about the turn at 30), then rows are cut.
with tempfile.TemporaryDirectory() as tmp:
    walks, cleaned = os.path.join(tmp, "data", "walks"), os.path.join(tmp, "data", "cleaned")
    os.makedirs(walks)
    dagger = [dict(row(s, 0, "Left"), kind="dagger", predicted="Straight") for s in (26, 44)]
    for name, rows_ in (("Raph_demo_W09.csv", raw_rule), ("Raph_dagger_W10.csv", dagger)):
        with open(os.path.join(walks, name), "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=list(raw_rule[0]), lineterminator="\n")
            w.writeheader()
            w.writerows(rows_)
    with open(os.path.join(tmp, "data", "walks_trim.txt"), "w") as f:
        f.write("Raph_demo_W09.csv  <=28  # test\nRaph_dagger_W10.csv  <40  # test\n")
    clean_labels.clean_all(walks, cleaned, lead=6, quiet=True)
    t9 = by_step(cleaned, "Raph_demo_W09.csv")
    t10 = by_step(cleaned, "Raph_dagger_W10.csv")
    check("trim: demo kept up to step 28 only", max(t9) == 28 and min(t9) == 2, str(sorted(t9)))
    check("trim: labels from the whole walk (24-28 still Left)", [t9[s] for s in (24, 26, 28)] == ["Left"] * 3, str(t9))
    check("trim: DAgger correction after the cut dropped (<40)", sorted(t10) == [26], str(t10))
    check("trim: raw walk files unchanged", len(open(os.path.join(walks, "Raph_demo_W09.csv")).read().splitlines()) == len(raw_rule) + 1)

print("ALL PASSED" if not fails else f"{fails} FAILED")
sys.exit(1 if fails else 0)
