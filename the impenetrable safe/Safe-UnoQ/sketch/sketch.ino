#include "Arduino_RouterBridge.h"
#include "Arduino_LED_Matrix.h"

// Wiring (see the README):
//   D2      button to GND (internal pull-up, pressed = LOW)
//   D5, D6  Cytron Maker Drive M1A, M1B -> yellow gear motor on M1 (the latch)
//   status  the UNO Q's own RGB LED (LED3), nothing to wire
const int BUTTON_PIN = 2;
const int MOTOR_A = 5;
const int MOTOR_B = 6;

// Opening turns the motor clockwise slowly for OPEN_MS; closing turns it back
// the same way for the same time, so it ends where it started.
// LATCH_SPEED: lower = slower. Below ~70 a TT motor may not turn at all.
// If it turns counterclockwise, set MOTOR_REVERSED = true (or swap its wires).
const int LATCH_SPEED = 90;                  // 0-255
const unsigned long OPEN_MS = 400;
const unsigned long CLOSE_MS = OPEN_MS;      // same time back, so it doesn't drift
const bool MOTOR_REVERSED = false;

bool pressed = false;                        // latched until Python reads it
int lastReading = HIGH;
int stableState = HIGH;
unsigned long lastChange = 0;

// Assumed closed at power-up. (Driving it "closed" at every start would turn
// it 15 degrees further each time.)
int latchOpen = 0;
unsigned long motorUntil = 0;

const int MATRIX_COLS = 13;
const int MATRIX_ROWS = 8;
Arduino_LED_Matrix matrix;
uint8_t frame[MATRIX_ROWS * MATRIX_COLS];

// 13x8 pictures for the LED matrix, '#' = on
const char* ICONS[4][8] = {
    {".....###.....",      // 0: locked padlock
     "....#...#....",
     "....#...#....",
     "...#######...",
     "...###.###...",
     "...###.###...",
     "...#######...",
     "...#######..."},
    {"........###..",      // 1: open padlock
     ".......#...#.",
     ".......#.....",
     "...#######...",
     "...###.###...",
     "...###.###...",
     "...#######...",
     "...#######..."},
    {"...#......#..",      // 2: wrong (X)
     "....#....#...",
     ".....#..#....",
     "......##.....",
     "......##.....",
     ".....#..#....",
     "....#....#...",
     "...#......#.."},
    {"...#######...",      // 3: locked out (hourglass)
     "....#...#....",
     ".....#.#.....",
     "......#......",
     "......#......",
     ".....###.....",
     "....#####....",
     "...#######..."},
};

// 3x5 digits, one row per byte (bit 2 = left column)
const uint8_t DIGITS[10][5] = {
    {7, 5, 5, 5, 7}, {2, 6, 2, 2, 7}, {7, 1, 7, 4, 7}, {7, 1, 7, 1, 7}, {5, 5, 7, 1, 1},
    {7, 4, 7, 1, 7}, {7, 4, 7, 5, 7}, {7, 1, 1, 1, 1}, {7, 5, 7, 5, 7}, {7, 5, 7, 1, 7},
};

void setup() {
    pinMode(BUTTON_PIN, INPUT_PULLUP);
    pinMode(MOTOR_A, OUTPUT);
    pinMode(MOTOR_B, OUTPUT);
    pinMode(LED3_R, OUTPUT);
    pinMode(LED3_G, OUTPUT);
    pinMode(LED3_B, OUTPUT);
    set_status(0);

    matrix.begin();
    matrix.setGrayscaleBits(3);
    show_icon(0);
    set_latch(0);

    Bridge.begin();
    Bridge.provide("button", button);
    Bridge.provide("set_status", set_status);
    Bridge.provide("set_latch", set_latch);
    Bridge.provide("show_icon", show_icon);
    Bridge.provide("show_entry", show_entry);
}

void loop() {
    unsigned long now = millis();

    // Debounced button: count a press when it has read LOW for 30 ms
    int reading = digitalRead(BUTTON_PIN);
    if (reading != lastReading) {
        lastReading = reading;
        lastChange = now;
    }
    if (now - lastChange > 30 && reading != stableState) {
        stableState = reading;
        if (stableState == LOW) pressed = true;
    }

    // Stop the latch motor when its run time is up
    if (motorUntil && (long)(now - motorUntil) >= 0) {
        drive(0);
        motorUntil = 0;
    }
}

// Maker Drive: PWM on A = forward, PWM on B = backward, both LOW = stop.
void drive(int speed) {
    if (MOTOR_REVERSED) speed = -speed;
    analogWrite(MOTOR_A, speed > 0 ? speed : 0);
    analogWrite(MOTOR_B, speed < 0 ? -speed : 0);
}

// 1 if the button was pressed since the last call
int button() {
    int was = pressed ? 1 : 0;
    pressed = false;
    return was;
}

// The UNO Q's RGB LED: 0 = off, 1 = green (open), 2 = red (wrong / locked
// out), 3 = blue (watching for your fingers). Its pins are active LOW.
void set_status(int s) {
    digitalWrite(LED3_R, s == 2 ? LOW : HIGH);
    digitalWrite(LED3_G, s == 1 ? LOW : HIGH);
    digitalWrite(LED3_B, s == 3 ? LOW : HIGH);
}

// Run the motor one way for a set time. Asking for the position it's
// already in does nothing, so it never grinds against the end.
void set_latch(int open) {
    open = open ? 1 : 0;
    if (open == latchOpen) return;
    latchOpen = open;
    drive(open ? LATCH_SPEED : -LATCH_SPEED);
    motorUntil = millis() + (open ? OPEN_MS : CLOSE_MS);
    if (motorUntil == 0) motorUntil = 1;
}

void show_icon(int i) {
    memset(frame, 0, sizeof(frame));
    if (i >= 0 && i < 4) {
        for (int r = 0; r < MATRIX_ROWS; r++) {
            for (int c = 0; c < MATRIX_COLS; c++) {
                if (ICONS[i][r][c] == '#') frame[r * MATRIX_COLS + c] = 7;
            }
        }
    }
    matrix.draw(frame);
}

// Code entry: three boxes along the bottom (dim = still to enter, bright =
// entered) and, if digit >= 0, that digit big in the middle for a moment.
void show_entry(int entered, int digit) {
    memset(frame, 0, sizeof(frame));
    if (digit >= 0 && digit <= 9) {
        for (int r = 0; r < 5; r++) {
            for (int c = 0; c < 3; c++) {
                if (DIGITS[digit][r] & (4 >> c)) frame[r * MATRIX_COLS + 5 + c] = 7;
            }
        }
    }
    for (int k = 0; k < 3; k++) {
        uint8_t level = k < entered ? 7 : 1;
        for (int c = 0; c < 3; c++) {
            frame[6 * MATRIX_COLS + 1 + 4 * k + c] = level;
            frame[7 * MATRIX_COLS + 1 + 4 * k + c] = level;
        }
    }
    matrix.draw(frame);
}
