"""Parse multimon-ng POCSAG text output into Page objects.

Handles lines like:
    POCSAG1200: Address:  870024  Function: 1  Alpha:   555-1212<NUL>
    POCSAG1200: Address:  870024  Function: 0  Numeric: 555-1212
    POCSAG1200: Address:  870024  Function: 1
with or without the date prefix multimon-ng adds for --timestamp.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional

_LINE_RE = re.compile(
    r"(?P<protocol>POCSAG(?:512|1200|2400)):\s*Address:\s*(?P<address>\d+)"
    r"\s+Function:\s*(?P<function>\d)"
    r"(?:\s+(?P<kind>Alpha|Numeric|Skyper):\s?(?P<text>.*?))?\s*$"
)
# multimon-ng shows control characters as <NUL>, <ETX>, <EOT> and so on.
_CTRL_RE = re.compile(r"<[A-Za-z]{3}>")


@dataclass(frozen=True)
class Page:
    capcode: int
    function: int
    kind: str       # "alpha", "numeric" or "tone" (address only, no text)
    text: str
    protocol: str   # e.g. "POCSAG1200"


def parse_line(line: str) -> Optional[Page]:
    """Return a Page for a POCSAG decode line, or None for anything else."""
    m = _LINE_RE.search(line.rstrip("\r\n"))
    if not m:
        return None
    text = m.group("text") or ""
    # The US charset maps [ and ] to these; same fix-up mmng-ui does.
    text = _CTRL_RE.sub("", text).replace("Ä", "[").replace("Ü", "]").strip()
    kind = (m.group("kind") or "").lower()
    if kind == "skyper":
        kind = "alpha"
    if not text:
        kind = "tone"
    return Page(
        capcode=int(m.group("address")),
        function=int(m.group("function")),
        kind=kind,
        text=text,
        protocol=m.group("protocol"),
    )
