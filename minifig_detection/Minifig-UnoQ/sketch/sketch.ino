#include "Arduino_RouterBridge.h"
#include "Arduino_LED_Matrix.h"

// Cytron Maker Drive control pins.
const int M1A = 4;  // Motor 1
const int M1B = 5;
const int M2A = 2;  // Motor 2
const int M2B = 3;

// Set to true for a motor that spins the wrong way (e.g. mounted mirrored).
const bool M1_REVERSED = false;
const bool M2_REVERSED = false;

const int MATRIX_COLS = 13;
const int MATRIX_ROWS = 8;

Arduino_LED_Matrix matrix;
uint8_t frame[MATRIX_ROWS * MATRIX_COLS];

void setup() {
    pinMode(M1A, OUTPUT);
    pinMode(M1B, OUTPUT);
    pinMode(M2A, OUTPUT);
    pinMode(M2B, OUTPUT);
    set_motors(0, 0);

    matrix.begin();
    matrix.setGrayscaleBits(3);  // brightness 0-7
    show_dot(-1, -1);

    Bridge.begin();
    Bridge.provide("set_motors", set_motors);
    Bridge.provide("show_dot", show_dot);
}

void loop() {}

// Maker Drive: PWM on A = forward, PWM on B = backward, both LOW = stop.
void drive(int pinA, int pinB, int speed) {
    if (speed > 0) {
        analogWrite(pinA, speed);
        analogWrite(pinB, 0);
    } else {
        analogWrite(pinA, 0);
        analogWrite(pinB, -speed);
    }
}

// Each speed: -255 (full backward) .. 0 (stop) .. 255 (full forward)
void set_motors(int speed1, int speed2) {
    speed1 = constrain(speed1, -255, 255);
    speed2 = constrain(speed2, -255, 255);
    drive(M1A, M1B, M1_REVERSED ? -speed1 : speed1);
    drive(M2A, M2B, M2_REVERSED ? -speed2 : speed2);
}

// Light one LED at (col, row); pass -1, -1 to clear the display.
void show_dot(int col, int row) {
    memset(frame, 0, sizeof(frame));
    if (col >= 0 && col < MATRIX_COLS && row >= 0 && row < MATRIX_ROWS) {
        frame[row * MATRIX_COLS + col] = 7;
    }
    matrix.draw(frame);
}
