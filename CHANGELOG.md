# Changelog

Releases of the whole repo, tagged in git. Capcoder's own detailed changes are in [capcoder/CHANGELOG.md](capcoder/CHANGELOG.md).

## Unreleased

**Code style: PEP 8**
- All Python code (`hmew`, `pager.py`, `capcoder`, tests) now meets PEP 8, including its 79-character line limit. `pycodestyle` reports nothing.
- The formatting was done with `black`, and long strings and comments were wrapped by hand. Help text, messages and behavior are unchanged.
- **Exception names now end in `Error`, as PEP 8 asks:**
  - `TransmitterUnreachableError`
  - `NoReplyError`
  - `UnexpectedReplyError`
  - `PageRejectedError`
  - `QueueFullError`

  The old names still work as aliases, so existing code doesn't break.
- `do_GET`/`do_POST` keep their names, because Python's `http.server` requires them.
- Removed an unused import.

## 0.3 (2026-10-11), git tag `v0.3`

Tested on the real unit: with defaults from `config.example`, pages went out over both serial and the network and were received on Capcoder.

**Sending (`hmew` library and `pager.py`)**
- **A config file for defaults:** `~/.hme-pager/config` (INI, `[pager]` section), with `mode` (network or serial), `host`, `serial_port`, `base`, `type` (alpha or numeric) and `verbose` (default false). A template is in `config.example`.
- **Fewer options needed.** With the config set, `pager.py -p 1 Test page` is a complete command, and options override the config for one page.
- **New options:**
  - `-m/--mode network|serial` switches mode using the configured address.
  - `-q/--quiet` turns verbose off.
  - `--config FILE` reads a different file.
- **No more environment variables.** `HMEWHOST`, `HMEWSERIAL` and `HMEWBASE` are no longer read, including by `HttpTransmitter`, which now requires a host.
- **Config errors stop early.** A misspelled setting, an unknown section or a bad value is reported before anything is sent.
- **`-v` shows where each setting came from** (the config file or an option).
- **Serial permissions hint.** "Permission denied" when opening the serial port now says to add the user to the `dialout` group (Ubuntu/Debian).
- Tests: `tests/test_hmew_config.py`.

**Receiving:** Capcoder is unchanged; its version follows the release to 0.3.

**Docs**
- README: a configuration section with a table of which option overrides which setting, the new `--help` text, and verbose samples.
- Serial details: the `dialout` group requirement.
- Systems tested: Ubuntu 24.04 and Windows 11.

## 0.2 (2026-10-11), git tag `v0.2`

**Sending (`hmew` library and `pager.py`)**
- **Serial (RS-232) sending,** alongside HTTP, using the Scope protocol: `pager.py -s /dev/ttyS0`. Tested against the real unit.
  - Pages by full capcode (`-c`), or by pager number plus base ID (`-p` with `--base` or `HMEWBASE`).
  - 9600 8N1 with no flow control. Linux needs only the standard library; Windows needs pyserial for serial.
  - The serial port is locked while sending, so two senders can't interleave.
  - The unit only ever answers `OK`, so no `OK` within 3 s is reported as an error.
- **Standard command-line options:** `(-a | -n) (-p N | -c CAPCODE) (-h HOST[:PORT] | -s DEVICE) [--base NNN] [-v] message`.
  - Each pair is mutually exclusive with one required.
  - `--pager` no longer defaults to pager 3.
  - Usage errors point to `--help`.
- **`-v/--verbose`** shows exactly what is sent (URL or bytes) and the reply with its timing.
- **Spaces are sent as `%20`.** The transmitter doesn't decode `+`, which used to appear on the pager in place of every space.
- **Stricter message checks.**
  - Numeric: a trailing newline no longer slips through.
  - Alpha: printable ASCII only, and not empty.
  - Errors name the offending characters.
- **An HTTP error status from the unit is reported as such,** not as "unreachable".
- **Library changes:**
  - The package is renamed `hmew_pager` → `hmew`.
  - The new `Page`, `HttpTransmitter` and `SerialTransmitter` share one `send(page)` method.
  - `PagerClient` still works.

**Receiving: Mockorola Capcoder 0.2** (formerly vpager)
- Renamed, with the new MOCKOROLA / CAPCODER badge. An existing vpager data folder is moved over on first run.
- Opens in its own resizable window.
- Retries a busy UDP port, and refuses to run twice on the same ports.

**Docs and tests**
- New top-level README:
  - hardware tested (ISTATION-N, PVer 2.48, RVer 003)
  - the serial cable (straight-through, DB9 male at the transmitter end)
  - a screenshot
- `TODO.md` for the spurious-decode investigation.
- Tests: `tests/test_hmew.py` and `tests/test_hmew_serial.py`, including real serial port code against a Linux pseudo-terminal.

## 0.1 (2026-10-10), git tag `v0.1`

- **vpager** (now Mockorola Capcoder): the first over-the-air page received and displayed.
- `hmew_pager` (now `hmew`) HTTP client and a basic `pager.py`.
