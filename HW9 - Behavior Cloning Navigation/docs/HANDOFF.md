# HW9 handoff (2026-11-19, afternoon)

For whoever continues today (Raph's Claude Code). Details are in `../README.md`,
`../uno_q/README.md` (protocol, build order, "Walking days"), `../data/README.md`,
`../data/RECORDING_CHECKLIST.md` and `process_log.md`.

## State right now

- Raph's UNO Q (hostname `Raph`) runs **Nolop Navigator** (`/home/arduino/ArduinoApps/nolop-navigator`),
  the latest code from this repo. It is the **default app**, it is running, and the sensor
  readings are OK (checked over USB).
- **No policy yet** (no route walks recorded). Navigate will show "No policy".
- **`/api/predict` problem:** `update_policy.py --via usb --check-only` reported that
  `/api/predict` closed the connection without a response. Not investigated yet (see
  Known issues).
- The board is still on **Tufts_Robot**. **NolopNav is not switched on yet.**
- Raph's How Many Steps app (`Steps-UnoQ`) is stopped; it goes back as the default each evening.
- Board walk files W01-W03 are yesterday's tests; they're listed in `data/walks_excluded.txt`.
  The first route walk will be **W04**.

## Commands

Run from the repo root, with the repo's `.venv`. `UP` below means
`.venv/bin/python "Mohammed's Projects/HW9 - Behavior Cloning Navigation/training/update_policy.py"`.

**USB (adb).** adb comes with App Lab, off the PATH:
```
export PATH="$HOME/Library/Arduino15/packages/arduino/tools/adb/32.0.0:$PATH"
adb devices            # the board must be listed (data cable, plugged into the laptop)
adb shell hostname     # must say Raph
```

**update_policy.py modes** (`--via usb`, `--via nolop` with the laptop on NolopNav, or
`--via ip --host <address>`; it always checks the board is Raph first):
- `UP --via usb`: pull the walks, clean, train, copy `policy.json` to the board, check. This
  is the command between walks. No restart needed: the app re-reads `policy.json`.
- `UP --via usb --no-deploy`: same, but stop after training (look at the table first).
- `UP --via usb --check-only`: only check (app running, sensor readings, `/api/predict`).
- `UP --via usb --code-only`: copy the app's code and restart it, then check.
- `UP --via usb --with-code`: the full run, plus copy the code first (only if code changed).
- `--lead 6`: steps of warning before a turn in the cleaned labels (untuned).

**Default app** (on the board, e.g. in `adb shell`):
```
arduino-app-cli properties set default /home/arduino/ArduinoApps/nolop-navigator   # walking day
arduino-app-cli properties set default /home/arduino/ArduinoApps/Steps-UnoQ        # evening (Raph's)
arduino-app-cli app list                                                           # which app runs
arduino-app-cli app logs --tail 30 /home/arduino/ArduinoApps/nolop-navigator
```

**Power-cycle rule.** After any start or restart, the app log should show
`Sensor: ~1000 readings in 10 s`. Another sign: the router log has a burst of ~37
"invalid packet" lines just before the app connects:
`journalctl --no-pager -u arduino-router --since "-2 min" | grep -c "invalid packet"`.
If the readings don't come (`get_batch timed out` in the log, or no burst), **unplug the
board's power (cable or power bank) for 5 s and plug it back in**. Wait about a minute; the
default app starts by itself. A restart from the CLI did not fix it; a power-off always did.

**Walking days** (full commands in `uno_q/README.md`, "Walking days"; do these over USB, since a
Wi-Fi command that switches the network cuts off its own session):
- **Once:** Mohammed creates the NolopNav connection himself. The password is typed, never written
  in the repo or a chat.
- **Morning:** NolopNav starts by itself with priority 10, Nolop Navigator is the default app,
  then `nmcli connection up NolopNav`. The phone joins NolopNav and opens
  **http://10.42.0.1:7000**.
- **Evening:** NolopNav's automatic start off, `nmcli connection down NolopNav` (the board
  rejoins Tufts_Robot), and How Many Steps (`Steps-UnoQ`) set as the default and started.

## Known issues

- **`/api/predict` closed the connection without a response** in `--check-only`. With no
  policy it should answer `{"ok": false, "error": "no policy on the board yet"}`. To check:
  - **app log:** errors around the request
  - **directly:** `adb forward tcp:7000 tcp:7000` then `curl http://localhost:7000/api/predict`
  - **compare:** `curl http://localhost:7000/api/state`, to see whether it's only `/api/predict`
- **The sketch sometimes doesn't start after a deploy or restart.** Use the power-cycle rule.
- **Steps go up 2 at a time,** about 0.6-0.85 s late (Raph's counter counts strides).
- **A batch of readings that arrives cut short** (a few times an hour) loses about 2-4 steps if
  it happens while walking.
- **After every Start, stand still 5 s.** The gyro offset is measured then. Raph's sensor's
  `gx` offset is about 35-38°/s and drifts as it warms up.
- **One radio:** while NolopNav is on, the board isn't on Tufts_Robot. Use USB, or join the
  laptop to NolopNav (no internet on the laptop then; push to GitHub later).
- **Don't restart the hotspot or the board mid-walk.** If the address changes, press Download
  CSV on the old page first.
- **The board's clock** may be wrong on NolopNav (no internet to sync it). The app only uses
  a clock that counts forward, so this doesn't matter for counting.
- **Turn rule:** 60° within 3 s, checked on 8 recordings. **Lead of 6 steps** for the turn
  labels: not tuned on real walks yet.

## Today's remaining plan

1. Fix or understand `/api/predict` (Known issues), then `UP --via usb --check-only`.
2. **Walk test:** board on the ankle, Start, stand 5 s, 20 counted steps and a couple of
   corners. Compare the steps and turns in the app log with what you counted and turned.
3. **NolopNav:** the one-time creation (Mohammed types the password), then the morning steps.
   Check the phone opens http://10.42.0.1:7000.
4. **Route demos:** both walkers walk the route with the Record demo tab, following
   `data/RECORDING_CHECKLIST.md`. Fill in the walk table in `data/README.md` after each walk.
   Budget: 10 full walks in total, corrections included.
5. **Clean, train, deploy:** `UP --via usb` (or `--via nolop`). Read the cleanup report
   (CHECK lines) and the table.
6. **Navigate test:** the Navigate + correct tab, Live, following the board's instructions.
7. **DAgger:** correction walks with "Save my corrections" ticked, then `UP` again.
8. **Final filmed test:** someone who doesn't know the way follows the guide to Nolop.
9. **Evening switch-back:** back to Tufts_Robot, How Many Steps as the default and running.
   Commit and push the walks (`data/walks/`, `data/cleaned/`), the policy and the
   process log.
