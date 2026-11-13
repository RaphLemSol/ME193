"""
Pictures of what happens inside FingerNet, one per layer, for the stop-action
movie. Print them, cut them out, and move them along frame by frame.

    python visualize.py                       # a training picture of 3 fingers
    python visualize.py --fingers 5
    python visualize.py --image some.png      # any 128x128 crop
    python visualize.py --live                # snap the taped square right now

Saves movie/<n>_<step>.png:
  input -> conv1 filters -> conv1 maps -> pooled -> conv2 maps -> pooled
        -> conv3 maps -> pooled -> probabilities
Uses the numpy net (the UNO Q's version), so it shows exactly the math
numpy_net.py does.
"""

import argparse
import random

import cv2
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

import safe_config as cfg
import vision
from numpy_net import NumpyFingerNet

OUT = cfg.HERE / "movie"


def grid(maps, title, path, cmap="viridis", limit=32):
    maps = maps[:limit]
    cols = 8
    rows = int(np.ceil(len(maps) / cols))
    fig, axes = plt.subplots(rows, cols, figsize=(cols * 1.6, rows * 1.7 + 0.6))
    for i, ax in enumerate(np.atleast_1d(axes).ravel()):
        ax.axis("off")
        if i < len(maps):
            ax.imshow(maps[i], cmap=cmap)
            ax.set_title(str(i + 1), fontsize=8)
    fig.suptitle(title)
    fig.tight_layout()
    fig.savefig(path, dpi=130)
    plt.close(fig)


def main():
    ap = argparse.ArgumentParser(description="Save a picture of every layer of FingerNet")
    ap.add_argument("--fingers", type=int, default=3)
    ap.add_argument("--image")
    ap.add_argument("--live", action="store_true")
    ap.add_argument("--camera", type=int, default=cfg.CAMERA_INDEX)
    args = ap.parse_args()

    if args.live:
        cap, _ = vision.open_camera(args.camera)
        for _ in range(5):
            frame = vision.read_frame(cap)
        cap.release()
        crop = vision.crop_square(frame, vision.load_roi())
    elif args.image:
        crop = cv2.resize(cv2.imread(args.image), (vision.CROP, vision.CROP))
    else:
        files = list((cfg.DATA_DIR / str(args.fingers)).glob("*.png"))
        if not files:
            raise SystemExit(f"No pictures in data/{args.fingers}")
        crop = cv2.imread(str(random.choice(files)))

    net = NumpyFingerNet(cfg.NPZ_PATH)
    layers = net.layers(vision.to_input(crop))
    OUT.mkdir(exist_ok=True)
    n = 1

    cv2.imwrite(str(OUT / f"{n:02d}_camera_crop.png"), cv2.resize(crop, (384, 384), interpolation=cv2.INTER_NEAREST))
    n += 1
    x = layers[0][1]
    fig, ax = plt.subplots(1, 4, figsize=(12, 3.4))
    ax[0].imshow(cv2.cvtColor(cv2.resize(crop, (vision.IMG, vision.IMG)), cv2.COLOR_BGR2RGB))
    ax[0].set_title("what the net sees (64x64)")
    for c, name in enumerate(["red", "green", "blue"]):
        ax[c + 1].imshow(x[c], cmap="gray")
        ax[c + 1].set_title(f"{name} channel (standardized)")
    for a in ax:
        a.axis("off")
    fig.tight_layout()
    fig.savefig(OUT / f"{n:02d}_input_channels.png", dpi=130)
    plt.close(fig)
    n += 1

    # The 16 first-layer filters: what each one looks for (as tiny color pictures)
    w = net.w["conv1.weight"].transpose(0, 2, 3, 1)
    w = (w - w.min()) / (w.max() - w.min())
    grid(w, "conv1: the 16 filters (5x5, each slides over the picture)", OUT / f"{n:02d}_conv1_filters.png")
    n += 1

    for name, value in layers[1:-1]:
        c, h, wd = value.shape
        grid(value, f"{name}: {c} maps of {h}x{wd}" + (" (showing 32)" if c > 32 else ""),
             OUT / f"{n:02d}_{name.replace(' + ', '_').replace(' ', '_')}.png")
        n += 1

    probs = layers[-1][1]
    fig, ax = plt.subplots(figsize=(6, 3.5))
    ax.bar(range(len(probs)), probs, color=["0.6" if i != probs.argmax() else "tab:orange" for i in range(len(probs))])
    ax.set(xlabel="fingers", ylabel="probability", ylim=(0, 1), xticks=range(len(probs)),
           title=f"linear layer + softmax: {probs.argmax()} fingers ({probs.max():.0%})")
    fig.tight_layout()
    fig.savefig(OUT / f"{n:02d}_probabilities.png", dpi=130)
    plt.close(fig)
    print(f"Saved {n} pictures to {OUT}")


if __name__ == "__main__":
    main()
