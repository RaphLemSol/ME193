"""
The sad song for when we get pushed out: "wah wah wah waaaah" (sad trombone).

Plays two ways at once:
  - on the laptop speakers (synthesized with numpy the first time, cached in
    ./sounds/sad_trombone.wav, played with `winsound` on Windows or
    `afplay` on macOS)
  - on the LEGO hub's beeper, note by note, so the robot itself is sad too
"""

import os
import subprocess
import threading
import time
import wave

import numpy as np

SR = 44100
HERE = os.path.dirname(os.path.abspath(__file__))
WAV_PATH = os.path.join(HERE, "sounds", "sad_trombone.wav")

# (frequency Hz, seconds): D4, C#4, C4, then a long wobbly B3.
NOTES = [(293.7, 0.45), (277.2, 0.45), (261.6, 0.45), (246.9, 1.4)]


def _trombone_note(freq, seconds, wobble):
    t = np.arange(int(seconds * SR)) / SR
    pitch = freq * (1 + wobble * 0.02 * np.sin(2 * np.pi * 5.5 * t))
    phase = np.cumsum(pitch) / SR
    # A few harmonics, falling off, sounds brassy enough.
    x = sum(np.sin(2 * np.pi * k * phase) / k ** 1.3 for k in range(1, 9))
    attack, release = int(0.04 * SR), int(min(0.25, seconds / 3) * SR)
    env = np.ones(len(t))
    env[:attack] = np.linspace(0, 1, attack)
    env[-release:] = np.linspace(1, 0, release)
    return x * env


def _make_wav():
    os.makedirs(os.path.dirname(WAV_PATH), exist_ok=True)
    parts = [_trombone_note(f, s, wobble=(i == len(NOTES) - 1)) for i, (f, s) in enumerate(NOTES)]
    x = np.concatenate(parts)
    x = x / (np.max(np.abs(x)) + 1e-9) * 0.85
    with wave.open(WAV_PATH, "wb") as f:
        f.setnchannels(1)
        f.setsampwidth(2)
        f.setframerate(SR)
        f.writeframes((x * 32767).astype(np.int16).tobytes())


def play(hub=None):
    """Start the sad song in the background and return right away.
    `hub` is any connected LEGO device (it needs a .beep() method), or None."""
    if not os.path.exists(WAV_PATH):
        _make_wav()
    try:
        if os.name == "nt":
            import winsound
            winsound.PlaySound(WAV_PATH, winsound.SND_FILENAME | winsound.SND_ASYNC)
        else:
            subprocess.Popen(["afplay", WAV_PATH], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except (OSError, RuntimeError) as e:
        print(f"sad song (laptop): {e}")
    if hub is not None:
        threading.Thread(target=_beep_song, args=(hub,), daemon=True).start()


def _beep_song(hub):
    for freq, seconds in NOTES:
        try:
            hub.beep(frequency=int(freq), blocking=False)
        except Exception as e:
            print(f"sad song (hub): {e}")
            return
        time.sleep(seconds)


if __name__ == "__main__":
    play()
    time.sleep(3)
