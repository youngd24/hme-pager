# Mockorola Capcoder changelog

## 0.3 (2026-10-11), git tag `v0.3`

- No changes to Capcoder. The version follows the repo release, which was about the sender (see the top-level [CHANGELOG](../CHANGELOG.md)).

## 0.2 (2026-10-11), git tag `v0.2`

- **Renamed vpager to Mockorola Capcoder.**
  - The package and command are now `capcoder` (`python -m capcoder`).
  - The case badge reads MOCKOROLA / CAPCODER.
  - The log file is now `capcoder.log` and the logger names start with `capcoder.`.
  - The data directory is now `~/.capcoder` (Windows) or `capcoder` (macOS/Linux). An existing vpager data directory is moved there on first run.
  - Tests moved to `tests/test_capcoder.py`.
- The pager now opens in its own resizable window by default, using Edge/Chrome/Chromium app mode, rather than a tab in an existing browser window. `--tab` restores the old behavior, and `--browser PATH` picks the browser.
- If the UDP audio port is busy, Capcoder now retries every 5 s and takes the port once it is free. Before, it logged an error once and never received audio. While it waits, the status line shows `port N in use, retrying`.
- Only one copy can run per port on Windows. Both ports are opened for exclusive use. A second copy on the same HTTP port now exits with "Is Capcoder already running?" instead of quietly sharing the port.
- Windows let a dual-stack listener open a UDP port that another program held on IPv4 only, and IPv4 audio would then go to that program. Capcoder now checks the IPv4 side first and counts the port as busy.
- Docs: the audio input is described as `rtl_fm` piped into netcat (SDR++ isn't used), with a section on sending audio from a separate RTL-SDR machine. The interface's tooltips and disconnect message no longer use em dashes.

## 0.1 (2026-10-10), git tag `v0.1`

This is the first release, under the old name **vpager**; names and paths below are as they were then. On 2026-10-10 it received a real over-the-air page from the iStation (pager 1, capcode 870008, `5551212`) and displayed it.

- Listens for raw UDP audio on port 8888 (e.g. `rtl_fm` piped into netcat) and decodes it with multimon-ng. The pipeline is adapted from mmng-ui.
- Answers to one capcode, set with `--capcode`, with `--base`/`--pager`, or from the pager's menu. Every other decode is logged and ignored. An identical page within 10 s is dropped as a duplicate.
- The Motorola Advisor-style face runs in the browser:
  - a 4×20 dot-matrix LCD
  - Read, Function, the arrow pad and On/Reset, behaving as the Advisor manual describes
  - the Function menu: speaker, alerts, clock, alarm and capcode
  - lock, delete, and the Personal Message File
  - backlight, vibrate, alert lamp, and the reminder beep for unread messages
- Message memory follows the Advisor's limits: 19 locations, 10 locked messages, and a Personal Message File of 10. It is saved in `state.json`.
- A rotating DEBUG log records every decode with its verdict, receiver events, UI actions and browser errors.
- `python -m vpager inject` sends test pages without a radio. Unit tests are in `tests/test_vpager.py`.
- multimon-ng is found on PATH, then in `C:\rtl-sdr` on Windows. It runs with `-f alpha` and without `-u`. Tested with multimon-ng 1.3.0 and 1.6.0.
- The Windows data directory is `%USERPROFILE%\.vpager`. It avoids `%LOCALAPPDATA%` because the Microsoft Store build of Python redirects writes there.
