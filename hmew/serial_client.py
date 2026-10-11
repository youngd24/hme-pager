"""Send pages to the transmitter over RS-232 using the Scope protocol."""

from __future__ import annotations

import logging
import time
from typing import Callable, Optional

from . import scope, serialport
from .errors import NoReplyError, ValidationError
from .models import (
    PageType,
    SendResult,
    pager_to_capcode,
    validate_base,
    validate_capcode,
)
from .page import Page

log = logging.getLogger("hmew")


class SerialTransmitter:
    """Sends pages over a serial port (HMEW doc section 4.A, Scope format).

    Serial addresses full capcodes. Pages given by pager number need
    ``base`` (the 3-digit base ID, e.g. 87) to work out the capcode. A
    group page is sent as one command per capcode.
    """

    def __init__(
        self,
        device: str,
        base: Optional[int] = None,
        timeout: float = 3.0,
        open_port: Optional[Callable[[str], serialport.Port]] = None,
    ):
        self.device = device
        self.base = None if base is None else validate_base(base)
        self.timeout = timeout
        self._open_port = open_port or serialport.open_port

    def capcode_for(self, pager: int) -> int:
        if self.base is None:
            raise ValidationError(
                "serial sends by capcode: give the base ID to page by "
                "pager number, or give a capcode"
            )
        return validate_capcode(pager_to_capcode(self.base, pager))

    def send(self, page: Page) -> SendResult:
        page.check()
        capcodes = list(page.capcodes) or [
            self.capcode_for(p) for p in page.pagers
        ]
        commands = [
            scope.build_command(page.kind, c, page.msg, page.beep, page.baud)
            for c in capcodes
        ]
        log.debug(
            "%s page to capcode(s) %s via serial %s: %r (beep %d)",
            "alpha" if page.kind is PageType.ALPHA else "numeric",
            ", ".join(f"{c:07d}" for c in capcodes),
            self.device,
            page.msg,
            page.beep,
        )

        sent = 0
        with self._open_port(self.device) as port:
            for capcode, cmd in zip(capcodes, commands):
                port.flush_input()
                log.debug("write %r", cmd)
                started = time.monotonic()
                port.write(cmd)
                reply = self._wait_for_ack(port)
                elapsed = (time.monotonic() - started) * 1000
                if not scope.is_ack(reply):
                    log.debug(
                        "no OK for capcode %07d after %.0f ms; got %r",
                        capcode,
                        elapsed,
                        reply,
                    )
                    raise self._no_reply(capcode, reply, sent, len(capcodes))
                log.debug("reply %r in %.0f ms", reply, elapsed)
                sent += 1
        return SendResult(code="OK", count=sent, raw="OK")

    def _no_reply(
        self, capcode: int, reply: bytes, sent: int, total: int
    ) -> NoReplyError:
        already = f"; {sent} of {total} capcodes were sent before this"
        return NoReplyError(
            f"no OK from the transmitter for capcode {capcode:07d} within "
            f"{self.timeout:.0f} s (got {reply!r}). The unit sends no error "
            "replies; check the cable (straight-through), the port, and that "
            f"the unit's output format is SCOPE{already if sent else ''}",
            sent,
            reply,
        )

    def _wait_for_ack(self, port: serialport.Port) -> bytes:
        buf = b""
        deadline = time.monotonic() + self.timeout
        while not scope.is_ack(buf):
            left = deadline - time.monotonic()
            if left <= 0:
                break
            buf += port.read(min(left, 0.2))
        return buf
