"""
Train and test both gait models on the recordings in data/.

    python train.py

Model 1  one feature: the peak acceleration along one axis, fed to a small
         decision tree (it just learns thresholds, printed as rules below).
Model 2  every IMU output (3 accel + 3 gyro axes, plus their magnitudes):
         mean, spread, range, jerkiness and stride frequency, fed to a
         random forest. No neural nets anywhere.

Each model is tested on whole recordings it never trained on (grouped
cross-validation), so the accuracy is what you'd get on a new walk, not a
replay of the training data. Saves the models to models/gait_models.joblib and
a results figure to models/results.png.
"""

import sys
from collections import Counter

import joblib
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import accuracy_score, classification_report, confusion_matrix
from sklearn.model_selection import StratifiedGroupKFold, StratifiedKFold, cross_val_predict
from sklearn.tree import DecisionTreeClassifier, export_text

import gait_config as cfg
from gait_features import AXIS_INDEX, all_features, feature_names, peak_accel, windows


def load_windows():
    files = sorted(cfg.DATA_DIR.glob("*.csv"))
    peaks, feats, labels, groups = [], [], [], []
    for g, path in enumerate(files):
        activity = path.stem.split("_")[0]
        if activity not in cfg.ACTIVITIES:
            print(f"  skipping {path.name}: '{activity}' isn't in ACTIVITIES")
            continue
        data = np.loadtxt(path, delimiter=",", skiprows=1, ndmin=2)[:, 1:]
        n = 0
        for win in windows(data):
            peaks.append([peak_accel(win, a) for a in AXIS_INDEX])
            feats.append(all_features(win)[0])
            labels.append(activity)
            groups.append(g)
            n += 1
        print(f"  {path.name:32s} {n:4d} windows")
    return np.array(peaks), np.array(feats), np.array(labels), np.array(groups)


def make_cv(labels, groups):
    """Hold out whole recordings when there are enough of them."""
    files_per_class = {a: len(set(groups[labels == a])) for a in set(labels)}
    k = min(5, min(files_per_class.values()))
    if k >= 2:
        return StratifiedGroupKFold(n_splits=k, shuffle=True, random_state=0), k, True
    print("\nWARNING: some activity has only 1 recording, so the test windows come from\n"
          "the same recordings as the training windows. The accuracy below will be too\n"
          "optimistic. Record each activity at least twice.")
    return StratifiedKFold(n_splits=5, shuffle=True, random_state=0), 5, False


def report(name, labels, pred, classes):
    acc = accuracy_score(labels, pred)
    print(f"\n=== {name}: {acc:.1%} accuracy on held-out data ===")
    cm = confusion_matrix(labels, pred, labels=classes)
    print("rows = true, columns = predicted")
    print(" " * 8 + "".join(f"{c:>8s}" for c in classes))
    for c, row in zip(classes, cm):
        print(f"{c:>8s}" + "".join(f"{v:8d}" for v in row))
    print(classification_report(labels, pred, labels=classes, zero_division=0))
    return acc, cm


def main():
    print(f"Loading recordings from {cfg.DATA_DIR}")
    peaks, feats, labels, groups = load_windows()
    if len(labels) == 0:
        sys.exit("No recordings yet. Record some with record.py first.")
    classes = [a for a in cfg.ACTIVITIES if a in set(labels)]
    print("Windows per activity:", dict(Counter(labels.tolist())))
    if len(classes) < 2:
        sys.exit("Need recordings of at least 2 activities to train.")
    missing = [a for a in cfg.ACTIVITIES if a not in classes]
    if missing:
        print(f"Not recorded yet: {', '.join(missing)} (the models can't predict these)")

    cv, k, grouped = make_cv(labels, groups)
    cv_args = dict(cv=cv, groups=groups) if grouped else dict(cv=cv)

    # --- Model 1: peak acceleration along one axis ---------------------------
    tree = DecisionTreeClassifier(max_depth=3, min_samples_leaf=5, random_state=0)
    axes = list(AXIS_INDEX) if cfg.PEAK_AXIS == "auto" else [cfg.PEAK_AXIS]
    print(f"\nModel 1: peak acceleration on one axis ({k}-fold, "
          f"{'by recording' if grouped else 'by window'})")
    best = None
    for axis in axes:
        x = peaks[:, [AXIS_INDEX[axis]]]
        pred = cross_val_predict(tree, x, labels, **cv_args)
        acc = accuracy_score(labels, pred)
        print(f"  {axis}: {acc:.1%}")
        if best is None or acc > best[1]:
            best = (axis, acc, pred)
    axis, _, pred1 = best
    acc1, cm1 = report(f"Model 1 (peak |{axis}| only)", labels, pred1, classes)
    x1 = peaks[:, [AXIS_INDEX[axis]]]
    model1 = DecisionTreeClassifier(max_depth=3, min_samples_leaf=5, random_state=0).fit(x1, labels)
    print("Model 1 rules (trained on all the data):")
    print(export_text(model1, feature_names=[f"peak_{axis}_g"], decimals=2))

    # --- Model 2: all IMU outputs ----------------------------------------------
    forest = RandomForestClassifier(n_estimators=300, min_samples_leaf=2,
                                    class_weight="balanced", random_state=0, n_jobs=-1)
    pred2 = cross_val_predict(forest, feats, labels, **cv_args)
    acc2, cm2 = report("Model 2 (all IMU outputs)", labels, pred2, classes)
    model2 = forest.fit(feats, labels)
    names = feature_names()
    top = np.argsort(model2.feature_importances_)[::-1][:10]
    print("Model 2's most useful features:")
    for i in top:
        print(f"  {names[i]:22s} {model2.feature_importances_[i]:.3f}")

    cfg.MODEL_PATH.parent.mkdir(exist_ok=True)
    joblib.dump({"model1": model1, "axis": axis, "model2": model2,
                 "feature_names": names, "classes": classes,
                 "accuracy": {"model1": acc1, "model2": acc2}}, cfg.MODEL_PATH)
    print(f"\nSaved both models to {cfg.MODEL_PATH.relative_to(cfg.HERE)}")

    save_figure(peaks[:, AXIS_INDEX[axis]], labels, classes, axis, model1, cm1, acc1, cm2, acc2)


def save_figure(peak, labels, classes, axis, model1, cm1, acc1, cm2, acc2):
    fig, ax = plt.subplots(1, 3, figsize=(16, 4.8))
    rng = np.random.default_rng(0)
    for i, c in enumerate(classes):
        v = peak[labels == c]
        ax[0].scatter(v, i + rng.uniform(-0.2, 0.2, len(v)), s=8, alpha=0.5)
    for t in model1.tree_.threshold[model1.tree_.feature >= 0]:
        ax[0].axvline(t, color="k", ls="--", lw=1)
    ax[0].set_yticks(range(len(classes)), classes)
    ax[0].set_xlabel(f"peak |{axis}| in the window (g)")
    ax[0].set_title("Model 1 input (dashed = learned thresholds)")
    for a, cm, acc, title in ((ax[1], cm1, acc1, "Model 1: peak accel"),
                              (ax[2], cm2, acc2, "Model 2: all IMU outputs")):
        a.imshow(cm, cmap="Blues")
        for (r, c), v in np.ndenumerate(cm):
            a.text(c, r, v, ha="center", va="center",
                   color="white" if v > cm.max() / 2 else "black")
        a.set_xticks(range(len(classes)), classes)
        a.set_yticks(range(len(classes)), classes)
        a.set_xlabel("predicted")
        a.set_ylabel("true")
        a.set_title(f"{title} ({acc:.0%})")
    fig.tight_layout()
    out = cfg.MODEL_PATH.parent / "results.png"
    fig.savefig(out, dpi=120)
    print(f"Saved the results figure to {out.relative_to(cfg.HERE)}")


if __name__ == "__main__":
    main()
