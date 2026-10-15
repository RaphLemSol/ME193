"""Advertise an Arduino UNO Q over mDNS, equivalent to:
dns-sd -P "<BOARD_NAME>" _arduino._tcp local 80 <BOARD_NAME>.local <BOARD_IP> board=unoq ...
Requires: pip install zeroconf
"""
import socket
import time

from zeroconf import ServiceInfo, Zeroconf

from config import BOARD_IP, BOARD_NAME  # edit these in board_secrets.py

info = ServiceInfo(
    type_="_arduino._tcp.local.",
    name=f"{BOARD_NAME}._arduino._tcp.local.",
    addresses=[socket.inet_aton(BOARD_IP)],
    port=80,
    server=f"{BOARD_NAME}.local.",
    properties={
        "board": "unoq",
        "vid": "0x2341",
        "pid": "0x0078",
        "vid.0": "0x2341",
        "pid.0": "0x0078",
    },
)

zc = Zeroconf()
zc.register_service(info)
print(f"Advertising {BOARD_NAME} ({BOARD_IP}). Press Ctrl+C to stop.")
try:
    while True:
        time.sleep(1)
except KeyboardInterrupt:
    pass
finally:
    zc.unregister_service(info)
    zc.close()