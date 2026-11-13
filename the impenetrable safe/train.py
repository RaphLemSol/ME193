"""
Train FingerNet on the pictures in data/ and test it.

    python train.py                          # train + test on bursts it never saw
    python train.py --no-augment             # same without augmentation, to compare
    python train.py --holdout-person anna    # test only on a person it never saw

Testing: pictures in one burst are nearly identical, so testing on a random
20% of pictures would mostly test on copies of training pictures. Instead,
whole bursts (or a whole person) are held out.

Saves models/finger_net.pt, models/training.png (loss + accuracy per epoch,
confusion matrix), models/report.json, and the weights for the UNO Q
(Safe-UnoQ/python/finger_net.npz), after checking that the numpy version of
the net gives the same answers as PyTorch.
"""

import argparse
import hashlib
import json
from collections import defaultdict

import cv2
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import torch
from torch import nn

import safe_config as cfg
import vision
from finger_net import FingerNet, augment, export_npz
from numpy_net import NumpyFingerNet


def load_data():
    """Every picture with its label, person and burst."""
    items = []
    for c in range(cfg.CLASSES):
        for path in sorted((cfg.DATA_DIR / str(c)).glob("*.png")):
            person, session = path.stem.split("_")[:2]
            items.append({"img": cv2.imread(str(path)), "label": c, "person": person,
                          "burst": f"{c}_{person}_{session}"})
    return items


def split(items, holdout_person, rng, frac=0.2):
    """Hold out whole bursts (~frac of each number's bursts) or one person."""
    if holdout_person:
        test = [i for i, it in enumerate(items) if it["person"] == holdout_person]
        if not test:
            raise SystemExit(f"No pictures from '{holdout_person}'")
    else:
        by_label = defaultdict(list)
        for it in items:
            if it["burst"] not in by_label[it["label"]]:
                by_label[it["label"]].append(it["burst"])
        held = set()
        for c, bursts in by_label.items():
            if len(bursts) < 2:
                print(f"  only one burst of {c} fingers: record more bursts so it can be tested")
                continue
            # Pick by a hash of the burst's name, not at random: adding new
            # bursts later doesn't reshuffle which old ones are test bursts,
            # so test scores from one run to the next can be compared.
            bursts.sort(key=lambda b: hashlib.md5(b.encode()).hexdigest())
            held.update(bursts[:max(1, round(frac * len(bursts)))])
        test = [i for i, it in enumerate(items) if it["burst"] in held]
    train = sorted(set(range(len(items))) - set(test))
    return train, test


def batch(items, idx, rng, aug):
    x = np.stack([vision.to_input(augment(items[i]["img"], rng) if aug else items[i]["img"]) for i in idx])
    y = np.array([items[i]["label"] for i in idx])
    return torch.from_numpy(x), torch.from_numpy(y)


@torch.no_grad()
def evaluate(net, items, idx, loss_fn):
    net.eval()
    if not idx:
        return float("nan"), float("nan"), np.array([], int)
    x, y = batch(items, idx, None, False)
    logits = net(x)
    pred = logits.argmax(1)
    return loss_fn(logits, y).item(), (pred == y).float().mean().item(), pred.numpy()


def main():
    ap = argparse.ArgumentParser(description="Train the finger-counting CNN")
    ap.add_argument("--epochs", type=int, default=40)
    ap.add_argument("--batch", type=int, default=64)
    ap.add_argument("--lr", type=float, default=1e-3)
    ap.add_argument("--no-augment", action="store_true")
    ap.add_argument("--holdout-person", help="test on this person only (never trained on)")
    ap.add_argument("--seed", type=int, default=0)
    args = ap.parse_args()

    rng = np.random.default_rng(args.seed)
    torch.manual_seed(args.seed)
    items = load_data()
    if not items:
        raise SystemExit("No pictures in data/. Run collect.py first.")
    labels = np.array([it["label"] for it in items])
    print(f"{len(items)} pictures from {len({it['person'] for it in items})} people; "
          f"per number: {np.bincount(labels, minlength=cfg.CLASSES).tolist()}")
    train_idx, test_idx = split(items, args.holdout_person, rng)
    print(f"train on {len(train_idx)}, test on {len(test_idx)} "
          f"({'person ' + args.holdout_person if args.holdout_person else 'held-out bursts'})")

    # Numbers with fewer pictures count more, so the net can't ignore them
    counts = np.bincount(labels[train_idx], minlength=cfg.CLASSES).astype(float)
    weight = torch.tensor(counts.sum() / np.maximum(counts, 1) / cfg.CLASSES, dtype=torch.float32)
    loss_fn = nn.CrossEntropyLoss(weight=weight)
    plain_loss = nn.CrossEntropyLoss()

    net = FingerNet()
    print(f"FingerNet: {sum(p.numel() for p in net.parameters()):,} weights")
    opt = torch.optim.Adam(net.parameters(), lr=args.lr, weight_decay=1e-4)
    sched = torch.optim.lr_scheduler.CosineAnnealingLR(opt, args.epochs)
    hist = defaultdict(list)
    best = (-1.0, None, 0)
    for epoch in range(args.epochs):
        net.train()
        order = rng.permutation(train_idx)
        total, correct, seen = 0.0, 0, 0
        for k in range(0, len(order), args.batch):
            x, y = batch(items, order[k:k + args.batch], rng, not args.no_augment)
            logits = net(x)                       # forward pass
            loss = loss_fn(logits, y)
            opt.zero_grad()
            loss.backward()                       # backpropagation: dLoss/dweight for every weight
            opt.step()                            # gradient descent step (Adam)
            total += loss.item() * len(y)
            correct += (logits.argmax(1) == y).sum().item()
            seen += len(y)
        sched.step()
        test_loss, test_acc, _ = evaluate(net, items, test_idx, plain_loss)
        hist["train_loss"].append(total / seen)
        hist["train_acc"].append(correct / seen)
        hist["test_loss"].append(test_loss)
        hist["test_acc"].append(test_acc)
        print(f"epoch {epoch + 1:3d}  train loss {total / seen:.3f} acc {correct / seen:.1%}   "
              f"test loss {test_loss:.3f} acc {test_acc:.1%}")
        # Keep the last epoch. Picking the epoch with the best test score would
        # let the test pictures choose the model, so the test score wouldn't
        # be an honest measure any more (and once picked epoch 1 by luck).
        score = epoch
        if best[1] is None or score > best[0]:
            best = (score, {k: v.clone() for k, v in net.state_dict().items()}, epoch + 1)

    net.load_state_dict(best[1])
    net.eval()
    _, test_acc, pred = evaluate(net, items, test_idx, plain_loss)
    truth = labels[test_idx]
    conf = np.zeros((cfg.CLASSES, cfg.CLASSES), int)
    for t, p in zip(truth, pred):
        conf[t, p] += 1
    per_class = {c: float(conf[c, c] / conf[c].sum()) if conf[c].sum() else None for c in range(cfg.CLASSES)}
    print(f"\nBest epoch {best[2]}: test accuracy {test_acc:.1%}")
    for c, a in per_class.items():
        print(f"  {c} fingers: " + (f"{a:.1%}" if a is not None else "not tested"))

    # Save the model, the numpy weights for the UNO Q, and a report. Comparison
    # runs only save their report and plot, so they never replace the real model.
    tag = ("_noaug" if args.no_augment else "") + (f"_holdout-{args.holdout_person}" if args.holdout_person else "")
    cfg.MODEL_DIR.mkdir(exist_ok=True)
    npz = cfg.NPZ_PATH if not tag else cfg.MODEL_DIR / f"finger_net{tag}.npz"
    if not tag:
        torch.save({"state": net.state_dict(), "test_acc": test_acc, "per_class": per_class}, cfg.MODEL_PATH)
    export_npz(net, npz)
    check = test_idx[:20] or train_idx[:20]
    np_net = NumpyFingerNet(npz)
    with torch.no_grad():
        diff = max(float(np.abs(np_net.predict(vision.to_input(items[i]["img"])) -
                                torch.softmax(net(batch(items, [i], None, False)[0]), 1)[0].numpy()).max())
                   for i in check)
    print(f"numpy net vs PyTorch: biggest probability difference {diff:.2e} "
          f"({'same' if diff < 1e-4 else 'MISMATCH, check numpy_net.py'})")
    report = {"pictures": len(items), "train": len(train_idx), "test": len(test_idx),
              "best_epoch": best[2], "test_acc": test_acc, "per_class": per_class,
              "confusion": conf.tolist(), "augment": not args.no_augment,
              "holdout_person": args.holdout_person, "numpy_vs_torch": diff, "history": hist}
    (cfg.MODEL_DIR / f"report{tag}.json").write_text(json.dumps(report, indent=2))

    fig, ax = plt.subplots(1, 3, figsize=(16, 4.5))
    ep = np.arange(1, args.epochs + 1)
    ax[0].plot(ep, hist["train_loss"], label="train")
    ax[0].plot(ep, hist["test_loss"], label="test")
    ax[0].set(xlabel="epoch", ylabel="cross-entropy loss", title="Loss")
    ax[1].plot(ep, hist["train_acc"], label="train")
    ax[1].plot(ep, hist["test_acc"], label="test")
    ax[1].set(xlabel="epoch", ylabel="accuracy", title="Accuracy", ylim=(0, 1.02))
    for a in ax[:2]:
        a.axvline(best[2], color="0.6", ls=":")
        a.legend()
    ax[2].imshow(conf, cmap="Blues")
    for t in range(cfg.CLASSES):
        for p in range(cfg.CLASSES):
            ax[2].text(p, t, conf[t, p], ha="center", va="center", color="black" if conf[t, p] < conf.max() / 2 else "white")
    ax[2].set(xlabel="net says", ylabel="really", title=f"Test confusion matrix ({test_acc:.0%})",
              xticks=range(cfg.CLASSES), yticks=range(cfg.CLASSES))
    fig.suptitle("FingerNet " + ("with" if not args.no_augment else "without") + " augmentation"
                 + (f", tested on {args.holdout_person}" if args.holdout_person else ""))
    fig.tight_layout()
    fig.savefig(cfg.MODEL_DIR / f"training{tag}.png", dpi=130)
    if tag:
        print(f"Saved {cfg.MODEL_DIR / f'training{tag}.png'} (comparison run: the real model wasn't changed)")
    else:
        print(f"Saved {cfg.MODEL_PATH}, {cfg.NPZ_PATH}, {cfg.MODEL_DIR / 'training.png'}")


if __name__ == "__main__":
    main()
