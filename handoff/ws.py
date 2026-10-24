import asyncio
import base64
import hashlib
import struct

GUID = b"258EAFA5-E914-47DA-95CA-C5AB0DC85B11"
TEXT, BINARY, CLOSE, PING, PONG = 1, 2, 8, 9, 10
MAX = 16 * 1024 * 1024


class Closed(Exception):
    pass


def accept_key(key):
    return base64.b64encode(hashlib.sha1(key.encode() + GUID).digest()).decode()


async def upgrade(writer, headers):
    key = headers.get("sec-websocket-key", "")
    if not key or "websocket" not in headers.get("upgrade", "").lower():
        return False
    writer.write(
        b"HTTP/1.1 101 Switching Protocols\r\n"
        b"Upgrade: websocket\r\nConnection: Upgrade\r\n"
        b"Sec-WebSocket-Accept: " + accept_key(key).encode() + b"\r\n\r\n"
    )
    await writer.drain()
    return True


class Socket:
    def __init__(self, reader, writer):
        self.reader = reader
        self.writer = writer
        self.lock = asyncio.Lock()
        self.closed = False

    async def _frame(self):
        head = await self.reader.readexactly(2)
        fin = head[0] & 0x80
        op = head[0] & 0x0F
        masked = head[1] & 0x80
        n = head[1] & 0x7F
        if n == 126:
            n = struct.unpack(">H", await self.reader.readexactly(2))[0]
        elif n == 127:
            n = struct.unpack(">Q", await self.reader.readexactly(8))[0]
        if n > MAX:
            raise Closed("frame too big")
        mask = await self.reader.readexactly(4) if masked else None
        data = await self.reader.readexactly(n) if n else b""
        if mask:
            data = unmask(data, mask)
        return fin, op, data

    async def recv(self):
        parts, kind = [], None
        while True:
            try:
                fin, op, data = await self._frame()
            except (asyncio.IncompleteReadError, ConnectionError, OSError):
                self.closed = True
                raise Closed("gone")
            if op == PING:
                await self._send(PONG, data)
                continue
            if op == PONG:
                continue
            if op == CLOSE:
                try:
                    await self._send(CLOSE, data[:2])
                except Exception:
                    pass
                self.closed = True
                raise Closed("closed")
            if op in (TEXT, BINARY):
                kind = op
                parts = [data]
            else:
                parts.append(data)
            if fin:
                msg = b"".join(parts)
                return (msg.decode("utf-8", "replace") if kind == TEXT else msg)

    async def _send(self, op, data):
        n = len(data)
        if n < 126:
            head = struct.pack(">BB", 0x80 | op, n)
        elif n < 65536:
            head = struct.pack(">BBH", 0x80 | op, 126, n)
        else:
            head = struct.pack(">BBQ", 0x80 | op, 127, n)
        async with self.lock:
            self.writer.write(head + data)
            await self.writer.drain()

    async def send(self, msg):
        if self.closed:
            return
        try:
            if isinstance(msg, str):
                await self._send(TEXT, msg.encode())
            else:
                await self._send(BINARY, bytes(msg))
        except (ConnectionError, OSError):
            self.closed = True

    async def close(self, code=1000):
        if not self.closed:
            try:
                await self._send(CLOSE, struct.pack(">H", code))
            except Exception:
                pass
        self.closed = True
        try:
            self.writer.close()
        except Exception:
            pass


def unmask(data, mask):
    n = len(data)
    key = (mask * (n // 4 + 1))[:n]
    return (int.from_bytes(data, "little") ^ int.from_bytes(key, "little")).to_bytes(n, "little")
