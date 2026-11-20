"""The live step counter for the board: Raph's StepNet ensemble in plain numpy (no PyTorch).

A port of Raph's step_net.py (https://github.com/RaphLemSol/ME193/tree/main/How%20many%20steps):
the same network, his trained weights (raph_step_model.npz, written by
training/export_raph_cnn.py) and his counting rule. training/check_numpy_port.py checks that
it gives the same output as his PyTorch version.

How it counts:
1. Keep the last 4 s of the ankle sensor (400 samples). Our strap holds the sensor turned
   differently from Raph's, so every sample's axes are renamed to his layout first
   (his x = our y, his y = our x, his z = -our z).
2. Every 0.25 s, run the 5 nets on that window. Each gives, for every sample, the chance that
   the strapped leg is at mid-swing.
3. Average the 5. Each peak above 0.5, at least 0.4 s from the next, is one stride of the
   strapped leg = 2 steps. A peak is counted once it is 0.6 s old (so the nets have seen what
   comes after it, and it can't be counted twice as the window slides) and only if it has
   1 s of the window before it.
4. Each net also keeps its own count; the spread of those 5 counts is the +/-.

So steps go up 2 at a time, about 0.6-0.85 s after the stride. Distance is Raph's fitted
0.823 m per stride (about 0.41 m per step), the same for everyone.

The live counter (LiveStrideCounter) has the same controls as HW7's LiveCounter: add() one
sample, reset(), and the steps / distance / totals(), so the board app can use either.
"""
import numpy as np

CHANNELS = 6                               # ax ay az (g), gx gy gz (deg/s), in OUR axes


# --- The network ------------------------------------------------------------------------

def conv1d(x, w, b, stride=1, pad=0, dil=1):
    """A 1-D convolution, as PyTorch's Conv1d: x (in, L), w (out, in, k), b (out,).
    Every output point is a weighted sum of k input points, `dil` apart, across all input
    signals, plus a bias. Done as one matrix multiply: gather the k shifted copies of the
    (zero-padded) input, then multiply by the weights."""
    c, n = x.shape
    o, _, k = w.shape
    xp = np.pad(x, ((0, 0), (pad, pad)))
    n_out = (n + 2 * pad - dil * (k - 1) - 1) // stride + 1
    cols = np.stack([xp[:, i * dil: i * dil + stride * (n_out - 1) + 1: stride] for i in range(k)])
    return w.transpose(0, 2, 1).reshape(o, k * c) @ cols.reshape(k * c, n_out) + b[:, None]


def batch_norm(x, w, b, mean, var, eps):
    """Batch norm while counting (not training): a fixed scale and shift per signal,
    learned in training. (x - mean) / sqrt(var + eps) * w + b."""
    return (x - mean[:, None]) / np.sqrt(var[:, None] + eps) * w[:, None] + b[:, None]


def stretch(y, n):
    """Linear stretch from len(y) points to n, as PyTorch's interpolate(mode="linear"):
    output point j sits at input position (j + 0.5) * len(y) / n - 0.5, clamped at the ends."""
    pos = (np.arange(n) + 0.5) * len(y) / n - 0.5
    return np.interp(pos, np.arange(len(y)), y).astype(np.float32)


def sigmoid(y):
    """Squash a score into 0..1. For very negative scores exp() overflows to infinity, which
    correctly gives 0; the warning is switched off."""
    with np.errstate(over="ignore"):
        return (1 / (1 + np.exp(-y))).astype(np.float32)


class StrideNets:
    """The 5 trained nets and the settings, from raph_step_model.npz."""

    def __init__(self, path):
        m = np.load(path)
        self.m = {k: m[k] for k in m.files}
        s = self.m
        self.window, self.hop = int(s["window"]), int(s["hop"])
        self.delay, self.min_gap, self.context = int(s["delay"]), int(s["min_gap"]), int(s["context"])
        self.threshold = float(s["threshold"])
        self.acc_scale, self.gyro_scale = float(s["acc_scale"]), float(s["gyro_scale"])
        self.to_raph = s["to_raph"]
        self.stride_m = float(s["stride_m"])
        self.n_nets = len(s["inp_w"])

    def to_raph_axes(self, x):
        """(n, 6) samples in our axes -> Raph's layout (accelerometer and gyro alike)."""
        return np.c_[x[:, :3] @ self.to_raph.T, x[:, 3:6] @ self.to_raph.T]

    def prep(self, win):
        """(n, 6) window in Raph's layout -> the 8 input signals (8, n), as his prep():
        acceleration / 2, rotation minus the window's median (removes the gyro's offset) / 300,
        (total acceleration - 1 g) / 2, total rotation / 300."""
        acc = win[:, :3]
        gyro = win[:, 3:6] - np.median(win[:, 3:6], axis=0)
        x = np.column_stack([acc / self.acc_scale, gyro / self.gyro_scale,
                             (np.linalg.norm(acc, axis=1) - 1) / self.acc_scale,
                             np.linalg.norm(gyro, axis=1) / self.gyro_scale])
        return x.T.astype(np.float32)

    def run_net(self, k, x):
        """Net k on prepared input x (8, n) -> chance of mid-swing at each sample (n,)."""
        s = self.m
        s_eps = s["bn_eps"]
        # First layer: 24 detectors, 7 samples wide, every other sample (n -> n/2); batch
        # norm; ReLU (negatives -> 0)
        y = conv1d(x, s["inp_w"][k], s["inp_b"][k], stride=2, pad=3)
        y = np.maximum(batch_norm(y, s["inp_bn_w"][k], s["inp_bn_b"][k],
                                  s["inp_bn_mean"][k], s["inp_bn_var"][k], s_eps), 0)
        # Five blocks, each looking at 5 points spread 1, 2, 4, 8, 16 apart, so the last one
        # sees about 2.5 s; each adds its input back (y + ...). Dropout does nothing here.
        for i, d in enumerate(s["dilations"]):
            z = conv1d(y, s["blk_w"][k, i], s["blk_b"][k, i], pad=2 * int(d), dil=int(d))
            y = y + np.maximum(batch_norm(z, s["blk_bn_w"][k, i], s["blk_bn_b"][k, i],
                                          s["blk_bn_mean"][k, i], s["blk_bn_var"][k, i], s_eps), 0)
        # Output: the 24 values -> 1 score per point; stretch back to n samples; squash to 0..1
        score = conv1d(y, s["out_w"][k], s["out_b"][k])[0]
        return sigmoid(stretch(score, x.shape[1]))

    def predict(self, win):
        """(n, 6) window in Raph's layout -> (5, n): each net's chance of mid-swing."""
        x = self.prep(win)
        return np.stack([self.run_net(k, x) for k in range(self.n_nets)])


# --- Finding peaks (scipy.signal.find_peaks with height and distance, without scipy) -------

def find_peaks(p, height, distance):
    """Peaks of p at least `height` high and at least `distance` samples apart, chosen exactly
    as scipy.signal.find_peaks(p, height=height, distance=distance) chooses them:
    1. A peak is a point higher than its left neighbour and higher than the next different
       value on its right. A flat top counts once, at its middle (left end if even). The
       first and last samples are never peaks.
    2. Keep peaks at least `height` high.
    3. Going from the highest peak down, remove every lower peak closer than `distance`."""
    n = len(p)
    peaks = []
    i = 1
    while i < n - 1:
        if p[i - 1] < p[i]:
            ahead = i + 1
            while ahead < n - 1 and p[ahead] == p[i]:   # walk along a flat top
                ahead += 1
            if p[ahead] < p[i]:
                peaks.append((i + ahead - 1) // 2)
                i = ahead
        i += 1
    peaks = np.array(peaks, dtype=int)
    peaks = peaks[p[peaks] >= height] if len(peaks) else peaks
    if len(peaks) > 1:
        keep = np.ones(len(peaks), bool)
        order = np.argsort(p[peaks])                    # lowest first; handled highest first
        for j in order[::-1]:
            if not keep[j]:
                continue
            k = j - 1
            while k >= 0 and peaks[j] - peaks[k] < distance:
                keep[k] = False
                k -= 1
            k = j + 1
            while k < len(peaks) and peaks[k] - peaks[j] < distance:
                keep[k] = False
                k += 1
        peaks = peaks[keep]
    return peaks


# --- Counting: Raph's StepCounter -------------------------------------------------------

class StrideCount:
    """Raph's StepCounter.update(), line for line: turns the nets' output on overlapping
    windows into a running count. `events` are the strides found from the 5 nets' average
    (these give the steps); each net also keeps its own count (their spread gives the +/-)."""

    def __init__(self, nets, since=0):
        self.nets = nets
        self.since = since                     # ignore strides before this sample (the reset)
        self.events = []
        self.member_last = [-10 ** 9] * nets.n_nets
        self.member_counts = [0] * nets.n_nets

    def update(self, probs, end, final=False):
        """probs (5, n): the nets' output for the n samples ending at absolute sample `end`.
        final=True also counts the newest strides (only at the end of a recording)."""
        nn = self.nets
        n = probs.shape[1]
        lo = max(end - n + (nn.context if end > n else 0), self.since)   # 1 s of context
        hi = end if final else end - nn.delay                           # at least 0.6 s old
        for m, p in enumerate(probs):
            for i in find_peaks(p, nn.threshold, nn.min_gap):
                t = end - n + i
                if lo <= t < hi and t - self.member_last[m] >= nn.min_gap:
                    self.member_last[m] = t
                    self.member_counts[m] += 1
        mean = probs.mean(axis=0)
        for i in find_peaks(mean, nn.threshold, nn.min_gap):
            t = end - n + i
            last = self.events[-1] if self.events else -10 ** 9
            if lo <= t < hi and t - last >= nn.min_gap:
                self.events.append(t)

    @property
    def steps(self):
        return 2 * len(self.events)

    def spread(self):
        """Standard deviation of the 5 nets' own step counts: the +/-."""
        return float(np.std(2 * np.array(self.member_counts)))


def count_recording(nets, data, raph_axes=False):
    """Count a whole recording offline, as Raph's run_counter(): a window every 0.25 s, plus
    one ending at the last sample (final). data (n, 6) in our axes (raph_axes=True: already in
    his layout). Returns the StrideCount, and every window's (end, probs) for checking."""
    x = data if raph_axes else nets.to_raph_axes(data)
    count = StrideCount(nets)
    ends = list(range(nets.window, len(x) + 1, nets.hop))
    if ends and ends[-1] != len(x):
        ends.append(len(x))
    outputs = []
    for e in ends:
        probs = nets.predict(x[e - nets.window:e])
        count.update(probs, e, final=(e == ends[-1]))
        outputs.append((e, probs))
    return count, outputs


# --- The live counter for the board app ---------------------------------------------------

class LiveStrideCounter:
    """Running totals from the samples as they arrive, with the same controls as HW7's
    LiveCounter: add(sample, ok), reset(), .steps, .distance, totals()."""

    def __init__(self, nets):
        self.nets = nets
        self.window = np.zeros((nets.window, CHANNELS))   # the last 4 s, Raph's layout, oldest first
        self.ok = np.zeros(nets.window, bool)            # which of them are real readings
        self.total = 0                                    # samples seen since the app started
        self.since_run = 0                                # new samples since the nets last ran
        self.reset()

    def reset(self):
        """Back to 0 steps and 0 m. The window is kept; strides before now are ignored."""
        self.count = StrideCount(self.nets, since=self.total)

    def add(self, sample, ok=True):
        """One sample (6 values, our axes). ok=False marks a sample that isn't a real reading
        (all 0 or all -1). Returns True when this sample made the nets run."""
        self.window = np.roll(self.window, -1, axis=0)
        self.window[-1] = self.nets.to_raph_axes(np.asarray(sample, float)[None])[0]
        self.ok = np.roll(self.ok, -1)
        self.ok[-1] = ok
        self.total += 1
        self.since_run += 1
        if self.total < self.nets.window or self.since_run < self.nets.hop:
            return False
        self.since_run = 0
        if self.ok.all():
            # Only from real readings: a window with sensor dropouts in it counts nothing
            self.count.update(self.nets.predict(self.window), self.total)
        return True

    @property
    def steps(self):
        return self.count.steps

    @property
    def distance(self):
        return len(self.count.events) * self.nets.stride_m

    def totals(self):
        return {"steps": self.steps, "steps_unc": self.count.spread(),
                "distance_m": self.distance, "distance_unc": self.count.spread() / 2 * self.nets.stride_m}
