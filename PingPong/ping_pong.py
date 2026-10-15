"""
Virtual ping-pong played with an Arduino UNO Q paddle.

The laptop runs the game: a webcam shows you, and a virtual ball flies at you
from the far end of the table. To return it you need ALL of:

  1. POSE  - MediaPipe Pose tracks your paddle wrist. The wrist has to be
             under the ball (left/right) when the ball reaches you.
  2. IMU   - The MPU6050 on the UNO Q paddle has to register a SWING while
             the ball is in the hit zone (a quick spike in rotation rate).
  3. GRIP  - The light sensor on the paddle handle has to be covered by your
             hand (you're actually holding the paddle). Set REQUIRE_GRIP =
             False to turn this off.

AprilTag 27 (family 36h11) sets up the game. How close you hold it to the
camera picks the level (ball speed), and holding it still starts the game:

    tag distance   level
    ------------   -------------------------
    far            1 - EASY   (slow ball)
    middle         2 - MEDIUM
    close          3 - HARD   (fast ball)

    Hold the tag still for START_HOLD_S seconds -> START at that level.

Every return counts as one hit. A miss ends the streak, and after MAX_MISSES
misses the game is over and you go back to the menu (show tag 27 again). Your record streak (the most continuous hits) is posted to
SCORE_TOPIC as a floating-point number, e.g. "7.0", in real time: every time
the record goes up.

The UNO Q app (PingPong-UnoQ) reads the MPU6050 and light sensor and sends
them here on PADDLE_TOPIC. This script answers on FEEDBACK_TOPIC with hit /
miss / game events, and the UNO Q buzzes its motors (through the Cytron Maker
Drive) and shows your streak on its LED matrix.

Usage:
    python ping_pong.py               # full game with the UNO Q paddle
    python ping_pong.py --keyboard    # no paddle: SPACE = swing (testing)
    python ping_pong.py --no-score    # real paddle, but don't post to ME193/Rogers (practice)
    python ping_pong.py --offline     # no MQTT at all (implies --keyboard)

Keys in the game window: SPACE = swing (keyboard mode), 1/2/3 = level,
s = start, q or Esc = quit.
"""

import argparse
import json
import math
import os
import random
import threading
import time
import urllib.request
import uuid

import cv2
import mediapipe as mp
import numpy as np
import paho.mqtt.client as mqtt
from mediapipe.tasks.python import vision, BaseOptions
from mediapipe.tasks.python.vision.core.vision_task_running_mode import VisionTaskRunningMode

# --- MQTT ---
MQTT_BROKER = "broker.hivemq.com"
MQTT_PORT = 1883
PLAYER_NAME = "Raphael"
SCORE_TOPIC = f"ME193/Rogers/{PLAYER_NAME}"             # record streak, as a float
PADDLE_TOPIC = f"ME193_{PLAYER_NAME}_paddle"            # UNO Q -> laptop: IMU + light
FEEDBACK_TOPIC = f"ME193_{PLAYER_NAME}_paddle/feedback"  # laptop -> UNO Q: hit / miss
PADDLE_TIMEOUT_S = 1.0     # paddle counts as disconnected after this long without data

# --- Camera / pose model ---
CAMERA_INDEX = 0
MODEL_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "models")
MODEL_PATH = os.path.join(MODEL_DIR, "pose_landmarker_lite.task")
MODEL_URL = ("https://storage.googleapis.com/mediapipe-models/pose_landmarker/"
             "pose_landmarker_lite/float16/latest/pose_landmarker_lite.task")
PADDLE_HAND = "right"      # which hand holds the paddle: "right" or "left"
WRIST = {"left": 15, "right": 16}   # MediaPipe Pose landmark indices
MIN_VISIBILITY = 0.5       # ignore the wrist if MediaPipe isn't this sure it's in view

# --- AprilTag ---
TAG_FAMILY = cv2.aruco.DICT_APRILTAG_36h11
GAME_TAG = 27
LEVEL_NAMES = {1: "EASY", 2: "MEDIUM", 3: "HARD"}
# Tag size (average side length as a fraction of the frame width) grows as the
# tag gets closer. Smaller than the first number = EASY, between = MEDIUM,
# bigger than the second = HARD. Run "python test_parts.py tags" to see your sizes.
LEVEL_SIZES = (0.10, 0.18)
START_HOLD_S = 2.0         # hold the tag still this long to start
STILL_MOVE = 0.04          # tag center moving more than this (fraction of width) = not still

# --- Game ---
# Seconds for the ball to travel from the far end of the table to you
LEVEL_TRAVEL_S = {1: 2.2, 2: 1.5, 3: 1.0}
MIN_TRAVEL_S = 0.6         # hard swings speed the ball up, but never faster than this
SPEEDUP_PER_HIT = 0.03     # each hit in a streak takes this fraction off the travel time
HIT_ZONE = (0.80, 1.05)    # ball depth (0 = far end, 1 = at you) where you can hit it
PADDLE_HALF_WIDTH = 0.12   # wrist within this many screen widths of the ball = in position
SWING_WINDOW_S = 0.45      # a swing this recent still counts (covers MQTT delay)
MAX_MISSES = 3             # misses before game over
REQUIRE_GRIP = True        # light sensor must be covered to hit (ignored with --keyboard)

# --- IMU swing detection ---
SWING_GYRO_DPS = 250       # rotation rate (deg/s) that counts as a swing
HARD_SWING_GYRO_DPS = 700  # a swing this fast (or faster) returns the ball fastest
SWING_COOLDOWN_S = 0.35    # one swing per this long (a swing is one spike, not many)

# --- Light-sensor grip detection ---
GRIP_CHANGE = 0.30         # reading must move this fraction away from the open-hand baseline
BASELINE_SAMPLES = 20      # paddle readings averaged as "nothing covering the sensor"


def clamp(value, lo, hi):
    return max(lo, min(hi, value))


# ----------------------------------------------------------------------------
# Paddle (UNO Q over MQTT, or the keyboard for testing)
# ----------------------------------------------------------------------------

class Paddle:
    """Latest IMU / light readings from the UNO Q, plus swing detection.

    The UNO Q sends {"gyro": peak deg/s, "accel": g, "light": raw 0-1023}
    about 30x a second. "gyro" is the biggest rotation rate the MPU6050 saw
    since the last message, so a quick swing between messages isn't missed.
    """

    def __init__(self, keyboard=False):
        self.keyboard = keyboard
        self.lock = threading.Lock()
        self.last_msg_time = 0.0
        self.gyro = 0.0
        self.accel = 0.0
        self.light = None
        self.light_samples = []
        self.light_baseline = None
        self.last_swing_time = 0.0
        self.last_swing_strength = 0.0

    def on_message(self, payload):
        try:
            data = json.loads(payload)
            gyro, accel, light = float(data["gyro"]), float(data["accel"]), float(data["light"])
        except (ValueError, KeyError, TypeError):
            return
        now = time.time()
        with self.lock:
            self.last_msg_time = now
            self.gyro, self.accel, self.light = gyro, accel, light
            if self.light_baseline is None:
                # Learn the uncovered reading first; hold the paddle by the
                # handle only after the HUD says the sensor is calibrated.
                self.light_samples.append(light)
                if len(self.light_samples) >= BASELINE_SAMPLES:
                    self.light_baseline = float(np.median(self.light_samples))
                    print(f"Light sensor baseline (uncovered): {self.light_baseline:.0f}")
            if gyro >= SWING_GYRO_DPS and now - self.last_swing_time >= SWING_COOLDOWN_S:
                self._swing(now, gyro)

    def keyboard_swing(self):
        with self.lock:
            self._swing(time.time(), HARD_SWING_GYRO_DPS * 0.7)

    def _swing(self, now, gyro):
        self.last_swing_time = now
        # 0 = just over the swing threshold, 1 = a hard swing
        self.last_swing_strength = clamp(
            (gyro - SWING_GYRO_DPS) / (HARD_SWING_GYRO_DPS - SWING_GYRO_DPS), 0.0, 1.0)
        print(f"Swing! {gyro:.0f} deg/s")

    @property
    def connected(self):
        return self.keyboard or time.time() - self.last_msg_time <= PADDLE_TIMEOUT_S

    @property
    def gripped(self):
        if self.keyboard or not REQUIRE_GRIP:
            return True
        with self.lock:
            if self.light is None or not self.light_baseline:
                return False
            # Works whichever way the photoresistor divider is wired: covering
            # the sensor moves the reading a long way from the open baseline.
            return abs(self.light - self.light_baseline) / self.light_baseline >= GRIP_CHANGE

    def recent_swing(self):
        """Swing strength (0-1) if there was a swing within SWING_WINDOW_S, else None."""
        with self.lock:
            if time.time() - self.last_swing_time <= SWING_WINDOW_S:
                return self.last_swing_strength
        return None

    def use_swing(self):
        """A swing can only return the ball once."""
        with self.lock:
            self.last_swing_time = 0.0


# ----------------------------------------------------------------------------
# MQTT
# ----------------------------------------------------------------------------

class Link:
    """MQTT connection: paddle data in, feedback and score out."""

    def __init__(self, paddle, offline=False, post_scores=True):
        self.offline = offline
        self.post_scores = post_scores and not offline
        self.client = None
        if not self.post_scores and not offline:
            print(f"[practice] Scores are only printed, NOT posted to '{SCORE_TOPIC}'.")
        if offline:
            print("[offline] MQTT disabled; scores are only printed.")
            return
        self.client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2,
                                  client_id=f"pingpong-{uuid.uuid4().hex[:8]}")

        def on_connect(client, userdata, flags, reason_code, properties):
            client.subscribe(PADDLE_TOPIC)
            target = SCORE_TOPIC if self.post_scores else "nowhere (practice)"
            print(f"MQTT connected to {MQTT_BROKER}; paddle on '{PADDLE_TOPIC}', "
                  f"score to {target}")

        self.client.on_connect = on_connect
        self.client.on_message = lambda c, u, msg: paddle.on_message(msg.payload.decode())
        self.client.connect(MQTT_BROKER, MQTT_PORT, keepalive=60)
        self.client.loop_start()

    def feedback(self, event, streak):
        """Tell the UNO Q what happened so it can buzz and update its LED matrix."""
        if self.client:
            self.client.publish(FEEDBACK_TOPIC, json.dumps({"event": event, "streak": streak}))

    def post_score(self, record):
        text = f"{float(record):.1f}"
        if not self.post_scores:
            print(f"Record streak: {text} (practice, not posted)")
            return
        print(f"Record streak -> {SCORE_TOPIC}: {text}")
        if self.client:
            # retain=True so anyone who subscribes later still sees the latest record
            self.client.publish(SCORE_TOPIC, text, qos=1, retain=True)

    def close(self):
        if self.client:
            self.client.loop_stop()
            self.client.disconnect()


# ----------------------------------------------------------------------------
# Vision: pose (wrist) and AprilTags
# ----------------------------------------------------------------------------

def make_pose_landmarker():
    if not os.path.exists(MODEL_PATH):
        os.makedirs(MODEL_DIR, exist_ok=True)
        print(f"Downloading the MediaPipe pose model to {MODEL_PATH} ...")
        urllib.request.urlretrieve(MODEL_URL, MODEL_PATH)
    options = vision.PoseLandmarkerOptions(
        base_options=BaseOptions(model_asset_path=MODEL_PATH),
        running_mode=VisionTaskRunningMode.VIDEO,
        num_poses=1,
        min_pose_detection_confidence=0.5,
        min_tracking_confidence=0.5,
    )
    return vision.PoseLandmarker.create_from_options(options)


def paddle_wrist(result):
    """Paddle wrist position as (x, y) fractions of the mirrored display, or None.

    Pose runs on the un-mirrored camera frame so MediaPipe's left/right labels
    match your real hands; x is flipped here to line up with the mirrored view.
    """
    if not result.pose_landmarks:
        return None
    wrist = result.pose_landmarks[0][WRIST[PADDLE_HAND]]
    if wrist.visibility is not None and wrist.visibility < MIN_VISIBILITY:
        return None
    return clamp(1.0 - wrist.x, 0.0, 1.0), clamp(wrist.y, 0.0, 1.0)


class GameTag:
    """Reads tag 27: its distance picks the level, holding it still starts the game."""

    def __init__(self):
        self.detector = cv2.aruco.ArucoDetector(
            cv2.aruco.getPredefinedDictionary(TAG_FAMILY), cv2.aruco.DetectorParameters())
        self.anchor = None     # (center, level, time) where the tag started holding still
        self.fired = False     # already started a game during this hold
        self.corners = None    # tag corners in the last frame, or None if not in view
        self.size = 0.0
        self.level = None
        self.progress = 0.0    # 0..1 of the way through the hold-to-start

    def read(self, frame):
        """Look for the tag; return True once when it has been held still long enough."""
        width = frame.shape[1]
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        corners, ids, _ = self.detector.detectMarkers(gray)
        self.corners = None
        if ids is not None:
            for tag_corners, tag_id in zip(corners, ids.flatten()):
                if int(tag_id) == GAME_TAG:
                    self.corners = tag_corners[0]
        if self.corners is None:
            self.anchor, self.fired, self.level, self.progress = None, False, None, 0.0
            return False

        sides = np.linalg.norm(self.corners - np.roll(self.corners, 1, axis=0), axis=1)
        self.size = float(sides.mean()) / width
        self.level = 1 if self.size < LEVEL_SIZES[0] else 2 if self.size < LEVEL_SIZES[1] else 3

        now = time.time()
        center = self.corners.mean(axis=0) / width
        if (self.anchor is None or self.anchor[1] != self.level
                or np.linalg.norm(center - self.anchor[0]) > STILL_MOVE):
            self.anchor = (center, self.level, now)   # moved: restart the hold
        self.progress = clamp((now - self.anchor[2]) / START_HOLD_S, 0.0, 1.0)
        if self.progress >= 1.0 and not self.fired:
            self.fired = True
            return True
        return False


# ----------------------------------------------------------------------------
# Game
# ----------------------------------------------------------------------------

class Game:
    def __init__(self, link):
        self.link = link
        self.state = "menu"          # menu -> playing -> gameover -> menu
        self.level = 1
        self.streak = 0
        self.record = 0              # best streak this session (what gets posted)
        self.misses = 0
        self.message = ""
        self.message_until = 0.0
        self.gameover_until = 0.0
        self.ball = None

    def flash(self, text, seconds=1.0):
        self.message, self.message_until = text, time.time() + seconds

    def select_level(self, level):
        if self.state == "menu" and level != self.level:
            self.level = level
            print(f"Level set to {level} ({LEVEL_NAMES[level]})")

    def start(self):
        if self.state != "menu":
            return
        self.state, self.streak, self.misses = "playing", 0, 0
        print(f"Game started at level {self.level} ({LEVEL_NAMES[self.level]})")
        self.flash("GO!")
        self.link.feedback("start", 0)
        self.serve()

    def travel_time(self, swing_strength=0.0):
        t = LEVEL_TRAVEL_S[self.level] * (1 - SPEEDUP_PER_HIT) ** self.streak
        t *= 1 - 0.3 * swing_strength      # a hard return comes back faster
        return max(MIN_TRAVEL_S, t)

    def serve(self, swing_strength=0.0, delay=0.6):
        """Opponent sends a new ball from the far end, aimed at a random spot."""
        self.ball = {
            "start_x": random.uniform(0.3, 0.7),
            "target_x": random.uniform(0.15, 0.85),
            "z": 0.0,                         # 0 = far end, 1 = at the player
            "travel_s": self.travel_time(swing_strength),
            "wait_until": time.time() + delay,
        }

    def ball_x(self):
        b = self.ball
        return b["start_x"] + (b["target_x"] - b["start_x"]) * clamp(b["z"], 0.0, 1.0)

    def update(self, dt, wrist, paddle):
        now = time.time()
        if self.state == "gameover" and now >= self.gameover_until:
            self.state = "menu"
        if self.state != "playing" or now < self.ball["wait_until"]:
            return

        self.ball["z"] += dt / self.ball["travel_s"]
        z = self.ball["z"]

        if HIT_ZONE[0] <= z <= HIT_ZONE[1]:
            in_position = wrist is not None and abs(wrist[0] - self.ball_x()) <= PADDLE_HALF_WIDTH
            strength = paddle.recent_swing()
            if in_position and strength is not None and paddle.gripped:
                paddle.use_swing()
                self.hit(strength)
        elif z > HIT_ZONE[1]:
            if wrist is None:
                why = "can't see your wrist"
            elif abs(wrist[0] - self.ball_x()) > PADDLE_HALF_WIDTH:
                why = "paddle not under the ball"
            elif not paddle.gripped:
                why = "hold the paddle (cover the light sensor)"
            else:
                why = "no swing"
            self.miss(why)

    def hit(self, strength):
        self.streak += 1
        print(f"HIT! streak {self.streak} (swing {strength:.2f})")
        self.flash(f"HIT! x{self.streak}", 0.6)
        self.link.feedback("hit", self.streak)
        if self.streak > self.record:
            self.record = self.streak
            self.link.post_score(self.record)
        self.serve(swing_strength=strength, delay=0.25)

    def miss(self, why):
        self.misses += 1
        print(f"MISS ({why}). Streak was {self.streak}. Misses {self.misses}/{MAX_MISSES}")
        self.flash(f"MISS - {why}", 1.5)
        self.streak = 0
        if self.misses >= MAX_MISSES:
            self.state = "gameover"
            self.gameover_until = time.time() + 3.0
            self.ball = None
            self.link.feedback("gameover", self.record)
            print(f"Game over. Record streak: {self.record}")
        else:
            self.link.feedback("miss", 0)
            self.serve(delay=1.2)


# ----------------------------------------------------------------------------
# Drawing
# ----------------------------------------------------------------------------

def table_point(x, z, width, height):
    """Map table coordinates (x 0-1 across, z 0 far .. 1 near) to a pixel, with perspective."""
    far_y, near_y = int(height * 0.15), int(height * 0.85)
    far_half, near_half = 0.18, 0.48     # half-width of the table, as a fraction of the frame
    y = far_y + (near_y - far_y) * z
    half = far_half + (near_half - far_half) * z
    px = width * (0.5 + (x - 0.5) * 2 * half)
    return int(px), int(y)


def draw_table(frame):
    height, width = frame.shape[:2]
    overlay = frame.copy()
    corners = [table_point(0, 0, width, height), table_point(1, 0, width, height),
               table_point(1, 1, width, height), table_point(0, 1, width, height)]
    cv2.fillPoly(overlay, [np.array(corners)], (90, 60, 0))
    cv2.addWeighted(overlay, 0.45, frame, 0.55, 0, frame)
    cv2.polylines(frame, [np.array(corners)], True, (255, 255, 255), 2)
    cv2.line(frame, table_point(0.5, 0, width, height), table_point(0.5, 1, width, height),
             (255, 255, 255), 1)
    # net halfway
    cv2.line(frame, table_point(0, 0.5, width, height), table_point(1, 0.5, width, height),
             (200, 200, 200), 3)
    # hit zone
    cv2.line(frame, table_point(0, HIT_ZONE[0], width, height),
             table_point(1, HIT_ZONE[0], width, height), (0, 200, 255), 1)


def draw_ball(frame, game):
    if game.ball is None or time.time() < game.ball["wait_until"]:
        return
    height, width = frame.shape[:2]
    z = clamp(game.ball["z"], 0.0, 1.1)
    px, py = table_point(game.ball_x(), z, width, height)
    # the ball "bounces": arc up between the ends of the table
    py -= int(height * 0.12 * abs(math.sin(math.pi * z)))
    radius = int(6 + 18 * z)
    shadow = table_point(game.ball_x(), z, width, height)
    cv2.ellipse(frame, shadow, (radius, radius // 3), 0, 0, 360, (30, 30, 30), -1)
    cv2.circle(frame, (px, py), radius, (0, 165, 255), -1)
    cv2.circle(frame, (px, py), radius, (255, 255, 255), 1)


def draw_paddle(frame, wrist, paddle, game):
    if wrist is None:
        return
    height, width = frame.shape[:2]
    px, py = int(wrist[0] * width), int(wrist[1] * height)
    in_zone = game.ball is not None and HIT_ZONE[0] <= game.ball["z"] <= HIT_ZONE[1]
    aligned = game.ball is not None and abs(wrist[0] - game.ball_x()) <= PADDLE_HALF_WIDTH
    color = (0, 220, 0) if aligned else (0, 0, 255)
    swinging = paddle.recent_swing() is not None
    cv2.circle(frame, (px, py), 34 if swinging else 28, color, -1 if in_zone and aligned else 3)
    # reach marker on the near edge of the table: where the paddle covers
    near_l = table_point(wrist[0] - PADDLE_HALF_WIDTH, 1, width, height)
    near_r = table_point(wrist[0] + PADDLE_HALF_WIDTH, 1, width, height)
    cv2.line(frame, near_l, near_r, color, 6)


def draw_tag(frame, tag):
    """The tag was detected on the un-mirrored frame, so mirror its corners to match."""
    if tag.corners is None:
        return
    width = frame.shape[1]
    pts = tag.corners.copy()
    pts[:, 0] = width - 1 - pts[:, 0]
    cv2.polylines(frame, [pts.astype(np.int32)], True, (255, 0, 255), 2)
    cx, cy = pts.mean(axis=0).astype(int)
    put(frame, f"{LEVEL_NAMES[tag.level]} ({tag.size:.2f})", (cx - 60, cy - 10), 0.7,
        (255, 0, 255))
    # hold-to-start ring fills up while the tag is held still
    radius = int(np.linalg.norm(pts[0] - pts[2]) / 2) + 15
    cv2.ellipse(frame, (cx, cy), (radius, radius), -90, 0, 360 * tag.progress, (0, 255, 0), 5)


def put(frame, text, org, scale=0.7, color=(255, 255, 255)):
    cv2.putText(frame, text, org, cv2.FONT_HERSHEY_SIMPLEX, scale, (0, 0, 0), 4)
    cv2.putText(frame, text, org, cv2.FONT_HERSHEY_SIMPLEX, scale, color, 2)


def draw_hud(frame, game, paddle):
    height, width = frame.shape[:2]
    put(frame, f"Level {game.level} {LEVEL_NAMES[game.level]}", (10, 28))
    put(frame, f"Streak {game.streak}   Record {game.record}", (10, 58))
    put(frame, f"Misses {game.misses}/{MAX_MISSES}", (10, 88))

    if paddle.keyboard:
        put(frame, "Paddle: KEYBOARD (space = swing)", (width - 420, 28), 0.6)
    else:
        ok = paddle.connected
        put(frame, f"Paddle: {'connected' if ok else 'NOT CONNECTED'}", (width - 300, 28), 0.6,
            (0, 255, 0) if ok else (0, 0, 255))
        put(frame, f"gyro {paddle.gyro:4.0f} dps  accel {paddle.accel:3.1f} g",
            (width - 300, 54), 0.5)
        if REQUIRE_GRIP:
            if paddle.light_baseline is None:
                grip = "grip: calibrating (don't cover)"
            else:
                grip = "grip: HELD" if paddle.gripped else "grip: cover the light sensor"
            put(frame, grip, (width - 300, 78), 0.5)

    if game.state == "menu":
        put(frame, f"Tag {GAME_TAG}: far = EASY, closer = MEDIUM, closest = HARD. "
                   f"Hold still {START_HOLD_S:.0f} s to START", (10, height - 20), 0.55, (0, 255, 255))
    elif game.state == "gameover":
        put(frame, f"GAME OVER - record {game.record}", (width // 2 - 200, height // 2), 1.1,
            (0, 0, 255))
    if time.time() < game.message_until:
        put(frame, game.message, (width // 2 - 150, 130), 1.0, (0, 255, 255))


# ----------------------------------------------------------------------------
# Main loop
# ----------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Virtual ping-pong with a UNO Q paddle")
    parser.add_argument("--keyboard", action="store_true", help="SPACE = swing; no paddle needed")
    parser.add_argument("--no-score", action="store_true",
                        help="use the paddle but don't post the score to ME193/Rogers")
    parser.add_argument("--offline", action="store_true", help="no MQTT (implies --keyboard)")
    args = parser.parse_args()
    keyboard = args.keyboard or args.offline

    paddle = Paddle(keyboard=keyboard)
    link = Link(paddle, offline=args.offline, post_scores=not args.no_score)
    game = Game(link)
    tag = GameTag()
    landmarker = make_pose_landmarker()

    cap = cv2.VideoCapture(CAMERA_INDEX, cv2.CAP_DSHOW)
    if not cap.isOpened():
        raise RuntimeError(f"Could not open camera index {CAMERA_INDEX}")

    start_time = time.perf_counter()
    last_frame_time = time.time()
    last_timestamp_ms = -1
    print(f"Show tag {GAME_TAG}: distance picks the level, hold it still to start. "
          "Press q or Esc to quit.")

    try:
        while True:
            ok, frame = cap.read()
            if not ok:
                break

            # AprilTags must be read BEFORE mirroring: a mirrored tag doesn't decode.
            start = tag.read(frame)
            if tag.level is not None:
                game.select_level(tag.level)
            if start:
                game.start()

            rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            timestamp_ms = int((time.perf_counter() - start_time) * 1000)
            timestamp_ms = max(timestamp_ms, last_timestamp_ms + 1)
            last_timestamp_ms = timestamp_ms
            result = landmarker.detect_for_video(
                mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb), timestamp_ms)
            wrist = paddle_wrist(result)
            frame = cv2.flip(frame, 1)   # mirror so moving right moves the paddle right

            now = time.time()
            game.update(min(now - last_frame_time, 0.1), wrist, paddle)
            last_frame_time = now

            draw_table(frame)
            draw_ball(frame, game)
            draw_paddle(frame, wrist, paddle, game)
            if game.state == "menu":
                draw_tag(frame, tag)
            draw_hud(frame, game, paddle)
            cv2.imshow("ME193 Ping-Pong", frame)

            key = cv2.waitKey(1) & 0xFF
            if key in (ord("q"), 27):
                break
            if key == ord(" ") and keyboard:
                paddle.keyboard_swing()
            elif key in (ord("1"), ord("2"), ord("3")):
                game.select_level(key - ord("0"))
            elif key == ord("s"):
                game.start()
    finally:
        print(f"Final record streak: {game.record}")
        link.feedback("gameover", game.record)
        link.close()
        landmarker.close()
        cap.release()
        cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
