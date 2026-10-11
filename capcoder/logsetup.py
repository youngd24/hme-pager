"""Logging setup and the per-OS data directory.

Everything goes to a rotating file at DEBUG; the console gets INFO (or
DEBUG with -v).
"""

from __future__ import annotations

import logging
import os
import shutil
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Optional

FORMAT = (
    "%(asctime)s.%(msecs)03d %(levelname)-7s %(name)s [%(threadName)s] "
    "%(message)s"
)
DATEFMT = "%Y-%m-%d %H:%M:%S"


def _data_dir(name: str) -> Path:
    if sys.platform == "win32":
        # Not %LOCALAPPDATA%: Microsoft Store Python silently redirects
        # writes there into its package sandbox, so the printed path would
        # never exist.
        return Path.home() / f".{name}"
    if sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support"
    else:
        base = Path(
            os.environ.get("XDG_STATE_HOME")
            or Path.home() / ".local" / "state"
        )
    return base / name


def default_data_dir() -> Path:
    return _data_dir("capcoder")


def migrate_old_data_dir() -> Optional[str]:
    """Move the data directory from the old name (vpager) to the new one, once.

    Returns a note for the log, or None if there was nothing to do.
    """
    old, new = _data_dir("vpager"), default_data_dir()
    if not old.is_dir() or new.exists():
        return None
    try:
        shutil.move(str(old), str(new))
    except OSError as e:
        return (
            f"could not move old data directory {old} to {new}: {e}; "
            "starting fresh"
        )
    return (
        f"moved data directory from {old} to {new} "
        "(vpager was renamed to capcoder)"
    )


def setup_logging(log_file: Path, verbose: bool) -> None:
    log_file.parent.mkdir(parents=True, exist_ok=True)
    fmt = logging.Formatter(FORMAT, DATEFMT)

    file_handler = RotatingFileHandler(
        log_file, maxBytes=5_000_000, backupCount=5, encoding="utf-8"
    )
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(fmt)

    console = logging.StreamHandler()
    console.setLevel(logging.DEBUG if verbose else logging.INFO)
    console.setFormatter(fmt)

    root = logging.getLogger("capcoder")
    root.setLevel(logging.DEBUG)
    root.addHandler(file_handler)
    root.addHandler(console)

    # asyncio reports its own problems (e.g. subprocess errors) on this logger.
    aio = logging.getLogger("asyncio")
    aio.setLevel(logging.WARNING)
    aio.addHandler(file_handler)
