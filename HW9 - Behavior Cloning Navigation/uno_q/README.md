# 🧭 Nolop Navigator (board app)

The UNO Q app for HW9. It reads the ankle sensor, counts steps and turns, saves each walk
and serves the phone page, all on the board. No laptop or internet is needed on the walk:
on walking days the board makes its own Wi-Fi network, **NolopNav**, and the phone opens
the page at **http://10.42.0.1:7000** (see "Walking days" below).

**Status (2026-11-18):** build steps 1, 3-7 and 9 run on the board (page, sensor, Raph's
step counter, `/api/state`, `/api/reset`, `/api/rows`, turn counting); 2 and 8 are skipped.
Next: walking tests with the board on the ankle. The build order is near the end.

## How the phone and the board talk

The phone page does the labeling: it knows which button was pressed. The board does the
sensing: it knows the steps and turns. They talk over three web addresses.

**1. `GET /api/state`: "what are the numbers now?"** The page asks 4 times a second. The
board answers with its running totals:

```json
{"steps": 42.6, "distance_m": 29.8, "turns_left": 1, "turns_right": 0,
 "steps_at_last_turn": 30.2, "distance_at_last_turn": 21.1,
 "heading_deg": 85, "on_stairs": false}
```

Decimals are fine; the page rounds steps down and works out "steps since the turn" itself.

**2. `GET /api/reset?walker=Raph&kind=demo`: "a new walk starts now."** The board sets every
count to 0, picks the next walk number, and answers `{"ok": true, "walk": 3}`. The page
doesn't start the walk until it gets this answer. The walk number goes on every row of the
walk, so the board knows which file each row belongs to. (The phone can't number the walks
itself: its counter starts over whenever the page reloads, and each phone has its own.)

**3. `POST /api/rows`: "here are rows to save."** Whenever a row is saved (one per step,
plus one per button tap), the page puts it in a **waiting line** on the phone and sends
the line to the board:

```json
{"items": [
  {"session": "k3x9", "seq": 1, "row": {"walk": 3, "walker": "Raph", "kind": "demo", "steps": 1, "label": "Straight", "...": "..."}},
  {"session": "k3x9", "seq": 2, "row": {"walk": 3, "walker": "Raph", "kind": "demo", "steps": 2, "label": "Straight", "...": "..."}}
]}
```

The board saves them and answers `{"ok": true}`. Only then do they leave the line. If the
board doesn't answer, they stay on the phone and are sent again a quarter-second later, in
the same order. So the board must handle getting the same row twice. That's what the
**ticket** is for:

- **Ticket** = `session` (a random name the page picks each time it opens) + `seq` (a
  number that goes up by 1 for every message). The board remembers the highest `seq` it
  has handled for each session and **skips anything not higher**. Then a row sent twice
  (because the board's "ok" got lost on the way back) is saved once.
- **Undo** is a message in the same line, with its own ticket: `{"session": "k3x9", "seq": 41,
  "undo": 40}` means "remove the row whose seq was 40". If the row hadn't been sent yet, the
  page just drops it from the line instead, and no undo is sent. An undo for a row the board
  never got is harmless: there's nothing to remove.
- Every request must be answered within **1.5 s**, or the page counts it as failed and
  tries again.

**4. `GET /api/predict`: "what should the walker do now?"** In Navigate mode (Live), the page
asks 4 times a second. The board looks up its own current state (left turns, right turns,
stairs, steps since the last turn) in the trained policy (`python/policy.py`, the table in
`python/policy.json`) and answers `{"ok": true, "action": "Left", "how": "exact"}` ("nearest"
if that situation was never seen and the nearest known one answered), or `{"ok": false,
"error": "no policy on the board yet"}`. The board reads `policy.json` again whenever it
changes, so a new policy needs no restart. A correction saves this answer as `predicted`.

## One walk, start to end

Raph records a demo walk; it's the third walk on this board.

| # | What happens | Phone → board | Board → phone |
|---|---|---|---|
| 1 | Raph picks **Raph**, **Live**, presses **Start walk** | `GET /api/reset?walker=Raph&kind=demo` | Zeroes the counts, starts walk 3: `{"ok": true, "walk": 3}` |
| 2 | The page says "Recording walk 3" and asks for numbers 4×/s | `GET /api/state` | `{"steps": 0.4, ...}` |
| 3 | Steps reach 1: the page saves a row, ticket seq 1 | `POST /api/rows` with seq 1 | Appends it to walk 3's CSV: `{"ok": true}` |
| 4 | … one row per step, seq 2, 3, … 24 | (same) | (same) |
| 5 | Raph taps **Left** before the corner: a row labeled Left, seq 25 | `POST /api/rows` with seq 25 | saved |
| 6 | The board's ankle gyro sees the turn | — | `/api/state` now says `turns_left: 1, steps_at_last_turn: 26.1, distance_at_last_turn: 18.3`; the page's label goes back to Straight |
| 7 | The hotspot hiccups for 2 s: rows seq 30-33 wait on the phone; the page shows a red warning | (requests fail) | — |
| 8 | The board answers again: the waiting rows go in one batch, in order | `POST /api/rows` with seq 30-33 | saved, `{"ok": true}`; the warning clears |
| 9 | That "ok" is lost on the way back, so the page sends seq 30-33 again | `POST /api/rows` with seq 30-33 | All already handled: skipped, `{"ok": true}` |
| 10 | Raph taps **Stairs** by mistake (seq 40, already sent), then **Undo** | `POST /api/rows` with `{"seq": 41, "undo": 40}` | Removes row 40 from walk 3's CSV |
| 11 | At Nolop: **Arrived**, then **End walk** | the last rows | saved; the page says "all sent to the board" |

## Build order: the minimum for the first real walk

Each step can be tested on its own before the next. The simplest version first; better
versions later.

### Step 0: can the ankle sensor alone count turns? (before building anything)

**Why:** if the ankle sensor can count turns, we don't need the waist sensor or the long
wire at all: the hardware for the first walk is exactly HW7's. Raph's old recording
already showed 180° turnarounds clearly at the ankle (`docs/process_log.md`, 2026-11-17
test). Step 0 checks what that walk couldn't: **90° corners while walking**, **left vs
right**, a longer route, and both walkers.

**Setup.** Board and one MPU-6050 strapped to the right lower leg, near the ankle, with
the short wire, exactly as in HW7. **No new code:** HW7's Step Recorder app already saves
the raw ankle readings at 100 per second. Use its **Test** activity.

**The walk** (a few minutes, once by Mohammed and once by Raph):
1. Press **Start**, then **stand still for 5 s**. This is when the gyro's bias (its false
   turning rate when still) is measured.
2. Walk a loop that comes back to the start with **four left corners** (for example
   around a block or a corridor loop, anticlockwise).
3. Walk the same loop the other way: **four right corners**.
4. Two turns on the spot (one left, one right), then stand still 5 s and press **Stop**.
5. Write down the order of the turns.

**Check:** run `training/ankle_turn_check.py <recording>.csv` and look at the heading plot.
- **Readings drop out?** The script prints the gaps over 25 ms; HW7's page also warns
  about bad readings. Should be none (short wire).
- **Every corner a clear step?** The heading should be flat on the straight stretches and
  climb (or drop) at each corner, one step per corner, without guessing which is which.
- **Left vs right:** left corners should go one way and right corners the other.
- **Size:** each loop should add up to about 360° (each corner about 90°). Raph's
  turnarounds read about 13% low, so about 310-320° per loop would match that; much less
  would mean corners get lost.
- **Margin for the turn rule:** note the biggest heading change within any 2 s on the
  straight stretches and at the corners. On HW7's straight walks the wobble stayed under
  20° in 2 s, and Raph's turnarounds climbed 118-169° in 2 s. If corners climb well over
  60° in 2 s and straights stay well under it, ">60° within 2 s" is a safe rule.
- **How long each corner takes:** a 90° corner taken while walking may take longer than
  2 s. Measure how long each corner's climb lasts, from where the heading leaves the flat
  part to where it is flat again. **If corners take longer than 2 s, widen the turn window
  to 3 s; don't lower the 60° threshold.** A lower threshold lets the walking wobble look
  like a turn, while a wider window still keeps it out: on HW7's straight walks the wobble
  stayed under 27° within 3 s.
- **Pass:** all of the above for both walkers. Then the waist sensor and the long wire are
  dropped from the plan.

**Backup if the ankle fails: the two-sensor test.** Wire a second MPU-6050 for the waist
at 0x69 (AD0 to 3.3 V) on the long wire, record both with a copy of HW7's sketch that
reads both, and walk the same loops. Check (a) dropouts: rows where all six channels read
0 (lost power) or −1 (no answer), or gaps over 10 ms; zero allowed, including while
wiggling the wire; and (b) turns in the waist gyro, the same heading plot as above
(the script finds "up" itself, so a tilted sensor on the belt is fine). If the waist fails
too, rethink before building the app.

### Steps 1-9: the board app

| # | Piece | Simplest version | Test |
|---|---|---|---|
| 1 | Serve the page | `python/main.py` with the `web_ui` brick, nothing else | Phone opens the page; Mock mode works |
| 2 | ~~Board address on the LED matrix~~ **Skipped** | Not needed: on walking days the board makes its own network, NolopNav, where its address is always 10.42.0.1 (see "Walking days") | — |
| 3 | Read the ankle sensor | HW7's `sketch.ino` as is (one MPU-6050 at 0x68, 100 Hz, with its reconnect fix) | Samples arrive in Python |
| 4 | Count steps and meters | Raph's counter, ported: `stride_counter.py` + `raph_step_model.npz` (`LiveStrideCounter`, same controls as HW7's `LiveCounter`); meters = steps × 0.41 | Walk 20 counted steps; the count is close; time it on the board |
| 5 | `GET /api/state` | The real `steps` and `distance_m`; every other field fixed at 0 / false | The page in Live mode shows steps going up |
| 6 | `GET /api/reset` | Zero the counts; walk number = highest walk number among saved files + 1 (as HW7 numbers trials) | Start walk works; the walk number goes up each time |
| 7 | `POST /api/rows` | Keep each walk's rows in memory as a list (with their seq), skip seqs already handled, remove a row on undo, then rewrite that walk's whole CSV and answer ok (a walk is only ~1000 rows) | A straight walk ends with a CSV on the board matching the phone's download |
| 8 | *Only if Step 0 fails:* read the waist sensor | Add the second MPU-6050 at 0x69 to the sketch (the backup test's sketch already does this) | Both read on a real walk (the long wire especially) |
| 9 | Count turns (ankle sensor) | **Done: `python/turns.py`.** The method of `training/ankle_turn_check.py`, live: measure the gyro offset of each axis while the walker stands still for 5 s right after `/api/reset` and subtract it; "up" from the accelerometer averaged over the last 1 s; add up the turning rate around "up". A turn = the heading changes by more than 60° within **3 s** (one corner took ~4 s with a pause, so 2 s missed it); after a turn, the next one in the same direction is measured as a quarter turn (60° beyond 30° past the last one), so a 180° counts as two turns and paired corners 1 s apart both count. Fills `turns_left/right`, both "at last turn" values and `heading_deg` | `training/check_turns.py`: all 8 Step 0 recordings counted exactly (every corner, no false turns; straights at most 31° within 3 s). On the board: 90° left and right on the table counted L, R |

After step 7 a straight walk can be recorded from start to end. After step 9 the first
real route walk can be recorded.

**Not needed for the first walk:** the stairs classifier (`on_stairs` stays false), running
the policy on the board (the first walks are demos), and MQTT. One known gap in the simple
version of step 7: if the board app restarts, it forgets which seqs it handled, so a
batch sent again right after a restart could be saved twice. Fine to start with; fix
later by saving the last seq to a file.

## How to deploy (from the terminal, no App Lab)

Copy this folder to the board (Python's `__pycache__` left out), then start it:

```
tar --exclude __pycache__ -cf - . | ssh arduino@<board> 'mkdir -p ~/ArduinoApps/nolop-navigator && tar -xf - -C ~/ArduinoApps/nolop-navigator'
ssh arduino@<board> 'arduino-app-cli app restart /home/arduino/ArduinoApps/nolop-navigator'
ssh arduino@<board> 'arduino-app-cli app logs --tail 30 /home/arduino/ArduinoApps/nolop-navigator'
```

`<board>` is the board's address on Tufts_Robot (check `hostname` says Raph first: campus
addresses get reused), or `10.42.0.1` with the laptop joined to NolopNav. Only one app runs
at a time: starting this one stops whichever app was running, and the first start installs
numpy (about a minute). `arduino-app-cli app list` shows which app runs.

## Walking days: the NolopNav network

Mohammed's phone can't use Tufts_Robot and we don't use a phone hotspot, so on walking days
the board makes its own Wi-Fi network. Raph agreed (it's his board), and Chris confirmed
that running our own Wi-Fi network on campus is OK.

**How it works.** NetworkManager (the board's network manager) has a hotspot mode: the
board's only Wi-Fi radio (`wlan0`) becomes a small Wi-Fi router called **NolopNav**, with
a WPA2 password. The board is always at **10.42.0.1**, and whatever joins gets a
10.42.0.x address. So the page is always at **http://10.42.0.1:7000** (no address on the
LED matrix needed). There is no internet on NolopNav: an iPhone says "No Internet
Connection" but stays joined; nothing on the page needs the internet. Checked on Raph's
board: its Wi-Fi chip supports hotspot mode, and the `arduino` user may change network
settings without the admin password.

**One radio:** while NolopNav is on, the board is **not** on Tufts_Robot (or Raph's home
networks), so it can't be reached there. To deploy or read logs, either join the laptop
to NolopNav (`ssh arduino@10.42.0.1`; no internet on the laptop meanwhile), or use the
**USB-C cable**: `adb shell` reaches the board whatever the Wi-Fi does. adb comes with App
Lab, off the PATH:

```
export PATH="$HOME/Library/Arduino15/packages/arduino/tools/adb/32.0.0:$PATH"
adb devices          # the board must be listed; if not: data cable (not charge-only), plugged into the laptop
adb shell hostname   # Raph
```

**Test the USB route before the first switch** (2026-11-18: not yet; the board showed no
USB data link). Switch networks over USB, not over Wi-Fi: a command that turns Wi-Fi off
can't cut off its own USB connection.

**Once: create NolopNav (switched off).** Mohammed types this himself in `adb shell` (or an
ssh session), so the password goes into the board's network settings only, never into this
repo or a chat. `read -rs` asks for the password without showing it or keeping it in the
shell history:

```
read -rs -p "NolopNav password (8+ characters): " PW; echo
nmcli connection add type wifi ifname wlan0 con-name NolopNav ssid NolopNav \
  802-11-wireless.mode ap 802-11-wireless.band bg \
  ipv4.method shared ipv4.addresses 10.42.0.1/24 ipv6.method disabled \
  wifi-sec.key-mgmt wpa-psk wifi-sec.proto rsn wifi-sec.pairwise ccmp wifi-sec.group ccmp \
  wifi-sec.psk "$PW" connection.autoconnect no
unset PW
```

**Morning of a walking day: NolopNav on, starts by itself after a power-off.** A hotspot is
always "available", so with a higher priority than the saved networks (all 0) it wins
every time the board starts. Nolop Navigator becomes the default app, so it starts too:

```
nmcli connection modify NolopNav connection.autoconnect yes connection.autoconnect-priority 10
arduino-app-cli properties set default /home/arduino/ArduinoApps/nolop-navigator
nmcli connection up NolopNav        # over Wi-Fi this drops the session: do it over USB
```

Check: the phone (and laptop) see NolopNav; http://10.42.0.1:7000 opens the page.

**Evening: back to Tufts_Robot.** Over USB:

```
nmcli connection modify NolopNav connection.autoconnect no
nmcli connection down NolopNav      # NetworkManager rejoins Tufts_Robot within seconds
arduino-app-cli properties set default /home/arduino/ArduinoApps/Steps-UnoQ
```

`arduino-app-cli` can set a default app but has no command to clear one, so the evening step
sets Raph's **How Many Steps** app (`Steps-UnoQ`), the app that was running when HW9 started
on his board, so each evening the board goes back to how Raph had it (his choice). Check: `nmcli -t -f NAME,DEVICE
connection show --active` shows Tufts_Robot on wlan0. To remove NolopNav for good:
`nmcli connection delete NolopNav`.
