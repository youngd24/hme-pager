"""HTTP client for the HMEW iStation send_page.php interface."""

from __future__ import annotations

import os
import re
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Optional

from .errors import (
    PageRejected,
    QueueFull,
    TransmitterUnreachable,
    UnexpectedReply,
    ValidationError,
)
from .models import (
    Baud,
    PageType,
    PagerArg,
    SendResult,
    validate_beep,
    validate_message,
    validate_pagers,
)

_REPLY_RE = re.compile(r"!s([a-z])(\d+)")


def parse_reply(raw: str) -> SendResult:
    """Parse a reply such as ``!sc1``; raise a PagerError subclass on failure."""
    m = _REPLY_RE.fullmatch(raw.strip())
    if not m:
        raise UnexpectedReply(raw)
    code, count = m.group(1), int(m.group(2))
    if code == "c":
        return SendResult(code=code, count=count, raw=raw.strip())
    if code == "g":
        raise QueueFull(count, raw.strip())
    if code in PageRejected.MEANINGS:
        raise PageRejected(code, raw.strip())
    raise UnexpectedReply(raw)


class PagerClient:
    def __init__(
        self,
        host: Optional[str] = None,
        port: int = 80,
        timeout: float = 3.0,
        retries: int = 3,
        backoff: float = 0.5,
    ):
        host = host or os.environ.get("HMEWHOST")
        if not host:
            raise ValidationError("no host given (set HMEWHOST or pass host=)")
        self.host = host
        self.port = port
        self.timeout = timeout
        self.retries = retries
        self.backoff = backoff
        self._lock = threading.Lock()  # serialize requests to the transmitter

    # -- public API ---------------------------------------------------------

    def send_numeric(
        self, pager: PagerArg, msg: str, beep: int = 1, baud: Baud = Baud.B1200
    ) -> SendResult:
        return self._send(pager, PageType.VIBE_NUMERIC, msg, baud, beep)

    def send_alpha(
        self, pager: PagerArg, msg: str, beep: int = 1, baud: Baud = Baud.B1200
    ) -> SendResult:
        return self._send(pager, PageType.ALPHA, msg, baud, beep)

    # -- internals ----------------------------------------------------------

    def build_url(
        self, pagers: list, page_type: PageType, msg: str, baud: Baud, beep: int
    ) -> str:
        # '+' separates pager numbers per the doc, so it must not be escaped.
        pager_str = "+".join(str(p) for p in pagers)
        rest = urllib.parse.urlencode(
            {
                "type": int(page_type),
                "msg": msg,
                "baud": int(baud),
                "beep": beep,
            }
        )
        netloc = self.host if self.port == 80 else f"{self.host}:{self.port}"
        return f"http://{netloc}/send_page.php?pager={pager_str}&{rest}"

    def _send(
        self, pager: PagerArg, page_type: PageType, msg: str, baud: Baud, beep: int
    ) -> SendResult:
        pagers = validate_pagers(pager)
        validate_beep(beep)
        validate_message(msg, page_type)
        url = self.build_url(pagers, page_type, msg, Baud(baud), beep)

        last_full: Optional[QueueFull] = None
        for attempt in range(self.retries + 1):
            try:
                with self._lock:
                    raw = self._get(url)
                return parse_reply(raw)
            except QueueFull as exc:
                # Retrying resends the whole request, which would re-page any
                # pagers already accepted. Only retry when nothing was accepted.
                if exc.processed > 0:
                    raise
                last_full = exc
                if attempt < self.retries:
                    time.sleep(self.backoff * (2 ** attempt))
        assert last_full is not None
        raise last_full

    def _get(self, url: str) -> str:
        try:
            with urllib.request.urlopen(url, timeout=self.timeout) as resp:
                return resp.read().decode("ascii", errors="replace")
        except (urllib.error.URLError, OSError, TimeoutError) as exc:
            raise TransmitterUnreachable(
                f"cannot reach transmitter at {self.host}:{self.port}: {exc}"
            ) from exc
