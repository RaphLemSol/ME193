#include "Arduino_RouterBridge.h"
#include "Arduino_LED_Matrix.h"

// Button test, same wiring as the safe: button COM -> GND, NO -> D2.
// While the button is held, the whole LED matrix lights up. Each press adds
// one to the count (shown on the matrix when released) and changes the RGB
// LED: red, green, blue, off, ...
const int BUTTON_PIN = 2;

int lastReading = HIGH;
int stableState = HIGH;
unsigned long lastChange = 0;
int presses = 0;

const int MATRIX_COLS = 13;
const int MATRIX_ROWS = 8;
Arduino_LED_Matrix matrix;
uint8_t frame[MATRIX_ROWS * MATRIX_COLS];

const uint8_t DIGITS[10][5] = {
    {7, 5, 5, 5, 7}, {2, 6, 2, 2, 7}, {7, 1, 7, 4, 7}, {7, 1, 7, 1, 7}, {5, 5, 7, 1, 1},
    {7, 4, 7, 1, 7}, {7, 4, 7, 5, 7}, {7, 1, 1, 1, 1}, {7, 5, 7, 5, 7}, {7, 5, 7, 1, 7},
};

void setup() {
    pinMode(BUTTON_PIN, INPUT_PULLUP);
    pinMode(LED3_R, OUTPUT);
    pinMode(LED3_G, OUTPUT);
    pinMode(LED3_B, OUTPUT);
    set_rgb(0);

    matrix.begin();
    matrix.setGrayscaleBits(3);
    show_count();

    Bridge.begin();
    Bridge.provide("presses", get_presses);
    Bridge.provide("held", held);
}

void loop() {
    unsigned long now = millis();
    int reading = digitalRead(BUTTON_PIN);
    if (reading != lastReading) {
        lastReading = reading;
        lastChange = now;
    }
    if (now - lastChange > 30 && reading != stableState) {
        stableState = reading;
        if (stableState == LOW) {
            presses++;
            set_rgb(presses % 4);
            memset(frame, 7, sizeof(frame));      // held: everything on
            matrix.draw(frame);
        } else {
            show_count();
        }
    }
}

int get_presses() {
    return presses;
}

// 1 while the button is held down
int held() {
    return stableState == LOW ? 1 : 0;
}

// 0 = off, 1 = red, 2 = green, 3 = blue (the LED's pins are active LOW)
void set_rgb(int c) {
    digitalWrite(LED3_R, c == 1 ? LOW : HIGH);
    digitalWrite(LED3_G, c == 2 ? LOW : HIGH);
    digitalWrite(LED3_B, c == 3 ? LOW : HIGH);
}

// The press count, up to 99
void show_count() {
    memset(frame, 0, sizeof(frame));
    int n = presses % 100;
    int x = n >= 10 ? 3 : 5;
    for (int d = (n >= 10 ? 1 : 0); d >= 0; d--) {
        int v = d == 1 ? n / 10 : n % 10;
        for (int r = 0; r < 5; r++) {
            for (int c = 0; c < 3; c++) {
                if (DIGITS[v][r] & (4 >> c)) frame[(r + 1) * MATRIX_COLS + x + c] = 7;
            }
        }
        x += 4;
    }
    matrix.draw(frame);
}
