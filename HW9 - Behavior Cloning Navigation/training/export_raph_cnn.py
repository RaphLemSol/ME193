"""Export Raph's trained StepNet ensemble to a plain numpy file for the board.

Usage:  python export_raph_cnn.py <folder of Raph's "How many steps">
Writes: ../uno_q/python/raph_step_model.npz

The folder is a copy of https://github.com/RaphLemSol/ME193/tree/main/How%20many%20steps
(models/step_net.pt from commit 713da130607d, 2026-11-03). The board has no PyTorch, so this
runs once on the laptop: it reads the five trained nets and saves every number in them,
unchanged, as numpy arrays (stacked: the first axis is the net, 0-4). Nothing is retrained.

Also saved, so the board's counter (uno_q/python/stride_counter.py) takes every setting from
this one file:
- the counting rule from Raph's step_net.py / gait_config.py (window 4 s, run every 0.25 s,
  peaks above 0.5 at least 0.4 s apart, counted once 0.6 s old, at least 1 s of context);
- the input scaling (acceleration / 2, rotation / 300);
- the axis renaming from our HW7-style strap to Raph's layout (see compare_raph_cnn.py);
- his distance model: a constant 0.823 m per stride (= about 0.41 m per step).

His model file is loaded with weights_only=True, which accepts only tensors and plain values,
so the file can't run code while loading.
"""
import sys
from pathlib import Path
import numpy as np
import torch

repo = Path(sys.argv[1])
out = Path(__file__).resolve().parent.parent / "uno_q" / "python" / "raph_step_model.npz"

saved = torch.load(repo / "models" / "step_net.pt", weights_only=True)
nets = saved["nets"]                     # 5 state dicts (layer name -> tensor)
print(f"{len(nets)} nets in {repo / 'models' / 'step_net.pt'}")


def stack(name):
    """The same layer from all 5 nets, as one float32 array (net first)."""
    return np.stack([n[name].numpy() for n in nets]).astype(np.float32)


arrays = {
    # First layer: conv 8 -> 24 signals, 7 samples wide, every other sample; then batch norm
    "inp_w": stack("inp.0.weight"), "inp_b": stack("inp.0.bias"),
    "inp_bn_w": stack("inp.1.weight"), "inp_bn_b": stack("inp.1.bias"),
    "inp_bn_mean": stack("inp.1.running_mean"), "inp_bn_var": stack("inp.1.running_var"),
    # Five blocks: conv 24 -> 24, 5 points wide, spread 1, 2, 4, 8, 16 apart; batch norm
    # (axes: net, block, ...)
    "blk_w": np.stack([stack(f"blocks.{i}.conv.weight") for i in range(5)], axis=1),
    "blk_b": np.stack([stack(f"blocks.{i}.conv.bias") for i in range(5)], axis=1),
    "blk_bn_w": np.stack([stack(f"blocks.{i}.norm.weight") for i in range(5)], axis=1),
    "blk_bn_b": np.stack([stack(f"blocks.{i}.norm.bias") for i in range(5)], axis=1),
    "blk_bn_mean": np.stack([stack(f"blocks.{i}.norm.running_mean") for i in range(5)], axis=1),
    "blk_bn_var": np.stack([stack(f"blocks.{i}.norm.running_var") for i in range(5)], axis=1),
    # Output: 24 -> 1 score per point
    "out_w": stack("out.weight"), "out_b": stack("out.bias"),
}

settings = {
    "dilations": np.array([1, 2, 4, 8, 16]),
    "bn_eps": np.float32(1e-5),          # PyTorch's BatchNorm1d default, which StepNet uses
    "sample_hz": 100,
    "window": 400,                       # NET_WINDOW_S 4.0 s
    "hop": 25,                           # NET_HOP_S 0.25 s
    "delay": 60,                         # COUNT_DELAY_S 0.6 s
    "min_gap": 40,                       # MIN_STRIDE_S 0.4 s
    "context": 100,                      # CONTEXT: 1 s before a stride in the window
    "threshold": np.float32(0.5),        # THRESHOLD
    "acc_scale": 2.0, "gyro_scale": 300.0,
    # Our axes -> Raph's layout (rows: his x, y, z; columns: our x, y, z)
    "to_raph": np.array([[0, 1, 0], [1, 0, 0], [0, 0, -1]], dtype=np.float64),
    "stride_m": float(saved["distance_model"]["a"]),   # his fitted metres per stride
    "source": "RaphLemSol/ME193 'How many steps' models/step_net.pt, commit 713da130607d",
}

# Sanity check: trainable weights per net (convolutions and batch-norm scale/shift, not the
# batch norm's running averages, which are fixed numbers learned during training)
trainable = [k for k in arrays if not k.endswith(("_mean", "_var"))]
per_net = sum(arrays[k][0].size for k in trainable)
fixed = sum(arrays[k][0].size for k in arrays if k.endswith(("_mean", "_var")))
print(f"per net: {per_net:,} trainable weights (Raph's Notion page: 16,201), plus {fixed} batch-norm running averages")
assert per_net == 16201, "weight count doesn't match Raph's StepNet"

out.parent.mkdir(parents=True, exist_ok=True)
np.savez(out, **arrays, **settings)
print(f"wrote {out} ({out.stat().st_size / 1024:.0f} KB)")
