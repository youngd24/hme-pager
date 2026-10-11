"""Scope serial protocol (HMEW Integration Protocol, section 4.A). Bytes only; no I/O.

A command is: type, 'F' for 1200 baud, 7-digit capcode, beep letter, message, CR.

    AF0870008ATest page\\r     alpha page to capcode 0870008, beep A
    NF0870008A5551212\\r       numeric page

The transmitter answers OK<CR><LF> when it takes a command (observed; the doc
doesn't specify) and never sends an error reply. It says OK for any valid
capcode, even one no pager uses. Anything other than OK in time counts as failure.
"""

from __future__ import annotations

from .models import (
    Baud,
    PageType,
    validate_beep,
    validate_capcode,
    validate_message,
)

BEEP_LETTERS = "ABCD"     # beep 1-4, as in the HTTP interface
ACK = b"OK"


def build_command(kind: PageType, capcode: int, msg: str, beep: int = 1,
                  baud: Baud = Baud.B1200) -> bytes:
    validate_capcode(capcode)
    validate_message(msg, kind)   # also rules out a CR inside the message
    validate_beep(beep)
    ptype = "A" if kind is PageType.ALPHA else "N"
    # The doc says to put F after the type for 1200 baud; without it the unit
    # uses its pre-programmed rate.
    rate = "F" if Baud(baud) is Baud.B1200 else ""
    return f"{ptype}{rate}{capcode:07d}{BEEP_LETTERS[beep - 1]}{msg}\r".encode("ascii")


def is_ack(reply: bytes) -> bool:
    return ACK in reply
