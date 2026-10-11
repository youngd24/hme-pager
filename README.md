# hme-pager

Python tools for the HME Wireless (JTECH) iStation paging transmitter. One side sends pages through the transmitter; the other receives them off the air with an RTL-SDR and shows them on a virtual pager.

Everything is plain Python 3 with no third-party dependencies, so it runs as-is on Windows, macOS, Linux, or a FreePBX box.

```
 pager.py / hmew ──HTTP──▶ iStation ──RF 457.575 MHz──▶ RTL-SDR ──UDP audio──▶ Mockorola Capcoder
      (send)                (transmitter)                                         (receive and display)
```

## What's inside

| Path | What it is |
|---|---|
| [`hmew/`](hmew/) | Library that sends pages through the iStation's HTTP interface (`send_page.php`). It checks pager numbers and message text before sending, and turns the transmitter's replies into results or clear errors. |
| [`pager.py`](pager.py) | Command line for sending a page, built on `hmew`. |
| [`capcoder/`](capcoder/) | **Mockorola Capcoder**: a virtual Motorola Advisor-style pager that answers to one capcode. See its [README](capcoder/README.md). |
| [`tests/`](tests/) | Unit tests for both sides. |
| [`refdocs/`](refdocs/) | Reference documents: the HMEW Integration Protocol and the Motorola Advisor user manual. |
| [`assets/`](assets/) | Images used in the docs. |

## Sending pages: `pager.py`

```
python pager.py -n -p 3 555-1212
python pager.py -a -p 3 -h 192.168.1.100 Barcode error aisle 3
```

```
usage: pager.py (-a | -n) -p N [-h HOST[:PORT]] message ...

Send a numeric or alphanumeric page through the HME/JTECH iStation.

positional arguments:
  message               the message to send

options:
  -a, --alpha           send an alphanumeric (text) page
  -n, --numeric         send a numeric page (digits, space, - [ ] U; max 20)
  -p, --pager N         pager number to page, 1-999
  -h, --host HOST[:PORT]
                        transmitter address (default: $HMEWHOST; port defaults to 80)
  --help                show this help and exit

The host can also come from the HMEWHOST environment variable. The message is everything that isn't an option; several words are joined
with single spaces (quote it to keep extra spaces). If the message starts with '-', put '--' before it.
```

The message is checked before anything is sent. A numeric page may contain only digits, space, `-`, `[`, `]` and `U` (up to 20 characters). An alpha page may contain only printable ASCII (up to 128 characters). Exit status is 0 on success, 2 for a usage or message error, and 1 if the transmitter rejects the page or can't be reached.

From Python:

```python
from hmew import PagerClient

c = PagerClient("192.168.1.100")
c.send_numeric(pager=3, msg="555-1212")
c.send_alpha(pager=3, msg="hello")
```

The transmitter takes a **pager number** (1-999) and adds its own base ID to form the capcode: capcode = 3-digit base ID followed by pager × 8 as 4 digits. For example, base 087 and pager 3 give capcode 0870024.

## Receiving pages: Mockorola Capcoder

![Mockorola Capcoder showing the idle screen while receiving audio](assets/capcoder.png)

Capcoder listens for raw demodulated audio over UDP, from SDR++ or from `rtl_fm` piped into netcat. It decodes the audio with multimon-ng and shows pages for its capcode on a dot-matrix LCD. The buttons, menus and alerts follow the Advisor's user manual. Every decode, for every capcode, goes to a log file.

```
python -m capcoder --base 87 --pager 3
rtl_fm -f 457.575M -s 22050 -g 30 - | nc -u -w1 <capcoder-host> 8888
```

See the [Capcoder README](capcoder/README.md) for setup, options, behavior and testing.

## Tests

```
python -m unittest tests.test_hmew tests.test_capcoder
```

The sender's tests use a fake transmitter on 127.0.0.1, so they never send a real page.

## Reference

- HMEW Integration Protocol rev 04/13 ([`refdocs/`](refdocs/)). Section 4.D covers the HTTP interface.
- Motorola Advisor user manual ([`refdocs/`](refdocs/)), the model for Capcoder's behavior.

## License

GPL-3.0. See [LICENSE](LICENSE). Capcoder's receiver code is adapted from [mmng-ui](https://github.com/lingfish/mmng-ui), also GPL-3.0.
