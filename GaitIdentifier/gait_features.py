"""
Turns raw IMU samples into windows and features for the two models.

A window is an (N, 6) array: ax, ay, az in g and gx, gy, gz in deg/s,
sampled at SAMPLE_HZ.

Model 1 sees ONE number per window: the peak acceleration along one axis.
Model 2 sees features from all six IMU outputs.
"""

import numpy as np

import gait_config as cfg

WINDOW = int(cfg.WINDOW_S * cfg.SAMPLE_HZ)
STEP = int(cfg.STEP_S * cfg.SAMPLE_HZ)
AXIS_INDEX = {"ax": 0, "ay": 1, "az": 2}


def windows(samples):
    """Slide a WINDOW-long window over (N, 6) samples, STEP at a time."""
    for start in range(0, len(samples) - WINDOW + 1, STEP):
        yield samples[start:start + WINDOW]


# --- Model 1 -----------------------------------------------------------------

def peak_accel(win, axis):
    """Largest acceleration (in g, either sign) along one axis in the window."""
    return float(np.max(np.abs(win[:, AXIS_INDEX[axis]])))


# --- Model 2 -----------------------------------------------------------------

def _dominant_freq(x):
    """Strongest frequency (Hz) between 0.5 and 5 Hz, and how much of the
    signal's power sits in that band. Steps, pedal strokes and running strides
    all live in this range; standing still has almost nothing there."""
    x = x - np.mean(x)
    power = np.abs(np.fft.rfft(x * np.hanning(len(x)))) ** 2
    freqs = np.fft.rfftfreq(len(x), 1 / cfg.SAMPLE_HZ)
    band = (freqs >= 0.5) & (freqs <= 5.0)
    if power[1:].sum() < 1e-9:
        return 0.0, 0.0
    return float(freqs[band][np.argmax(power[band])]), float(power[band].sum() / power[1:].sum())


def _channels(win):
    """The six IMU outputs plus the total acceleration and rotation rate,
    which don't depend on how the sensor is rotated on your leg.

    The gyro has its window average subtracted. An MPU6050 reads a constant
    offset (tens of deg/s) even when still, and it changes between power-ups.
    Leg motion swings back and forth, so averages ~0 over 2 s anyway."""
    gyro = win[:, 3:6] - win[:, 3:6].mean(axis=0)
    acc_mag = np.linalg.norm(win[:, 0:3], axis=1)
    gyro_mag = np.linalg.norm(gyro, axis=1)
    names = cfg.CHANNELS + ["acc_mag", "gyro_mag"]
    return names, np.column_stack([win[:, 0:3], gyro, acc_mag, gyro_mag])


def all_features(win):
    """Feature vector for model 2, and the matching names."""
    names, data = _channels(win)
    feats, labels = [], []
    for name, x in zip(names, data.T):
        stats = {"mean": np.mean(x), "std": np.std(x), "min": np.min(x), "max": np.max(x),
                 "p90-p10": np.percentile(x, 90) - np.percentile(x, 10),
                 "jerk": np.mean(np.abs(np.diff(x)))}    # how jerky the signal is
        if name in ("gx", "gy", "gz"):
            del stats["mean"]                            # always 0 after removing the offset
        feats += list(stats.values())
        labels += [f"{name}_{s}" for s in stats]
    for name in ("acc_mag", "gyro_mag"):
        f, share = _dominant_freq(data[:, names.index(name)])
        feats += [f, share]
        labels += [f"{name}_freq_hz", f"{name}_band_power"]
    return np.array(feats), labels


def feature_names():
    return all_features(np.zeros((WINDOW, 6)) + 1e-3)[1]
