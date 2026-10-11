"""Enums, validation and capcode helpers. No network code lives here.

Rules come from the HMEW Integration Protocol rev 04/13, section 4.D (HTTP)
and the Scope section (numeric charset and length).
"""

from __future__ import annotations

import enum
import re
from dataclasses import dataclass
from typing import Iterable, List, Union

from .errors import ValidationError

MAX_PAGERS_PER_REQUEST = 9
PAGER_MIN, PAGER_MAX = 1, 999
BEEP_MIN, BEEP_MAX = 1, 4
NUMERIC_MAX_LEN = 20      # stated in the Scope section
ALPHA_MAX_BYTES = 128     # stated in the HTTP section

# Digits, space, hyphen, square brackets, and 'U' (urgent) per the Scope section.
_NUMERIC_RE = re.compile(r"^[0-9 \-\[\]U]*$")


class PageType(enum.IntEnum):
    VIBE_NUMERIC = 1
    ALPHA = 2


class Baud(enum.IntEnum):
    B512 = 0
    B1200 = 1


PagerArg = Union[int, Iterable[int]]


def validate_pagers(pager: PagerArg) -> List[int]:
    items = [pager] if isinstance(pager, int) else list(pager)
    if not items:
        raise ValidationError("at least one pager number is required")
    if len(items) > MAX_PAGERS_PER_REQUEST:
        raise ValidationError(
            f"at most {MAX_PAGERS_PER_REQUEST} pagers per request, got {len(items)}"
        )
    for p in items:
        if isinstance(p, bool) or not isinstance(p, int):
            raise ValidationError(f"pager number must be an int, got {p!r}")
        if not PAGER_MIN <= p <= PAGER_MAX:
            raise ValidationError(
                f"pager number must be {PAGER_MIN}-{PAGER_MAX}, got {p}"
            )
    return items


def validate_beep(beep: int) -> int:
    if isinstance(beep, bool) or not isinstance(beep, int):
        raise ValidationError(f"beep must be an int, got {beep!r}")
    if not BEEP_MIN <= beep <= BEEP_MAX:
        raise ValidationError(f"beep must be {BEEP_MIN}-{BEEP_MAX}, got {beep}")
    return beep


def validate_message(msg: str, page_type: PageType) -> str:
    if not isinstance(msg, str):
        raise ValidationError("message must be a string")
    if page_type is PageType.VIBE_NUMERIC:
        if len(msg) > NUMERIC_MAX_LEN:
            raise ValidationError(
                f"numeric message max {NUMERIC_MAX_LEN} chars, got {len(msg)}"
            )
        if not _NUMERIC_RE.match(msg):
            raise ValidationError(
                "numeric message may only contain digits, space, '-', '[', ']', 'U'"
            )
    else:
        n = len(msg.encode("utf-8"))
        if n > ALPHA_MAX_BYTES:
            raise ValidationError(
                f"alpha message max {ALPHA_MAX_BYTES} bytes, got {n}"
            )
        if not msg.isascii():
            raise ValidationError("alpha message must be ASCII")
    return msg


@dataclass(frozen=True)
class SendResult:
    code: str      # status letter, e.g. "c" for OK
    count: int     # pagers processed
    raw: str       # raw reply, e.g. "!sc1"


def pager_to_capcode(base_id: int, pager: int) -> int:
    """Capcode = base ID (3 digits) followed by pager*8 (4 digits)."""
    return base_id * 10000 + pager * 8


def capcode_to_pager(capcode: Union[int, str]) -> int:
    """Pager number from a capcode, e.g. 874440 -> 555.

    Does not check the base ID; only the last four digits are used.
    """
    value = int(capcode) % 10000
    if value % 8 != 0:
        raise ValidationError(f"capcode {capcode} is not a multiple-of-8 pager address")
    return value // 8
