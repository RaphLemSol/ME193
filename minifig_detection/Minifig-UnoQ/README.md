# Minifig-UnoQ

Arduino UNO Q app that drives a car until the minifig reaches the middle of
the camera image. The computer side is `minifig_detection/track_minifig.py`,
which detects the minifig with YOLO and publishes its position over MQTT.

- `python/main.py` - runs on the UNO Q's Linux side: subscribes to the MQTT
  topic, shows the minifig as a dot on the LED matrix, and picks motor speeds.
- `sketch/sketch.ino` - runs on the UNO Q's microcontroller: drives two DC
  motors through a Cytron Maker Drive and lights the LED matrix.
- `python/requirements.txt` - Python packages for the App Lab app.

## Wiring

| UNO Q | Cytron Maker Drive |
|-------|--------------------|
| D4, D5 | M1A, M1B (Motor 1) |
| D2, D3 | M2A, M2B (Motor 2) |
| 5V | 5V |
| GND | GND |

Motors run from a separate 6-12 V battery on VB+/VB-. The Maker Drive's 5V OUT
is left unconnected.

## MQTT message

Topic `ME193_Raphael_minifig` on `test.mosquitto.org`:

```json
{"x": 0.0, "y": 0.0, "width": 0.125, "height": 0.167}
```

`x`, `y` are the box center in [-1, 1] with (0, 0) at the image center;
`width`, `height` are fractions of the frame. `{"found": false}` means no
minifig is in view.
