import math
import time

import numpy as np

from .osc import ChannelSender

TOUCHES = 3

NAMES = [
    "ph_connected", "ph_fps", "ph_rtt", "ph_width", "ph_height", "ph_front",
    "ph_yaw", "ph_pitch", "ph_roll", "ph_tilt_x", "ph_tilt_y",
    "ph_acc_x", "ph_acc_y", "ph_acc_z", "ph_motion", "ph_shake",
    "ph_touches", "ph_tap", "ph_pinch", "ph_pinch_amt",
]
for _i in range(TOUCHES):
    NAMES += [f"ph_t{_i}_x", f"ph_t{_i}_y", f"ph_t{_i}_down"]


def clamp(v, lo=-1.0, hi=1.0):
    return max(lo, min(hi, v))


def num(v, d=0.0):
    try:
        f = float(v)
    except (TypeError, ValueError):
        return d
    return f if math.isfinite(f) else d


class Sensors:
    def __init__(self, host, port):
        self.sender = ChannelSender(host, port, NAMES)
        self.i = {n: k for k, n in enumerate(NAMES)}
        self.v = np.zeros(len(NAMES), np.float32)
        self.shake_until = 0.0
        self.tap_until = 0.0
        self.last_tap = 0
        self.pinch_base = None
        self.motion = 0.0

    def set(self, name, value):
        self.v[self.i[name]] = value

    def video(self, fps, width, height, rtt, front):
        self.set("ph_fps", fps)
        self.set("ph_width", width)
        self.set("ph_height", height)
        self.set("ph_rtt", rtt)
        self.set("ph_front", 1 if front else 0)

    def connected(self, on):
        self.set("ph_connected", 1 if on else 0)
        if not on:
            keep = {n: self.v[self.i[n]] for n in ("ph_width", "ph_height")}
            self.v[:] = 0
            for n, x in keep.items():
                self.set(n, x)
            self.pinch_base = None

    def update(self, msg):
        now = time.perf_counter()
        o = msg.get("o") or [0, 0, 0]
        a, b, g = (num(x) for x in (o + [0, 0, 0])[:3])
        yaw = (a + 180) % 360 - 180
        self.set("ph_yaw", yaw)
        self.set("ph_pitch", b)
        self.set("ph_roll", g)
        self.set("ph_tilt_x", clamp(g / 90))
        self.set("ph_tilt_y", clamp(b / 90))

        acc = msg.get("a") or [0, 0, 0]
        ax, ay, az = (num(x) for x in (acc + [0, 0, 0])[:3])
        self.set("ph_acc_x", ax)
        self.set("ph_acc_y", ay)
        self.set("ph_acc_z", az)
        mag = math.sqrt(ax * ax + ay * ay + az * az)
        self.motion += (min(mag / 20, 1) - self.motion) * 0.2
        self.set("ph_motion", self.motion)
        if mag > 16:
            self.shake_until = now + 0.25
        self.set("ph_shake", 1 if now < self.shake_until else 0)

        pts = msg.get("p") or []
        pts = [(clamp(num(p[0]), 0, 1), clamp(num(p[1]), 0, 1)) for p in pts if isinstance(p, (list, tuple)) and len(p) >= 2]
        self.set("ph_touches", len(pts))
        for k in range(TOUCHES):
            if k < len(pts):
                x, y = pts[k]
                self.set(f"ph_t{k}_x", x)
                self.set(f"ph_t{k}_y", 1 - y)
                self.set(f"ph_t{k}_down", 1)
            else:
                self.set(f"ph_t{k}_down", 0)
        if len(pts) >= 2:
            d = math.dist(pts[0], pts[1])
            if self.pinch_base is None:
                self.pinch_base = max(d, 1e-3)
            self.set("ph_pinch", 1)
            self.set("ph_pinch_amt", d / self.pinch_base)
        else:
            self.pinch_base = None
            self.set("ph_pinch", 0)
            self.set("ph_pinch_amt", 1)

        taps = int(num(msg.get("k")))
        if taps != self.last_tap:
            if taps > self.last_tap:
                self.tap_until = now + 0.15
            self.last_tap = taps
        self.set("ph_tap", 1 if now < self.tap_until else 0)

    def tick(self):
        now = time.perf_counter()
        if now >= self.shake_until:
            self.set("ph_shake", 0)
        if now >= self.tap_until:
            self.set("ph_tap", 0)
        self.sender.send(self.v)

    def close(self):
        self.sender.close()
