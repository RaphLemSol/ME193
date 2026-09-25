# Whistling World Cup

Drive a LEGO Education robot (Double Motor + Color Sensor) by whistling.
PyAudio listens to the mic, an FFT finds the whistle's pitch, and MQTT
(topic `ME193/Rogers`) runs the match.

## Setup

```powershell
pip install pyaudio paho-mqtt numpy legoeducation
```

On Python 3.14 there's no PyAudio wheel yet; install `pyaudiowpatch` instead
(a drop-in PyAudio fork). The script uses it automatically if `pyaudio` is missing.

At the top of `theWhistlignWorldCup.py`, set `CARD_COLOR` / `CARD_SERIAL` to your Connection Card.

## Whistle commands

Your whistle range (`WHISTLE_LOW_HZ` to `WHISTLE_HIGH_HZ` at the top of the script) is split into five bands ("faster" gets double width, since you use it most). Run `--calibrate`, whistle your lowest and highest notes, press Ctrl+C, and paste in the values it suggests. With the current values (700–1450 Hz):

| Pitch | Command |
|---|---|
| < 825 Hz | stop |
| 825–950 Hz | turn left (spins in place if stopped) |
| 950–1075 Hz | turn right |
| 1075–1325 Hz | speed up (keep whistling to keep accelerating) |
| > 1325 Hz, held 1 s | **GOAL!** (ball only) |

Silence keeps your current speed and drives straight.

## Running

```powershell
python theWhistlignWorldCup.py --calibrate                   # see what pitch you whistle, then set WHISTLE_LOW_HZ / WHISTLE_HIGH_HZ
python theWhistlignWorldCup.py --role ball
python theWhistlignWorldCup.py --role goalie
python theWhistlignWorldCup.py --role ball --no-robot --skip-start   # test without hardware or the start signal
python theWhistlignWorldCup.py --role ball --practice               # practice offline: no MQTT, starts right away
python theWhistlignWorldCup.py --role ball --practice --no-robot   # ...and watch a simulated robot on screen
python theWhistlignWorldCup.py --role goalie --practice --no-robot # goalie practice against a CPU ball
python theWhistlignWorldCup.py --test-sensor                        # live light-sensor readings (needs the Color Sensor)
```

With `--no-robot`, a window shows a top-down field where your robot (yellow) drives from your whistles, with the current command, speed and pitch in the corner. A computer opponent (blue) plays the other role:

- **Ball practice:** a CPU goalie slides along the goal line to block you. The dashed cone in front of you is your simulated light sensor: if the goalie gets inside it (or touches you), you're caught. The GOAL whistle only counts once you're in front of the goal.
- **Goalie practice:** a CPU ball weaves toward your goal. Get in front of it so its light-sensor cone sees you to win; if it reaches the goal, you lose.

Close the window or press **Ctrl+C** to quit.

`--test-sensor` connects just the Color Sensor, records the empty-view baseline, then prints the live reflection, the change from the baseline, and `CAUGHT!` when the ball would count as caught. Use it to tune `CATCH_DELTA`.

Press **Ctrl+C** to quit at any time; the robot stops and disconnects.

## Match protocol (agree with your opponent!)

| Event | Who publishes | Message | Ball plays | Goalie plays |
|---|---|---|---|---|
| Kick-off | instructor | `start` | – | – |
| Goalie reaches the ball's light sensor | ball | `ball_caught` | death song | victory song |
| Ball whistles GOAL in the goal | ball | `goal_scored` | victory song | death song |

The ball averages the light sensor's reflection at startup, so keep the area in
front of it clear then. After that, a change of `CATCH_DELTA` counts as "caught".
