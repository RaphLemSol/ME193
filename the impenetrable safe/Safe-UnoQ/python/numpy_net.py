"""
FingerNet's forward pass written in plain numpy, so the UNO Q doesn't need
PyTorch (a ~1 GB install). It loads the weights train.py exports
(finger_net.npz) and gives the same answer as the PyTorch model; train.py
checks that after every training run.

Each step is the same math PyTorch does:
  conv   -> slide every filter over the image; each output pixel is the dot
            product of the filter with the patch under it, plus a bias
  ReLU   -> negative numbers become 0
  pool   -> keep the biggest value in each 2x2 block (image gets half as big)
  linear -> one dot product per class gives 6 scores (logits)
  softmax-> scores become probabilities that add to 1
"""

from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
NPZ_PATH = HERE / "finger_net.npz"


def conv2d(x, w, b):
    """x: (C, H, W), w: (F, C, k, k), 'same' padding, stride 1 -> (F, H, W)."""
    f, c, k, _ = w.shape
    p = k // 2
    xp = np.pad(x, ((0, 0), (p, p), (p, p)))
    # every k x k patch of every channel: (C, H, W, k, k)
    patches = np.lib.stride_tricks.sliding_window_view(xp, (k, k), axis=(1, 2))
    h, wd = patches.shape[1:3]
    cols = patches.transpose(1, 2, 0, 3, 4).reshape(h * wd, c * k * k)
    return (cols @ w.reshape(f, -1).T + b).T.reshape(f, h, wd)


def relu(x):
    return np.maximum(x, 0)


def max_pool(x):
    c, h, w = x.shape
    return x[:, :h // 2 * 2, :w // 2 * 2].reshape(c, h // 2, 2, w // 2, 2).max(axis=(2, 4))


def softmax(z):
    e = np.exp(z - z.max())
    return e / e.sum()


class NumpyFingerNet:
    def __init__(self, path=NPZ_PATH):
        self.w = dict(np.load(path))
        self.convs = sorted({k.split(".")[0] for k in self.w if k.startswith("conv")})

    def layers(self, x):
        """Every intermediate result, for visualizing: [(name, array), ...]."""
        out = [("input", x)]
        for name in self.convs:
            x = relu(conv2d(x, self.w[f"{name}.weight"], self.w[f"{name}.bias"]))
            out.append((f"{name} + ReLU", x))
            x = max_pool(x)
            out.append((f"{name} pooled", x))
        logits = self.w["fc.weight"] @ x.reshape(-1) + self.w["fc.bias"]
        out.append(("probabilities", softmax(logits)))
        return out

    def predict(self, x):
        """(3, 64, 64) input -> 6 probabilities (0-5 fingers)."""
        return self.layers(x)[-1][1]
