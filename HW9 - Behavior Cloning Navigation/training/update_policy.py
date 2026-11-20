"""One command between walks: pull the walks from the board, clean the labels, train the
policy, and put the new policy on the board.

Usage (from the repo, laptop next to the board):
    python update_policy.py --via usb            # USB-C cable (adb)
    python update_policy.py --via nolop          # laptop joined to the board's NolopNav network
    python update_policy.py --via ip --host 10.247.137.63   # board on Tufts_Robot
  options:
    --no-deploy    stop after training (look at the table first)
    --check-only   only check the board (app running, sensor readings, policy answers)
    --with-code    also copy the app's code (uno_q/) and restart it (only when code changed)
    --code-only    only copy the app's code and restart it (e.g. before the first walk, when
                   there are no walks to train on yet), then the check
    --lead 6       steps of warning before a turn, for the label cleanup

Steps:
1. Connect, and check the board's name (Raph) before touching anything: campus addresses
   get reused by other boards.
2. Pull every walk file from the board's app folder (python/walks/) to data/walks/, except
   the files in data/walks_excluded.txt (test walks). A laptop copy is never replaced by a
   shorter one from the board.
3. Clean the labels (clean_labels.py) and print the report.
4. Train the table (train_policy.py), print it, save uno_q/python/policy.json.
5. Copy only policy.json to the board (to a temporary name, then renamed, so the board never
   reads half a file). The app reads it again by itself: no restart, so no reflash.
6. Check: the board answers /api/predict with the new policy, the app log shows "Policy
   loaded" and recent sensor readings. If the readings have stopped (the sketch isn't
   running), it prints the power-off steps.
"""
import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
PROJECT = HERE.parent
sys.path.insert(0, str(HERE))
import clean_labels  # noqa: E402
import train_policy  # noqa: E402

APP = "/home/arduino/ArduinoApps/nolop-navigator"



def find_adb():
    """adb comes with App Lab but isn't on the PATH: look in App Lab's folder on a Mac
    (Mohammed's laptop) and on Windows (Raph's laptop)."""
    for path in (shutil.which("adb"),
                 os.path.expanduser("~/Library/Arduino15/packages/arduino/tools/adb/32.0.0/adb"),
                 os.path.join(os.environ.get("LOCALAPPDATA", ""),
                              "Arduino15/packages/arduino/tools/adb/32.0.0/adb.exe")):
        if path and os.path.isfile(path):
            return path
    return "adb"            # not found: running it fails with a clear "not found" error


ADB = find_adb()
# Over USB the page's port is reached through an adb port forward. The laptop end must NOT
# be 7000: on a Mac, AirPlay Receiver already listens on 7000, so the forward failed
# silently and AirPlay answered instead, closing the connection with no response (that
# was the "/api/predict didn't answer" bug, 2026-11-19). tools/deploy.py uses 7007 too.
USB_LOCAL_PORT = 7007
# ssh/scp over Wi-Fi. HostKeyAlias: remember Raph's board under one name, whatever its
# address (Tufts_Robot or NolopNav), and accept-new: remember it the first time instead of
# failing. Without these, a laptop that only knew the board from tools/deploy.py (which
# saves it as "unoq") got "Host key verification failed" in BatchMode, the name check read
# nothing, and the script stopped (2026-11-19). The name check below still makes sure the
# board answering is Raph's.
SSH_OPTS = ["-o", "BatchMode=yes", "-o", "ConnectTimeout=8",
            "-o", "HostKeyAlias=nolop-raph", "-o", "StrictHostKeyChecking=accept-new"]
POWER_OFF_STEPS = """
The sketch isn't running (no sensor readings): power the board off and on.
  1. Unplug the board's cable or power bank, wait 5 s, plug it back in.
  2. Wait about a minute: Nolop Navigator starts by itself (it is the default app on walking days).
  3. Check again:  python training/update_policy.py --via {via} --check-only
     (After a restart the board needs 5 s of standing still after Start to measure the gyro.)
"""


# --- Talking to the board: over USB (adb), over Wi-Fi (ssh), or a folder (for tests) ---------

class Board:
    def __init__(self, via, host=None, folder=None):
        self.via, self.host, self.folder = via, host, folder

    def run(self, cmd):
        """Run a shell command on the board, return its output."""
        if self.via == "local":
            return "Raph" if cmd == "hostname" else ""
        args = [ADB, "shell", cmd] if self.via == "usb" else ["ssh", *SSH_OPTS, f"arduino@{self.host}", cmd]
        return subprocess.run(args, capture_output=True, text=True, timeout=120).stdout.strip()

    def path(self, remote):
        return os.path.join(self.folder, remote.replace(APP + "/", "")) if self.via == "local" else remote

    def pull(self, remote, local):
        if self.via == "local":
            shutil.copy(self.path(remote), local)
        elif self.via == "usb":
            subprocess.run([ADB, "pull", remote, local], check=True, capture_output=True)
        else:
            subprocess.run(["scp", "-q", *SSH_OPTS, f"arduino@{self.host}:{remote}", local], check=True)

    def push(self, local, remote):
        """Copy to a temporary name, then rename on the board (the app never sees half a file)."""
        if self.via == "local":
            shutil.copy(local, self.path(remote) + ".tmp")
            os.replace(self.path(remote) + ".tmp", self.path(remote))
            return
        if self.via == "usb":
            subprocess.run([ADB, "push", local, remote + ".tmp"], check=True, capture_output=True)
        else:
            subprocess.run(["scp", "-q", *SSH_OPTS, local, f"arduino@{self.host}:{remote}.tmp"], check=True)
        self.run(f"mv {remote}.tmp {remote}")

    def list_walks(self):
        if self.via == "local":
            d = self.path(APP + "/python/walks")
            return sorted(n for n in os.listdir(d) if n.endswith(".csv")) if os.path.isdir(d) else []
        out = self.run(f"ls {APP}/python/walks/ 2>/dev/null")
        return sorted(n for n in out.split() if n.endswith(".csv"))

    def get(self, api):
        """GET http://<board>:7000<api> as JSON (over USB through a port forward)."""
        if self.via == "local":
            return None
        if self.via == "usb":
            # laptop port 7007 -> board port 7000 (see USB_LOCAL_PORT). Stop with adb's own
            # message if the forward fails, instead of asking whatever else is on that port.
            fwd = subprocess.run([ADB, "forward", f"tcp:{USB_LOCAL_PORT}", "tcp:7000"],
                                 capture_output=True, text=True)
            if fwd.returncode != 0:
                raise RuntimeError(f"adb forward failed: {(fwd.stderr or fwd.stdout).strip()}")
            url = f"http://localhost:{USB_LOCAL_PORT}{api}"
        else:
            url = f"http://{self.host}:7000{api}"
        with urllib.request.urlopen(url, timeout=5) as r:
            return json.loads(r.read())


def rows_in(path):
    with open(path) as f:
        return sum(1 for _ in f) - 1


# --- The steps ------------------------------------------------------------------------------

def connect(board, name):
    got = board.run("hostname")
    if got != name:
        raise SystemExit(f"The board answering is {got or 'nobody'!r}, not {name!r}. Check the cable/network "
                         f"(USB: is it listed by '{ADB} devices'?); nothing was changed.")
    print(f"1. Connected to {name} over {board.via}.")


def pull(board, data):
    walks, skip = data / "walks", clean_labels.excluded(str(data / "walks"))
    walks.mkdir(parents=True, exist_ok=True)
    new = updated = kept = 0
    for name in board.list_walks():
        if name in skip:
            continue
        local = walks / name
        with tempfile.TemporaryDirectory() as tmp:
            board.pull(f"{APP}/python/walks/{name}", os.path.join(tmp, name))
            fresh = os.path.join(tmp, name)
            if not local.exists():
                shutil.copy(fresh, local); new += 1
            elif rows_in(fresh) > rows_in(local):
                shutil.copy(fresh, local); updated += 1
            elif rows_in(fresh) < rows_in(local):
                kept += 1
                print(f"   {name}: the board's copy is shorter than the laptop's; kept the laptop's")
    print(f"2. Pulled walks to {walks}: {new} new, {updated} updated, {kept} kept "
          f"(skipped {len(skip)} listed in walks_excluded.txt).")


def check(board, via, expect_policy=True):
    """The app is running, readings arrive, and the policy answers. Returns True if all good."""
    ok = True
    if board.via == "local":
        return True
    running = "running" in board.run(f"arduino-app-cli app list 2>&1 | grep nolop-navigator")
    log = board.run(f"arduino-app-cli app logs --tail 40 {APP} 2>&1")
    print(f"   app {'running' if running else 'NOT running'}")
    readings = [l for l in log.splitlines() if "Sensor:" in l and "readings in" in l]
    last = readings[-1] if readings else ""
    try:
        got = int(last.split("Sensor: ")[1].split(" readings")[0]) if last else 0
    except (IndexError, ValueError):
        got = 0
    sketch_silent = bool(log) and "TimeoutError" in log.splitlines()[-1]   # get_batch timing out
    if not running or sketch_silent or got < 500:
        ok = False
        print(f"   sensor readings: {last.split('INFO - ')[-1] if last else 'none in the log'}")
        print(POWER_OFF_STEPS.format(via=via))
    else:
        print(f"   sensor readings OK: {got} in the last 10 s")
    if "Policy loaded" in log:
        print("   " + [l for l in log.splitlines() if "Policy loaded" in l][-1].split("INFO - ")[-1].strip())
    try:
        answer = board.get("/api/predict")
        print(f"   /api/predict: {answer}")
        if expect_policy and not answer.get("ok"):
            ok = False
    except Exception as e:
        ok = False
        print(f"   /api/predict didn't answer ({e})")
    return ok


def deploy_code(board):
    """Copy uno_q/ (not the board's walks) and restart the app; then the start-up check."""
    src = PROJECT / "uno_q"
    if board.via == "local":
        return
    with tempfile.TemporaryDirectory() as tmp:
        tar = os.path.join(tmp, "app.tar")
        subprocess.run(["tar", "--exclude", "__pycache__", "--exclude", "walks", "-cf", tar, "-C", str(src), "."],
                       check=True, env=dict(os.environ, COPYFILE_DISABLE="1"))
        board.push(tar, "/tmp/nolop-app.tar")
    board.run(f"tar -xf /tmp/nolop-app.tar -C {APP} && rm /tmp/nolop-app.tar")
    print("   code copied; restarting the app (about 30 s)")
    board.run(f"arduino-app-cli app restart {APP}")
    time.sleep(25)
    burst = board.run('journalctl --no-pager -u arduino-router --since "-60 s" 2>&1 | grep -c "invalid packet"')
    print(f"   sketch start-up burst in the router log: {'yes' if burst not in ('', '0') else 'NO (the sketch may not be running)'}")


def main():
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--via", choices=["usb", "nolop", "ip", "local"], required=True)
    p.add_argument("--host", help="board address for --via ip")
    p.add_argument("--board-dir", help="--via local: a folder standing in for the app folder (tests)")
    p.add_argument("--board-name", default="Raph")
    p.add_argument("--data", default=str(PROJECT / "data"), help="the data folder (walks, cleaned)")
    p.add_argument("--policy", default=str(PROJECT / "uno_q" / "python" / "policy.json"))
    p.add_argument("--lead", type=float, default=6)
    p.add_argument("--report", default=str(HERE / "policy_report.md"), help="where to write the printed table")
    p.add_argument("--no-deploy", action="store_true")
    p.add_argument("--check-only", action="store_true")
    p.add_argument("--with-code", action="store_true")
    p.add_argument("--code-only", action="store_true")
    a = p.parse_args()
    host = {"nolop": "10.42.0.1", "ip": a.host}.get(a.via)
    if a.via == "ip" and not host:
        raise SystemExit("--via ip needs --host <address>")
    board = Board(a.via, host, a.board_dir)
    data = Path(a.data)

    connect(board, a.board_name)
    if a.check_only:
        print("Check:")
        sys.exit(0 if check(board, a.via, expect_policy=False) else 1)
    if a.code_only:
        print("Deploying the app's code:")
        deploy_code(board)
        print("Check:")
        sys.exit(0 if check(board, a.via, expect_policy=False) else 1)
    pull(board, data)
    print("3. Cleaning the labels:")
    clean_labels.clean_all(str(data / "walks"), str(data / "cleaned"), a.lead)
    print("4. Training:")
    if not any(n.endswith(".csv") for n in os.listdir(data / "cleaned")) if (data / "cleaned").exists() else True:
        print("   No walks to train on yet: nothing trained, no policy deployed.")
        if a.with_code:
            print("5a. Deploying the app's code:")
            deploy_code(board)
        print("6. Check:")
        sys.exit(0 if check(board, a.via, expect_policy=False) else 1)
    train_policy.train(str(data / "cleaned"), a.policy, report=a.report)
    if a.no_deploy:
        print("Not deployed (--no-deploy).")
        return
    if a.with_code:
        print("5a. Deploying the app's code:")
        deploy_code(board)
    board.push(a.policy, f"{APP}/python/policy.json")
    print("5. policy.json copied to the board (the app reads it again by itself).")
    time.sleep(0 if a.via == "local" else 2)
    print("6. Check:")
    sys.exit(0 if check(board, a.via) else 1)


if __name__ == "__main__":
    main()
