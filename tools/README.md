# UNO Q tools

Helper scripts that run on your computer (not on the board) to deploy apps to
an Arduino UNO Q and connect to it. Nothing in this folder is copied to the board.

| File | What it does |
|---|---|
| `deploy.py` | Copies an app to the board and starts it, runs commands, opens a terminal or Python on the board |
| `Tufts_WiFi.py` | Advertises the board over mDNS so App Lab can find it on Tufts WiFi (needs `pip install zeroconf`) |
| `board_secrets.example.py` | Template for your board's settings. Shared on GitHub. Don't edit |
| `board_secrets.py` | **Your** board's settings. Created automatically, never uploaded to GitHub |
| `config.py` | Loads the settings (and creates `board_secrets.py` on first run) |

## First-time setup

1. Run any command below once. `deploy.py` creates `board_secrets.py` from the template.
2. Open `board_secrets.py` and set your board's values:

   ```python
   HOSTS = ["192.168.1.50", "unoq.local"]   # addresses to try (WiFi)
   USER = "arduino"
   BOARD_NAME = "unoq"                      # used by Tufts_WiFi.py
   BOARD_IP = "192.168.1.50"                # used by Tufts_WiFi.py
   ```

   Not sure of the IP? Plug the board in over USB and run
   `python3 tools/deploy.py --cmd "hostname -I"`.
3. When you `git pull` updates, `board_secrets.py` is left alone.

If the board is plugged in over USB and `adb` is installed, USB is used first and
`HOSTS` isn't needed.

## Commands

Run from the `ArduinoApps` folder (use `python` instead of `python3` on Windows):

    python3 tools/deploy.py <app-name>            # stop, copy, start one app
    python3 tools/deploy.py --python              # Python in the running app's container,
                                                  # or on the board's Linux side if none is running
    python3 tools/deploy.py --cmd "<command>"     # run any command on the board
    python3 tools/deploy.py --shell               # open a terminal on the board (type exit to leave)
    python3 tools/Tufts_WiFi.py                   # advertise the board (Ctrl+C to stop)

## From VS Code

Open a file inside an app and press **Cmd+Shift+B** (Ctrl+Shift+B on Windows).
Pick one of:

- **Run on UNO Q**: deploy and start the open file's app
- **Python in UNO Q container**: Python prompt in the running app, or on the board
- **Terminal on UNO Q**: a command-line session on the board
- **Advertise UNO Q on Tufts WiFi**: runs `Tufts_WiFi.py`

The board runs one app at a time, so deploying stops whichever app was running.
