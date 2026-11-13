"""
Fit Anna's V data with gradient descent, written out by hand (no PyTorch),
so every derivative is visible. See MATH.md for the derivation.

    python fit_v.py

Three models, each trained on the same scaled data (u = x/100, t = y/100):

  1. one linear neuron       y = m*u + b
  2. one ReLU neuron         y = ReLU(m*u + b)
  3. a ReLU layer (2 wide)   y = v1*ReLU(w1*u + b1) + v2*ReLU(w2*u + b2) + c

A line can't make a V, and one ReLU neuron can only make one arm of it. Two
ReLU neurons (one per arm) added together by an output neuron can.

Saves v_fit.png (data + fits) and v_loss.png (loss vs epoch), and prints the
first 5 iterations of models 1 and 2 so you can check them against the
spreadsheet (make_excel.py).
"""

from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

HERE = Path(__file__).resolve().parent
SCALE = 100.0          # x and y are 0-100; dividing by 100 keeps the gradients ~1

# Same starting values and learning rate as the spreadsheet
LINEAR_INIT = {"m": 0.0, "b": 0.0}
RELU_INIT = {"m": 1.0, "b": -0.5}
LR = 0.5


def load():
    data = np.loadtxt(HERE / "annacode-v.tsv", delimiter="\t", skiprows=1)
    return data[:, 1] / SCALE, data[:, 2] / SCALE      # u, t


def relu(z):
    return np.maximum(z, 0.0)


def linear_step(p, u, t):
    """Loss and gradient for y = m*u + b, MSE loss."""
    err = p["m"] * u + p["b"] - t
    return np.mean(err ** 2), {"m": 2 * np.mean(err * u), "b": 2 * np.mean(err)}


def relu_step(p, u, t):
    """Loss and gradient for y = ReLU(m*u + b). ReLU'(z) is 1 where z > 0,
    else 0, so points the neuron is 'off' for don't move the weights."""
    z = p["m"] * u + p["b"]
    err = relu(z) - t
    on = (z > 0).astype(float)
    return np.mean(err ** 2), {"m": 2 * np.mean(err * on * u), "b": 2 * np.mean(err * on)}


def layer_step(p, u, t):
    """Loss and gradient for the 2-neuron ReLU layer + output neuron.
    Backpropagation = the chain rule, from the loss back to each weight."""
    # forward
    z1, z2 = p["w1"] * u + p["b1"], p["w2"] * u + p["b2"]
    h1, h2 = relu(z1), relu(z2)
    y = p["v1"] * h1 + p["v2"] * h2 + p["c"]
    err = y - t
    # backward
    dy = 2 * err / len(u)                       # dL/dy for each point
    dz1 = dy * p["v1"] * (z1 > 0)               # dL/dz1 = dL/dy * dy/dh1 * dh1/dz1
    dz2 = dy * p["v2"] * (z2 > 0)
    grad = {"v1": np.sum(dy * h1), "v2": np.sum(dy * h2), "c": np.sum(dy),
            "w1": np.sum(dz1 * u), "b1": np.sum(dz1),
            "w2": np.sum(dz2 * u), "b2": np.sum(dz2)}
    return np.mean(err ** 2), grad


def descend(step, params, u, t, lr, epochs):
    """Plain gradient descent: w <- w - lr * dL/dw, once per epoch."""
    p = dict(params)
    history = []
    for _ in range(epochs):
        loss, grad = step(p, u, t)
        history.append((loss, dict(p), grad))
        for k in p:
            p[k] -= lr * grad[k]
    history.append((step(p, u, t)[0], dict(p), None))
    return p, history


def print_iterations(name, history):
    print(f"\n{name}  (first 5 iterations, compare with the spreadsheet)")
    print(f"  {'iter':>4} {'m':>10} {'b':>10} {'loss':>10} {'dL/dm':>10} {'dL/db':>10}")
    for k, (loss, p, g) in enumerate(history[:6]):
        gm, gb = (f"{g['m']:10.5f}", f"{g['b']:10.5f}") if g else ("", "")
        print(f"  {k:>4} {p['m']:10.5f} {p['b']:10.5f} {loss:10.5f} {gm:>10} {gb:>10}")


def main():
    u, t = load()

    lin, lin_hist = descend(linear_step, LINEAR_INIT, u, t, LR, 2000)
    one, one_hist = descend(relu_step, RELU_INIT, u, t, LR, 2000)
    # One neuron per arm of the V: w1 > 0 turns on for big x, w2 < 0 for small x
    layer_init = {"w1": 1.0, "b1": -0.5, "w2": -1.0, "b2": 0.5, "v1": 1.0, "v2": 1.0, "c": 0.0}
    lay, lay_hist = descend(layer_step, layer_init, u, t, LR, 2000)

    print_iterations("1. Linear neuron  y = m*u + b", lin_hist)
    print_iterations("2. ReLU neuron    y = ReLU(m*u + b)", one_hist)

    print("\nAfter 2000 epochs (scaled units, u = x/100):")
    print(f"  linear: m={lin['m']:.3f} b={lin['b']:.3f}  loss={lin_hist[-1][0]:.5f}")
    print(f"  ReLU  : m={one['m']:.3f} b={one['b']:.3f}  loss={one_hist[-1][0]:.5f}")
    print("  layer : " + " ".join(f"{k}={v:.3f}" for k, v in lay.items()) + f"  loss={lay_hist[-1][0]:.5f}")
    # Where the V bottoms out: the two neurons switch on at u = -b/w
    print(f"  the V's corner: x = {-lay['b1'] / lay['w1'] * SCALE:.1f} and {-lay['b2'] / lay['w2'] * SCALE:.1f}"
          f"  (slopes {lay['v1'] * lay['w1']:.2f} and {lay['v2'] * lay['w2']:.2f})")

    xs = np.linspace(0.15, 1.05, 300)
    fig, ax = plt.subplots(figsize=(8, 5))
    ax.scatter(u * SCALE, t * SCALE, s=14, color="0.35", label="Anna's V data")
    ax.plot(xs * SCALE, (lin["m"] * xs + lin["b"]) * SCALE, lw=4, alpha=0.5, label="1 linear neuron")
    # The ReLU neuron ends up switched on for every point, so it lands on the same line
    ax.plot(xs * SCALE, relu(one["m"] * xs + one["b"]) * SCALE, "--", label="1 ReLU neuron (same as the line)")
    yl = lay["v1"] * relu(lay["w1"] * xs + lay["b1"]) + lay["v2"] * relu(lay["w2"] * xs + lay["b2"]) + lay["c"]
    ax.plot(xs * SCALE, yl * SCALE, lw=2.5, label="2 ReLU neurons + output neuron")
    ax.set(xlabel="x", ylabel="output", title="Fitting the V with gradient descent")
    ax.legend()
    fig.tight_layout()
    fig.savefig(HERE / "v_fit.png", dpi=150)

    fig, ax = plt.subplots(figsize=(8, 5))
    for name, hist in [("1 linear neuron", lin_hist), ("1 ReLU neuron", one_hist),
                       ("2 ReLU neurons + output", lay_hist)]:
        ax.plot([h[0] for h in hist], label=name)
    ax.set(xlabel="epoch", ylabel="mean squared error (scaled units)", yscale="log",
           title="Loss as a function of epoch")
    ax.legend()
    fig.tight_layout()
    fig.savefig(HERE / "v_loss.png", dpi=150)
    print(f"\nSaved {HERE / 'v_fit.png'} and {HERE / 'v_loss.png'}")


if __name__ == "__main__":
    main()
