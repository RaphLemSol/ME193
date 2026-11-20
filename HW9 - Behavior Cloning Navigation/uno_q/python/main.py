"""Nolop Navigator: the board side of HW9 (Linux side of the UNO Q).

Built in the order of uno_q/README.md:
- Step 1: the App Lab web_ui brick serves ../assets/ (the phone page) on port 7000 and
  answers the page's API requests.
- Step 3: read the ankle sensor (sensor.py) 10 times a second and check every reading.
- Step 4: count steps with Raph's counter (stride_counter.py, his 5 trained nets in plain
  numpy). Every reading, including the "not real" placeholders for lost ones, goes to the
  counter; every 0.25 s it runs the nets on the last 4 s.
- Steps 5-7 (now): the page's three addresses (protocol: uno_q/README.md):
    GET  /api/state  -> the running totals since the last reset
    GET  /api/reset  -> counts to 0, a new walk (walks.py), {"ok": true, "walk": n}
    POST /api/rows   -> the page's rows and undos, saved to the walk's CSV (walks.py)
- Step 9: count turns from the same readings (turns.py): after Start the walker stands
  still for 5 s while the gyro's offset is measured; then a turn is the heading changing
  by more than 60° within 3 s. When a turn is counted, the step count and meters at that
  moment are kept (steps_at_last_turn, distance_at_last_turn) for "steps since the turn".
  Stairs stay false (no stairs classifier).
- Navigate: GET /api/predict answers with the trained policy (policy.py, a lookup table in
  policy.json) for the board's current state. policy.json is read again whenever it
  changes, so a new policy can be copied over without restarting the app.
The log shows the steps each time they change, and every 10 s a summary with how long the
nets took on the board.

The page's requests are handled on other threads while loop() keeps counting, so `lock`
makes sure a reset, a reading being counted and an answer never interleave halfway.
"""
import os
import threading
import time
import traceback

import numpy as np
from arduino.app_utils import App, Logger
from arduino.app_bricks.web_ui import WebUI

from sensor import Sensor
from stride_counter import StrideNets, LiveStrideCounter
from walks import WalkStore
from turns import TurnCounter
from policy import Policy

logger = Logger("nolop-navigator")
HERE = os.path.dirname(os.path.abspath(__file__))

ui = WebUI()            # serves ../assets/ on port 7000 (the port is set in ../app.yaml)
sensor = Sensor(logger)
counter = LiveStrideCounter(StrideNets(os.path.join(HERE, "raph_step_model.npz")))
walks = WalkStore(os.path.join(HERE, "walks"), logger)
turns = TurnCounter()
at_last_turn = {"steps": 0, "distance_m": 0.0}   # the counts when the last turn was counted
STILL_MAX_G = 0.05      # accelerometer spread while the offset was measured; more = not still
policy = Policy(os.path.join(HERE, "policy.json"), logger)
lock = threading.Lock()

SUMMARY_S = 10          # log a summary this often
summary = {"time": time.monotonic(), "received": 0, "gaps": 0, "bad": 0}
run_ms = []             # how long each run of the 5 nets took since the last summary
last_steps = 0          # to log the steps only when they change


# --- Counting -----------------------------------------------------------------------------

def count_readings(readings):
    """Feed the readings to the step counter, timing each call that ran the nets."""
    global last_steps
    for values, ok in readings:
        start = time.perf_counter()
        with lock:
            ran = counter.add(values, ok)
            was_ready = turns.ready
            turn = turns.add(values, ok)
            if turn:
                at_last_turn.update(steps=counter.steps, distance_m=counter.distance)
        if ran and ok:
            run_ms.append((time.perf_counter() - start) * 1000)
        if turns.ready and not was_ready:
            still = "" if turns.still_spread <= STILL_MAX_G else " - NOT STILL, turns may be off"
            logger.info(f"Gyro offset measured (gx gy gz {[round(float(b), 1) for b in turns.bias]} deg/s, "
                        f"accelerometer spread {turns.still_spread:.3f} g{still})")
        if turn:
            logger.info(f"Turn {turn}: {turns.left} left, {turns.right} right, at {counter.steps} steps")
    if counter.steps != last_steps:
        last_steps = counter.steps
        t = counter.totals()
        logger.info(f"Steps {t['steps']} (± {t['steps_unc']:.1f}), {t['distance_m']:.1f} m")


def log_summary():
    """Every SUMMARY_S seconds: what arrived since the last summary, the count, and how long
    the nets took (typical and slowest; one run every 250 ms is the budget)."""
    global run_ms
    now = time.monotonic()
    if now - summary["time"] < SUMMARY_S:
        return
    got = sensor.received - summary["received"]
    lost = sensor.gaps - summary["gaps"]
    bad = sensor.bad - summary["bad"]
    timing = (f"nets ran {len(run_ms)} times, median {np.median(run_ms):.0f} ms, slowest {max(run_ms):.0f} ms"
              if run_ms else "nets didn't run")
    logger.info(f"Sensor: {got} readings in {now - summary['time']:.1f} s, {lost} lost, {bad} bad, "
                f"status {sensor.status()} | steps {counter.steps}, {counter.distance:.1f} m | "
                f"turns L{turns.left} R{turns.right}, heading {turns.heading:.0f}° | {timing}")
    summary.update(time=now, received=sensor.received, gaps=sensor.gaps, bad=sensor.bad)
    run_ms = []


# --- The page's API (steps 5-7) ------------------------------------------------------------

def http_state():
    """GET /api/state: the running totals since the last reset. The page rounds steps down
    and works out steps/meters since the last turn and the number of turns itself."""
    with lock:
        return {
            "steps": counter.steps,                 # whole strides x 2
            "distance_m": round(counter.distance, 2),
            "turns_left": turns.left, "turns_right": turns.right,
            "steps_at_last_turn": at_last_turn["steps"],
            "distance_at_last_turn": round(at_last_turn["distance_m"], 2),
            "heading_deg": round(turns.heading, 1),  # drifts; the page saves it, the policy doesn't use it
            "on_stairs": False,                     # no stairs classifier yet
            "walks_used": walks.route_walk_count(), # route walk files on the board ("Walks used")
        }


def http_reset(walker: str = "", kind: str = ""):
    """GET /api/reset?walker=Raph&kind=demo: counts to 0 and a new walk. The page only starts
    the walk once it gets {"ok": true, "walk": n}."""
    try:
        with lock:
            number = walks.start_walk(walker, kind)
            counter.reset()
            turns.reset()                           # measures the gyro offset again (stand still 5 s)
            at_last_turn.update(steps=0, distance_m=0.0)
        return {"ok": True, "walk": number}
    except ValueError as e:
        logger.warning(f"Reset refused: {e}")
        return {"ok": False, "error": str(e)}


def http_rows(body: dict):
    """POST /api/rows with {"items": [...]}: save the rows and undos in order; answer ok only
    once every walk touched is written to disk."""
    try:
        with lock:
            result = walks.add_items(body.get("items", []))
        if result["added"] or result["removed"]:
            logger.info(f"Rows: +{result['added']} -{result['removed']} ({result['skipped']} already had)")
        return {"ok": True, **result}
    except Exception as e:
        logger.error(f"Rows not saved: {e}\n{traceback.format_exc()}")
        return {"ok": False, "error": str(e)}


def http_predict():
    """GET /api/predict: the policy's action for the board's current state (the same counts
    the page shows): {"ok": true, "action": "Left", "how": "exact" or "nearest", ...}, or
    {"ok": false, "error": ...} if there is no policy.json yet."""
    with lock:
        obs = {"turns_left": turns.left, "turns_right": turns.right, "on_stairs": 0,
               "steps_since_turn": counter.steps - at_last_turn["steps"]}
    try:
        answer = policy.predict(obs)
    except Exception as e:                      # a broken policy.json: say so, keep running
        logger.error(f"Policy not usable: {e}")
        return {"ok": False, "error": f"policy not usable: {e}"}
    if not answer["action"]:
        return {"ok": False, "error": "no policy on the board yet"}
    return {"ok": True, **answer, "observation": obs}


ui.expose_api("GET", "/api/state", http_state)
ui.expose_api("GET", "/api/predict", http_predict)
ui.expose_api("GET", "/api/reset", http_reset)
ui.expose_api("POST", "/api/rows", http_rows)


# --- The main loop ---------------------------------------------------------------------------

def loop():
    """Runs over and over (App.run): collect the sensor's readings, count, then wait 0.1 s."""
    try:
        count_readings(sensor.poll())
        log_summary()
    except Exception:
        # On a power bank nobody would restart a crashed app, so log and carry on (as HW7)
        logger.error(f"Error in loop, continuing:\n{traceback.format_exc()}")
    time.sleep(0.1)            # 10 polls a second -> about 10 readings per batch


logger.info("Nolop Navigator started (build step 9: page + sensor + steps + turns + API)")
App.run(user_loop=loop)
