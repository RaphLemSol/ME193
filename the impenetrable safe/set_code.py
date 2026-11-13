"""
Set the safe's code: three different numbers, 1-5.

    python set_code.py 4 1 3

Only a salted SHA-256 hash is saved (Safe-UnoQ/python/code.json), so the
code can't be read out of the file. Deploy the app again after changing it.
"""

import json
import secrets
import sys

import safe_config  # noqa: F401  (makes lock_policy importable)
from lock_policy import CODE_LENGTH, CODE_PATH, hash_code


def main():
    try:
        digits = [int(d) for d in sys.argv[1:]]
    except ValueError:
        digits = []
    if len(digits) != CODE_LENGTH or any(not 1 <= d <= 5 for d in digits):
        sys.exit(f"Usage: python set_code.py 4 1 3   ({CODE_LENGTH} numbers, each 1-5)")
    if len(set(digits)) != CODE_LENGTH:
        sys.exit("Use three different numbers.")
    salt = secrets.token_hex(8)
    CODE_PATH.write_text(json.dumps({"salt": salt, "hash": hash_code(digits, salt)}, indent=2))
    print(f"Code saved (hashed) to {CODE_PATH}")


if __name__ == "__main__":
    main()
