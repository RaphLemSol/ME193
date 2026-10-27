// HC-SR04 ultrasonic sensor on the UNO Q's microcontroller.
// loop() keeps measuring; the Python side asks for the latest value with
// Bridge.call("distance_cm") and publishes it over MQTT.
//
// Wiring:
//   HC-SR04 VCC  -> 5V
//   HC-SR04 GND  -> GND
//   HC-SR04 TRIG -> D9
//   HC-SR04 ECHO -> D10 through a voltage divider (e.g. 1k from ECHO to D10,
//                   2k from D10 to GND): ECHO is 5 V, the UNO Q pins are 3.3 V.

#include <Arduino_RouterBridge.h>

const int TRIG_PIN = 9;
const int ECHO_PIN = 10;
const unsigned long ECHO_TIMEOUT_US = 25000;   // ~4 m; longer = nothing there

volatile float latest_cm = -1.0;               // -1 = no echo

float read_once_cm() {
  digitalWrite(TRIG_PIN, LOW);
  delayMicroseconds(2);
  digitalWrite(TRIG_PIN, HIGH);
  delayMicroseconds(10);
  digitalWrite(TRIG_PIN, LOW);
  unsigned long us = pulseIn(ECHO_PIN, HIGH, ECHO_TIMEOUT_US);
  if (us == 0) return -1.0;
  return us / 58.0;                            // round trip at 343 m/s
}

float distance_cm() {
  return latest_cm;
}

void setup() {
  pinMode(TRIG_PIN, OUTPUT);
  pinMode(ECHO_PIN, INPUT);
  Bridge.begin();
  Bridge.provide("distance_cm", distance_cm);
}

void loop() {
  latest_cm = read_once_cm();
  delay(30);                                   // let old echoes die out
}
