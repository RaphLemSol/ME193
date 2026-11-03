"""
Train the neural-net step counter, test how good it is, and fit the
distance estimate.

    python train_steps.py               # ~15 min on a laptop CPU
    python train_steps.py --quick       # ~4 min, fewer training steps (for trying things out)

1. Labels every recording in data/ (step_net.label_strides). Recordings you
   counted the steps of (record.py asks) are the real ground truth.
2. Cross-validation: each recording is counted by a net that never trained
   on it, using exactly the live counter (step_net.StepCounter). That gives
   the uncertainty analysis: how far off the count is, how often it misses or
   invents a stride, and how many fake steps it counts while you stand or bike.
   The same is done for a plain peak counter (no AI), for comparison.
3. Distance: recordings where you entered the distance are used to fit stride
   length, and each one is tested with a fit made without it.
4. Trains ENSEMBLE nets on all the data for live_steps.py and saves them to
   models/step_net.pt, plus models/steps_results.png and models/step_report.json.
"""

import argparse
import json
import sys
import time

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

import gait_config as cfg
import step_net as sn


def assign_folds(recs, k):
    """Spread each activity's recordings over the k folds."""
    order = sorted(range(len(recs)), key=lambda i: (recs[i]["activity"], recs[i]["name"]))
    folds = np.zeros(len(recs), int)
    for j, i in enumerate(order):
        folds[i] = j % k
    return folds


def error_stats(err, ref):
    """Count error summary. err = counted - true, ref = true count."""
    err, ref = np.asarray(err, float), np.asarray(ref, float)
    rel = err / ref
    out = {"n": len(err), "bias": float(err.mean()), "mae": float(np.abs(err).mean()),
           "sd": float(err.std(ddof=1)) if len(err) > 1 else float("nan"),
           "rel_bias": float(rel.mean()), "mape": float(np.abs(rel).mean()),
           "rel_sd": float(rel.std(ddof=1)) if len(rel) > 1 else float("nan")}
    if len(err) >= 3:                                  # 95% CI of the mean % error, by bootstrap
        rng = np.random.default_rng(0)
        boot = [np.abs(rel[rng.integers(0, len(rel), len(rel))]).mean() for _ in range(5000)]
        out["mape_ci"] = [float(np.percentile(boot, 2.5)), float(np.percentile(boot, 97.5))]
    return out


def print_stats(title, s):
    print(f"\n{title}  ({s['n']} recordings)")
    print(f"  average error (bias)    {s['bias']:+.1f} steps  ({s['rel_bias']:+.1%})")
    print(f"  average size of error   {s['mae']:.1f} steps  ({s['mape']:.1%})")
    if "mape_ci" in s:
        print(f"    95% confidence range  {s['mape_ci'][0]:.1%} to {s['mape_ci'][1]:.1%}")
    if s["n"] > 1:
        print(f"  spread of the error     {s['sd']:.1f} steps  ({s['rel_sd']:.1%})")
        print(f"  95% of counts land within {s['bias'] - 1.96 * s['sd']:+.1f} to "
              f"{s['bias'] + 1.96 * s['sd']:+.1f} steps of the truth (limits of agreement)")


def fit_distance(rows, kind):
    """Least squares for stride length = a + b * feature, so that the sum
    over each recording's strides matches its distance."""
    n = np.array([len(r["strides"]) for r in rows], float)
    z = np.array([sn.stride_features(r["strides"], kind).sum() for r in rows])
    d = np.array([r["distance_m"] for r in rows], float)
    if kind == "constant":
        return {"kind": kind, "a": float(n @ d / (n @ n)), "b": 0.0}
    a, b = np.linalg.lstsq(np.column_stack([n, z]), d, rcond=None)[0]
    return {"kind": kind, "a": float(a), "b": float(b)}


def distance_analysis(rows):
    """Test each stride-length model on recordings it wasn't fitted to."""
    rows = [r for r in rows if r["distance_m"] and r["strides"]]
    if not rows:
        return None, {}
    results = {}
    for kind in sn.DISTANCE_FEATURES:
        need = 1 if kind == "constant" else 2
        if len(rows) < need + 1:
            continue
        errs = []
        for i, r in enumerate(rows):
            model = fit_distance(rows[:i] + rows[i + 1:], kind)
            errs.append((sn.distance_m(r["strides"], model) - r["distance_m"]) / r["distance_m"])
        results[kind] = {"errors": errs, "mape": float(np.mean(np.abs(errs))),
                         "rel_sd": float(np.std(errs, ddof=1)) if len(errs) > 1 else float("nan")}
    uncal = [(sn.distance_m(r["strides"], None) - r["distance_m"]) / r["distance_m"] for r in rows]
    results["height rule (no fit)"] = {"errors": uncal, "mape": float(np.mean(np.abs(uncal))),
                                       "rel_sd": float(np.std(uncal, ddof=1)) if len(uncal) > 1 else float("nan")}
    fitted = [k for k in results if k in sn.DISTANCE_FEATURES]
    if fitted:
        best = min(fitted, key=lambda k: results[k]["mape"])
        model = fit_distance(rows, best)
    elif len(rows) == 1:             # one recording: fit the constant, but it can't be tested
        model = fit_distance(rows, "constant")
    else:
        model = None
    if model:
        model["tested_mape"] = results.get(model["kind"], {}).get("mape")
        model["tested_rel_sd"] = results.get(model["kind"], {}).get("rel_sd")
        model["recordings"] = len(rows)
    return model, results


def main():
    ap = argparse.ArgumentParser(description="Train and test the step counter")
    ap.add_argument("--quick", action="store_true", help="fewer training steps (worse, faster)")
    ap.add_argument("--folds", type=int, default=6, help="cross-validation folds (max)")
    args = ap.parse_args()
    iters = 300 if args.quick else 1000

    recs = [r for r in sn.load_recordings() if len(r["data"]) >= sn.T]
    if not recs:
        sys.exit("No recordings in data/. Record some with record.py first.")
    print(f"Labels (strides of the strapped leg; 1 stride = 2 steps):")
    for r in recs:
        r["events"], note = sn.label_strides(r["data"], r["activity"], r["steps"])
        print(f"  {r['name']:32s} {2 * len(r['events']):4d} steps  {note}")
    if not any(len(r["events"]) for r in recs):
        sys.exit("No walk or run recordings, so there's nothing to learn steps from.")

    # --- Cross-validation --------------------------------------------------------
    k = min(args.folds, len(recs))
    folds = assign_folds(recs, k)
    print(f"\nCross-validation: {k} folds, each recording counted by a net that never saw it")
    fold_nets = {}
    for f in range(k):
        train = [r for r, g in zip(recs, folds) if g != f]
        test = [r for r, g in zip(recs, folds) if g == f]
        if not any(len(r["events"]) for r in train):
            print(f"  fold {f + 1}: no strides to train on, skipped")
            continue
        start = time.time()
        print(f"  fold {f + 1}/{k}: testing on {', '.join(r['name'] for r in test)}")
        net = sn.train_net(train, seed=f, iters=iters)
        fold_nets[f] = net
        for r in test:
            c = sn.run_counter([net], r["data"])
            r["found"], r["strides"] = np.array(c.events), c.strides
            r["nn_steps"] = c.steps
            r["base_steps"] = 2 * len(sn.baseline_count(r["data"]))
        print(f"    done in {time.time() - start:.0f} s")
    recs = [r for r in recs if "nn_steps" in r]

    # --- Per-recording table -------------------------------------------------------
    print(f"\n{'recording':32s} {'true':>6s} {'net':>6s} {'error':>6s} {'no-AI':>6s}   true count from")
    for r in recs:
        ref = r["steps"] if r["steps"] else 2 * len(r["events"])
        src = "you counted" if r["steps"] else ("auto labels" if r["activity"] in cfg.STEP_ACTIVITIES else "0 (no steps)")
        print(f"{r['name']:32s} {ref:6d} {r['nn_steps']:6d} {r['nn_steps'] - ref:+6d} {r['base_steps']:6d}   {src}")

    # --- Stride by stride ----------------------------------------------------------
    walking = [r for r in recs if r["activity"] in cfg.STEP_ACTIVITIES]
    hits = misses = extras = 0
    dts = []
    for r in walking:
        h, m, e, d = sn.match_events(r["found"], r["events"])
        hits, misses, extras, dts = hits + h, misses + m, extras + e, dts + d
    report = {}
    if walking:
        prec, rec = hits / max(hits + extras, 1), hits / max(hits + misses, 1)
        print(f"\nStride by stride, walking + running (vs the labels, +-{sn.TOLERANCE * 10} ms):")
        print(f"  found {hits} of {hits + misses} strides (recall {rec:.1%}), "
              f"{extras} extra (precision {prec:.1%}), F1 {2 * prec * rec / max(prec + rec, 1e-9):.1%}")
        if dts:
            print(f"  timing: {np.mean(dts):+.0f} ms on average, spread {np.std(dts):.0f} ms")
        report["stride"] = {"recall": rec, "precision": prec, "timing_ms": float(np.mean(dts)) if dts else None,
                            "timing_sd_ms": float(np.std(dts)) if dts else None}

    # --- Count accuracy --------------------------------------------------------------
    counted = [r for r in walking if r["steps"]]
    if counted:
        stats = error_stats([r["nn_steps"] - r["steps"] for r in counted], [r["steps"] for r in counted])
        print_stats("COUNT ACCURACY vs the steps you counted (the real test)", stats)
        base = error_stats([r["base_steps"] - r["steps"] for r in counted], [r["steps"] for r in counted])
        print(f"  no-AI peak counter for comparison: {base['mae']:.1f} steps ({base['mape']:.1%}) average error")
        report["count"], report["count_baseline"], report["count_source"] = stats, base, "counted"
    elif walking:
        stats = error_stats([r["nn_steps"] - 2 * len(r["events"]) for r in walking],
                            [2 * len(r["events"]) for r in walking])
        print_stats("COUNT vs the automatic labels (NOT real ground truth: record some walks\n"
                    "and enter how many steps you counted, then retrain)", stats)
        report["count"], report["count_source"] = stats, "auto labels"

    idle = [r for r in recs if r["activity"] not in cfg.STEP_ACTIVITIES]
    if idle:
        print("\nFake steps while not walking (should be 0):")
        report["idle"] = {}
        for act in sorted({r["activity"] for r in idle}):
            rs = [r for r in idle if r["activity"] == act]
            minutes = sum(len(r["data"]) for r in rs) / sn.HZ / 60
            nn_rate = sum(r["nn_steps"] for r in rs) / minutes
            base_rate = sum(r["base_steps"] for r in rs) / minutes
            print(f"  {act:6s} net {nn_rate:5.1f} steps/min    no-AI peak counter {base_rate:5.1f} steps/min")
            report["idle"][act] = {"net_per_min": nn_rate, "baseline_per_min": base_rate}

    # --- Distance ----------------------------------------------------------------------
    model, dist = distance_analysis(walking)
    if not dist:
        print(f"\nDistance: no recordings with a distance yet. Until then live_steps.py uses a rule\n"
              f"of thumb from your height ({cfg.HEIGHT_M} m in gait_config.py), roughly +-20%.")
    else:
        print("\nDistance, each recording estimated by a fit made without it:")
        for kind, res in dist.items():
            print(f"  {kind:22s} average error {res['mape']:.1%}   "
                  f"(per recording: {', '.join(f'{e:+.0%}' for e in res['errors'])})")
        if model:
            print(f"  -> using '{model['kind']}': stride length = {model['a']:.3f} + "
                  f"{model['b']:.3f} x feature (m)")
    report["distance"] = {"model": model, "tests": {k: v["mape"] for k, v in dist.items()}}

    # --- Final ensemble ------------------------------------------------------------------
    print(f"\nTraining the final {cfg.ENSEMBLE} nets on all recordings...")
    nets = []
    for s in range(cfg.ENSEMBLE):
        start = time.time()
        nets.append(sn.train_net(recs, seed=100 + s, iters=iters))
        print(f"  net {s + 1}/{cfg.ENSEMBLE} done in {time.time() - start:.0f} s")
    sn.save_nets(nets, {"report": report, "distance_model": model})
    cfg.STEP_MODEL_PATH.with_name("step_report.json").write_text(json.dumps(report, indent=2))
    print(f"Saved {cfg.STEP_MODEL_PATH.relative_to(cfg.HERE)} and models/step_report.json")

    save_figure(recs, folds, fold_nets, model, dist)


def save_figure(recs, folds, fold_nets, model, dist):
    fig, ax = plt.subplots(2, 2, figsize=(14, 9))
    colors = {"still": "gray", "walk": "tab:green", "run": "tab:red", "bike": "tab:orange"}

    # Example of what the net sees and outputs, on a recording it never trained on
    ex = next((r for r in recs if r["activity"] == "walk"), next((r for r in recs if len(r["events"])), None))
    a = ax[0, 0]
    if ex is not None and folds[recs.index(ex)] in fold_nets:
        net = fold_nets[folds[recs.index(ex)]]
        s0 = min(1000, max(len(ex["data"]) - 1000, 0))
        seg = ex["data"][s0:s0 + 1000]
        p = sn.predict([net], [seg])[0, 0]
        t = np.arange(len(seg)) / sn.HZ
        gyro = np.linalg.norm(seg[:, 3:6] - np.median(seg[:, 3:6], axis=0), axis=1)
        a.plot(t, gyro / gyro.max(), color="0.6", lw=1, label="shin rotation rate (scaled)")
        a.plot(t, p, color="tab:blue", lw=1.5, label="net output")
        lab = ex["events"][(ex["events"] >= s0) & (ex["events"] < s0 + len(seg))] - s0
        fnd = ex["found"][(ex["found"] >= s0) & (ex["found"] < s0 + len(seg))] - s0
        a.plot(lab / sn.HZ, np.full(len(lab), 1.08), "kv", label="labeled stride")
        a.plot(fnd / sn.HZ, np.full(len(fnd), 1.15), "o", color="tab:blue", label="counted stride")
        a.axhline(sn.THRESHOLD, color="tab:blue", ls=":", lw=1)
        a.set_xlabel("time (s)")
        a.set_title(f"{ex['name']} (net never trained on it)")
        a.legend(loc="lower right", fontsize=8)

    # Counted vs true steps
    a = ax[0, 1]
    for r in recs:
        ref = r["steps"] if r["steps"] else 2 * len(r["events"])
        a.scatter(ref, r["nn_steps"], color=colors[r["activity"]], marker="o" if r["steps"] else "s",
                  s=60, edgecolor="k", zorder=3)
        a.scatter(ref, r["base_steps"], color=colors[r["activity"]], marker="x", s=40, zorder=2)
    top = max([max(r["nn_steps"], r["base_steps"], r["steps"] or 0, 2 * len(r["events"])) for r in recs] + [10])
    a.plot([0, top], [0, top], "k--", lw=1)
    a.set_xlabel("true steps (circle = you counted, square = auto labels)")
    a.set_ylabel("steps counted")
    a.set_title("Net (filled) vs no-AI peak counter (x)")
    for act, c in colors.items():
        a.scatter([], [], color=c, label=act)
    a.legend(fontsize=8)

    # Bland-Altman: error vs size of the count
    a = ax[1, 0]
    walk = [r for r in recs if r["activity"] in cfg.STEP_ACTIVITIES]
    ref = np.array([r["steps"] or 2 * len(r["events"]) for r in walk], float)
    err = np.array([r["nn_steps"] for r in walk]) - ref
    a.scatter(ref, err, c=[colors[r["activity"]] for r in walk], s=60, edgecolor="k")
    a.axhline(0, color="k", lw=1)
    if len(err) > 1:
        m, s = err.mean(), err.std(ddof=1)
        for v, ls in ((m, "-"), (m - 1.96 * s, "--"), (m + 1.96 * s, "--")):
            a.axhline(v, color="tab:blue", ls=ls, lw=1)
        a.set_title(f"Count error: bias {m:+.1f}, 95% limits {m - 1.96 * s:+.1f} to {m + 1.96 * s:+.1f} steps")
    a.set_xlabel("true steps")
    a.set_ylabel("net - true (steps)")

    # Distance
    a = ax[1, 1]
    rows = [r for r in walk if r["distance_m"] and r["strides"]]
    if rows and model:
        true = [r["distance_m"] for r in rows]
        k = model["kind"]
        est = [d * (1 + e) for d, e in zip(true, dist[k]["errors"])] if k in dist else \
              [sn.distance_m(r["strides"], model) for r in rows]
        rule = [sn.distance_m(r["strides"], None) for r in rows]
        a.scatter(true, est, s=60, edgecolor="k", label=f"fitted ({k}), tested on unseen recordings")
        a.scatter(true, rule, marker="x", label="height rule of thumb")
        top = max(true + est + rule) * 1.1
        a.plot([0, top], [0, top], "k--", lw=1)
        a.set_xlabel("true distance (m)")
        a.set_ylabel("estimated distance (m)")
        a.legend(fontsize=8)
    else:
        a.text(0.5, 0.5, "No recordings with a measured distance yet.\n"
               "Record walks over a known distance\n(record.py asks for it).",
               ha="center", va="center", transform=a.transAxes)
        a.set_axis_off()
    a.set_title("Distance estimate")

    fig.tight_layout()
    out = cfg.STEP_MODEL_PATH.with_name("steps_results.png")
    fig.savefig(out, dpi=120)
    print(f"Saved the results figure to {out.relative_to(cfg.HERE)}")


if __name__ == "__main__":
    main()
