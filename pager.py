"""Send a page through the HME/JTECH iStation, over HTTP or serial (RS-232).

    python pager.py -n -p 3 -h 192.168.1.100 555-1212
    python pager.py -a -p 3 -h 192.168.1.100:8080 Barcode error aisle 3
    python pager.py -n -p 1 -s /dev/ttyS0 --base 087 5551212
    python pager.py -a -c 0870008 -s /dev/ttyS0 Test page
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from typing import Optional

from hmew import (
    HttpTransmitter,
    Page,
    PagerError,
    PageType,
    SerialTransmitter,
    ValidationError,
)
from hmew.models import (
    BASE_MAX,
    BASE_MIN,
    PAGER_MAX,
    PAGER_MIN,
    validate_base,
    validate_capcode,
    validate_message,
)

log = logging.getLogger("pager")


def pager_number(text: str) -> int:
    try:
        n = int(text)
    except ValueError:
        raise argparse.ArgumentTypeError(f"pager must be a number, got {text!r}") from None
    if not PAGER_MIN <= n <= PAGER_MAX:
        raise argparse.ArgumentTypeError(f"pager must be {PAGER_MIN}-{PAGER_MAX}, got {n}")
    return n


def capcode_number(text: str) -> int:
    if not text.isdigit() or len(text) > 7:
        raise argparse.ArgumentTypeError(f"capcode must be up to 7 digits, got {text!r}")
    try:
        return validate_capcode(int(text))
    except ValidationError as exc:
        raise argparse.ArgumentTypeError(str(exc)) from None


def base_number(text: str) -> int:
    if not text.isdigit():
        raise argparse.ArgumentTypeError(f"base ID must be digits, e.g. 087, got {text!r}")
    try:
        return validate_base(int(text))
    except ValidationError as exc:
        raise argparse.ArgumentTypeError(str(exc)) from None


def split_host(text: str) -> tuple[str, int]:
    """'192.168.1.100' -> (host, 80); '192.168.1.100:8080' -> (host, 8080)."""
    host, sep, port = text.rpartition(":")
    if sep and host and port.isdigit():
        return host, int(port)
    return text, 80


HELP_HINT = "Run 'python pager.py --help' for more information."


class Parser(argparse.ArgumentParser):
    """argparse, with a pointer to --help after the short usage error."""

    def error(self, message: str):
        self.print_usage(sys.stderr)
        self.exit(2, f"{self.prog}: error: {message}\n{HELP_HINT}\n")


def build_parser() -> argparse.ArgumentParser:
    p = Parser(
        prog="pager.py",
        usage=("%(prog)s (-a | -n) (-p N | -c CAPCODE) (-h HOST[:PORT] | -s DEVICE) "
               "[--base NNN] [-v] message ..."),
        description=("Send a numeric or alphanumeric page through the HME/JTECH iStation, "
                     "over the network (HTTP) or a serial cable (RS-232)."),
        add_help=False,   # -h is --host here; help is --help only
        epilog=(
            "HTTP sends by pager number and the transmitter adds its base ID. Serial sends "
            "by full capcode: give -c, or -p with the base ID (--base or HMEWBASE). "
            "Environment defaults: HMEWHOST, HMEWSERIAL, HMEWBASE; if both HMEWHOST and "
            "HMEWSERIAL are set, choose with -h or -s. The message is everything that isn't "
            "an option; several words are joined with single spaces (quote it to keep extra "
            "spaces). If the message starts with '-', put '--' before it."
        ),
    )
    what = p.add_argument_group("what to send")
    what.add_argument("-a", "--alpha", action="store_true", help="send an alphanumeric (text) page")
    what.add_argument("-n", "--numeric", action="store_true",
                      help="send a numeric page (digits, space, - [ ] U; max 20)")
    who = p.add_argument_group("who to page")
    who.add_argument("-p", "--pager", type=pager_number, metavar="N",
                     help=f"pager number, {PAGER_MIN}-{PAGER_MAX}")
    who.add_argument("-c", "--capcode", type=capcode_number, metavar="CAPCODE",
                     help="full 7-digit capcode, e.g. 0870008 (serial only)")
    who.add_argument("--base", type=base_number, metavar="NNN",
                     help=f"base ID ({BASE_MIN:03d}-{BASE_MAX:03d}), needed with -p over serial "
                          "(default: $HMEWBASE)")
    how = p.add_argument_group("how to send")
    how.add_argument("-h", "--host", metavar="HOST[:PORT]",
                     help="send over HTTP to this transmitter (default: $HMEWHOST; port 80)")
    how.add_argument("-s", "--serial", metavar="DEVICE",
                     help="send over this serial port, e.g. /dev/ttyS0 (default: $HMEWSERIAL)")
    other = p.add_argument_group("other")
    other.add_argument("-v", "--verbose", action="store_true",
                       help="show what is sent and what the transmitter replies (on stderr)")
    other.add_argument("--help", action="help", help="show this help and exit")
    p.add_argument("message", nargs="+", help="the message to send")
    return p


def main(argv: Optional[list] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if not args.verbose:
        return _run(parser, args)
    # Verbose: debug messages from this script and the hmew library go to stderr.
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(logging.Formatter("%(name)s: %(message)s"))
    loggers = [logging.getLogger("pager"), logging.getLogger("hmew")]
    for lg in loggers:
        lg.setLevel(logging.DEBUG)
        lg.addHandler(handler)
    try:
        return _run(parser, args)
    finally:
        for lg in loggers:
            lg.removeHandler(handler)
            lg.setLevel(logging.NOTSET)


def _usage_error(message: str) -> int:
    print(f"error: {message}\n{HELP_HINT}", file=sys.stderr)
    return 2


def _run(parser: argparse.ArgumentParser, args: argparse.Namespace) -> int:
    if args.alpha and args.numeric:
        parser.error("-a/--alpha and -n/--numeric are mutually exclusive; use one")
    if not (args.alpha or args.numeric):
        parser.error("say what kind of page: -a/--alpha or -n/--numeric")
    if args.pager is not None and args.capcode is not None:
        parser.error("-p/--pager and -c/--capcode are mutually exclusive; use one")
    if args.pager is None and args.capcode is None:
        parser.error("say who to page: -p/--pager N or -c/--capcode NNNNNNN")
    if args.host and args.serial:
        parser.error("-h/--host and -s/--serial are mutually exclusive; use one")

    msg = " ".join(args.message)
    page_type = PageType.ALPHA if args.alpha else PageType.VIBE_NUMERIC
    kind = "alpha" if args.alpha else "numeric"

    # Check the message before anything about the transmitter, so a bad message is reported first.
    try:
        validate_message(msg, page_type)
    except ValidationError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    # Which transmitter: a flag wins; otherwise the environment, which must not be ambiguous.
    env_host, env_serial = os.environ.get("HMEWHOST"), os.environ.get("HMEWSERIAL")
    if args.host or args.serial:
        host_text, device = args.host, args.serial
        source = "-h/--host" if args.host else "-s/--serial"
    elif env_host and env_serial:
        return _usage_error("both HMEWHOST and HMEWSERIAL are set; choose with -h/--host or -s/--serial")
    elif env_host or env_serial:
        host_text, device = env_host, env_serial
        source = "HMEWHOST" if env_host else "HMEWSERIAL"
    else:
        return _usage_error("no transmitter: use -h/--host or -s/--serial "
                            "(or set HMEWHOST or HMEWSERIAL)")

    page_kwargs = {"pagers": (args.pager,)} if args.pager is not None else {"capcodes": (args.capcode,)}
    page = Page(kind=page_type, msg=msg, **page_kwargs)

    try:
        if host_text:
            if args.capcode is not None:
                return _usage_error("HTTP sends by pager number and the transmitter adds its base ID; "
                                    "use -p/--pager, or -s/--serial to send by capcode")
            host, port = split_host(host_text)
            log.debug("HTTP transmitter %s port %d (from %s)", host, port, source)
            transmitter = HttpTransmitter(host, port=port)
            via = f"HTTP {host_text}"
            target = f"pager {args.pager}"
        else:
            base = args.base
            if base is None and os.environ.get("HMEWBASE"):
                try:
                    base = base_number(os.environ["HMEWBASE"])
                except argparse.ArgumentTypeError as exc:
                    return _usage_error(f"HMEWBASE: {exc}")
            if args.pager is not None and base is None:
                return _usage_error("serial sends by capcode: add --base NNN (or set HMEWBASE) "
                                    "to page by pager number, or use -c/--capcode")
            log.debug("serial transmitter %s (from %s)%s", device, source,
                      f", base ID {base:03d}" if base is not None else "")
            transmitter = SerialTransmitter(device, base=base)
            via = f"serial {device}"
            if args.pager is not None:
                target = f"pager {args.pager} (capcode {transmitter.capcode_for(args.pager):07d})"
            else:
                target = f"capcode {args.capcode:07d}"
        result = transmitter.send(page)
    except ValidationError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    except PagerError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    print(f"sent {kind} page to {target} via {via}: {msg!r} (transmitter replied {result.raw})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
