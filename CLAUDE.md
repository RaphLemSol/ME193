# Arduino UNO Q Apps

This folder holds Arduino App Lab apps for an Arduino UNO Q board. It mirrors
`/home/arduino/ArduinoApps` on the board. Each subfolder with an `app.yaml` is
a separate app:

- `python/main.py` runs in a container on the board's Linux side.
- `sketch/` is the microcontroller (STM32) code.
- `arduino.app_utils` (App, Bridge, etc.) only exists on the board, so
  unresolved-import warnings locally are expected. Don't try to pip install it.

## Talking to the board

Always go through `tools/deploy.py`. It finds the board over USB (adb) first, then
by trying each address in the `HOSTS` list in `tools/board_secrets.py`, so don't
call `ssh` or `scp` directly (there may be no ssh config entry for the board). On Windows use `python` instead of `python3`.

Deploy and run one app (only the app you changed):

    python3 tools/deploy.py <app-name>

This stops the app, copies its files up, and starts it. Read the output for
errors and fix them before reporting back.

Run any other command on the board:

    python3 tools/deploy.py --cmd "<command>"

Examples:

    python3 tools/deploy.py --cmd "arduino-app-cli app stop /home/arduino/ArduinoApps/<app-name>"
    python3 tools/deploy.py --cmd "rm /home/arduino/ArduinoApps/<app-name>/python/old_module.py"
    python3 tools/deploy.py --cmd "arduino-app-cli --help"

If deploy.py says it can't reach the board, stop and tell the user. The
board's IP has probably changed and they need to update `HOSTS` in tools/board_secrets.py.

## Notes

- Deploying copies files but never deletes them on the board. If you remove or
  rename a file, also delete the old copy with `--cmd "rm ..."`.
- Make edits here, not on the board. Changes made only on the board get
  overwritten on the next deploy.
- Hidden folders like `.cache` are the board's Python environment. They are not
  copied and are ignored by Git; leave them alone.
