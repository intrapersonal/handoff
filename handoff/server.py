import asyncio
import json
import struct
import sys
import time
from pathlib import Path

from . import __version__, qr
from .hands import Hands
from .hub import Hub
from .sensors import Sensors
from .ws import Closed, Socket, upgrade

WEB = Path(__file__).parent / "web"
TYPES = {
    ".html": "text/html; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".svg": "image/svg+xml",
    ".png": "image/png",
    ".webmanifest": "application/manifest+json",
}
STATIC = {"/": "index.html", "/index.html": "index.html", "/app.js": "app.js", "/style.css": "style.css",
          "/icon.svg": "icon.svg", "/manifest.webmanifest": "manifest.webmanifest"}
HEADER = struct.Struct(">IHH")


async def read_request(reader):
    try:
        line = await asyncio.wait_for(reader.readline(), 15)
    except (asyncio.TimeoutError, ConnectionError, OSError):
        return None
    parts = line.decode("latin-1").split()
    if len(parts) < 2:
        return None
    headers = {}
    while True:
        h = await reader.readline()
        if h in (b"\r\n", b"\n", b""):
            break
        k, _, v = h.decode("latin-1").partition(":")
        headers[k.strip().lower()] = v.strip()
        if len(headers) > 100:
            return None
    path = parts[1].split("?", 1)[0]
    return parts[0].upper(), path, headers


def respond(writer, status, body=b"", ctype="text/plain; charset=utf-8", extra=""):
    if isinstance(body, str):
        body = body.encode()
    writer.write(
        f"HTTP/1.1 {status}\r\nContent-Type: {ctype}\r\nContent-Length: {len(body)}\r\n"
        f"Cache-Control: no-store\r\nConnection: close\r\n{extra}\r\n".encode() + body
    )


class Server:
    def __init__(self, cfg, ssl_ctx, ips, log=print):
        self.cfg = cfg
        self.ssl = ssl_ctx
        self.ips = ips
        self.log = log
        self.hub = Hub(cfg["spout_name"], spout=cfg["spout"], log=log)
        self.sensors = Sensors(cfg["osc_host"], cfg["osc_port"])
        self.phone = None
        self.phone_info = {}
        self.rtt = 0.0
        self.front = False
        self.started = time.time()
        self.hands = None
        if cfg.get("hands"):
            h = Hands(f"http://127.0.0.1:{cfg['local_port']}/stream.mjpg", cfg.get("hands_streams", "hands"),
                      cfg.get("wintd_port", 7400), cfg.get("data_dir"), log)
            self.hands = h if h.available() else None

    @property
    def url(self):
        host = self.ips[0] if self.ips else "127.0.0.1"
        return f"https://{host}:{self.cfg['port']}"

    @property
    def local(self):
        return f"http://127.0.0.1:{self.cfg['local_port']}"

    def status(self):
        return {
            "version": __version__,
            "url": self.url,
            "urls": [f"https://{ip}:{self.cfg['port']}" for ip in self.ips],
            "connected": self.phone is not None,
            "phone": self.phone_info.get("name", ""),
            "fps": round(self.hub.fps, 1),
            "width": self.hub.width,
            "height": self.hub.height,
            "rtt": round(self.rtt, 1),
            "spout": self.hub.spout_state,
            "spout_name": self.cfg["spout_name"],
            "osc": f"{self.cfg['osc_host']}:{self.cfg['osc_port']}",
            "mjpeg": self.local + "/stream.mjpg",
            "hands": self.hands.state if self.hands else "off",
        }

    async def phone_conn(self, reader, writer):
        try:
            req = await read_request(reader)
            if not req:
                writer.close()
                return
            method, path, headers = req
            if path == "/ws":
                if await upgrade(writer, headers):
                    await self.session(Socket(reader, writer))
                else:
                    respond(writer, "400 Bad Request", "websocket only")
            elif method == "GET" and path in STATIC:
                f = WEB / STATIC[path]
                respond(writer, "200 OK", f.read_bytes(), TYPES.get(f.suffix, "application/octet-stream"))
            else:
                respond(writer, "404 Not Found", "nothing here")
            await writer.drain()
        except (ConnectionError, OSError, asyncio.IncompleteReadError):
            pass
        finally:
            try:
                writer.close()
            except Exception:
                pass

    async def session(self, sock):
        old = self.phone
        self.phone = sock
        if old is not None:
            await old.send(json.dumps({"t": "kick"}))
            await old.close()
        await sock.send(json.dumps({
            "t": "hi", "v": __version__, "fps": self.cfg["fps"], "res": self.cfg["res"],
            "quality": self.cfg["quality"], "mirror": self.cfg["mirror"], "rotate": self.cfg["rotate"],
        }))
        self.sensors.connected(True)
        try:
            while True:
                msg = await sock.recv()
                if isinstance(msg, bytes):
                    if len(msg) <= HEADER.size:
                        continue
                    seq, w, h = HEADER.unpack_from(msg)
                    await self.hub.push(msg[HEADER.size:], w, h)
                    await sock.send('{"t":"ack","n":%d}' % seq)
                    continue
                try:
                    m = json.loads(msg)
                except ValueError:
                    continue
                t = m.get("t")
                if t == "s":
                    self.sensors.update(m)
                elif t == "hello":
                    self.phone_info = {"name": str(m.get("name", "phone"))[:60]}
                    self.log(f"phone connected: {self.phone_info['name']}")
                elif t == "stat":
                    try:
                        self.rtt = float(m.get("rtt", 0))
                    except (TypeError, ValueError):
                        pass
                    self.front = bool(m.get("front"))
                elif t == "ping":
                    await sock.send(json.dumps({"t": "pong", "c": m.get("c")}))
        except Closed:
            pass
        finally:
            if self.phone is sock:
                self.phone = None
                self.phone_info = {}
                self.sensors.connected(False)
                self.log("phone disconnected")

    async def local_conn(self, reader, writer):
        try:
            req = await read_request(reader)
            if not req:
                return
            method, path, headers = req
            if path == "/stream.mjpg":
                await self.mjpeg(writer)
                return
            if path == "/frame.jpg":
                if self.hub.jpeg:
                    respond(writer, "200 OK", self.hub.jpeg, "image/jpeg")
                else:
                    respond(writer, "503 Service Unavailable", "no phone yet")
            elif path == "/status.json":
                respond(writer, "200 OK", json.dumps(self.status()), "application/json")
            elif path == "/qr.svg":
                respond(writer, "200 OK", qr.svg(self.url), "image/svg+xml")
            elif path in ("/", "/index.html"):
                page = (WEB / "local.html").read_text(encoding="utf-8")
                page = page.replace("{{qr}}", qr.svg(self.url, fg="#0b0f0d", bg="#efeae0")).replace("{{url}}", self.url)
                respond(writer, "200 OK", page, "text/html; charset=utf-8")
            else:
                respond(writer, "404 Not Found", "nothing here")
            await writer.drain()
        except (ConnectionError, OSError, asyncio.IncompleteReadError):
            pass
        finally:
            try:
                writer.close()
            except Exception:
                pass

    async def mjpeg(self, writer):
        writer.write(
            b"HTTP/1.1 200 OK\r\nContent-Type: multipart/x-mixed-replace; boundary=frame\r\n"
            b"Cache-Control: no-store\r\nConnection: close\r\n\r\n"
        )
        last = -1
        while True:
            seq, jpeg = await self.hub.wait(last)
            if seq == last or jpeg is None:
                continue
            last = seq
            writer.write(b"--frame\r\nContent-Type: image/jpeg\r\nContent-Length: %d\r\n\r\n" % len(jpeg) + jpeg + b"\r\n")
            await writer.drain()

    async def ticker(self):
        step = 1 / 60
        n = 0
        while True:
            self.hub.idle()
            self.sensors.video(self.hub.fps, self.hub.width, self.hub.height, self.rtt, self.front)
            self.sensors.tick()
            n += 1
            if self.hands and n % 15 == 0:
                self.hands.tick(self.phone is not None and self.hub.fps > 0, self.front)
            if n % 60 == 0 and self.cfg["live"] and sys.stdout.isatty():
                s = self.status()
                line = (f"live  {s['width']}x{s['height']}  {s['fps']:.0f} fps  {s['rtt']:.0f} ms"
                        if s["connected"] else "waiting for a phone...")
                sys.stdout.write("\r" + line.ljust(60))
                sys.stdout.flush()
            await asyncio.sleep(step)

    async def run(self):
        phone = await asyncio.start_server(self.phone_conn, self.cfg["bind"], self.cfg["port"], ssl=self.ssl)
        local = await asyncio.start_server(self.local_conn, "127.0.0.1", self.cfg["local_port"])
        async with phone, local:
            await asyncio.gather(phone.serve_forever(), local.serve_forever(), self.ticker())

    def close(self):
        if self.hands:
            self.hands.stop()
        self.hub.close()
        self.sensors.close()
