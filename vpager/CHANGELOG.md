# vpager changelog

## 0.1 (2026-10-10), git tag `v0.1`

This is the first release. On 2026-10-10 it received a real over-the-air page from the iStation (pager 1, capcode 870008, `5551212`) and displayed it.

- Listens for raw UDP audio on port 8888 (the SDR++ network sink) and decodes it with multimon-ng. The pipeline is adapted from mmng-ui.
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
