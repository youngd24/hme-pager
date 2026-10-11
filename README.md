# hme-pager

Python tools for the HME Wireless (JTECH) iStation paging transmitter. One side sends pages through the transmitter; the other receives them off the air with an RTL-SDR and shows them on a virtual pager.

Everything is plain Python 3 with no third-party dependencies, so it runs as-is on Windows, macOS, Linux, or a FreePBX box. The one exception is sending over a serial cable on Windows, which needs `pyserial`.

```
 pager.py / hmew ──HTTP or RS-232──▶ iStation ──RF 457.575 MHz──▶ RTL-SDR ──UDP audio──▶ Mockorola Capcoder
      (send)                         (transmitter)                                         (receive and display)
```

## Hardware and systems tested

Everything here was built and tested against an HME/JTECH **ISTATION-N** transmitter reporting these software versions:

```
PVer: 2.48   RVer: 003
```

Other models or firmware versions may behave differently, particularly in their replies and in how they encode pages on air.

Operating systems: **Ubuntu 24.04** for Linux and **Windows 11** for Windows. Serial sending was tested on Ubuntu; on Windows it would use `pyserial` and hasn't been tried with the transmitter.

## What's inside

| Path | What it is |
|---|---|
| [`hmew/`](hmew/) | Library that sends pages through the iStation, either over the network (its HTTP interface, `send_page.php`) or over an RS-232 serial cable (the Scope protocol). It checks pager numbers, capcodes and message text before sending, and turns the transmitter's replies into results or clear errors. |
| [`pager.py`](pager.py) | Command line for sending a page, built on `hmew`. |
| [`config.example`](config.example) | Example defaults for `pager.py`; copy to `~/.hme-pager/config`. |
| [`capcoder/`](capcoder/) | **Mockorola Capcoder**: a virtual Motorola Advisor-style pager that answers to one capcode. See its [README](capcoder/README.md). |
| [`tests/`](tests/) | Unit tests for both sides. |
| [`refdocs/`](refdocs/) | Reference documents: the HMEW Integration Protocol and the Motorola Advisor user manual. |
| [`assets/`](assets/) | Images used in the docs. |
| [`TODO.md`](TODO.md) | Open items for later. |
| [`CHANGELOG.md`](CHANGELOG.md) | What changed in each tagged release (current: 0.3). |

## Sending pages: `pager.py`

Pages go over the network (the transmitter's HTTP interface) or a serial cable (RS-232). With the defaults set in a config file, a page needs only who to page and the message:

```
python pager.py -p 1 Test page
```

Options override the config for one page, or replace it entirely:

```
python pager.py -n -p 1 5551212                         # numeric this time
python pager.py -m network -p 3 Barcode error aisle 3   # network this time, using the configured host
python pager.py -a -p 3 -h 192.168.1.100 Barcode error aisle 3
python pager.py -n -p 1 --base 087 -s /dev/ttyS0 5551212
python pager.py -a -c 0870008 -s /dev/ttyS0 Test page
```

### Configuration file

Defaults live in `~/.hme-pager/config`; copy [`config.example`](config.example) there to start. Every setting is optional, and options on the command line always win.

```ini
[pager]
mode = serial              # network or serial
host = 192.168.1.100       # for network: host or host:port (port 80 if not given)
serial_port = /dev/ttyS0   # for serial
base = 087                 # base ID, so serial can page by pager number
type = alpha               # alpha or numeric, when neither -a nor -n is given
verbose = false            # true or false
```

| Setting | Overridden by |
|---|---|
| `mode` | `-m network\|serial`, or `-h`/`-s`, which also give the address |
| `host` | `-h HOST[:PORT]` |
| `serial_port` | `-s DEVICE` |
| `base` | `--base NNN` |
| `type` | `-a` / `-n` |
| `verbose` | `-v` turns it on, `-q` turns it off |

- **Other locations:** `--config FILE` reads a different file. This is useful for a service account, such as FreePBX's `asterisk` user, whose home folder is elsewhere.
- **No file:** if `~/.hme-pager/config` doesn't exist, there are no defaults, and everything comes from the command line as before.
- **Errors:** a misspelled setting, an unknown section or a bad value stops with an error naming the file and setting, before anything is sent.
- **No environment variables:** pager.py no longer reads `HMEWHOST`, `HMEWSERIAL` or `HMEWBASE`.

### Options

```
usage: pager.py [-a | -n] (-p N | -c CAPCODE) [-m MODE | -h HOST[:PORT] | -s DEVICE] [--base NNN] [-v | -q] [--config FILE] message ...

Send a numeric or alphanumeric page through the HME/JTECH iStation, over the network (HTTP) or a serial cable (RS-232).

positional arguments:
  message               the message to send

what to send (default: type in the config):
  -a, --alpha           send an alphanumeric (text) page
  -n, --numeric         send a numeric page (digits, space, - [ ] U; max 20)

who to page:
  -p, --pager N         pager number, 1-999
  -c, --capcode CAPCODE
                        full 7-digit capcode, e.g. 0870008 (serial only)
  --base NNN            base ID (000-209), needed with -p over serial (default: base in the config)

how to send (default: mode in the config):
  -m, --mode {network,serial}
                        network or serial, using the config's host or serial_port
  -h, --host HOST[:PORT]
                        send over the network to this transmitter (port 80 unless given)
  -s, --serial DEVICE   send over this serial port, e.g. /dev/ttyS0

other:
  -v, --verbose         show what is sent and what the transmitter replies (on stderr)
  -q, --quiet           not verbose, even if the config says verbose = true
  --config FILE         read defaults from FILE instead of ~/.hme-pager/config
  --help                show this help and exit

Defaults come from ~/.hme-pager/config ([pager] section: mode, host, serial_port, base, type, verbose); options override them. HTTP sends
by pager number and the transmitter adds its base ID. Serial sends by full capcode: give -c, or -p with the base ID. The message is
everything that isn't an option; several words are joined with single spaces (quote it to keep extra spaces). If the message starts with
'-', put '--' before it.
```

The message is checked before anything is sent. A numeric page may contain only digits, space, `-`, `[`, `]` and `U` (up to 20 characters). An alpha page may contain only printable ASCII (up to 128 characters) on either connection. Exit status is 0 on success, 2 for a usage or message error, and 1 if the transmitter rejects the page, gives no reply, answers with an HTTP error, or can't be reached.

### Capcodes, pager numbers and base IDs

Capcode = 3-digit base ID followed by pager × 8 as 4 digits. For example, base 087 and pager 3 give capcode 0870024.

- **HTTP** takes a pager number (1-999), and the transmitter adds its own base ID. HTTP can't address a capcode directly.
- **Serial** takes the full capcode. Give it with `-c`, or give `-p` plus the base ID (`base` in the config, or `--base`) and pager.py works out the capcode.

### Serial details

- **Cable:** a straight-through RS-232 cable (not a null-modem cable) with a DB9 male connector at the transmitter end. The transmitter's serial port is a DB9 female.
- **Format:** the Scope format (HMEW doc section 4.A), for example `AF0870008ATest page` followed by a carriage return. The parts are the type (`A` alpha, `N` numeric), `F` for 1200 baud (always sent, as the doc says), the 7-digit capcode, beep `A`, and the message.
- **Port settings:** 9600 baud, 8 data bits, no parity, 1 stop bit, no flow control.
- **Permissions (Linux):** the user sending pages must be allowed to open the serial port. On Ubuntu, and likely Debian and other distributions, serial ports belong to the `dialout` group. Add the user with `sudo usermod -aG dialout $USER`, then log out and back in (or start a new login session) for it to take effect. Without it, the port fails to open with "Permission denied". Some distributions use a different group; `ls -l /dev/ttyS0` shows which one owns the port.
- **Reply:** the unit answers `OK` when it accepts a command, and never sends an error reply. It says `OK` for any valid capcode, even one no pager uses (0870001 was accepted in testing). Capcodes the unit rejects are refused by `pager.py` before sending, so in practice no `OK` within 3 seconds means a cable, port or unit-setting problem, and the error says to check those.
- **Group pages:** each capcode gets its own command. If one goes unanswered, the error says how many were already sent, so you don't page those people twice.
- **One sender at a time:** while a page is being sent, the serial port is locked, and a second sender waits up to 10 seconds for its turn.
- **Linux and macOS** need nothing extra; the serial code uses only the standard library. **Windows** needs the `pyserial` package for serial; HTTP needs nothing.
- **Both connections at once:** the unit accepts pages over HTTP and serial at the same time.

### Verbose output

`-v` (or `verbose = true` in the config) shows which config file was read, where each setting came from, exactly what is sent, and the reply with its timing. Over serial, with everything from the config:

```
$ python pager.py -v -p 1 Test page
pager: config /home/youngd/.hme-pager/config: mode=serial, serial_port=/dev/ttyS0, base=087, type=alpha, host=192.168.1.100
pager: type alpha (from config)
pager: mode serial (from config)
pager: serial port /dev/ttyS0 (from config)
pager: base ID 087 (from config)
hmew: alpha page to capcode(s) 0870008 via serial /dev/ttyS0: 'Test page' (beep 1)
hmew: opened /dev/ttyS0 at 9600 baud, 8N1, no flow control
hmew: write b'AF0870008ATest page\r'
hmew: reply b'OK\r\n' in 34 ms
sent alpha page to pager 1 (capcode 0870008) via serial /dev/ttyS0: 'Test page' (transmitter replied OK)
```

Over the network, overriding the config's mode and type:

```
$ python pager.py -v -n -m network -p 3 555-1212
pager: config /home/youngd/.hme-pager/config: mode=serial, serial_port=/dev/ttyS0, base=087, type=alpha, host=192.168.1.100
pager: type numeric (from -a/-n)
pager: mode network (from -m/--mode)
pager: transmitter 192.168.1.100 port 80 (from config)
hmew: numeric page to pager(s) 3 via 192.168.1.100:80: '555-1212' (beep 1, 1200 baud)
hmew: GET http://192.168.1.100/send_page.php?pager=3&type=1&msg=555-1212&baud=1&beep=1
hmew: reply '!sc1' (HTTP 200) in 50 ms
sent numeric page to pager 3 via network 192.168.1.100: '555-1212' (transmitter replied !sc1)
```

### From Python

```python
from hmew import HttpTransmitter, SerialTransmitter, Page, PageType

page = Page(PageType.ALPHA, "Test page", pagers=(1,))

HttpTransmitter("192.168.1.100").send(page)
SerialTransmitter("/dev/ttyS0", base=87).send(page)
SerialTransmitter("/dev/ttyS0").send(Page(PageType.ALPHA, "Test page", capcodes=(870008,)))
```

Both have the same `send(page)` method, so code can take either one. Scripts can read the same defaults as pager.py with `hmew.config.load()` (or `load("/path/to/config")`), which returns the settings or raises `ConfigError`. The older `PagerClient("192.168.1.100").send_numeric(pager=3, msg="555-1212")` still works; `PagerClient` is another name for `HttpTransmitter`.

## Receiving pages: Mockorola Capcoder

![Mockorola Capcoder showing the idle screen while receiving audio](assets/capcoder.png)

Capcoder listens for raw demodulated audio over UDP, sent by `rtl_fm` piped into netcat. It decodes the audio with multimon-ng and shows pages for its capcode on a dot-matrix LCD. The buttons, menus and alerts follow the Advisor's user manual. Every decode, for every capcode, goes to a log file.

```
python -m capcoder --base 87 --pager 3
rtl_fm -f 457.575M -s 22050 -g 30 - | nc -u -w1 <capcoder-host> 8888
```

See the [Capcoder README](capcoder/README.md) for setup, options, behavior and testing.

## Tests

```
python -m unittest tests.test_hmew tests.test_hmew_serial tests.test_hmew_config tests.test_capcoder
```

The tests never read your real `~/.hme-pager/config`.

The sender's tests never send a real page. HTTP tests use a fake transmitter on 127.0.0.1. Serial tests use a fake port, plus, on Linux and macOS, a pseudo-terminal pair that plays the transmitter (those 4 tests are skipped on Windows).

## Reference

- HMEW Integration Protocol rev 04/13 ([`refdocs/`](refdocs/)). Section 4.D covers the HTTP interface.
- Motorola Advisor user manual ([`refdocs/`](refdocs/)), the model for Capcoder's behavior.

## License

GPL-3.0. See [LICENSE](LICENSE). Capcoder's receiver code is adapted from [mmng-ui](https://github.com/lingfish/mmng-ui), also GPL-3.0.
