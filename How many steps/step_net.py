"""
The neural-net step counter, shared by train_steps.py and live_steps.py.

The net (StepNet, a 1-D convolutional network in PyTorch) reads 4 s of all
six IMU outputs plus the total acceleration and rotation rate, and outputs,
for every sample, how likely it is that the strapped leg is at mid-swing
right then. Each peak in that output is one stride = 2 steps.

Where the training targets come from: in a walk or run recording, the
strapped shin's rotation rate has one big peak per stride (mid-swing).
label_strides() finds those peaks, and if you counted your steps it picks the
threshold that matches your count. Still and bike recordings have no strides,
which teaches the net that pedaling (also a big, regular rotation) isn't
walking. A plain peak counter can't tell those apart.
"""

import json
import math

import numpy as np
import torch
from scipy.signal import butter, filtfilt, find_peaks
from torch import nn

import gait_config as cfg

HZ = cfg.SAMPLE_HZ
T = int(cfg.NET_WINDOW_S * HZ)          # samples the net sees at once
HOP = int(cfg.NET_HOP_S * HZ)
DELAY = int(cfg.COUNT_DELAY_S * HZ)
MIN_GAP = int(cfg.MIN_STRIDE_S * HZ)
CONTEXT = 100                          # a stride must have 1 s before it in the window
THRESHOLD = 0.5                        # net output that counts as a stride
TOLERANCE = 15                         # +-150 ms: a found stride this close to a label is a hit
ACC_SCALE, GYRO_SCALE = 2.0, 300.0     # rough size of each signal, so the net sees ~unit values


# --- Recordings and labels ----------------------------------------------------

def load_labels():
    """Your step counts / distances: {"walk_....csv": {"steps": 96, "distance_m": 50}}"""
    if cfg.LABELS_PATH.exists():
        return json.loads(cfg.LABELS_PATH.read_text())
    return {}


def load_recordings():
    """Every recording in data/ (not subfolders) as a dict."""
    labels = load_labels()
    recs = []
    for path in sorted(cfg.DATA_DIR.glob("*.csv")):
        activity = path.stem.split("_")[0]
        if activity not in cfg.ACTIVITIES:
            continue
        data = np.loadtxt(path, delimiter=",", skiprows=1, ndmin=2)[:, 1:]
        info = labels.get(path.name, {})
        recs.append({"name": path.name, "activity": activity, "data": data,
                     "steps": info.get("steps"), "distance_m": info.get("distance_m")})
    return recs


def label_strides(data, activity, steps=None):
    """Sample index of every mid-swing of the strapped leg.

    Returns (indices, note). The rotation axis with the most motion is the
    one the shin swings around; its biggest peaks (one per stride) are the
    labels. If you counted your steps, the threshold that gives steps / 2
    strides is used instead of the default."""
    if activity not in cfg.STEP_ACTIVITIES:
        return np.array([], int), "no steps (not walking or running)"
    b, a = butter(2, 6 / (HZ / 2))
    gyro = filtfilt(b, a, data[:, 3:6] - np.median(data[:, 3:6], axis=0), axis=0)
    axis = int(np.argmax(gyro.std(axis=0)))
    best = None
    for sign in (1, -1):
        sig = sign * gyro[:, axis]
        tops, _ = find_peaks(sig, distance=MIN_GAP)
        ref = np.percentile(sig[tops], 95) if len(tops) else 0.0
        if best is None or ref > best[1]:
            best = (sig, ref)
    sig, ref = best

    def strides(frac):
        return find_peaks(sig, height=max(frac * ref, 80.0), distance=MIN_GAP)[0]

    if not steps:
        return strides(0.45), "auto (you didn't count this one)"
    target = steps / 2
    frac = min(np.arange(0.2, 0.81, 0.025), key=lambda f: (abs(len(strides(f)) - target), abs(f - 0.45)))
    found = strides(frac)
    note = f"matched to your count ({2 * len(found)} vs {steps} steps)"
    if abs(2 * len(found) - steps) > max(3, 0.05 * steps):
        note += "  <-- doesn't match well, recount or re-record"
    return found, note


def baseline_count(data):
    """The non-AI comparison: count big swing peaks, the same way as
    label_strides() but without knowing the activity or your count."""
    return label_strides(data, "walk")[0]


# --- The net --------------------------------------------------------------------

def prep(win):
    """(n, 6) raw window -> (8, n) net input. The gyro's offset is removed with
    the window's median (an MPU6050 reads tens of deg/s when still)."""
    acc = win[:, :3]
    gyro = win[:, 3:6] - np.median(win[:, 3:6], axis=0)
    x = np.column_stack([acc / ACC_SCALE, gyro / GYRO_SCALE,
                         (np.linalg.norm(acc, axis=1) - 1) / ACC_SCALE,
                         np.linalg.norm(gyro, axis=1) / GYRO_SCALE])
    return x.T.astype(np.float32)


class Block(nn.Module):
    def __init__(self, width, dilation):
        super().__init__()
        self.conv = nn.Conv1d(width, width, 5, padding=2 * dilation, dilation=dilation)
        self.norm = nn.BatchNorm1d(width)
        self.drop = nn.Dropout(0.1)

    def forward(self, x):
        return x + self.drop(torch.relu(self.norm(self.conv(x))))


class StepNet(nn.Module):
    """8 input signals -> one stride score per sample. The first layer halves
    the rate to 50 Hz (plenty for strides, and twice as fast to train), then
    five dilated convolution blocks let each output see 2.5 s around it:
    the whole stride and the ones next to it, not just one peak."""

    def __init__(self, width=24):
        super().__init__()
        self.inp = nn.Sequential(nn.Conv1d(8, width, 7, stride=2, padding=3),
                                 nn.BatchNorm1d(width), nn.ReLU())
        self.blocks = nn.Sequential(*[Block(width, d) for d in (1, 2, 4, 8, 16)])
        self.out = nn.Conv1d(width, 1, 1)

    def forward(self, x):
        y = self.out(self.blocks(self.inp(x)))
        return nn.functional.interpolate(y, size=x.shape[-1], mode="linear")[:, 0]


# --- Training ----------------------------------------------------------------------

def _rotation(rng, max_deg):
    axis = rng.normal(size=3)
    axis /= np.linalg.norm(axis)
    angle = math.radians(rng.uniform(-max_deg, max_deg))
    k = np.array([[0, -axis[2], axis[1]], [axis[2], 0, -axis[0]], [-axis[1], axis[0], 0]])
    r = np.eye(3) + math.sin(angle) * k + (1 - math.cos(angle)) * k @ k
    if rng.random() < 0.3:                       # strapped on upside down / back to front
        r = r @ np.diag(rng.permutation([1, -1, -1]))
    return r


def _crop(rec, rng):
    """One augmented T-sample training example and its target."""
    data, events = rec["data"], rec["events"]
    stretch = rng.uniform(0.8, 1.25)             # slower / faster cadence
    n = min(int(round(T * stretch)), len(data))
    start = rng.integers(0, len(data) - n + 1)
    src = data[start:start + n]
    pos = np.linspace(0, n - 1, T)
    win = np.column_stack([np.interp(pos, np.arange(n), src[:, c]) for c in range(6)])
    r = _rotation(rng, 25)
    win[:, :3] = win[:, :3] @ r.T * rng.uniform(0.85, 1.15)
    win[:, 3:6] = win[:, 3:6] @ r.T * (n / T) * rng.uniform(0.85, 1.15)
    win += rng.normal(0, [0.01] * 3 + [1.0] * 3, win.shape)
    target = np.zeros(T, np.float32)
    t = np.arange(T)
    for e in (events[(events >= start - 20) & (events < start + n + 20)] - start) * (T - 1) / max(n - 1, 1):
        target = np.maximum(target, np.exp(-0.5 * ((t - e) / 4.0) ** 2))
    return prep(win), target


def train_net(recs, seed=0, iters=1500, batch=32, log=None):
    """Train one StepNet on recordings that have rec["events"] filled in."""
    rng = np.random.default_rng(seed)
    torch.manual_seed(seed)
    recs = [r for r in recs if len(r["data"]) >= T]
    net = StepNet()
    opt = torch.optim.AdamW(net.parameters(), lr=3e-3, weight_decay=1e-4)
    sched = torch.optim.lr_scheduler.OneCycleLR(opt, max_lr=3e-3, total_steps=iters)
    net.train()
    for it in range(iters):
        xs, ys = zip(*(_crop(recs[rng.integers(len(recs))], rng) for _ in range(batch)))
        x, y = torch.from_numpy(np.stack(xs)), torch.from_numpy(np.stack(ys))
        logits = net(x)
        loss = nn.functional.binary_cross_entropy_with_logits(logits, y, weight=1 + 4 * y)
        opt.zero_grad()
        loss.backward()
        opt.step()
        sched.step()
        if log and (it + 1) % 500 == 0:
            log(f"    iter {it + 1}/{iters}  loss {loss.item():.4f}")
    return net.eval()


def save_nets(nets, extra):
    cfg.STEP_MODEL_PATH.parent.mkdir(exist_ok=True)
    torch.save({"nets": [n.state_dict() for n in nets], **extra}, cfg.STEP_MODEL_PATH)


def load_nets():
    saved = torch.load(cfg.STEP_MODEL_PATH, weights_only=False)
    nets = []
    for state in saved["nets"]:
        net = StepNet()
        net.load_state_dict(state)
        nets.append(net.eval())
    return nets, saved


@torch.no_grad()
def predict(nets, wins):
    """(B, n, 6) raw windows -> (members, B, n) stride probabilities."""
    x = torch.from_numpy(np.stack([prep(w) for w in wins]))
    return np.stack([torch.sigmoid(net(x)).numpy() for net in nets])


# --- Counting ----------------------------------------------------------------------

class StepCounter:
    """Turns the net's output on overlapping windows into a running count,
    exactly the same way live and in testing. A stride is counted once it is
    COUNT_DELAY_S old, so it's never counted twice as the window slides.
    Each ensemble member keeps its own count too: their spread is the
    counter's own estimate of how unsure it is."""

    def __init__(self, members, since=0):
        """since: ignore strides before this sample number (live: the reset)."""
        self.members = members
        self.since = since
        self.events = []                       # strides found by the ensemble average
        self.member_last = [-10 ** 9] * members
        self.member_counts = [0] * members
        self.strides = []                      # per-stride info for the distance estimate

    def update(self, probs, win, end, final=False):
        """probs: (members, n) net output for win, the n samples ending at
        absolute sample number end. final=True also counts the newest strides
        (end of a recording)."""
        n = probs.shape[1]
        lo = max(end - n + (CONTEXT if end > n else 0), self.since)
        hi = end if final else end - DELAY
        for m, p in enumerate(probs):
            for i in find_peaks(p, height=THRESHOLD, distance=MIN_GAP)[0]:
                t = end - n + i
                if lo <= t < hi and t - self.member_last[m] >= MIN_GAP:
                    self.member_last[m] = t
                    self.member_counts[m] += 1
        mean = probs.mean(axis=0)
        for i in find_peaks(mean, height=THRESHOLD, distance=MIN_GAP)[0]:
            t = end - n + i
            last = self.events[-1] if self.events else -10 ** 9
            if lo <= t < hi and t - last >= MIN_GAP:
                self.events.append(t)
                self.strides.append(stride_info(win, i, t - last))

    @property
    def steps(self):
        return 2 * len(self.events)

    def spread(self):
        """Standard deviation of the members' step counts."""
        return float(np.std(2 * np.array(self.member_counts)))


def run_counter(nets, data):
    """Run the live counter over a whole recording."""
    counter = StepCounter(len(nets))
    ends = list(range(T, len(data) + 1, HOP))
    if not ends:
        return counter
    if ends[-1] != len(data):
        ends.append(len(data))
    for k in range(0, len(ends), 64):            # many windows per net call, for speed
        chunk = ends[k:k + 64]
        probs = predict(nets, [data[e - T:e] for e in chunk])
        for j, e in enumerate(chunk):
            counter.update(probs[:, j], data[e - T:e], e, final=(e == ends[-1]))
    return counter


def match_events(found, truth, tol=TOLERANCE):
    """Pair found strides with labeled ones (each used once): hits, misses,
    extras, and the timing error of each hit in ms."""
    found, truth = list(found), list(truth)
    used, dts = set(), []
    for f in found:
        best = None
        for j, t in enumerate(truth):
            if j not in used and abs(f - t) <= tol and (best is None or abs(f - t) < abs(f - truth[best])):
                best = j
        if best is not None:
            used.add(best)
            dts.append((f - truth[best]) * 1000 / HZ)
    hits = len(used)
    return hits, len(truth) - hits, len(found) - hits, dts


# --- Distance ----------------------------------------------------------------------

def stride_info(win, i, gap):
    """What the distance model needs about one stride: its duration, the
    shin's peak rotation rate (faster swing = longer stride) and the range of
    total acceleration over the stride."""
    period = gap / HZ if gap < 2.5 * HZ else None        # first stride after stopping
    gyro = win[:, 3:6] - np.median(win[:, 3:6], axis=0)
    swing = float(np.max(np.linalg.norm(gyro[max(0, i - 15):i + 16], axis=1)))
    back = int((period or 1.1) * HZ)
    acc = np.linalg.norm(win[max(0, i - back):i + 1, :3], axis=1)
    return {"period": period, "swing": swing, "acc_range": float(np.ptp(acc)) if len(acc) else 0.0}


# Stride length = a + b * feature. Fitted by train_steps.py.
DISTANCE_FEATURES = {
    "constant": lambda s, p: 0.0,
    "cadence": lambda s, p: 1.0 / p,                       # strides per second
    "swing": lambda s, p: s["swing"] / 100.0 * p,          # swing speed x stride time
    "weinberg": lambda s, p: s["acc_range"] ** 0.25,       # Weinberg (2002) bounce rule
}


def stride_features(strides, kind):
    """Feature value of each stride. A stride with no duration (the first one
    after standing) gets the median duration of the others."""
    periods = [s["period"] for s in strides if s["period"]]
    typical = float(np.median(periods)) if periods else 1.1
    return np.array([DISTANCE_FEATURES[kind](s, s["period"] or typical) for s in strides])


def distance_m(strides, model):
    """Metres walked, from the strides found and a fitted distance model."""
    if not strides:
        return 0.0
    if model is None:                       # not calibrated: rule of thumb from your height
        periods = np.array([s["period"] or 1.1 for s in strides])
        step = np.where(periods < 0.85, 0.65, 0.415) * cfg.HEIGHT_M   # running vs walking
        return float(np.sum(2 * step))
    z = stride_features(strides, model["kind"])
    return float(np.sum(np.clip(model["a"] + model["b"] * z, 0.3, 3.5)))
