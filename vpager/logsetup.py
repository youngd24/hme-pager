"""Logging: everything at DEBUG to a rotating file, INFO (or DEBUG with -v) to the console."""

from __future__ import annotations

import logging
import os
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

FORMAT = "%(asctime)s.%(msecs)03d %(levelname)-7s %(name)s [%(threadName)s] %(message)s"
DATEFMT = "%Y-%m-%d %H:%M:%S"


def default_data_dir() -> Path:
    if sys.platform == "win32":
        base = Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local")
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support"
    else:
        base = Path(os.environ.get("XDG_STATE_HOME") or Path.home() / ".local" / "state")
    return base / "vpager"


def setup_logging(log_file: Path, verbose: bool) -> None:
    log_file.parent.mkdir(parents=True, exist_ok=True)
    fmt = logging.Formatter(FORMAT, DATEFMT)

    file_handler = RotatingFileHandler(log_file, maxBytes=5_000_000, backupCount=5, encoding="utf-8")
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(fmt)

    console = logging.StreamHandler()
    console.setLevel(logging.DEBUG if verbose else logging.INFO)
    console.setFormatter(fmt)

    root = logging.getLogger("vpager")
    root.setLevel(logging.DEBUG)
    root.addHandler(file_handler)
    root.addHandler(console)

    # asyncio reports its own problems (e.g. subprocess errors) on this logger.
    aio = logging.getLogger("asyncio")
    aio.setLevel(logging.WARNING)
    aio.addHandler(file_handler)
