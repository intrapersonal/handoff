import os
import socket
import subprocess
import sys
import time
from pathlib import Path

NO_WINDOW = 0x08000000 if os.name == "nt" else 0


def wintd_root():
    env = os.environ.get("WINTD_HOME")
    if env:
        return Path(env)
    if os.name == "nt":
        return Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local")) / "wintd"
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "wintd"
    return Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share")) / "wintd"


def wintd_python(root):
    return root / ("python/python.exe" if os.name == "nt" else "venv/bin/python")


class Hands:
    def __init__(self, stream_url, streams="hands", port=7400, log_dir=None, log=print):
        self.url = stream_url
        self.streams = streams
        self.port = port
        self.log = log
        self.root = wintd_root()
        self.python = wintd_python(self.root)
        self.log_path = (log_dir or self.root) / "handoff-wintd.log"
        self.proc = None
        self.out = None
        self.mirror = None
        self.lost_at = 0.0
        self.live_since = 0.0
        self.next_try = 0.0
        self.state = "off"

    def available(self):
        return self.python.exists() and (self.root / "pkg" / "wintd").exists()

    def running(self):
        return self.proc is not None and self.proc.poll() is None

    def start(self, mirror):
        self.stop()
        env = dict(os.environ)
        env.pop("PYTHONHOME", None)
        env["PYTHONPATH"] = str(self.root / "pkg")
        env["WINTD_HOME"] = str(self.root)
        cmd = [
            str(self.python), "-m", "wintd",
            "--video-file", self.url,
            "--streams", self.streams,
            "--port", str(self.port),
            "--parent", str(os.getpid()),
        ]
        if not mirror:
            cmd.append("--no-mirror")
        try:
            self.out = open(self.log_path, "w")
            self.proc = subprocess.Popen(cmd, cwd=str(self.root), env=env, stdout=self.out,
                                         stderr=subprocess.STDOUT, creationflags=NO_WINDOW)
        except OSError as e:
            self.log(f"couldn't start wintd: {e}")
            self.proc = None
            self.state = "failed"
            return
        self.mirror = mirror
        self.state = "on"
        self.log("hand tracking on (wintd)")

    def stop(self):
        if self.proc is not None:
            try:
                if self.proc.poll() is None:
                    q = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                    q.sendto(b"/quit\0\0\0,\0\0\0", ("127.0.0.1", self.port + 9))
                    q.close()
                self.proc.wait(timeout=3)
            except Exception:
                try:
                    self.proc.kill()
                except Exception:
                    pass
            self.proc = None
        if self.out:
            self.out.close()
            self.out = None
        if self.state == "on":
            self.state = "waiting"

    def tick(self, live, front):
        now = time.monotonic()
        if not live:
            self.live_since = 0.0
            if self.running() and self.lost_at and now - self.lost_at > 3:
                self.stop()
            if not self.lost_at:
                self.lost_at = now
            return
        self.lost_at = 0.0
        if not self.live_since:
            self.live_since = now
        if now - self.live_since < 1.5:
            return
        if self.running():
            if self.mirror != front:
                self.start(front)
            return
        if self.proc is not None:
            self.log(f"wintd stopped, restarting it (log: {self.log_path})")
            self.stop()
            self.next_try = now + 2
        if now >= self.next_try:
            self.next_try = now + 5
            self.start(front)
