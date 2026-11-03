#include "Arduino_RouterBridge.h"
#include "Arduino_LED_Matrix.h"
#include <Wire.h>

// MPU6050 on I2C (header pins labeled SDA / SCL), VCC -> 3.3V, GND -> GND.
// AD0 low = 0x68, AD0 high = 0x69.
const uint8_t MPU_ADDR = 0x68;

// Full ranges: a running foot can hit well over 8 g and 1000 deg/s.
// The laptop converts raw counts with the same numbers (gait_config.py).
//   ACCEL_CONFIG 0x18 = +-16 g    -> 2048 counts per g
//   GYRO_CONFIG  0x18 = +-2000 dps -> 16.4 counts per deg/s
const int SAMPLE_MS = 10;          // 100 Hz
const int MAX_SAMPLES = 64;        // ~0.6 s of buffer between Python reads

struct Sample {
    unsigned long t;
    int16_t v[6];                  // ax, ay, az, gx, gy, gz (raw counts)
};
Sample buf[MAX_SAMPLES];
int count = 0;
bool imuOk = false;
unsigned long lastInit = 0;
unsigned long nextSample = 0;

const int MATRIX_COLS = 13;
const int MATRIX_ROWS = 8;
Arduino_LED_Matrix matrix;
uint8_t frame[MATRIX_ROWS * MATRIX_COLS];

void writeReg(uint8_t reg, uint8_t value) {
    Wire.beginTransmission(MPU_ADDR);
    Wire.write(reg);
    Wire.write(value);
    Wire.endTransmission();
}

// The MPU6050 powers up asleep, so this runs at startup AND again whenever it
// stops answering (a loose wire while you're running, for example).
void initMpu() {
    writeReg(0x6B, 0x00);  // PWR_MGMT_1: wake up
    writeReg(0x1B, 0x18);  // GYRO_CONFIG: +-2000 deg/s
    writeReg(0x1C, 0x18);  // ACCEL_CONFIG: +-16 g
    writeReg(0x1A, 0x03);  // CONFIG: ~44 Hz low-pass (below half the 100 Hz sample rate)
    lastInit = millis();
}

bool readMpu(int16_t out[6]) {
    Wire.beginTransmission(MPU_ADDR);
    Wire.write(0x3B);
    if (Wire.endTransmission(false) != 0 || Wire.requestFrom(MPU_ADDR, (uint8_t)14) != 14) {
        return false;
    }
    int16_t raw[7];
    for (int i = 0; i < 7; i++) {
        raw[i] = (Wire.read() << 8) | Wire.read();
    }
    // All-zero accel is impossible (gravity is always there): the chip is asleep
    if (raw[0] == 0 && raw[1] == 0 && raw[2] == 0) return false;
    out[0] = raw[0]; out[1] = raw[1]; out[2] = raw[2];   // accel
    out[3] = raw[4]; out[4] = raw[5]; out[5] = raw[6];   // gyro (raw[3] is temperature)
    return true;
}

void setup() {
    Wire.begin();
    Wire.setClock(400000);
    initMpu();

    matrix.begin();
    matrix.setGrayscaleBits(3);
    show_activity(-1);

    Bridge.begin();
    Bridge.provide("imu_batch", imu_batch);
    Bridge.provide("show_activity", show_activity);
    Bridge.provide("show_number", show_number);
    nextSample = millis();
}

void loop() {
    unsigned long now = millis();
    if ((long)(now - nextSample) < 0) return;
    nextSample += SAMPLE_MS;
    if ((long)(now - nextSample) > 100) nextSample = now + SAMPLE_MS;  // fell far behind: resync

    Sample s;
    s.t = now;
    if (readMpu(s.v)) {
        imuOk = true;
        if (count < MAX_SAMPLES) buf[count++] = s;   // full = Python stopped reading; drop newest
    } else {
        imuOk = false;
        if (now - lastInit > 500) initMpu();
    }
}

// Every sample since the last call, as "t,ax,ay,az,gx,gy,gz;" (raw counts).
// "ERR" if the MPU6050 isn't answering.
String imu_batch() {
    if (!imuOk && count == 0) return String("ERR");
    String out;
    out.reserve(count * 44);
    for (int i = 0; i < count; i++) {
        out += String(buf[i].t);
        for (int k = 0; k < 6; k++) {
            out += ',';
            out += String(buf[i].v[k]);
        }
        out += ';';
    }
    count = 0;
    return out;
}

// 3x5 digits for the step count, one row per byte (bit 2 = left column).
const uint8_t DIGITS[10][5] = {
    {7, 5, 5, 5, 7}, {2, 6, 2, 2, 7}, {7, 1, 7, 4, 7}, {7, 1, 7, 1, 7}, {5, 5, 7, 1, 1},
    {7, 4, 7, 1, 7}, {7, 4, 7, 5, 7}, {7, 1, 1, 1, 1}, {7, 5, 7, 5, 7}, {7, 5, 7, 1, 7},
};

// Up to 3 digits fit across the 13 columns. Past 999 it shows the last 3
// digits with a dot in the corner for each thousand (up to 4).
void show_number(int n) {
    memset(frame, 0, sizeof(frame));
    if (n < 0) n = 0;
    int thousands = n / 1000;
    n %= 1000;
    int digits = n >= 100 ? 3 : (n >= 10 ? 2 : 1);
    int x = 1 + (3 - digits) * 4;                 // right-aligned
    for (int d = digits - 1; d >= 0; d--) {
        int v = (n / (d == 2 ? 100 : (d == 1 ? 10 : 1))) % 10;
        for (int r = 0; r < 5; r++) {
            for (int c = 0; c < 3; c++) {
                if (DIGITS[v][r] & (4 >> c)) frame[(r + 1) * MATRIX_COLS + x + c] = 7;
            }
        }
        x += 4;
    }
    for (int k = 0; k < thousands && k < 4; k++) frame[7 * MATRIX_COLS + 12 - 2 * k] = 7;
    matrix.draw(frame);
}

// 5x7 letters for the LED matrix, one row per byte (bit 4 = left column).
// 0 = Still, 1 = Walk, 2 = Run, 3 = Bike; anything else = dash.
const uint8_t LETTERS[4][7] = {
    {0x0E, 0x11, 0x10, 0x0E, 0x01, 0x11, 0x0E},   // S
    {0x11, 0x11, 0x11, 0x15, 0x15, 0x15, 0x0A},   // W
    {0x1E, 0x11, 0x11, 0x1E, 0x14, 0x12, 0x11},   // R
    {0x1E, 0x11, 0x11, 0x1E, 0x11, 0x11, 0x1E},   // B
};

void show_activity(int code) {
    memset(frame, 0, sizeof(frame));
    if (code >= 0 && code < 4) {
        for (int r = 0; r < 7; r++) {
            for (int c = 0; c < 5; c++) {
                if (LETTERS[code][r] & (0x10 >> c)) frame[r * MATRIX_COLS + 4 + c] = 7;
            }
        }
    } else {
        for (int c = 4; c < 9; c++) frame[3 * MATRIX_COLS + c] = 7;
    }
    matrix.draw(frame);
}
