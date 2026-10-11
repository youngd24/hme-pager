"""Command line.

    python -m vpager --capcode 870024            run the pager (opens its own browser window)
    python -m vpager --base 87 --pager 3         same capcode, from base ID + pager number
    python -m vpager inject "555-1212"           send a fake decode to the running pager
    python -m vpager inject --line "POCSAG1200: Address:  870024  Function: 1  Alpha:   HI"
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

from . import __version__
from .core import Core, Hub
from .launch import open_ui
from .logsetup import default_data_dir, setup_logging
from .receiver import DECODE_MODES, Receiver, multimon_args
from .server import PagerServer
from .store import Store, StoreError

log = logging.getLogger("vpager")

DEFAULT_HTTP_PORT = 8073
DEFAULT_UDP_PORT = 8888


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="python -m vpager", description="Virtual Motorola Advisor-style pager.")
    p.add_argument("--version", action="version", version=__version__)
    sub = p.add_subparsers(dest="cmd")

    cap = p.add_argument_group("capcode (overrides the one saved from last run)")
    cap.add_argument("--capcode", type=int, help="POCSAG address to answer to, e.g. 870024")
    cap.add_argument("--base", type=int, help="HME base ID, e.g. 87 (use with --pager)")
    cap.add_argument("--pager", type=int, help="HME pager number, e.g. 3 (use with --base)")

    net = p.add_argument_group("network")
    net.add_argument("--udp-port", type=int, default=DEFAULT_UDP_PORT, help="UDP port for raw audio (default 8888)")
    net.add_argument("--udp-bind", default="::", help="address to listen on for audio (default all, IPv4+IPv6)")
    net.add_argument("--http-host", default="127.0.0.1",
                     help="address for the pager page (default 127.0.0.1; 0.0.0.0 to view from other machines)")
    net.add_argument("--http-port", type=int, default=DEFAULT_HTTP_PORT, help="port for the pager page (default 8073)")

    dec = p.add_argument_group("decoder")
    dec.add_argument("--mmng", default="multimon-ng", help="multimon-ng binary (default: found on PATH)")
    dec.add_argument("--decode-mode", choices=DECODE_MODES, default="alpha",
                     help="multimon-ng -f mode (default alpha, as in mmng-ui; 'standard' omits -f)")
    dec.add_argument("--charset", default="US", help="multimon-ng -C charset (default US)")
    dec.add_argument("--mmng-args", help="replace all multimon-ng arguments (space separated)")
    dec.add_argument("--no-receiver", action="store_true", help="don't listen for audio; inject only")
    dec.add_argument("--dedupe", type=float, default=10.0,
                     help="ignore an identical page within this many seconds (default 10, 0 = off)")

    misc = p.add_argument_group("files and UI")
    misc.add_argument("--data-dir", type=Path, help=f"where state and logs go (default {default_data_dir()})")
    misc.add_argument("--log-file", type=Path, help="log file (default <data-dir>/vpager.log)")
    misc.add_argument("--tab", action="store_true",
                      help="open the pager in a normal browser tab instead of its own window")
    misc.add_argument("--browser", help="Edge/Chrome/Chromium binary for the pager window (default: found)")
    misc.add_argument("--no-browser", action="store_true", help="don't open a browser")
    misc.add_argument("-v", "--verbose", action="store_true", help="show debug messages on the console too")

    inj = sub.add_parser("inject", help="send a fake decode to a running vpager")
    inj.add_argument("text", nargs="?", default="", help="message text")
    inj.add_argument("--line", help="raw multimon-ng line to inject instead")
    inj.add_argument("--capcode", type=int, dest="inject_capcode",
                     help="address to page (default: the pager's own capcode)")
    inj.add_argument("--function", type=int, default=1, choices=range(4), help="POCSAG function bits (default 1)")
    inj.add_argument("--numeric", action="store_true", help="send as a Numeric decode instead of Alpha")
    inj.add_argument("--port", type=int, default=DEFAULT_HTTP_PORT, help="vpager HTTP port (default 8073)")
    return p


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    if args.cmd == "inject":
        return cmd_inject(args)
    return cmd_run(args)


def _log_uncaught(exc_type, exc, tb) -> None:
    log.critical("uncaught exception", exc_info=(exc_type, exc, tb))


def cmd_run(args) -> int:
    data_dir = args.data_dir or default_data_dir()
    data_dir.mkdir(parents=True, exist_ok=True)
    log_file = args.log_file or data_dir / "vpager.log"
    setup_logging(log_file, args.verbose)
    sys.excepthook = _log_uncaught
    threading.excepthook = lambda a: _log_uncaught(a.exc_type, a.exc_value, a.exc_traceback)
    log.info("vpager %s starting (Python %s on %s)", __version__, sys.version.split()[0], sys.platform)
    log.info("log file: %s", log_file)
    log.info("state file: %s", data_dir / "state.json")

    store = Store(data_dir / "state.json")
    try:
        if args.capcode is not None:
            store.apply("capcode", value=args.capcode)
        elif args.pager is not None or args.base is not None:
            if args.pager is None or args.base is None:
                log.error("--base and --pager must be used together")
                return 2
            from hmew_pager.models import pager_to_capcode
            store.apply("capcode", value=pager_to_capcode(args.base, args.pager))
    except StoreError as e:
        log.error("bad capcode: %s", e)
        return 2
    if store.capcode is None:
        log.warning("no capcode set; pages will be logged but not shown. Use --capcode or the pager's menu.")
    else:
        log.info("answering to capcode %d", store.capcode)

    core = Core(store, Hub(), args.dedupe, log_file)

    try:
        server = PagerServer((args.http_host, args.http_port), core)
    except OSError as e:
        log.error(
            "cannot serve the pager page on %s:%d: %s. Is vpager already running? "
            "Stop the other copy, or give this one different ports (--http-port, --udp-port).",
            args.http_host, args.http_port, e,
        )
        return 1
    threading.Thread(target=server.serve_forever, name="http", daemon=True).start()
    host = "127.0.0.1" if args.http_host in ("0.0.0.0", "::", "") else args.http_host
    url = f"http://{host}:{args.http_port}/"
    log.info("pager page: %s", url)

    receiver = None
    if args.no_receiver:
        log.info("receiver disabled (--no-receiver)")
        core.set_status(udp="disabled", decoder="disabled")
    else:
        mmng = args.mmng_args.split() if args.mmng_args else multimon_args(args.decode_mode, args.charset)
        receiver = Receiver(core, args.udp_port, args.udp_bind, args.mmng, mmng)
        receiver.start()

    open_ui(url, "none" if args.no_browser else "tab" if args.tab else "window", args.browser)

    try:
        while True:
            time.sleep(0.5)
    except KeyboardInterrupt:
        log.info("stopping (Ctrl+C)")
    finally:
        if receiver is not None:
            receiver.stop()
        server.shutdown()
        server.server_close()
        log.info("stopped")
    return 0


def _http(url: str, body=None):
    data = None if body is None else json.dumps(body).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=5) as resp:
        return json.loads(resp.read())


def cmd_inject(args) -> int:
    base = f"http://127.0.0.1:{args.port}"
    try:
        if args.line:
            line = args.line
        else:
            capcode = args.inject_capcode
            if capcode is None:
                capcode = _http(base + "/api/state")["capcode"]
                if capcode is None:
                    print("the pager has no capcode set; pass --capcode", file=sys.stderr)
                    return 2
            kind = "Numeric" if args.numeric else "Alpha"
            line = f"POCSAG1200: Address: {capcode:>7}  Function: {args.function}  {kind}:   {args.text}"
        result = _http(base + "/api/inject", {"line": line})
    except (urllib.error.URLError, OSError) as e:
        print(f"could not reach vpager on port {args.port}: {e}", file=sys.stderr)
        return 1
    print(f"{line}\n-> {result.get('result')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
