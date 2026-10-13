# hme-pager

Python client for the HME Wireless (HMEW) iStation paging transmitter, over its HTTP interface or RS-232 (Scope protocol). Stdlib only, no pip dependencies, so it runs on a FreePBX box as-is (exception: serial on Windows uses pyserial if installed; Linux serial is stdlib termios).

Goal: let a FreePBX IVR (or any script) send **numeric** pages to the transmitter. Planned hook-up is a Python AGI script that imports this package instead of using Asterisk's `CURL()`.

## Hardware and environment

- Transmitter: JTECH/HME iStation, model **ISTATION-N**, firmware reporting `PVer: 2.48 RVer: 003` (HME Wireless Computer Controlled Paging System), POCSAG at 457.5750 MHz (HME's standard US frequency), 1200 baud default. Everything in this repo was built and tested against that unit.
- Serial cable: straight-through RS-232 (not null-modem), DB9 male at the transmitter end; the transmitter's port is DB9 female. Connected to the user's Linux box (`/dev/ttyS0`). The sending user must be in the `dialout` group on Ubuntu/Debian (`sudo usermod -aG dialout $USER`, then log in again); `PosixPort` adds that hint to a "Permission denied" error.
- Systems tested: Ubuntu 24.04 (Linux, incl. the serial box) and Windows 11 (dev machine, Capcoder, HTTP sending). The Windows serial path (pyserial) has never been run against the transmitter.
- Transmitter IP on the lab network: 192.168.42.66, port 80 (from the user's curl tests; confirm before hard-coding).
- Reception/verification rig: RTL-SDR on Windows 10 (Zadig/WinUSB, `rtl_fm` piped to `multimon-ng`, or to `nc` to feed Capcoder over UDP). Decode command that works:
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

### Serial (Scope protocol, doc section 4.A)

- RS-232 9600 8N1, no flow control. Command: type (`A`/`N`), `F` (1200 baud; always send it, per the doc and the user), 7-digit capcode, beep letter `A`-`D` (= beep 1-4), message, CR. E.g. `AF0870008ATest page\r`.
- Observed on the user's Linux box (netsrv26, `/dev/ttyS0`): the unit answers `OK\r\n` and nothing else, ever. 2026-10-11: it also answered `OK` for capcode 0870001 (valid POCSAG, not a multiple of 8, no pager has it), so it accepts any valid capcode. The capcodes it rejects per the doc are blocked locally before sending. So the only failure serial can detect is "no OK within the timeout" (`NoReplyError`, 3 s), and in practice that means cable/port/output-format problems, not a bad capcode. (The user's earlier "blank for a bad capcode" note was before this test.)
- Serial addresses full capcodes (HTTP takes pager numbers and adds the unit's base ID). Group pages = one command per capcode.
- HTTP and serial are active on the unit at the same time.
- Numeric pages over serial encode on air the same way as HTTP ones (user observed via Capcoder).
- Serial alpha limit kept at 128 like HTTP, by the user's choice (doc allows 512-2000 depending on firmware).

Network setup on the unit: SETUP, password 1173 for IP/port; SETUP, password 9731 for output format (SCOPE/HME recommended for the TCP/serial interface). Do not use ports 21, 23, 80, 99 for the listen port.

## Design (implemented in `hmew/`)

```
hmew/
  __init__.py       exports HttpTransmitter, SerialTransmitter, PagerClient (= HttpTransmitter),
                    Page, Transmitter, PageType, Baud, SendResult, capcode helpers, exceptions
  errors.py         PagerError base; ValidationError, TransmitterUnreachableError, TransmitterHTTPError,
                    UnexpectedReplyError, PageRejectedError, QueueFullError, NoReplyError (serial)
  models.py         enums, message/pager/beep/capcode/base checks, SendResult, capcode helpers
  page.py           Page (kind, msg, pagers or capcodes, beep, baud) and the Transmitter protocol
  http_client.py    HttpTransmitter (was client.py / PagerClient), parse_reply
  scope.py          Scope command bytes + ACK check; no I/O
  serialport.py     open_port(): PosixPort (termios, flock exclusive lock, 10 s wait) or PySerialPort
  serial_client.py  SerialTransmitter: capcodes (or pagers + base), one command per capcode, wait for OK
  config.py         load() ~/.hme-pager/config (INI, [pager] section) -> Settings; ConfigError
```

Public API (package renamed from `hmew_pager` to `hmew`). Both transmitters have `send(page) -> SendResult`:

```python
from hmew import HttpTransmitter, SerialTransmitter, Page, PageType
page = Page(PageType.ALPHA, "hello", pagers=(3,))
HttpTransmitter("192.168.42.66").send(page)                 # SendResult(code="c", count=1, raw="!sc1")
SerialTransmitter("/dev/ttyS0", base=87).send(page)         # SendResult(code="OK", count=1, raw="OK")
SerialTransmitter("/dev/ttyS0").send(Page(PageType.ALPHA, "hi", capcodes=(870008,)))
# Older calls still work: PagerClient("...").send_numeric(pager=3, msg="555-1212")
```

`HttpTransmitter` with `capcodes` raises `ValidationError` (HTTP can't address a capcode). `SerialTransmitter` with `pagers` needs `base`. `HttpTransmitter(host)` requires the host; no environment variables are read anywhere (removed for 0.3, by the user's request).

Decisions:
- **Validate before sending.** Bad input raises `ValidationError` locally so a typo in the IVR can't become a stray page.
- **Reply handling.** `!sc` returns `SendResult`. `!sd/!se/!sf/!sh` raise `PageRejectedError` (request was built wrong, not retryable). `!sg` raises `QueueFullError`. Anything else raises `UnexpectedReplyError` with the raw text (reply parsing stays strict on purpose: the unit's PHP is rough, and the user prefers not to loosen it). An HTTP error status (404, 500, ...) raises `TransmitterHTTPError` (the unit answered); only no answer at all raises `TransmitterUnreachableError`.
- **Logging.** `hmew` logs to the `hmew` logger at DEBUG (page summary, request URL, reply with HTTP status and time, queue-full retries) and is silent unless the app configures logging. `pager.py -v` sends it to stderr. No log file for the sender (user's choice).
- **Not doing:** beep/baud/group options in `pager.py` (the user says the transmitter and pagers don't need more than the defaults). Cross-process locking for HTTP is deferred to the FreePBX work; serial already has it (exclusive `flock` on the device, second sender waits up to 10 s).
- **Queue-full retries.** Retry with exponential backoff only when `processed == 0`. If some pagers were accepted, raise `QueueFullError` with `.processed` set, because resending the whole request would page those pagers twice.
- **Serialized sends.** A `threading.Lock` around each request, since the doc describes a small input buffer and concurrent behavior is unknown.
- **URL building.** `pager` is built by hand so the `+` separator isn't escaped; everything else goes through `urllib.parse.urlencode` with `quote_via=quote`, so spaces become `%20`. The default `+` for spaces went out on air as literal `+` signs (seen on Capcoder 2026-10-11): the unit's PHP doesn't decode `+` as a space. Confirmed on the real unit 2026-10-11: with `%20`, spaces arrive as spaces.

## Status

- HTTP sending works against the real iStation (pages received on Capcoder). Serial: `pager.py -s /dev/ttyS0` works against the real unit (2026-10-11, netsrv26: `AF0870008ASerial test\r` -> `OK` in 34 ms), on top of tests with fake ports and a Linux pty.
- Command line: `pager.py` at the repo root. `python pager.py [-a | -n] (-p N | -c CAPCODE) [-m MODE | -h HOST[:PORT] | -s DEVICE] [--base NNN] [-v | -q] [--config FILE] message...`. With a config, `pager.py -p 1 Test page` is enough. Precedence: command line > config file > nothing. `-a`/`-n` override `type`; `-h`/`-s` give the address and imply the mode; `-m network|serial` switches mode using the config's `host`/`serial_port` (at most one of `-m`/`-h`/`-s`); `--base` overrides `base`; `-v`/`-q` override `verbose`. `-p`/`-c` exactly one. `-c` is serial only; `-p` over serial needs a base ID. `-h` is host, so help is `--help` only. The message is the only positional (words joined with single spaces). Config errors and the message are checked before anything is sent; exit 2 for usage/config/validation errors, 1 for transmitter/network errors (including serial `NoReplyError`). Missing settings give errors naming the config path to set them in.
- Config file (0.3): `~/.hme-pager/config`, INI, `[pager]` section, keys `mode` (network|serial), `host` (host[:port]), `serial_port`, `base` (digits, 000-209), `type` (alpha|numeric), `verbose` (true|false, default false). `base` wasn't in the user's list but replaces `HMEWBASE` so serial `-p` doesn't need `--base` every time. Unknown keys/sections and bad values are errors (catch typos). Missing default file = no defaults; missing `--config FILE` = error. Template: `config.example` at the repo root. For FreePBX, the asterisk user's home differs, so use `--config` or put the file in that user's `~/.hme-pager/`. Tests patch `hmew.config.DEFAULT_PATH` so they never read the real file.
- Message checks (`models.validate_message`): numeric = only digits, space, `-`, `[`, `]`, `U`, max 20 (empty allowed: type 1 is also "vibe only"); alpha = printable ASCII only (no control chars), not empty/all spaces, max 128 bytes. Errors name the offending characters.
- Tests: `tests/test_hmew.py` (message checks + HTTP CLI against a fake transmitter on 127.0.0.1); `tests/test_hmew_serial.py` (Scope bytes, capcode rules, SerialTransmitter and serial CLI with a fake port; `PosixPortTests` use a pty and are skipped on Windows; run them in WSL: `wsl -d Ubuntu --cd /mnt/c/Users/youngd/src/hme-pager -- python3 -m unittest tests.test_hmew_serial`); `tests/test_hmew_config.py` (loader, precedence, `--config`, `-q`).
- Not written yet: the FreePBX AGI wrapper (set aside for later), packaging.

## Open questions (test on the real unit)

- How `beep` 1-4 maps to the POCSAG function bits. Observed: keypad pages decoded as Function 0, curl pages with `beep=1` decoded as Function 1. The doc doesn't say. Send `beep=2,3,4` and watch the Function value in multimon-ng.
- Whether the unit needs a pause between back-to-back requests.
- Behavior for pager numbers the unit hasn't seen (doc says no pager database is needed).
- Which numeric characters the HTTP path really accepts beyond the Scope-section list.
- Address-only lines in the decoder output (no Alpha) are probably tone-only pages, unconfirmed.

## FreePBX plan

Interim approach (works today): a custom dialplan context in `/etc/asterisk/extensions_custom.conf` that `Read()`s the pager number and digits, regex-checks they are digits only, then calls `CURL()` against `send_page.php` with `type=1` and checks for `!sc1`. Requires `func_curl`. Hooked in through Admin > Custom Destinations (`ivr-numeric-page,s,1`). Restrict access (e.g. `Authenticate()` or internal extensions only), since anyone reaching the IVR can page.

Target approach: replace `CURL()` with a Python AGI script that imports this package, for better validation, retries and logging.

## Mockorola Capcoder (virtual pager, `capcoder/`, formerly vpager)

Receive side: a Motorola Advisor-style pager in the browser that answers to one capcode. Stdlib only. Version 0.1 (tag `v0.1`, 2026-10-10): first real over-the-air page received and shown (released as "vpager"; renamed to Mockorola Capcoder after). Badge: MOCKOROLA / CAPCODER, a parody, so no Motorola name or logo on the case. Tags are repo-wide (`v0.1` 2026-10-10; `v0.2`, `v0.3` and `v0.4` 2026-10-11; `v0.4.1` 2026-10-12). `capcoder.cmd` in the repo root launches Capcoder on Windows: `capcoder.cmd [CAPCODE]`, default 870008 (pager 1). `freepbx/` holds the user's FreePBX IVR guide (`README.md`) and prompt WAV files, committed by the user. `hmepager` (repo root, committed by the user) is a pass-through wrapper: `python3 /usr/local/hme-pager/pager.py "$@"`.

- Audio in: raw UDP on 8888, sent by `rtl_fm ... | nc -u <host> 8888` from the RTL-SDR machine (the same raw-audio input mmng-ui takes), piped into multimon-ng. SDR++ is not used anywhere in this project. multimon-ng is found on PATH, then in `C:\rtl-sdr` on Windows (`receiver.EXTRA_DIRS`). Uses mmng-ui's multimon-ng flags (POCSAG only) minus `-u`. `C:\rtl-sdr` holds `multimon-ng.exe` (reports 1.3.0) and `multimon-ng_1.61.exe` (reports 1.6.0); the bare-name lookup finds only the former, so use `--mmng` for 1.6.0 unless it's renamed. `-u` was tried with both builds; the user found the output messier with it (stray address-only decodes for random capcodes), so it stays out. `receiver.py` is adapted from mmng-ui (GPL-3.0, attribution in the file header).
- `decode.py` parses multimon-ng POCSAG lines; `core.py` does capcode filter + duplicate suppression and pushes server-sent events; `store.py` holds memory per the Advisor manual (`refdocs/advisor_inst.pdf`): 19 slots, 10 locked, Personal Message File of 10.
- `web/` is the pager face (canvas 5x7 dot-matrix LCD, 4x20) and the button state machine.
- Log: everything at DEBUG to `<data-dir>/capcoder.log` (rotating), including every multimon-ng line, filter verdicts, UDP start/stop, and browser key presses/errors via `/api/log`. Data dir defaults to `%USERPROFILE%\.capcoder` on Windows (an old `~/.vpager` is moved there on first run), deliberately not `%LOCALAPPDATA%`: the user's Python is the Microsoft Store build, which silently redirects AppData writes into its package sandbox (`%LOCALAPPDATA%\Packages\PythonSoftwareFoundation.Python.3.13_*\LocalCache\Local\...`).
- Run: `python -m capcoder --capcode 870024` (or `--base 87 --pager 3`). Test without radio: `python -m capcoder inject "555-1212"`. Tests: `python -m unittest tests.test_capcoder`.
- Observed 2026-10-10: a page to pager 1 (870008) arrived as `Function: 0` but decoded cleanly as text (`5551212`) with `-f alpha`, so the transmitter sent the body as 7-bit alpha despite the "numeric" function bits. Keep `-f alpha`; `standard` mode trusts the function bits and would likely garble it. The protocol doc doesn't say how the unit encodes on air, and the user can't control it. Still unknown whether any page ever goes out BCD-numeric; if one shows up garbled, compare `--decode-mode auto`. Which Advisor button is Read vs Function is a guess (yellow = Read, red = Function).

## Conventions

- Python 3, standard library only. No third-party runtime dependencies.
- PEP 8, with PEP 8's own 79-character line limit. Code was formatted with `black -l 79 -t py38 --skip-string-normalization`; long strings and comments are wrapped by hand. Check with `pycodestyle --max-line-length=79` (expect no output) and `flake8 --select=N,F` (naming, unused imports). W503 (break before a binary operator) is what PEP 8 recommends, so ignore it. `do_GET`/`do_POST` keep their names (required by `http.server`) with `# noqa: N802`. Exceptions end in `Error`; the pre-0.4 names (`NoReply`, `QueueFull`, etc.) remain as aliases in `hmew/errors.py` and are exported from `hmew`. Install the linters in the scratchpad, not the user's Python.
- Don't state guesses about the transmitter's behavior as facts; mark anything not from the doc or an observation as unconfirmed.
- Never send test pages to real customer pagers; use the lab unit and known test capcodes.
