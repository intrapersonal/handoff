import argparse
import asyncio
import ssl
import sys
import webbrowser

from . import __version__, qr
from .certs import context
from .net import data_dir, lan_ips


def parse(argv=None):
    ap = argparse.ArgumentParser(prog="handoff", description="use your phone as a camera for touchdesigner")
    ap.add_argument("--version", action="version", version=f"handoff {__version__}")
    ap.add_argument("--port", type=int, default=7420, help="port the phone connects to")
    ap.add_argument("--local-port", type=int, default=7421, help="mjpeg + status page on this pc")
    ap.add_argument("--bind", default="0.0.0.0")
    ap.add_argument("--osc-host", default="127.0.0.1")
    ap.add_argument("--osc-port", type=int, default=7410)
    ap.add_argument("--spout-name", default="handoff")
    ap.add_argument("--no-spout", action="store_true")
    ap.add_argument("--no-hands", action="store_true", help="don't run wintd hand tracking on the phone")
    ap.add_argument("--track", default="hands", help="wintd streams to run, like hands,face,pose")
    ap.add_argument("--wintd-port", type=int, default=7400)
    ap.add_argument("--res", type=int, default=720, choices=(360, 480, 720, 1080))
    ap.add_argument("--fps", type=int, default=30)
    ap.add_argument("--quality", type=float, default=0.75)
    ap.add_argument("--mirror", action="store_true")
    ap.add_argument("--rotate", type=int, default=0, choices=(0, 90, 180, 270))
    ap.add_argument("--ip", default="", help="force the address put in the qr code")
    ap.add_argument("--data-dir", default="")
    ap.add_argument("--open", action="store_true", help="open the status page with the qr code")
    ap.add_argument("--quiet", action="store_true")
    return ap.parse_args(argv)


def quiet_ssl(loop, ctx):
    exc = ctx.get("exception")
    if isinstance(exc, (ssl.SSLError, ConnectionError, OSError)):
        return
    loop.default_exception_handler(ctx)


def main(argv=None):
    a = parse(argv)
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    ips = lan_ips()
    if a.ip:
        ips = [a.ip] + [i for i in ips if i != a.ip]
    folder = data_dir(a.data_dir)
    ctx = context(folder, ips)
    cfg = {
        "port": a.port, "local_port": a.local_port, "bind": a.bind, "osc_host": a.osc_host,
        "osc_port": a.osc_port, "spout_name": a.spout_name, "spout": not a.no_spout, "res": a.res,
        "fps": max(1, min(60, a.fps)), "quality": max(0.3, min(0.95, a.quality)), "mirror": a.mirror,
        "rotate": a.rotate, "live": not a.quiet, "hands": not a.no_hands, "hands_streams": a.track,
        "wintd_port": a.wintd_port, "data_dir": folder,
    }
    from .server import Server
    srv = Server(cfg, ctx, ips)
    print(f"\nhandoff {__version__}\n")
    if not ips:
        print("couldn't find this pc on a network. is wifi or ethernet connected?\n")
    print(qr.terminal(srv.url))
    print(f"\nscan that with your phone, or open {srv.url}")
    for u in srv.status()["urls"][1:]:
        print(f"  also try {u}")
    print("your phone will warn about the certificate the first time, that's normal, go past it")
    print(f"\nspout   {a.spout_name}" + ("  (off)" if a.no_spout else ""))
    print(f"osc     {a.osc_host}:{a.osc_port}")
    print(f"mjpeg   {srv.local}/stream.mjpg")
    if a.no_hands:
        print("hands   off")
    elif srv.hands:
        print(f"hands   wintd ({a.track}) on osc {a.wintd_port}, starts when the phone does")
    else:
        print("hands   install wintd in touchdesigner once and this turns on by itself")
    print(f"status  {srv.local}\n")
    if a.open:
        webbrowser.open(srv.local)
    loop = asyncio.new_event_loop()
    loop.set_exception_handler(quiet_ssl)
    try:
        loop.run_until_complete(srv.run())
    except KeyboardInterrupt:
        print("\nbye")
    except OSError as e:
        print(f"\ncouldn't start: {e}. is handoff already running?")
    finally:
        srv.close()
        loop.close()


if __name__ == "__main__":
    main(sys.argv[1:])
