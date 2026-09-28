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

Keep whistling to keep moving: when you stop whistling, the Double Motor stops immediately (set `SILENCE_STOP_S` above 0, e.g. 0.3, to ride through quick breaths).

**Background noise:** at startup the script listens to the room for about a second (don't whistle), then subtracts that noise from everything it hears and keeps updating it between whistles. A sound only counts as a whistle if it's clearly louder than the room at its own pitch and most of its energy sits in one sharp peak. If noise still gets through, raise `NOISE_SNR`, `NOISE_RMS_FACTOR` or `MIN_PEAK_SHARE`; if your whistle stops registering, lower them.

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

### Live spectrogram

Playing and `--calibrate` open a live spectrogram window: the last ~11 s of mic
audio scrolls right to left, with your detected pitch traced in cyan. The top left
shows the pitch in Hz and the nearest note (e.g. `B5 +21c`); the top right shows
what the robot is doing (`FASTER`, `TURN LEFT`, `STOPPED`, ...) with its speed and
wheel powers. The command bands are drawn on the right and light up when active.
Closing the window quits. Use `--no-spectrogram` to turn it off.

### Two whistlers, one robot: the Single Motor

A second teammate whistles a **Single Motor** on the same robot from their own
computer, using their own mic and pitch range. The two computers talk over MQTT:

```
partner's mic -> partner's computer --MQTT--> robot computer --BLE--> Single Motor
 (--role motor)     speed -100..100     ME193/Rogers/<CARD_SERIAL>/single_motor
```

| Partner's whistle (their range) | Single Motor |
|---|---|
| lowest end | full reverse |
| lower part | reverse, slower toward the middle |
| middle (`MOTOR_STOP_SHARE` of the range) | stop |
| upper part | forward, faster toward the top |
| highest end | full forward |
| silence | stop |

1. **Partner calibrates:** `python theWhistlignWorldCup.py --calibrate`. At the end it prints `MOTOR_WHISTLE_LOW_HZ` / `MOTOR_WHISTLE_HIGH_HZ` to paste at the top of the file, or a ready-made `--low ... --high ...`.
2. **Partner runs:** `python theWhistlignWorldCup.py --role motor --low 700 --high 1900` (with their numbers). Their spectrogram shows the reverse / stop / forward bands and the speed being sent.
3. **Robot computer runs its usual role plus `--single-motor`:** e.g. `python theWhistlignWorldCup.py --role ball --single-motor`. It connects the Single Motor (same Connection Card as the Double Motor) and shows `motor +45%` in its spectrogram.

The partner's computer sends ~10 messages a second. If the robot computer hears
nothing for `MOTOR_TIMEOUT_S` (1 s), it stops the Single Motor, so a crash or a
Wi-Fi drop can't leave it spinning. Both computers must use the same `CARD_SERIAL`,
since it's part of the topic. That keeps these messages private to your robot, and
your opponent never sees them.

## Match protocol (agree with your opponent!)

| Event | Who publishes | Message | Ball plays | Goalie plays |
|---|---|---|---|---|
| Kick-off | instructor | `start` | – | – |
| Goalie reaches the ball's light sensor | ball | `RLS-ball_caught` | death song | victory song |
| Ball whistles GOAL in the goal | ball | `RLS-goal_scored` | victory song | death song |

Everyone in ME193 listens on `ME193/Rogers`, so the result messages start with a
match code (`MATCH_CODE`, currently `RLS`) that only you and your opponent use.
Set the same code on both robots before the match; messages with any other code
are ignored.

The ball averages the light sensor's reflection at startup, so keep the area in
front of it clear then. After that, a change of `CATCH_DELTA` counts as "caught".
