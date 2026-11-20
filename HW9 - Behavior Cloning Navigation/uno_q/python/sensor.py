"""Reading the ankle sensor from the sketch, with checks (build step 3).

The sketch (../sketch/sketch.ino, HW7's) reads the MPU-6050 100 times a second and queues
each reading as 7 numbers: [running sample number, ax, ay, az (g), gx, gy, gz (deg/s)].
Sensor.poll() collects the whole queue (Bridge.call("get_batch")) and checks it:

- Real reading or not: all six exactly 0 = the sensor restarted asleep (it lost power, e.g.
  a loose VCC/GND wire); all six equal to a raw -1 = the sensor didn't answer (a wire off).
  A real reading is never either: gravity is always there. Same rules as HW7's main.py.
- Missing readings: the running number should go up by exactly 1; a jump of n means n-1
  readings were lost (counted in `gaps`).
- Status: if no real reading arrived for 0.5 s, the sensor "isn't reading"; every change is
  logged.

poll() returns the readings in order as (values, ok) pairs, with a placeholder
(zeros, ok=False) for every lost reading, so that whatever uses them (the step counter in
step 4) keeps the right timing: 400 entries are always 4 s.

One change from HW7: when a batch arrives cut short (not whole readings, which happened a
few times an hour today), it is dropped as in HW7, but the last running number is kept, so
the next batch shows exactly how many readings were lost and they get placeholders.
"""
import time

from arduino.app_utils import Bridge

FIELDS = 7                                   # running number + 6 values per reading
FAILED_READ = (-1 / 2048.0, -1 / 16.4)       # a raw -1 (no answer), converted like the sketch does
STALE_S = 0.5                                # no real reading for this long = not reading
# Times here use time.monotonic(), a clock that only counts forward. The wall clock
# (time.time()) jumps when the board syncs its clock over the network after a restart (about
# 50 s on 2026-11-18), which made the sensor look silent for a moment.
MAX_FILL = 400                               # at most 4 s of placeholders for one gap


def sample_kind(values):
    """'ok', 'zeros' (sensor restarted asleep) or 'no_answer' (sensor didn't answer)."""
    if all(v == 0 for v in values):
        return "zeros"
    acc, gyro = values[:3], values[3:]
    if all(abs(v - FAILED_READ[0]) < 1e-4 for v in acc) and all(abs(v - FAILED_READ[1]) < 1e-3 for v in gyro):
        return "no_answer"
    return "ok"


class Sensor:
    def __init__(self, logger):
        self.logger = logger
        self.last_number = None              # running number of the last reading received
        self.last_good_time = time.monotonic()    # starts as "now" so nothing warns during start-up
        self.last_batch_time = time.monotonic()
        self.last_problem = None             # "zeros" or "no_answer", from the latest bad reading
        self.last_values = None              # the latest reading (6 values), for the log
        # Totals since the app started
        self.received = self.gaps = self.bad = self.cut_batches = 0

    def status(self):
        """{"ok": True}, or {"ok": False, "problem": "zeros" / "no_answer" / "no_data"}."""
        now = time.monotonic()
        if now - self.last_good_time < STALE_S:
            return {"ok": True}
        if now - self.last_batch_time > STALE_S:
            return {"ok": False, "problem": "no_data"}     # the sketch sent nothing at all
        return {"ok": False, "problem": self.last_problem}

    def poll(self):
        """Collect every reading queued since the last call. Returns [(values, ok), ...] in
        order, with (zeros, False) placeholders for lost readings."""
        was_ok = self.status()["ok"]
        batch = Bridge.call("get_batch") or []
        if len(batch) % FIELDS != 0:
            # Not whole readings: drop it (as HW7), but keep last_number so the next batch
            # shows how many readings were lost
            self.cut_batches += 1
            self.logger.warning(f"Dropped a batch of {len(batch)} values (not whole readings)")
            return []
        out = []
        now = time.monotonic()
        for i in range(0, len(batch), FIELDS):
            number, values = int(batch[i]), [float(v) for v in batch[i + 1:i + FIELDS]]
            if self.last_number is not None and number != self.last_number + 1:
                lost = number - self.last_number - 1
                if lost > 0:
                    self.gaps += lost
                    out += [([0.0] * 6, False)] * min(lost, MAX_FILL)
            self.last_number = number
            kind = sample_kind(values)
            self.received += 1
            self.last_batch_time = now
            if kind == "ok":
                self.last_good_time = now
            else:
                self.bad += 1
                self.last_problem = kind
            self.last_values = values
            out.append((values, kind == "ok"))
        # Log each change, for working out later what happened
        is_ok = self.status()
        if is_ok["ok"] != was_ok:
            if is_ok["ok"]:
                self.logger.info("Sensor reading again")
            else:
                self.logger.warning(f"Sensor isn't reading: {is_ok['problem']}")
        return out
