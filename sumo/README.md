# Sumo

A LEGO robot fights another robot in a ring of blue tape. If it gets pushed
out, it stops and plays a sad song.

## How it meets the requirements

| Requirement | How |
|---|---|
| LEGO build | Double Motor drive base + Color Sensor, controlled from the laptop over Bluetooth (`lelib.py`) |
| UNO Q as a sensor, over MQTT | HC-SR04 ultrasonic on the UNO Q faces forward. It publishes the distance in cm to `ME193/Rogers/Fiona/sumo/distance` (`unoq_distance/`) |
| Decision policy | **Behavior tree** (`behavior_tree.py`, tree built in `sumo.py`) |
| Autonomous sensor (at least one) | Color Sensor pointing down (sees the blue tape) and the ultrasonic (sees the opponent) |
| Teleop sensor (at least one) | Laptop keyboard (`teleop.py`) publishes `charge` / `out` to `ME193/Rogers/Fiona/sumo/cmd` |
| Pushed out: stop + sad song | `out` command: motors stop, sad trombone plays on the laptop and beeps from the hub |
| ≤ 1 kg, fits in a 30 cm cube | Hardware build: check it on a scale and a box before the match |

## Behavior tree

Ticked top to bottom 20 times a second. The first branch whose condition is true runs.

```
Selector (root)
|-- told we're out?               -> stop + play the sad song (until "reset")
|-- light sensor sees blue tape?  -> back up 0.6 s, then turn 0.5 s
|-- opponent < 30 cm, or "charge" -> full speed forward
'-- otherwise                     -> spin slowly to search
```

## Files

- `sumo.py`: the robot brain. Runs on the laptop.
- `teleop.py`: keyboard commands. Run it in a second terminal.
- `config.py`: card serials, MQTT topics, speeds, and timings. Edit this one.
- `behavior_tree.py`: the Selector, Sequence, Condition, and Action nodes.
- `sad_song.py`: plays "wah wah wah waaah" on the laptop and on the hub.
- `test_sumo.py`: checks the tree's priorities with no hardware.
- `unoq_distance/`: the UNO Q app. `sketch/` reads the HC-SR04, `python/` publishes the distance over MQTT.

## Setup

1. **UNO Q**: wire the HC-SR04 as described at the top of `unoq_distance/sketch/sketch.ino`. ECHO needs a voltage divider. Then open `unoq_distance` as an app in Arduino App Lab and run it.
2. **Config**: put your Double Motor and Color Sensor card serials and colors in `config.py`.
3. **Tape color**: put the robot on the floor, then on the tape, and run the check below. Set `TAPE_COLORS` to whatever the sensor reports on the tape.

## Run

```bash
source my_env_pingpong_py312/bin/activate
cd sumo
python sumo.py --check     # motors off: prints the tape color and the UNO Q distance
python sumo.py             # fight!
python teleop.py           # second terminal: c/SPACE = charge, o = out, r = reset, q = quit
python sumo.py --dry       # no LEGO: prints motor commands (for testing MQTT and teleop)
python test_sumo.py        # unit tests for the behavior tree
```

If forward drives backward, set `FORWARD_SIGN = -1` in `config.py`. If the
robot spins when it should go straight, set `SWAP_SIDES = True`.
