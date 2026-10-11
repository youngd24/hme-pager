"""Open the pager page in its own window.

Chromium-family browsers (Edge, Chrome, Chromium) have an app mode, --app=URL,
which opens the page in a separate window without tabs or an address bar,
sized and resized on its own. If none is found, fall back to the default
browser, which normally opens a tab.
"""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
import sys
import webbrowser
from pathlib import Path
from typing import Optional

log = logging.getLogger("capcoder.launch")

# Fits the pager plus the status lines under it; the page scales to any size.
WINDOW_SIZE = (880, 760)


def _candidates() -> list[str]:
    if sys.platform == "win32":
        roots = [
            os.environ.get(v)
            for v in ("ProgramFiles(x86)", "ProgramFiles", "LOCALAPPDATA")
        ]
        rel = [
            r"Microsoft\Edge\Application\msedge.exe",
            r"Google\Chrome\Application\chrome.exe",
            r"Chromium\Application\chrome.exe",
        ]
        return [str(Path(root) / r) for r in rel for root in roots if root]
    if sys.platform == "darwin":
        return [
            "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
            "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
            "/Applications/Chromium.app/Contents/MacOS/Chromium",
        ]
    names = (
        "microsoft-edge",
        "microsoft-edge-stable",
        "google-chrome",
        "google-chrome-stable",
        "chromium",
        "chromium-browser",
    )
    return [p for p in (shutil.which(n) for n in names) if p]


def find_app_browser(explicit: Optional[str] = None) -> Optional[str]:
    if explicit:
        return shutil.which(explicit) or (
            explicit if Path(explicit).is_file() else None
        )
    return next((c for c in _candidates() if Path(c).is_file()), None)


def open_ui(url: str, mode: str, browser: Optional[str] = None) -> None:
    """mode: 'window' (app-mode window, else tab), 'tab', or 'none'."""
    if mode == "none":
        return
    if mode == "window":
        exe = find_app_browser(browser)
        if exe:
            w, h = WINDOW_SIZE
            cmd = [exe, f"--app={url}", f"--window-size={w},{h}"]
            try:
                subprocess.Popen(
                    cmd,
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    close_fds=True,
                )
                log.info("opened pager window with %s", exe)
                return
            except OSError as e:
                log.warning(
                    "could not start %s (%s); opening a browser tab instead",
                    exe,
                    e,
                )
        elif browser:
            log.warning(
                "browser %r not found; opening a browser tab instead", browser
            )
        else:
            log.info(
                "no Edge/Chrome/Chromium found for a separate window; "
                "opening a browser tab"
            )
    webbrowser.open(url)
