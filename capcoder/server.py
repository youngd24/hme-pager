"""Local HTTP server: serves the pager page, pushes events, takes UI actions.

GET  /                -> web/index.html (and other files in web/)
GET  /api/state       -> full state as JSON
GET  /api/events      -> server-sent events: state, page, status, decode
POST /api/action      -> {"action": ..., "id": ..., "value": ...}
POST /api/log         -> {"level": ..., "msg": ...} from the browser, into the log file
POST /api/inject      -> {"line": "<multimon-ng line>"}, loopback clients only
"""

from __future__ import annotations

import ipaddress
import json
import logging
import queue
import socket
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

from .core import Core
from .store import StoreError

log = logging.getLogger("capcoder.http")
ui_log = logging.getLogger("capcoder.ui")

WEB_DIR = Path(__file__).resolve().parent / "web"
MAX_BODY = 64 * 1024
CONTENT_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".svg": "image/svg+xml",
    ".png": "image/png",
    ".ico": "image/x-icon",
}
UI_LEVELS = {"debug": logging.DEBUG, "info": logging.INFO, "warn": logging.WARNING, "error": logging.ERROR}


class PagerServer(ThreadingHTTPServer):
    daemon_threads = True
    block_on_close = False
    # HTTPServer turns on SO_REUSEADDR, which on Windows lets a second process bind a
    # port that is already in use. Off there, plus exclusive use, so a second capcoder
    # fails to start instead of quietly sharing the port.
    allow_reuse_address = sys.platform != "win32"

    def __init__(self, addr, core: Core):
        self.core = core
        super().__init__(addr, Handler)

    def server_bind(self) -> None:
        if sys.platform == "win32":
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        super().server_bind()


class Handler(BaseHTTPRequestHandler):
    server: PagerServer
    server_version = "capcoder"

    def log_message(self, fmt, *args) -> None:
        if "/api/log " in self.requestline:   # the UI line itself is already logged
            return
        log.debug("%s %s", self.client_address[0], fmt % args)

    # ---- GET ----

    def do_GET(self) -> None:
        path = urlsplit(self.path).path
        if path == "/api/state":
            self._json(self.server.core.state())
        elif path == "/api/events":
            self._events()
        else:
            self._static(path)

    def _static(self, path: str) -> None:
        if path == "/":
            path = "/index.html"
        target = (WEB_DIR / path.lstrip("/")).resolve()
        if WEB_DIR not in target.parents or not target.is_file():
            self.send_error(404)
            return
        body = target.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", CONTENT_TYPES.get(target.suffix, "application/octet-stream"))
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _events(self) -> None:
        core = self.server.core
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        q = core.hub.subscribe()
        who = self.client_address[0]
        log.info("browser connected from %s", who)
        try:
            self._send_event("state", json.dumps(core.state()))
            while core.hub.is_subscribed(q):
                try:
                    event, payload = q.get(timeout=15)
                except queue.Empty:
                    self.wfile.write(b": ping\n\n")
                    self.wfile.flush()
                    continue
                self._send_event(event, payload)
        except OSError:
            pass
        finally:
            core.hub.unsubscribe(q)
            log.info("browser disconnected from %s", who)

    def _send_event(self, event: str, payload: str) -> None:
        self.wfile.write(f"event: {event}\ndata: {payload}\n\n".encode("utf-8"))
        self.wfile.flush()

    # ---- POST ----

    def do_POST(self) -> None:
        path = urlsplit(self.path).path
        body = self._read_json()
        if body is None:
            return
        core = self.server.core
        if path == "/api/action":
            action = body.get("action")
            try:
                core.store.apply(action, body.get("id"), body.get("value"))
            except StoreError as e:
                log.info("action %s id=%s refused: %s", action, body.get("id"), e)
                self._json({"ok": False, "error": str(e), "state": core.state()})
                return
            log.info("action %s id=%s value=%r", action, body.get("id"), body.get("value"))
            core.publish_state()
            self._json({"ok": True, "state": core.state()})
        elif path == "/api/log":
            level = UI_LEVELS.get(str(body.get("level", "info")).lower(), logging.INFO)
            ui_log.log(level, "%s", str(body.get("msg", ""))[:2000])
            self._json({"ok": True})
        elif path == "/api/inject":
            if not ipaddress.ip_address(self.client_address[0]).is_loopback:
                self.send_error(403, "inject is only allowed from this machine")
                return
            line = str(body.get("line", ""))
            result = core.handle_line(line, "inject")
            self._json({"ok": True, "result": result})
        else:
            self.send_error(404)

    def _read_json(self):
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            length = -1
        if not 0 <= length <= MAX_BODY:
            self.send_error(400, "bad body length")
            return None
        try:
            data = json.loads(self.rfile.read(length) or b"{}")
        except ValueError:
            self.send_error(400, "body is not JSON")
            return None
        if not isinstance(data, dict):
            self.send_error(400, "body must be a JSON object")
            return None
        return data

    def _json(self, data) -> None:
        body = json.dumps(data).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)
