"""Loads board_secrets.py, creating it from the example on first use."""
import shutil
from pathlib import Path

_here = Path(__file__).resolve().parent
_secrets = _here / "board_secrets.py"

if not _secrets.exists():
    shutil.copy(_here / "board_secrets.example.py", _secrets)
    print(f"Created {_secrets.name} with default values. "
          f"Edit it with your board's address.\n", flush=True)

from board_secrets import BOARD_IP, BOARD_NAME, HOSTS, USER  # noqa: E402,F401
