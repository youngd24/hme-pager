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
NUMERIC_MAX_LEN = 20  # stated in the Scope section
ALPHA_MAX_BYTES = 128  # stated in the HTTP section

# Digits, space, hyphen, square brackets, and 'U' (urgent), per the Scope
# section.
_NUMERIC_RE = re.compile(r"[0-9 \-\[\]U]")  # one allowed character


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
            f"at most {MAX_PAGERS_PER_REQUEST} pagers per request, "
            f"got {len(items)}"
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
        raise ValidationError(
            f"beep must be {BEEP_MIN}-{BEEP_MAX}, got {beep}"
        )
    return beep


def _describe(chars: Iterable[str]) -> str:
    return ", ".join(repr(c) for c in sorted(set(chars)))


def validate_message(msg: str, page_type: PageType) -> str:
    """Check the message really is numeric or alpha text, per page_type.

    Numeric: only digits, space, '-', '[', ']' and 'U'; at most 20 characters.
    An empty numeric message is allowed (type 1 is also "vibe only"; how the
    unit treats it is unconfirmed).
    Alpha: printable ASCII only (space to '~'; no tabs, newlines or other
    control characters); not empty or all spaces; at most 128 bytes.
    """
    if not isinstance(msg, str):
        raise ValidationError("message must be a string")
    if page_type is PageType.VIBE_NUMERIC:
        bad = [c for c in msg if not _NUMERIC_RE.fullmatch(c)]
        if bad:
            hint = (
                " (send text as alpha)"
                if any(c.isalpha() for c in bad)
                else ""
            )
            raise ValidationError(
                "numeric message may only contain digits, space, "
                f"'-', '[', ']' and 'U'; found {_describe(bad)}{hint}"
            )
        if len(msg) > NUMERIC_MAX_LEN:
            raise ValidationError(
                f"numeric message max {NUMERIC_MAX_LEN} chars, got {len(msg)}"
            )
    else:
        if not msg.strip():
            raise ValidationError("alpha message is empty")
        bad = [c for c in msg if not " " <= c <= "~"]
        if bad:
            raise ValidationError(
                "alpha message may only contain printable ASCII (letters, "
                f"digits, punctuation, space); found {_describe(bad)}"
            )
        n = len(msg.encode("ascii"))
        if n > ALPHA_MAX_BYTES:
            raise ValidationError(
                f"alpha message max {ALPHA_MAX_BYTES} bytes, got {n}"
            )
    return msg


@dataclass(frozen=True)
class SendResult:
    code: str  # status letter, e.g. "c" for OK
    count: int  # pagers processed
    raw: str  # raw reply, e.g. "!sc1"


CAPCODE_MIN, CAPCODE_MAX = 8, 2097143
BASE_MIN, BASE_MAX = 0, 209  # base*10000 + pager*8 must stay a valid capcode
# Capcodes the transmitter rejects, per the protocol doc (Waveware error 03):
# 0-7, 2007664-2007671, 2045056-2045063, 2097144 and up.
_RESERVED_CAPCODES = (range(2007664, 2007672), range(2045056, 2045064))


def validate_capcode(capcode: int) -> int:
    if isinstance(capcode, bool) or not isinstance(capcode, int):
        raise ValidationError(f"capcode must be an int, got {capcode!r}")
    if not CAPCODE_MIN <= capcode <= CAPCODE_MAX or any(
        capcode in r for r in _RESERVED_CAPCODES
    ):
        raise ValidationError(
            f"capcode {capcode:07d} is not valid (the transmitter rejects "
            "0-7, 2007664-2007671, 2045056-2045063 and 2097144 up)"
        )
    return capcode


def validate_base(base: int) -> int:
    if isinstance(base, bool) or not isinstance(base, int):
        raise ValidationError(f"base ID must be an int, got {base!r}")
    if not BASE_MIN <= base <= BASE_MAX:
        raise ValidationError(
            f"base ID must be {BASE_MIN:03d}-{BASE_MAX:03d}, got {base}"
        )
    return base


def pager_to_capcode(base_id: int, pager: int) -> int:
    """Capcode = base ID (3 digits) followed by pager*8 (4 digits)."""
    return base_id * 10000 + pager * 8


def capcode_to_pager(capcode: Union[int, str]) -> int:
    """Pager number from a capcode, e.g. 874440 -> 555.

    Does not check the base ID; only the last four digits are used.
    """
    value = int(capcode) % 10000
    if value % 8 != 0:
        raise ValidationError(
            f"capcode {capcode} is not a multiple-of-8 pager address"
        )
    return value // 8
