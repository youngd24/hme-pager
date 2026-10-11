"""Send a page through the HME/JTECH iStation.

    python pager.py -n -p 3 555-1212
    python pager.py -a -p 3 -h 192.168.42.66 Barcode error aisle 3
    python pager.py --alpha --pager 3 --host 192.168.42.66:8080 "Two  spaces kept"
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from typing import Optional

from hmew import PagerClient, PagerError, PageType, ValidationError
from hmew.models import PAGER_MAX, PAGER_MIN, validate_message

log = logging.getLogger("pager")


def pager_number(text: str) -> int:
    try:
        n = int(text)
    except ValueError:
        raise argparse.ArgumentTypeError(f"pager must be a number, got {text!r}") from None
    if not PAGER_MIN <= n <= PAGER_MAX:
        raise argparse.ArgumentTypeError(f"pager must be {PAGER_MIN}-{PAGER_MAX}, got {n}")
    return n


def split_host(text: str) -> tuple[str, int]:
    """'192.168.42.66' -> (host, 80); '192.168.42.66:8080' -> (host, 8080)."""
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
        usage="%(prog)s (-a | -n) -p N [-h HOST[:PORT]] [-v] message ...",
        description="Send a numeric or alphanumeric page through the HME/JTECH iStation.",
        add_help=False,   # -h is --host here; help is --help only
        epilog=(
            "The host can also come from the HMEWHOST environment variable. "
            "The message is everything that isn't an option; several words are joined "
            "with single spaces (quote it to keep extra spaces). If the message starts "
            "with '-', put '--' before it."
        ),
    )
    p.add_argument("-a", "--alpha", action="store_true", help="send an alphanumeric (text) page")
    p.add_argument("-n", "--numeric", action="store_true",
                   help="send a numeric page (digits, space, - [ ] U; max 20)")
    p.add_argument("-p", "--pager", type=pager_number, required=True, metavar="N",
                   help=f"pager number to page, {PAGER_MIN}-{PAGER_MAX}")
    p.add_argument("-h", "--host", metavar="HOST[:PORT]",
                   help="transmitter address (default: $HMEWHOST; port defaults to 80)")
    p.add_argument("-v", "--verbose", action="store_true",
                   help="show what is sent and what the transmitter replies (on stderr)")
    p.add_argument("--help", action="help", help="show this help and exit")
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


def _run(parser: argparse.ArgumentParser, args: argparse.Namespace) -> int:
    if args.alpha and args.numeric:
        parser.error("-a/--alpha and -n/--numeric are mutually exclusive; use one")
    if not (args.alpha or args.numeric):
        parser.error("say what kind of page: -a/--alpha or -n/--numeric")

    msg = " ".join(args.message)
    page_type = PageType.ALPHA if args.alpha else PageType.VIBE_NUMERIC
    kind = "alpha" if args.alpha else "numeric"

    # Check the message before looking for a host, so a bad message is reported first.
    try:
        validate_message(msg, page_type)
    except ValidationError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    host_text = args.host or os.environ.get("HMEWHOST")
    if not host_text:
        print(f"error: no transmitter host; use -h/--host or set HMEWHOST\n{HELP_HINT}", file=sys.stderr)
        return 2
    host, port = split_host(host_text)
    log.debug("transmitter %s port %d (from %s)", host, port, "-h/--host" if args.host else "HMEWHOST")
    try:
        client = PagerClient(host, port=port)
        if args.alpha:
            result = client.send_alpha(pager=args.pager, msg=msg)
        else:
            result = client.send_numeric(pager=args.pager, msg=msg)
    except ValidationError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    except PagerError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    print(f"sent {kind} page to pager {args.pager}: {msg!r} (transmitter replied {result.raw})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
