import socket
import struct

import numpy as np

BUNDLE = b"#bundle\0" + b"\0\0\0\0\0\0\0\1"


def pad(b):
    return b + b"\0" * (4 - len(b) % 4)


class ChannelSender:
    def __init__(self, host, port, names):
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.target = (host, int(port))
        self.names = list(names)
        heads = [pad(("/" + n).encode()) + b",f\0\0" for n in self.names]
        self.frames = [struct.pack(">i", len(h) + 4) + h for h in heads]

    def send(self, values):
        raw = np.asarray(values, dtype=">f4").tobytes()
        parts = [BUNDLE]
        for i, f in enumerate(self.frames):
            parts.append(f)
            parts.append(raw[i * 4:i * 4 + 4])
        try:
            self.sock.sendto(b"".join(parts), self.target)
        except OSError:
            pass

    def close(self):
        self.sock.close()
