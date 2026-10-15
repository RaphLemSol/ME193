# Virtual Ping-Pong with an Arduino UNO Q Paddle

ME193 assignment by Raphael Lemus Solis.

A virtual ball flies at you across a table drawn over your webcam feed. You
return it by swinging a real paddle: an Arduino UNO Q with an MPU6050 IMU, a
light sensor in the handle, and two motors that buzz when you hit or miss.
Your record of continuous hits is posted live to MQTT topic
`ME193/Rogers/Raphael` as a floating-point number.

## How the assignment requirements are met

| Requirement | How it's done | Code |
|---|---|---|
| **Pose**: is the paddle in the right place? | MediaPipe Pose tracks your right wrist. It has to be under the ball, left to right, when the ball reaches you. | `paddle_wrist()` in `ping_pong.py` |
| **IMU**: is the player swinging? | The MPU6050 reports the peak rotation rate. Over 250 deg/s while the ball is in the hit zone counts as a swing, and harder swings return the ball faster. | `sketch.ino` `loop()`, `Paddle` in `ping_pong.py` |
| **AprilTag**: player level (ball speed) | AprilTag 27 (36h11). How close you hold it picks the level: far is EASY, middle is MEDIUM, close is HARD. | `GameTag` in `ping_pong.py` |
| **AprilTag**: start of the game | Hold tag 27 still for 2 s. A green ring fills, then the game starts. | `GameTag.read()` |
| **Score posted in real time** | Every new record streak is published to `ME193/Rogers/Raphael` as a float, e.g. `7.0` (retained). | `Link.post_score()` |

Two extras use the rest of the hardware:

- **Light sensor (grip check):** your hand has to cover the sensor on the
  handle, so a hit only counts when you're really holding the paddle.
- **Motors and LED matrix:** a short buzz on a hit, a long buzz on a miss, and
  your current streak shown on the UNO Q's LED matrix.

A hit needs all three checks at once: **wrist under the ball + swing + grip**.
A miss resets the streak, and after 3 misses the game is over.

## How it fits together

```
 Paddle (UNO Q)                                    Laptop
 ┌───────────────────────────────┐                 ┌─────────────────────────────┐
 │ sketch.ino (microcontroller)  │                 │ ping_pong.py                │
 │  MPU6050 ─┐                   │                 │  webcam → Pose (wrist)      │
 │  light  ──┼→ Bridge → main.py ┼── MQTT ────────→│        → AprilTag 27        │
 │  motors ←─┤   (Linux side)    │←─ hit / miss ───┤  game logic + drawing       │
 │  LEDs   ←─┘                   │                 │                             │
 └───────────────────────────────┘                 └──────────┬──────────────────┘
                                                              │ record streak (float)
                                                              ▼
                                                  MQTT: ME193/Rogers/Raphael
```

## What's in this folder

| Path | Runs on | What it does |
|---|---|---|
| `ping_pong.py` | Laptop | The game: webcam, pose, AprilTag, scoring, drawing, MQTT |
| `test_parts.py` | Laptop | Tests each part on its own (tags, pose, MQTT, light, MPU6050, motors) |
| `PingPong-UnoQ/sketch/sketch.ino` | UNO Q microcontroller | Reads the MPU6050 and light sensor, drives the motors and LED matrix |
| `PingPong-UnoQ/python/main.py` | UNO Q Linux side | Sends sensor readings to the laptop over MQTT and plays hit / miss feedback |
| `PingPong-UnoQ/app.yaml` | UNO Q | Arduino App Lab app description |
| `tags/tag27.png` | (print it) | The AprilTag used to pick the level and start |
| `models/pose_landmarker_lite.task` | Laptop | MediaPipe pose model (downloaded automatically if missing) |

The deploy tool that copies the app to the board is in [`../tools`](../tools).

## Hardware

- Arduino UNO Q
- Cytron Maker Drive motor driver and two DC motors, on their own battery
- MPU6050 IMU
- Photoresistor and 10 kΩ resistor (light sensor)
- Laptop with a webcam

### Wiring

| Part | UNO Q |
|---|---|
| Maker Drive M1A, M1B | D5, D6 |
| Maker Drive M2A, M2B | D3, D9 |
| Maker Drive GND | GND |
| Motor battery | Maker Drive VB+ / VB− (5V OUT not connected) |
| MPU6050 VCC, GND | 3.3V, GND |
| MPU6050 SDA, SCL | Header pins labeled SDA, SCL (next to AREF) |
| MPU6050 XDA, XCL, AD0, INT | Not connected |
| Photoresistor | 3.3V → photoresistor → A0 |
| 10 kΩ resistor | A0 → 10 kΩ → GND |

```
3.3V ── photoresistor ──┬── 10 kΩ ── GND
                        │
                        A0
```

The UNO Q's pins are 3.3 V, so power the light-sensor divider from 3.3V, never
5V. Tape the MPU6050 and its wires firmly to the paddle so they don't come loose
when you swing.

## Running it

From the `ME193` folder:

```
python tools/deploy.py PingPong-UnoQ       # 1. put the paddle app on the board
cd PingPong
python ping_pong.py                        # 2. play (score is posted)
```

- Keep the paddle still for a second while the board app starts, because it
  measures the gyro offset then.
- Don't cover the light sensor until the grip status stops saying
  "calibrating", because that's when it measures the uncovered reading.
- The board app doesn't restart by itself after the board loses power. Run step 1 again.

Options:

```
python ping_pong.py --no-score    # practice: real paddle, score NOT posted
python ping_pong.py --keyboard    # no paddle: SPACE = swing
python ping_pong.py --offline     # no MQTT at all (implies --keyboard)
```

### Playing

1. Check the top right says **Paddle: connected**.
2. Hold the paddle so your hand covers the light sensor. The grip status says **HELD**.
3. Hold up **tag 27**: far for EASY, closer for MEDIUM, closest for HARD. Keep it still until the green ring fills.
4. Move your **right wrist** under the ball and **swing** as it reaches the orange line.
5. Press **q** or **Esc** in the game window to quit.

Keys: `1` `2` `3` choose the level, `s` starts, and SPACE swings in keyboard mode.

## Watching the score

```
python -c "import paho.mqtt.subscribe as s; s.callback(lambda c,u,m: print(m.topic, m.payload.decode()), 'ME193/Rogers/Raphael', hostname='broker.hivemq.com')"
```

You can also use the HiveMQ web client (hivemq.com/demos/websocket-client):
connect, then subscribe to `ME193/Rogers/Raphael`.

The posted value is the **best streak in the current session**. It only goes up
during a session, and it starts again from `1.0` at the first hit after you
relaunch the game.

### MQTT topics (broker.hivemq.com)

| Topic | Direction | Payload |
|---|---|---|
| `ME193/Rogers/Raphael` | laptop → class | Record streak as a float, e.g. `7.0` (retained) |
| `ME193_Raphael_paddle` | UNO Q → laptop | `{"gyro": 312.4, "accel": 1.03, "light": 512, "imu": true}` |
| `ME193_Raphael_paddle/feedback` | laptop → UNO Q | `{"event": "hit", "streak": 4}` |

## Testing each part

```
python test_parts.py            # pick from a menu
python test_parts.py tags       # AprilTag 27: size → level, hold still → start
python test_parts.py pose       # right-wrist tracking
python test_parts.py mqtt       # is the paddle sending data?
python test_parts.py light      # live light reading and grip check
python test_parts.py mpu        # live gyro / accel and swing counter
python test_parts.py motors     # each motor forward / backward, then the buzzes
```

Quit a camera test with `q` (click the window first), and a terminal test with Ctrl+C.

## Tuning

The settings are at the top of `ping_pong.py`:

| Problem | Change |
|---|---|
| Real swings aren't detected | Lower `SWING_GYRO_DPS` |
| Small wiggles count as swings | Raise `SWING_GYRO_DPS` |
| Swings on time are judged late | Raise `SWING_WINDOW_S` |
| Too hard to line up with the ball | Raise `PADDLE_HALF_WIDTH` |
| Grip never shows HELD | Lower `GRIP_CHANGE`, or set `REQUIRE_GRIP = False` |
| Tag distance → level feels off | Change `LEVEL_SIZES` (see `test_parts.py tags`) |
| Ball too fast / slow | Change `LEVEL_TRAVEL_S` |

## Troubleshooting

| Symptom | Fix |
|---|---|
| "Paddle: NOT CONNECTED" / "No paddle data" | The board app isn't running. Run `python tools/deploy.py PingPong-UnoQ` |
| "MPU6050 not answering" | A loose VCC / GND / SDA / SCL wire. The sketch wakes the sensor again on its own once the wire is back. |
| Gyro well above 0 while still | The paddle moved while the app started. Redeploy with it still. |
| Light stuck at 1023 or 0 | The resistor or A0 wire is loose |
| Motors don't spin | Check the motor battery on VB+ / VB− and that the board app is running |
| Board app keeps stopping | The board is losing power. Keep the motors on their own battery. |
