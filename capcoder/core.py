"""Glue between the receiver, the message store and the browser.

Every decoded line goes through Core.handle_line, which logs it, applies the
capcode filter and duplicate suppression, stores matches and pushes them to
connected browsers through the Hub.
"""

from __future__ import annotations

import json
import logging
import queue
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from . import __version__
from .decode import parse_line
from .store import MAX_LOCKED, MAX_PERSONAL, MAX_SLOTS, Store

log = logging.getLogger("capcoder.core")
decode_log = logging.getLogger("capcoder.decode")


class Hub:
    """Fan-out of server-sent events to every connected browser."""

    def __init__(self) -> None:
        self._subs: set[queue.Queue] = set()
        self._lock = threading.Lock()

    def subscribe(self) -> queue.Queue:
        q: queue.Queue = queue.Queue(maxsize=200)
        with self._lock:
            self._subs.add(q)
        return q

    def unsubscribe(self, q: queue.Queue) -> None:
        with self._lock:
            self._subs.discard(q)

    def is_subscribed(self, q: queue.Queue) -> bool:
        with self._lock:
            return q in self._subs

    def publish(self, event: str, data: Any) -> None:
        payload = json.dumps(data)
        with self._lock:
            subs = list(self._subs)
        for q in subs:
            try:
                q.put_nowait((event, payload))
            except queue.Full:
                log.warning("browser is not keeping up, dropping its connection")
                self.unsubscribe(q)


class Core:
    def __init__(self, store: Store, hub: Hub, dedupe_seconds: float, log_file: Optional[Path]):
        self.store = store
        self.hub = hub
        self.dedupe_seconds = dedupe_seconds
        self.log_file = log_file
        self.status: dict[str, Any] = {
            "udp": "starting", "udp_port": None, "sender": None,
            "decoder": "starting", "packets": 0,
        }
        self.last_decode: Optional[dict] = None
        self._lock = threading.Lock()
        self._seen: dict[tuple, float] = {}

    def state(self) -> dict:
        snap = self.store.snapshot()
        with self._lock:
            snap["status"] = dict(self.status)
            snap["last_decode"] = self.last_decode
        snap["log_file"] = str(self.log_file) if self.log_file else None
        snap["limits"] = {"slots": MAX_SLOTS, "locked": MAX_LOCKED, "personal": MAX_PERSONAL}
        snap["version"] = __version__
        return snap

    def set_status(self, publish: bool = True, **changes: Any) -> None:
        with self._lock:
            changed = {k: v for k, v in changes.items() if self.status.get(k) != v}
            self.status.update(changes)
            status = dict(self.status)
        if changed and publish:
            self.hub.publish("status", status)

    def publish_state(self) -> None:
        self.hub.publish("state", self.state())

    def handle_line(self, line: str, source: str) -> str:
        """Process one line of multimon-ng output. Returns what happened, for the log and inject."""
        decode_log.info("%s: %s", source, line)
        page = parse_line(line)
        if page is None:
            decode_log.debug("not a POCSAG page line, ignored")
            return "not a page"

        capcode = self.store.capcode
        now = time.monotonic()
        with self._lock:
            if capcode is None:
                verdict = "ignored: no capcode set"
            elif page.capcode != capcode:
                verdict = "ignored: other capcode"
            elif not self.store.power:
                verdict = "ignored: pager is off"
            else:
                key = (page.capcode, page.function, page.text)
                last = self._seen.get(key)
                self._seen[key] = now
                # Forget old entries so the table can't grow forever.
                self._seen = {k: t for k, t in self._seen.items() if now - t < max(self.dedupe_seconds, 1)}
                if last is not None and now - last < self.dedupe_seconds:
                    verdict = "ignored: duplicate"
                else:
                    verdict = "stored"
            self.last_decode = {
                "time": datetime.now().astimezone().isoformat(timespec="seconds"),
                "capcode": page.capcode, "function": page.function,
                "kind": page.kind, "text": page.text, "verdict": verdict,
            }
            last_decode = dict(self.last_decode)

        decode_log.info(
            "page capcode=%d function=%d kind=%s text=%r -> %s",
            page.capcode, page.function, page.kind, page.text, verdict,
        )
        self.hub.publish("decode", last_decode)
        if verdict != "stored":
            return verdict

        msg = self.store.add(page, datetime.now().astimezone())
        log.info("new message id=%d for capcode %d: %r", msg["id"], page.capcode, page.text)
        self.hub.publish("page", {"message": msg, "state": self.state()})
        return verdict
