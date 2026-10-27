"""
Sumo robot brain: runs on the laptop, drives the LEGO robot over Bluetooth.

Sensors
  LEGO light sensor (autonomous)  -> Color Sensor pointing down: on the blue tape?
  UNO Q ultrasonic (autonomous)   -> distance to the opponent, arrives over MQTT
  Laptop keyboard (teleop)        -> "charge" / "out" commands, arrive over MQTT
                                     (sent by teleop.py)

Behavior tree, ticked top to bottom LOOP_HZ times a second:

    Selector (root)
    |-- Sequence: told we're out?               -> stop + sad song
    |-- Sequence: on the blue tape?             -> back up, then turn
    |-- Sequence: opponent < 30 cm or "charge"? -> full speed forward
    '-- search                                  -> spin slowly

Run (from the repo root, with the ping-pong environment):
    source my_env_pingpong_py312/bin/activate
    cd sumo
    python sumo.py            # fight!
    python sumo.py --check    # motors off; print what the sensors see
    python sumo.py --dry      # no LEGO hardware; print motor commands instead
"""

import argparse
import random
import time

import paho.mqtt.client as mqtt

import config
import sad_song
from behavior_tree import Action, Condition, Selector, Sequence, SUCCESS


class Blackboard:
    """Everything the robot currently knows. MQTT callbacks write to it from
    their own thread; the main loop reads it once per tick."""

    def __init__(self):
        self.now = time.monotonic()
        self.on_tape = False
        self.distance_cm = None
        self.distance_time = 0.0
        self.charge_until = 0.0
        self.out = False
        self.song_played = False
        self.escape_start = None       # when the current back-up-and-turn began
        self.escape_turn = 1           # +1 = turn right, -1 = turn left
        self.active = ""               # name of the action that ran last tick


# --- Robot hardware ---------------------------------------------------------

class LegoRobot:
    def __init__(self):
        from lelib import colorSensor, doubleMotor
        print("Connecting to the Double Motor...")
        self.dm = doubleMotor()
        self.dm.connect(config.MOTOR_CARD_SERIAL, card_color=config.MOTOR_CARD_COLOR)
        print("Connecting to the Color Sensor...")
        self.cs = colorSensor()
        self.cs.connect(config.SENSOR_CARD_SERIAL, card_color=config.SENSOR_CARD_COLOR)
        self._last = None

    def color(self):
        return self.cs.detect_color()

    def on_tape(self):
        return self.color() in config.TAPE_COLORS

    def drive(self, left, right):
        """Tank drive, -100..100 each side. Only sends when the command changes,
        so we don't flood Bluetooth with the same command 20 times a second."""
        cmd = (int(left), int(right))
        if cmd == self._last:
            return
        self._last = cmd
        l, r = (cmd[1], cmd[0]) if config.SWAP_SIDES else cmd
        self.dm.movement_move_tank(config.FORWARD_SIGN * l, config.FORWARD_SIGN * r)

    def stop(self):
        self.drive(0, 0)

    def sad_song(self):
        sad_song.play(hub=self.dm)

    def close(self):
        try:
            self._last = None
            self.stop()
        except Exception:
            pass


class DryRobot:
    """Stand-in with no hardware: prints motor commands. Never sees tape."""

    def __init__(self):
        self._last = None

    def color(self):
        return "No color"

    def on_tape(self):
        return False

    def drive(self, left, right):
        cmd = (int(left), int(right))
        if cmd != self._last:
            self._last = cmd
            print(f"  motors  left={cmd[0]:4d}  right={cmd[1]:4d}")

    def stop(self):
        self.drive(0, 0)

    def sad_song(self):
        sad_song.play()

    def close(self):
        pass


# --- The behavior tree ------------------------------------------------------

def build_tree(robot):
    # Conditions ------------------------------------------------------------
    def told_out(bb):
        return bb.out

    def on_tape_or_escaping(bb):
        # Keep escaping after we've rolled off the tape, until the turn is done.
        if bb.on_tape:
            return True
        return bb.escape_start is not None and bb.now - bb.escape_start < config.BACKUP_S + config.TURN_S

    def opponent_close_or_charge(bb):
        fresh = bb.now - bb.distance_time < config.DISTANCE_STALE_S
        close = fresh and bb.distance_cm is not None and 0 < bb.distance_cm < config.OPPONENT_CM
        return close or bb.now < bb.charge_until

    # Actions ---------------------------------------------------------------
    def stop_and_sad_song(bb):
        robot.stop()
        if not bb.song_played:
            bb.song_played = True
            robot.sad_song()
        # RUNNING forever: we stay out until someone sends "reset".

    def back_up_and_turn(bb):
        if bb.on_tape:
            # Still on the tape: (re)start backing up. Pick a turn direction
            # only when a fresh escape starts.
            if bb.escape_start is None or bb.now - bb.escape_start >= config.BACKUP_S + config.TURN_S:
                bb.escape_turn = random.choice((-1, 1))
            bb.escape_start = bb.now
        t = bb.now - bb.escape_start
        if t < config.BACKUP_S:
            robot.drive(-config.BACKUP_SPEED, -config.BACKUP_SPEED)
        else:
            s = config.TURN_SPEED * bb.escape_turn
            robot.drive(s, -s)

    def charge(bb):
        robot.drive(config.CHARGE_SPEED, config.CHARGE_SPEED)

    def search(bb):
        robot.drive(config.SEARCH_SPEED, -config.SEARCH_SPEED)

    return Selector("root", [
        Sequence("out?", [Condition("told out", told_out),
                          Action("OUT: stop + sad song", stop_and_sad_song)]),
        Sequence("tape?", [Condition("on blue tape", on_tape_or_escaping),
                           Action("EDGE: back up + turn", back_up_and_turn)]),
        Sequence("attack?", [Condition("opponent close or charge", opponent_close_or_charge),
                             Action("CHARGE", charge)]),
        Action("SEARCH: spin slowly", search),
    ])


# --- MQTT -------------------------------------------------------------------

def start_mqtt(bb):
    def on_connect(client, userdata, flags, reason_code, properties):
        if reason_code.is_failure:
            print(f"MQTT: could not connect to {config.MQTT_BROKER}: {reason_code}")
            return
        client.subscribe([(config.TOPIC_DISTANCE, 0), (config.TOPIC_CMD, 1)])
        print(f"MQTT: connected, listening on {config.MQTT_BASE}/...")

    def on_message(client, userdata, msg):
        text = msg.payload.decode(errors="replace").strip()
        if msg.topic == config.TOPIC_DISTANCE:
            try:
                bb.distance_cm = float(text)
                bb.distance_time = time.monotonic()
            except ValueError:
                pass
        elif msg.topic == config.TOPIC_CMD:
            cmd = text.lower()
            print(f"MQTT: command '{cmd}'")
            if cmd == "charge":
                bb.charge_until = time.monotonic() + config.CHARGE_HOLD_S
            elif cmd == "out":
                bb.out = True
            elif cmd == "reset":
                bb.out = False
                bb.song_played = False
                bb.charge_until = 0.0

    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
    client.on_connect = on_connect
    client.on_message = on_message
    client.connect_async(config.MQTT_BROKER, config.MQTT_PORT, keepalive=30)
    client.loop_start()
    return client


# --- Main loops -------------------------------------------------------------

def check_sensors(robot, bb):
    """Motors off. Print the color sensor and the latest UNO Q distance so you
    can set TAPE_COLORS and OPPONENT_CM."""
    print("Sensor check -- motors are off. Ctrl+C to stop.\n")
    while True:
        age = time.monotonic() - bb.distance_time
        dist = f"{bb.distance_cm:6.1f} cm ({age:4.1f} s ago)" if bb.distance_cm is not None else "  (none yet)"
        tape = "TAPE" if robot.on_tape() else "    "
        print(f"\rcolor={robot.color():10s} {tape}   distance={dist}   ", end="", flush=True)
        time.sleep(0.1)


def fight(robot, bb, client):
    tree = build_tree(robot)
    period = 1.0 / config.LOOP_HZ
    last_active = None
    print("Fighting! Ctrl+C to stop.\n")
    while True:
        start = time.monotonic()
        bb.now = start
        bb.on_tape = robot.on_tape()
        tree.tick(bb)
        if bb.active != last_active:
            last_active = bb.active
            print(f"{time.strftime('%H:%M:%S')}  {bb.active}")
            client.publish(config.TOPIC_STATE, bb.active, retain=True)
        time.sleep(max(0.0, period - (time.monotonic() - start)))


def main():
    ap = argparse.ArgumentParser(description="ME193 sumo robot")
    ap.add_argument("--check", action="store_true", help="motors off; print sensor readings")
    ap.add_argument("--dry", action="store_true", help="no LEGO hardware; print motor commands")
    args = ap.parse_args()

    bb = Blackboard()
    client = start_mqtt(bb)
    robot = DryRobot() if args.dry else LegoRobot()
    try:
        if args.check:
            check_sensors(robot, bb)
        else:
            fight(robot, bb, client)
    except KeyboardInterrupt:
        print("\nStopping.")
    finally:
        robot.close()
        client.loop_stop()
        client.disconnect()


if __name__ == "__main__":
    main()
