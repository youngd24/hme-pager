"""A page to send, independent of how it is sent (HTTP or serial)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, Tuple

from .errors import ValidationError
from .models import (
    Baud,
    PageType,
    SendResult,
    validate_beep,
    validate_capcode,
    validate_message,
    validate_pagers,
)


@dataclass(frozen=True)
class Page:
    """Who to page and what to send.

    Give either ``pagers`` (pager numbers 1-999; HTTP adds the transmitter's base ID,
    serial needs a base ID to work out the capcode) or ``capcodes`` (full 7-digit
    capcodes; serial only), not both.
    """

    kind: PageType
    msg: str
    pagers: Tuple[int, ...] = ()
    capcodes: Tuple[int, ...] = ()
    beep: int = 1
    baud: Baud = Baud.B1200

    def check(self) -> "Page":
        if bool(self.pagers) == bool(self.capcodes):
            raise ValidationError("give pager numbers or capcodes (one of them, not both)")
        if self.pagers:
            validate_pagers(list(self.pagers))
        for c in self.capcodes:
            validate_capcode(c)
        validate_beep(self.beep)
        validate_message(self.msg, self.kind)
        Baud(self.baud)
        return self


class Transmitter(Protocol):
    """What HttpTransmitter and SerialTransmitter have in common."""

    def send(self, page: Page) -> SendResult: ...
