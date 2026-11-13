"""
The lock policy: how the safe turns the net's per-frame guesses into
"open" or "stay locked". The laptop (safe_laptop.py) and the UNO Q
(main.py) both run this same code.

    press button ──> ENTERING (status LED turns blue)
        each frame: smooth the net's probabilities over the last few frames;
        a digit (1-5) is accepted once the same answer has been held, with
        at least MIN_CONF confidence, for HOLD_S seconds
        the next digit must be different, or the square must be cleared
        (no hand / fist = 0) first, so one held hand never counts twice
    3 digits ──> right code: OPEN (relocks after OPEN_S or a button press)
                 wrong code: back to locked; MAX_TRIES wrong in a row ->
                 LOCKOUT, which doubles each time it happens again
    no new digit for DIGIT_TIMEOUT_S ──> give up, back to locked

The code itself is never stored, only a salted SHA-256 hash of it
(code.json, written by set_code.py), and a wrong entry never says which
digit was wrong.

Every method returns a list of events (plain dicts, so they can also go
over MQTT) that the caller turns into LEDs, the LED matrix and the latch.
"""

import hashlib
import hmac
import json
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
CODE_PATH = HERE / "code.json"

CODE_LENGTH = 3
MIN_CONF = 0.75          # smoothed probability needed before a digit can count
HOLD_S = 1.0             # how long a digit must be held steady
SMOOTH = 0.5             # weight of the newest frame in the running average
DIGIT_TIMEOUT_S = 15.0
OPEN_S = 20.0
MAX_TRIES = 3
LOCKOUT_S = 30.0

IDLE, ENTERING, OPEN, LOCKOUT = "idle", "entering", "open", "lockout"


def hash_code(digits, salt):
    text = f"{salt}:" + "-".join(str(int(d)) for d in digits)
    return hashlib.sha256(text.encode()).hexdigest()


def load_code(path=CODE_PATH):
    if not path.exists():
        raise SystemExit(f"No code set. Run:  python set_code.py 4 1 3   (your own 3 digits)  -> {path}")
    return json.loads(path.read_text())


class SafeLock:
    def __init__(self, code=None):
        self.code = code or load_code()
        self.state = IDLE
        self.failed = 0
        self.lockouts = 0
        self.until = 0.0                 # when OPEN / LOCKOUT ends
        self._reset_entry(0.0)

    def _reset_entry(self, now):
        self.entered = []
        self.avg = None                  # smoothed probabilities
        self.cand = None                 # digit currently being held
        self.cand_since = now
        self.cleared = True
        self.last_progress = now

    # --- inputs -----------------------------------------------------------------

    def press(self, now):
        """The button on the box."""
        if self.state == LOCKOUT:
            return [{"event": "lockout", "seconds": round(self.until - now)}]
        if self.state == OPEN:
            self.state = IDLE
            return [{"event": "locked"}]
        self.state = ENTERING
        self._reset_entry(now)
        return [{"event": "lights", "on": 1}]

    def update(self, probs, now):
        """Call every frame. probs = the net's 6 probabilities (0-5 fingers),
        or None when no frame was read."""
        if self.state in (OPEN, LOCKOUT) and now >= self.until:
            self.state = IDLE
            return [{"event": "locked"}]
        if self.state != ENTERING:
            return []
        if now - self.last_progress > DIGIT_TIMEOUT_S:
            self.state = IDLE
            return [{"event": "timeout"}, {"event": "locked"}]
        if probs is None:
            return []

        probs = np.asarray(probs, float)
        self.avg = probs if self.avg is None else SMOOTH * probs + (1 - SMOOTH) * self.avg
        best = int(np.argmax(self.avg))
        cand = best if self.avg[best] >= MIN_CONF else None
        if cand != self.cand:
            self.cand, self.cand_since = cand, now
        if cand == 0:
            self.cleared = True
        if cand is None or cand == 0 or now - self.cand_since < HOLD_S:
            return []
        if not self.cleared and self.entered and cand == self.entered[-1]:
            return []                    # still the same hand as the last digit

        self.entered.append(cand)
        self.cleared = False
        self.last_progress = now
        events = [{"event": "digit", "slot": len(self.entered) - 1, "n": cand}]
        if len(self.entered) == CODE_LENGTH:
            events += self._check(now)
        return events

    # --- the decision ------------------------------------------------------------

    def _check(self, now):
        ok = hmac.compare_digest(hash_code(self.entered, self.code["salt"]), self.code["hash"])
        if ok:
            self.state, self.until = OPEN, now + OPEN_S
            self.failed = self.lockouts = 0
            return [{"event": "open"}]
        self.failed += 1
        if self.failed >= MAX_TRIES:
            seconds = LOCKOUT_S * 2 ** self.lockouts
            self.lockouts += 1
            self.failed = 0
            self.state, self.until = LOCKOUT, now + seconds
            return [{"event": "wrong", "tries_left": 0}, {"event": "lockout", "seconds": round(seconds)}]
        self.state = IDLE
        return [{"event": "wrong", "tries_left": MAX_TRIES - self.failed}]

    # --- for drawing --------------------------------------------------------------

    def hold_progress(self, now):
        """(digit being held, 0-1 how far to accepted), or (None, 0)."""
        if self.state != ENTERING or self.cand in (None, 0):
            return None, 0.0
        return self.cand, min(1.0, (now - self.cand_since) / HOLD_S)
