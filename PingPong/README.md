# Ping-Pong

Virtual ping-pong played with an Arduino UNO Q as the paddle.

- `ping_pong.py` runs on the laptop. It runs the webcam, MediaPipe Pose (wrist
  position), AprilTags (level and start), the game itself, and posts the score.
- `../PingPong-UnoQ` is the UNO Q app. It reads the MPU6050 and the light
  sensor, sends them over MQTT, and buzzes the motors and shows your streak on
  the LED matrix when you hit or miss.

## A hit needs all three

| Check | Sensor | Rule |
|---|---|---|
| Position | Pose (webcam) | Paddle wrist within `PADDLE_HALF_WIDTH` of the ball, left to right |
| Swing | MPU6050 | Rotation rate over `SWING_GYRO_DPS` within `SWING_WINDOW_S` |
| Grip | Light sensor | Reading moved `GRIP_CHANGE` from the uncovered baseline (hand on it) |

Each hit adds one to your streak. A miss resets the streak. After `MAX_MISSES` misses the game ends.

## AprilTag 27 (36h11)

Only tag 27 is used. How close you hold it picks the level (ball speed):

| Tag distance | Level |
|---|---|
| Far (size < 0.10) | 1, EASY |
| Middle | 2, MEDIUM |
| Close (size > 0.18) | 3, HARD |

Hold it still for 2 s to start. A green ring fills up while you hold it. Run
`python test_parts.py tags` to see the size reading, and change `LEVEL_SIZES`
in `ping_pong.py` if the distances feel wrong.

## MQTT (broker.hivemq.com)

| Topic | Direction | Payload |
|---|---|---|
| `ME193/Rogers/Raphael` | laptop → class | Record streak as a float, e.g. `7.0` (retained) |
| `ME193_Raphael_paddle` | UNO Q → laptop | `{"gyro": 312.4, "accel": 1.03, "light": 512}` |
| `ME193_Raphael_paddle/feedback` | laptop → UNO Q | `{"event": "hit", "streak": 4}` |

## Wiring (UNO Q)

| Part | UNO Q |
|---|---|
| Maker Drive M1A, M1B / M2A, M2B | D5, D6 / D3, D9 |
| MPU6050 VCC, GND | 3.3V, GND |
| MPU6050 SDA, SCL | Header pins labeled SDA, SCL (next to AREF) |
| MPU6050 XDA, XCL, AD0, INT | Not connected |
| Photoresistor | 3.3V → photoresistor → A0 |
| 10 kΩ resistor | A0 → 10 kΩ → GND |

The UNO Q's pins are 3.3 V. Power the light-sensor divider from 3.3V, never 5V.

## Running

    python tools/deploy.py PingPong-UnoQ     # from the ME193 folder
    python PingPong/ping_pong.py             # laptop
    python PingPong/ping_pong.py --no-score  # real paddle, score NOT posted (practice)
    python PingPong/ping_pong.py --keyboard  # test without the paddle (SPACE = swing)

The pose model is downloaded to `PingPong/models/` the first time you run it.
Don't cover the light sensor for the first second after the paddle connects,
because that's when it measures the uncovered baseline.
