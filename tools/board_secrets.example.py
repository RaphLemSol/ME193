"""Your board's settings. This file is the template and is safe to share.

On first run, deploy.py copies it to board_secrets.py (which Git ignores) and
you edit that copy. Updates from GitHub never overwrite board_secrets.py.
"""

# Addresses to try, in order, when the board isn't plugged in over USB.
# Find the board's IP by running:  python3 deploy.py --cmd "hostname -I"
HOSTS = [
    "10.247.137.34",     # the board's IP address on your WiFi
    "Raph.local",       # board name + .local (works on many home networks)
]

USER = "arduino"        # login name on the board (leave as is)

# Used by Tufts_WiFi.py to advertise the board on the network
BOARD_NAME = "Raph"
BOARD_IP = "10.247.137.34"
