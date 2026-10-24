import ipaddress
import os
import socket
from pathlib import Path


def private(ip):
    try:
        a = ipaddress.ip_address(ip)
    except ValueError:
        return False
    return a.version == 4 and a.is_private and not a.is_loopback and not a.is_link_local


def lan_ips():
    found = []
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("10.255.255.255", 1))
        ip = s.getsockname()[0]
        s.close()
        if private(ip):
            found.append(ip)
    except OSError:
        pass
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            ip = info[4][0]
            if private(ip) and ip not in found:
                found.append(ip)
    except OSError:
        pass
    return found


def data_dir(override=""):
    if override:
        p = Path(override)
    elif os.name == "nt":
        p = Path(os.environ.get("LOCALAPPDATA", Path.home())) / "handoff"
    else:
        p = Path.home() / ".handoff"
    p.mkdir(parents=True, exist_ok=True)
    return p
