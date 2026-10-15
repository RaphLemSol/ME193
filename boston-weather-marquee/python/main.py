import os
import time

import numpy as np
import requests
from arduino.app_utils import App, Bridge, Frame

# Boston, MA
LATITUDE = 42.3601
LONGITUDE = -71.0589
WEATHER_URL = (
    "https://api.open-meteo.com/v1/forecast"
    f"?latitude={LATITUDE}&longitude={LONGITUDE}"
    "&current=temperature_2m&temperature_unit=fahrenheit&timezone=America%2FNew_York"
)

REFRESH_SECONDS = 60  # re-fetch weather every minute
SCROLL_DELAY = 0.12  # seconds between animation steps
MATRIX_ROWS = 8
MATRIX_COLS = 13

# 3-column-wide, 5-row-tall bitmap font
FONT = {
    "0": ["111", "101", "101", "101", "111"],
    "1": ["010", "110", "010", "010", "111"],
    "2": ["111", "001", "111", "100", "111"],
    "3": ["111", "001", "111", "001", "111"],
    "4": ["101", "101", "111", "001", "001"],
    "5": ["111", "100", "111", "001", "111"],
    "6": ["111", "100", "111", "101", "111"],
    "7": ["111", "001", "001", "001", "001"],
    "8": ["111", "101", "111", "101", "111"],
    "9": ["111", "101", "111", "001", "111"],
    "-": ["000", "000", "111", "000", "000"],
    "F": ["111", "100", "111", "100", "100"],
    ".": ["000", "000", "000", "000", "010"],
    " ": ["000", "000", "000", "000", "000"],
}


def build_bitmap(text: str) -> np.ndarray:
    rows = ["" for _ in range(5)]
    for ch in text:
        pattern = FONT.get(ch, FONT[" "])
        for i in range(5):
            rows[i] += pattern[i] + "0"  # 1-column gap after each character

    width = len(rows[0])
    bitmap = np.zeros((MATRIX_ROWS, width), dtype=np.uint8)
    for i, row in enumerate(rows):
        for x, bit in enumerate(row):
            if bit == "1":
                bitmap[1 + i, x] = 7  # vertically centered in the 8 rows
    return bitmap


def fetch_boston_temperature() -> int:
    response = requests.get(WEATHER_URL, timeout=10)
    response.raise_for_status()
    return round(response.json()["current"]["temperature_2m"])


def get_ip_address() -> str:
    # the app runs in its own network namespace (container eth0), so the
    # board's real LAN address is only available via the host-injected env var
    return os.environ.get("HOST_IP", "0.0.0.0")


class Marquee:
    def __init__(self, text: str):
        bitmap = build_bitmap(text)
        # trailing blank columns so the message fully scrolls off before looping
        self.width = bitmap.shape[1] + MATRIX_COLS
        self.padded = np.zeros((MATRIX_ROWS, self.width), dtype=np.uint8)
        self.padded[:, : bitmap.shape[1]] = bitmap
        self.offset = 0

    def next_frame(self) -> np.ndarray:
        idx = (np.arange(MATRIX_COLS) + self.offset) % self.width
        self.offset = (self.offset + 1) % self.width
        return self.padded[:, idx]


temp_marquee = None
ip_marquee = None
last_fetch = 0.0
showing_temp = True


def update_display():
    global temp_marquee, ip_marquee, last_fetch, showing_temp

    now = time.monotonic()
    if temp_marquee is None or now - last_fetch >= REFRESH_SECONDS:
        temp = fetch_boston_temperature()
        ip = get_ip_address()
        print(f"Boston temperature: {temp}F, board IP: {ip}")
        temp_marquee = Marquee(f"{temp}F")
        ip_marquee = Marquee(ip)
        last_fetch = now

    marquee = temp_marquee if showing_temp else ip_marquee
    frame_bytes = Frame(marquee.next_frame()).to_board_bytes()
    if marquee.offset == 0:  # finished a full scroll pass
        showing_temp = not showing_temp
    Bridge.call("draw", frame_bytes)
    time.sleep(SCROLL_DELAY)


App.run(user_loop=update_display)
