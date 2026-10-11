# hme-pager

Python client for the HME Wireless (HMEW) iStation paging transmitter, HTTP interface. Stdlib only, no pip dependencies, so it runs on a FreePBX box as-is.

Goal: let a FreePBX IVR (or any script) send **numeric** pages to the transmitter. Planned hook-up is a Python AGI script that imports this package instead of using Asterisk's `CURL()`.

## Hardware and environment

- Transmitter: JTECH/HME iStation (HME Wireless Computer Controlled Paging System), POCSAG at 457.5750 MHz (HME's standard US frequency), 1200 baud default.
- Transmitter IP on the lab network: 192.168.42.66, port 80 (from the user's curl tests; confirm before hard-coding).
- Reception/verification rig: RTL-SDR on Windows 10 (Zadig/WinUSB, SDR++, `rtl_fm` piped to `multimon-ng`). Decode command that works:
  `rtl_fm -f 457.5750M -s 22050 -g 30 - | multimon-ng -t raw -a POCSAG1200 -f alpha -`
  Keep the dongle on a long USB cable, away from the transmitter, or the front end overloads.
- Dev machine: Windows, repo at `C:\Users\youngd\src\hme-pager`. Target runtime: FreePBX (Linux, system Python 3).

## Reference

HMEW Integration Protocol rev 04/13: https://incompetel.net/stuff/I-station/HMEW%20Integration%20Protocol%20rev04_13.pdf (section 4.D is the HTTP interface; the Scope section covers numeric charset and length limits).

### HTTP API (from the doc)

```
http://<IP>/send_page.php?pager=<PGR>&type=<TYPE>&msg=<CHAR>&baud=<BAUD>&beep=<BEEP>
```

| Param | Meaning |
|---|---|
| `pager` | 1-999; up to 9 joined with `+` (e.g. `1+2+3`) |
| `type` | 1 = vibe only and numeric, 2 = alphanumeric (doc says 2 should be default) |
| `msg` | up to 128 bytes |
| `baud` | 0 = 512, 1 = 1200 (default 1) |
| `beep` | 1-4, beep type / vibration pattern, only on certain pager styles (default 1) |

Replies: `!s<code><n>`
- `!sc<n>` n pagers processed OK
- `!sd0` bad parameter label, `!se0` bad parameter value, `!sf0` unsupported .php page, `!sh0` good URL but no pager number
- `!sg<n>` internal queue full, unable to accept, but processed n

Capcode = 3-digit base ID + (pager number x 8) as 4 digits. Examples seen on air: 870024 = base 087, pager 3; 874440 = pager 555; 875328 = pager 666; 877104 = pager 888.

Numeric pages: digits, space, `-`, `[`, `]`, and `U` (urgent); max 20 characters. These two limits are stated in the Scope (serial) section, not the HTTP section, so the HTTP path may be more permissive. We use the stricter limits.

Network setup on the unit: SETUP, password 1173 for IP/port; SETUP, password 9731 for output format (SCOPE/HME recommended for the TCP/serial interface). Do not use ports 21, 23, 80, 99 for the listen port.

## Design (implemented in `hmew_pager/`)

```
hmew_pager/
  __init__.py   exports PagerClient, parse_reply, PageType, Baud, SendResult,
                capcode_to_pager, pager_to_capcode, and the exceptions
  errors.py     PagerError base; ValidationError, TransmitterUnreachable,
                UnexpectedReply, PageRejected, QueueFull
  models.py     enums, validation, SendResult, capcode helpers (no network)
  client.py     PagerClient, parse_reply
```

Public API:

```python
c = PagerClient("192.168.42.66", timeout=3.0)
c.send_numeric(pager=3, msg="555-1212")           # -> SendResult(code="c", count=1, raw="!sc1")
c.send_alpha(pager=3, msg="hello")
c.send_numeric(pager=[1, 2, 3], msg="42", beep=2)  # group page
```

`host` is optional; if omitted, `PagerClient()` reads it from the `HMEWHOST` environment variable. Raises `ValidationError` if neither is given.

Decisions:
- **Validate before sending.** Bad input raises `ValidationError` locally so a typo in the IVR can't become a stray page.
- **Reply handling.** `!sc` returns `SendResult`. `!sd/!se/!sf/!sh` raise `PageRejected` (request was built wrong, not retryable). `!sg` raises `QueueFull`. Anything else raises `UnexpectedReply` with the raw text. Network failures raise `TransmitterUnreachable`.
- **Queue-full retries.** Retry with exponential backoff only when `processed == 0`. If some pagers were accepted, raise `QueueFull` with `.processed` set, because resending the whole request would page those pagers twice.
- **Serialized sends.** A `threading.Lock` around each request, since the doc describes a small input buffer and concurrent behavior is unknown.
- **URL building.** `pager` is built by hand so the `+` separator isn't escaped; everything else goes through `urllib.parse.urlencode`.

## Status

- Package written and smoke-tested against a local fake HTTP server (URL shape, every reply code, retry rules, validation, unreachable host, capcode helpers). **Not yet tested against the real iStation.**
- Not written yet: `cli.py` (`python -m hmew_pager send --pager 3 --msg 555-1212`), a proper `tests/` folder (the smoke test was a throwaway script; port it to unittest/pytest with a fake HTTP server), the FreePBX AGI wrapper, packaging.

## Open questions (test on the real unit)

- How `beep` 1-4 maps to the POCSAG function bits. Observed: keypad pages decoded as Function 0, curl pages with `beep=1` decoded as Function 1. The doc doesn't say. Send `beep=2,3,4` and watch the Function value in multimon-ng.
- Whether the unit needs a pause between back-to-back requests.
- Behavior for pager numbers the unit hasn't seen (doc says no pager database is needed).
- Which numeric characters the HTTP path really accepts beyond the Scope-section list.
- Address-only lines in the decoder output (no Alpha) are probably tone-only pages, unconfirmed.

## FreePBX plan

Interim approach (works today): a custom dialplan context in `/etc/asterisk/extensions_custom.conf` that `Read()`s the pager number and digits, regex-checks they are digits only, then calls `CURL()` against `send_page.php` with `type=1` and checks for `!sc1`. Requires `func_curl`. Hooked in through Admin > Custom Destinations (`ivr-numeric-page,s,1`). Restrict access (e.g. `Authenticate()` or internal extensions only), since anyone reaching the IVR can page.

Target approach: replace `CURL()` with a Python AGI script that imports this package, for better validation, retries and logging.

## vpager (virtual pager, `vpager/`)

Receive side: a Motorola Advisor-style pager in the browser that answers to one capcode. Stdlib only.

- Audio in: raw UDP on 8888 (same SDR++ network-sink stream mmng-ui takes), piped into multimon-ng. multimon-ng is found on PATH, then in `C:\rtl-sdr` on Windows (`receiver.EXTRA_DIRS`; v1.3.1 there works). Uses mmng-ui's multimon-ng flags minus `-u`, which caused problems for the user. `receiver.py` is adapted from mmng-ui (GPL-3.0, attribution in the file header).
- `decode.py` parses multimon-ng POCSAG lines; `core.py` does capcode filter + duplicate suppression and pushes server-sent events; `store.py` holds memory per the Advisor manual (`refdocs/advisor_inst.pdf`): 19 slots, 10 locked, Personal Message File of 10.
- `web/` is the pager face (canvas 5x7 dot-matrix LCD, 4x20) and the button state machine.
- Log: everything at DEBUG to `<data-dir>/vpager.log` (rotating), including every multimon-ng line, filter verdicts, UDP start/stop, and browser key presses/errors via `/api/log`. Data dir defaults to `%USERPROFILE%\.vpager` on Windows, deliberately not `%LOCALAPPDATA%`: the user's Python is the Microsoft Store build, which silently redirects AppData writes into its package sandbox (`%LOCALAPPDATA%\Packages\PythonSoftwareFoundation.Python.3.13_*\LocalCache\Local\...`).
- Run: `python -m vpager --capcode 870024` (or `--base 87 --pager 3`). Test without radio: `python -m vpager inject "555-1212"`. Tests: `python -m unittest tests.test_vpager`.
- Unconfirmed: whether `-f alpha` (mmng-ui's default, kept here) mangles HME numeric (type=1) pages; try `--decode-mode auto` or `standard` if they look wrong. Which Advisor button is Read vs Function is a guess (yellow = Read, red = Function).

## Conventions

- Python 3, standard library only. No third-party runtime dependencies.
- Don't state guesses about the transmitter's behavior as facts; mark anything not from the doc or an observation as unconfirmed.
- Never send test pages to real customer pagers; use the lab unit and known test capcodes.
