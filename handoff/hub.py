import asyncio
import os
import threading
import time

import numpy as np

GL_RGBA = 0x1908


class Spout:
    def __init__(self, name):
        import SpoutGL
        self.sender = SpoutGL.SpoutSender()
        self.sender.setSenderName(name)
        self.name = name
        self.fails = 0

    def send(self, rgba):
        h, w = rgba.shape[:2]
        ok = self.sender.sendImage(np.ascontiguousarray(rgba), w, h, GL_RGBA, False, 0)
        try:
            self.sender.setFrameSync(self.name)
        except Exception:
            pass
        self.fails = 0 if ok else self.fails + 1
        return ok

    def close(self):
        try:
            self.sender.releaseSender()
        except Exception:
            pass


class Hub:
    def __init__(self, spout_name="handoff", spout=True, log=print):
        self.log = log
        self.jpeg = None
        self.seq = 0
        self.width = 0
        self.height = 0
        self.stamp = 0.0
        self.fps = 0.0
        self._n = 0
        self._t0 = time.perf_counter()
        self.cond = asyncio.Condition()
        self.spout_name = spout_name
        self.spout_state = "off"
        self._pending = None
        self._event = threading.Event()
        self._running = True
        self._thread = None
        if spout:
            self._thread = threading.Thread(target=self._spout_loop, daemon=True)
            self._thread.start()

    async def push(self, jpeg, width=0, height=0):
        self.jpeg = jpeg
        self.seq += 1
        if width and height:
            self.width, self.height = width, height
        self.stamp = time.perf_counter()
        self._n += 1
        if self.stamp - self._t0 >= 1:
            self.fps = self._n / (self.stamp - self._t0)
            self._n, self._t0 = 0, self.stamp
        if self._thread:
            self._pending = jpeg
            self._event.set()
        async with self.cond:
            self.cond.notify_all()

    async def wait(self, last, timeout=2.0):
        async with self.cond:
            if self.seq == last:
                try:
                    await asyncio.wait_for(self.cond.wait(), timeout)
                except asyncio.TimeoutError:
                    pass
        return self.seq, self.jpeg

    def idle(self):
        if self.stamp and time.perf_counter() - self.stamp > 2:
            self.fps = 0.0

    def _spout_loop(self):
        if os.name != "nt":
            self.spout_state = "windows only"
            return
        try:
            import cv2
            spout = Spout(self.spout_name)
            self.spout_state = "on"
        except Exception as e:
            self.spout_state = "missing SpoutGL"
            self.log(f"spout is off ({e}), try: pip install SpoutGL")
            return
        while self._running:
            if not self._event.wait(0.5):
                continue
            self._event.clear()
            jpeg = self._pending
            if jpeg is None:
                continue
            img = cv2.imdecode(np.frombuffer(jpeg, np.uint8), cv2.IMREAD_COLOR)
            if img is None:
                continue
            h, w = img.shape[:2]
            rgba = np.empty((h, w, 4), np.uint8)
            rgba[:, :, :3] = img[:, :, ::-1]
            rgba[:, :, 3] = 255
            if not spout.send(rgba) and spout.fails > 60:
                self.spout_state = "failing"
        spout.close()

    def close(self):
        self._running = False
        self._event.set()
        if self._thread:
            self._thread.join(timeout=2)
