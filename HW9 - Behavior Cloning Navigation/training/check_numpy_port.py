"""Check the numpy port of Raph's step counter against his PyTorch original.

Usage:  python check_numpy_port.py <folder of Raph's "How many steps"> <recording.csv> ...
(the laptop needs torch, scipy and numpy; the port, uno_q/python/stride_counter.py, needs
only numpy)

Recordings in HW7's format (time, ax..gz) are in our axes and get the axis renaming;
recordings in Raph's format (t_ms, ax..gz) are already in his layout.

For every recording, on exactly the same windows (4 s, one every 0.25 s, plus the last):
1. Scores: each of the 5 nets' chance of mid-swing at every sample, PyTorch vs numpy.
   Must agree within TOLERANCE (both are 32-bit; only the order of additions differs).
2. Peaks: scipy.signal.find_peaks vs the port's find_peaks, on every window's average and
   on every net's own output. Must be identical.
3. Counting: Raph's run_counter vs the port's count_recording: the same strides at the same
   samples, the same per-net counts, the same steps.
4. Live: the board's LiveStrideCounter fed one sample at a time (as on the board). It never
   counts the last ~0.6 s (no "final" window), so it may be lower by a stride if the walk
   ends right at the end of the recording.
"""
import sys
from pathlib import Path
import numpy as np
import torch
from scipy.signal import find_peaks as scipy_find_peaks

TOLERANCE = 1e-5

repo = sys.argv[1]
files = sys.argv[2:]
sys.path.insert(0, repo)
import step_net as sn                                   # noqa: E402  Raph's original

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "uno_q" / "python"))
import stride_counter as port                           # noqa: E402  the numpy port

nets_np = port.StrideNets(Path(__file__).resolve().parent.parent / "uno_q" / "python" / "raph_step_model.npz")
saved = torch.load(f"{repo}/models/step_net.pt", weights_only=True)
nets_t = []
for state in saved["nets"]:
    net = sn.StepNet()
    net.load_state_dict(state)
    nets_t.append(net.eval())

all_ok = True
print(f"{'recording':42s} {'max score diff':>14s} peaks  strides(torch/numpy)  net counts  steps torch/numpy/live")
for f in files:
    d = np.genfromtxt(f, delimiter=",", names=True, dtype=None, encoding="utf-8")
    raph_format = "t_ms" in d.dtype.names
    data = np.c_[d["ax"], d["ay"], d["az"], d["gx"], d["gy"], d["gz"]].astype(float)
    x = data if raph_format else nets_np.to_raph_axes(data)     # both versions get this input

    # 1-3: the port, offline, with every window's output kept
    count_np, outputs = port.count_recording(nets_np, x, raph_axes=True)
    # 1: Raph's nets on the same windows
    wins = [x[e - nets_np.window:e] for e, _ in outputs]
    probs_t = np.concatenate([sn.predict(nets_t, wins[i:i + 64]) for i in range(0, len(wins), 64)], axis=1)
    probs_np = np.stack([p for _, p in outputs], axis=1)        # (5, windows, 400)
    max_diff = float(np.abs(probs_t - probs_np).max())
    # 2: peaks, scipy vs the port, on every window (average and each net)
    peaks_same = True
    for w in range(probs_np.shape[1]):
        for p in [probs_np[:, w].mean(axis=0), *probs_np[:, w]]:
            a = scipy_find_peaks(p, height=nets_np.threshold, distance=nets_np.min_gap)[0]
            b = port.find_peaks(p, nets_np.threshold, nets_np.min_gap)
            peaks_same &= np.array_equal(a, b)
    # 3: Raph's counting on his own output
    count_t = sn.run_counter(nets_t, x)
    strides_same = list(count_t.events) == list(count_np.events)
    members_same = list(count_t.member_counts) == list(count_np.member_counts)
    # 4: live, one sample at a time
    live = port.LiveStrideCounter(nets_np)
    for row in data if not raph_format else data @ np.linalg.inv(np.kron(np.eye(2), nets_np.to_raph)).T:
        live.add(row)

    ok = max_diff < TOLERANCE and peaks_same and strides_same and members_same
    all_ok &= ok
    print(f"{Path(f).name:42s} {max_diff:14.1e} {'same' if peaks_same else 'DIFF':5s}  "
          f"{len(count_t.events):3d}/{len(count_np.events):3d} {'same' if strides_same else 'DIFF':5s} "
          f"     {'same' if members_same else 'DIFF':5s}     {count_t.steps:3d}/{count_np.steps:3d}/{live.steps:3d}"
          f"  {'OK' if ok else 'MISMATCH'}")

print("ALL MATCH" if all_ok else "SOMETHING DIFFERS")
sys.exit(0 if all_ok else 1)
