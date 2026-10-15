#include "Arduino_RouterBridge.h"
#include "Arduino_LED_Matrix.h"
#include <Wire.h>

// Cytron Maker Drive control pins (all PWM-capable).
const int M1A = 5;  // Motor 1
const int M1B = 6;
const int M2A = 3;  // Motor 2
const int M2B = 9;

// Light sensor: photoresistor + resistor voltage divider, middle point on A0.
const int LIGHT_PIN = A0;

// MPU6050 on I2C (header pins labeled SDA / SCL). AD0 low = 0x68, AD0 high = 0x69.
const uint8_t MPU_ADDR = 0x68;
const float GYRO_LSB_PER_DPS = 32.8;   // +-1000 deg/s range
const float ACCEL_LSB_PER_G = 4096.0;  // +-8 g range

const int MATRIX_COLS = 13;
const int MATRIX_ROWS = 8;

Arduino_LED_Matrix matrix;
uint8_t frame[MATRIX_ROWS * MATRIX_COLS];

// Biggest rotation rate since Python last asked, so a quick swing
// between two Python reads isn't missed. Sampled in loop() at ~200 Hz.
float gyroPeak = 0;
float accelG = 1;
bool imuOk = false;
unsigned long lastInit = 0;
float gyroBias[3] = {0, 0, 0};  // deg/s each axis reads while still; subtracted from readings

void writeReg(uint8_t reg, uint8_t value) {
    Wire.beginTransmission(MPU_ADDR);
    Wire.write(reg);
    Wire.write(value);
    Wire.endTransmission();
}

// The MPU6050 powers up asleep, so this runs at startup AND again whenever it
// stops answering (e.g. a loose wire or a power dip from the motors).
void initMpu() {
    writeReg(0x6B, 0x00);  // PWR_MGMT_1: wake up
    writeReg(0x1B, 0x10);  // GYRO_CONFIG: +-1000 deg/s
    writeReg(0x1C, 0x10);  // ACCEL_CONFIG: +-8 g
    writeReg(0x1A, 0x03);  // CONFIG: ~44 Hz low-pass to smooth vibration
    lastInit = millis();
}

// Average the gyro for ~1 s while the paddle is still. Every MPU6050 reads a
// few deg/s even when not moving; subtracting that keeps "still" near 0.
void calibrateGyro() {
    float sum[3] = {0, 0, 0};
    int n = 0;
    for (int i = 0; i < 200; i++) {
        Wire.beginTransmission(MPU_ADDR);
        Wire.write(0x43);
        if (Wire.endTransmission(false) == 0 && Wire.requestFrom(MPU_ADDR, (uint8_t)6) == 6) {
            for (int a = 0; a < 3; a++) {
                int16_t raw = (Wire.read() << 8) | Wire.read();
                sum[a] += raw / GYRO_LSB_PER_DPS;
            }
            n++;
        }
        delay(5);
    }
    if (n > 0) {
        for (int a = 0; a < 3; a++) gyroBias[a] = sum[a] / n;
    }
}

void setup() {
    pinMode(M1A, OUTPUT);
    pinMode(M1B, OUTPUT);
    pinMode(M2A, OUTPUT);
    pinMode(M2B, OUTPUT);
    set_motors(0, 0);

    Wire.begin();
    initMpu();
    delay(100);         // let the gyro settle after waking
    calibrateGyro();    // keep the paddle still while the app starts

    matrix.begin();
    matrix.setGrayscaleBits(3);  // brightness 0-7
    show_number(0);

    Bridge.begin();
    Bridge.provide("set_motors", set_motors);
    Bridge.provide("show_number", show_number);
    Bridge.provide("gyro_peak", gyro_peak);
    Bridge.provide("accel_g", accel_g);
    Bridge.provide("light", light);
}

void loop() {
    // Read accel (0x3B..0x40), temp, gyro (0x43..0x48) in one burst.
    Wire.beginTransmission(MPU_ADDR);
    Wire.write(0x3B);
    if (Wire.endTransmission(false) == 0 && Wire.requestFrom(MPU_ADDR, (uint8_t)14) == 14) {
        int16_t raw[7];
        for (int i = 0; i < 7; i++) {
            raw[i] = (Wire.read() << 8) | Wire.read();
        }
        // All-zero accel is impossible (gravity is always there): the chip is asleep
        if (raw[0] == 0 && raw[1] == 0 && raw[2] == 0) {
            imuOk = false;
            if (millis() - lastInit > 500) initMpu();
            delay(5);
            return;
        }
        float ax = raw[0] / ACCEL_LSB_PER_G, ay = raw[1] / ACCEL_LSB_PER_G, az = raw[2] / ACCEL_LSB_PER_G;
        float gx = raw[4] / GYRO_LSB_PER_DPS - gyroBias[0];
        float gy = raw[5] / GYRO_LSB_PER_DPS - gyroBias[1];
        float gz = raw[6] / GYRO_LSB_PER_DPS - gyroBias[2];
        accelG = sqrt(ax * ax + ay * ay + az * az);
        float gyro = sqrt(gx * gx + gy * gy + gz * gz);
        if (gyro > gyroPeak) gyroPeak = gyro;
        imuOk = true;
    } else {
        imuOk = false;
        if (millis() - lastInit > 500) initMpu();
    }
    delay(5);
}

// Peak rotation rate (deg/s) since the last call; -1 if the MPU6050 isn't answering.
float gyro_peak() {
    float peak = imuOk ? gyroPeak : -1;
    gyroPeak = 0;
    return peak;
}

// Total acceleration in g (about 1.0 when the paddle is still).
float accel_g() {
    return accelG;
}

// Raw light-sensor reading.
int light() {
    return analogRead(LIGHT_PIN);
}

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
    drive(M1A, M1B, constrain(speed1, -255, 255));
    drive(M2A, M2B, constrain(speed2, -255, 255));
}

// 3x5 digits for the streak counter.
const uint8_t DIGITS[10][5] = {
    {7, 5, 5, 5, 7}, {2, 6, 2, 2, 7}, {7, 1, 7, 4, 7}, {7, 1, 7, 1, 7}, {5, 5, 7, 1, 1},
    {7, 4, 7, 1, 7}, {7, 4, 7, 5, 7}, {7, 1, 1, 1, 1}, {7, 5, 7, 5, 7}, {7, 5, 7, 1, 7},
};

void drawDigit(int d, int col) {
    for (int r = 0; r < 5; r++) {
        for (int c = 0; c < 3; c++) {
            if (DIGITS[d][r] & (4 >> c)) frame[(r + 1) * MATRIX_COLS + col + c] = 7;
        }
    }
}

// Show 0-99 on the LED matrix (the current streak).
void show_number(int n) {
    n = constrain(n, 0, 99);
    memset(frame, 0, sizeof(frame));
    if (n >= 10) {
        drawDigit(n / 10, 2);
        drawDigit(n % 10, 7);
    } else {
        drawDigit(n, 5);
    }
    matrix.draw(frame);
}
