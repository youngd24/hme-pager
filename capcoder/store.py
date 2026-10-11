"""Message memory and settings, saved to a JSON file.

Limits follow the Motorola Advisor manual: 19 regular message locations, up to
10 locked messages, and a Personal Message File (location 20) holding up to 10.
"""

from __future__ import annotations

import json
import logging
import os
import threading
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from .decode import Page

log = logging.getLogger("capcoder.store")

MAX_SLOTS = 19
MAX_LOCKED = 10
MAX_PERSONAL = 10
MAX_CAPCODE = 2_097_151   # POCSAG addresses are 21 bits

AUDIBLE_ALERTS = ("escalert", "loud_long", "loud_short", "soft_long", "soft_short", "chirp", "none")
SILENT_ALERTS = ("chirp_vibrate", "vibrate", "none")

DEFAULT_SETTINGS = {
    "speaker": "audible",        # audible | silent
    "audible_alert": "loud_short",
    "silent_alert": "vibrate",
    "alarm_enabled": False,
    "alarm_hour": 7,
    "alarm_minute": 0,
}


class StoreError(Exception):
    """An action the pager refuses, e.g. lock memory full. The text is shown on the LCD."""


def parse_capcode(value: Any) -> int:
    try:
        capcode = int(value)
    except (TypeError, ValueError):
        raise StoreError("BAD CAPCODE") from None
    if not 1 <= capcode <= MAX_CAPCODE:
        raise StoreError("BAD CAPCODE")
    return capcode


class Store:
    def __init__(self, path: Optional[Path]):
        self.path = path
        self._lock = threading.RLock()
        self.capcode: Optional[int] = None
        self.power = True
        self.settings = dict(DEFAULT_SETTINGS)
        self.messages: list[dict] = []
        self._next_id = 1
        if path is not None and path.exists():
            self._load()

    def _load(self) -> None:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as e:
            log.error("could not read %s, starting empty: %s", self.path, e)
            return
        self.capcode = data.get("capcode")
        self.power = bool(data.get("power", True))
        saved = data.get("settings", {})
        self.settings.update({k: v for k, v in saved.items() if k in DEFAULT_SETTINGS})
        self.messages = list(data.get("messages", []))
        self._next_id = max((m["id"] for m in self.messages), default=0) + 1
        log.info("loaded %d messages from %s", len(self.messages), self.path)

    def _save(self) -> None:
        if self.path is None:
            return
        data = {
            "capcode": self.capcode,
            "power": self.power,
            "settings": self.settings,
            "messages": self.messages,
        }
        tmp = self.path.with_suffix(".tmp")
        try:
            tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
            os.replace(tmp, self.path)
        except OSError as e:
            log.error("could not save %s: %s", self.path, e)

    def snapshot(self) -> dict:
        with self._lock:
            return {
                "capcode": self.capcode,
                "power": self.power,
                "settings": dict(self.settings),
                "messages": [dict(m) for m in self.messages],
            }

    def add(self, page: Page, received: datetime) -> dict:
        """Store a page. When the 19 regular locations are full, the oldest unlocked one goes."""
        with self._lock:
            msg = {
                "id": self._next_id,
                "capcode": page.capcode,
                "function": page.function,
                "kind": page.kind,
                "text": page.text,
                "received": received.isoformat(timespec="seconds"),
                "read": False,
                "locked": False,
                "personal": False,
            }
            self._next_id += 1
            self.messages.append(msg)
            regular = [m for m in self.messages if not m["personal"]]
            while len(regular) > MAX_SLOTS:
                victim = next((m for m in regular if not m["locked"]), None)
                if victim is None:
                    break
                self.messages.remove(victim)
                regular.remove(victim)
                log.info("memory full, dropped oldest message id=%d text=%r", victim["id"], victim["text"])
            self._save()
            return dict(msg)

    def apply(self, action: str, msg_id: Any = None, value: Any = None) -> None:
        """Run a UI action. Raises StoreError (with LCD-ready text) if refused."""
        with self._lock:
            if action == "power":
                self.power = bool(value)
            elif action == "capcode":
                self.capcode = parse_capcode(value)
            elif action == "settings":
                self._update_settings(value)
            elif action in ("read", "delete", "lock", "unlock", "file"):
                msg = self._find(msg_id)
                if action == "read":
                    msg["read"] = True
                elif action == "delete":
                    self.messages.remove(msg)
                elif action == "lock":
                    if not msg["locked"] and sum(m["locked"] for m in self.messages) >= MAX_LOCKED:
                        raise StoreError("LOCK FULL")
                    msg["locked"] = True
                elif action == "unlock":
                    msg["locked"] = False
                elif action == "file":
                    if msg["personal"]:
                        raise StoreError("ALREADY FILED")
                    if sum(m["personal"] for m in self.messages) >= MAX_PERSONAL:
                        raise StoreError("FILE FULL")
                    msg["personal"] = True
            else:
                raise StoreError("UNKNOWN ACTION")
            self._save()

    def _find(self, msg_id: Any) -> dict:
        for m in self.messages:
            if m["id"] == msg_id:
                return m
        raise StoreError("NO SUCH MESSAGE")

    def _update_settings(self, patch: Any) -> None:
        if not isinstance(patch, dict):
            raise StoreError("BAD SETTINGS")
        new = dict(self.settings)
        for key, val in patch.items():
            if key not in DEFAULT_SETTINGS:
                raise StoreError("BAD SETTINGS")
            new[key] = val
        ok = (
            new["speaker"] in ("audible", "silent")
            and new["audible_alert"] in AUDIBLE_ALERTS
            and new["silent_alert"] in SILENT_ALERTS
            and isinstance(new["alarm_enabled"], bool)
            and isinstance(new["alarm_hour"], int) and 0 <= new["alarm_hour"] <= 23
            and isinstance(new["alarm_minute"], int) and 0 <= new["alarm_minute"] <= 59
        )
        if not ok:
            raise StoreError("BAD SETTINGS")
        self.settings = new
