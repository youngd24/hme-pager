"""Send a page through the HME/JTECH iStation.

Pages go over the network (HTTP) or a serial cable (RS-232). Defaults come
from ~/.hme-pager/config; options override them. With a config that sets
mode, host or serial_port, base and type, a page is just:

    python pager.py -p 1 Test page

Without a config, or to override it:

    python pager.py -a -p 3 -h 192.168.1.100 Barcode error aisle 3
    python pager.py -n -p 1 --base 087 -s /dev/ttyS0 5551212
    python pager.py -a -c 0870008 -s /dev/ttyS0 Test page
"""

from __future__ import annotations

import argparse
import logging
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
from hmew import config as hconfig
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
        raise argparse.ArgumentTypeError(
            f"pager must be a number, got {text!r}"
        ) from None
    if not PAGER_MIN <= n <= PAGER_MAX:
        raise argparse.ArgumentTypeError(
            f"pager must be {PAGER_MIN}-{PAGER_MAX}, got {n}"
        )
    return n


def capcode_number(text: str) -> int:
    if not text.isdigit() or len(text) > 7:
        raise argparse.ArgumentTypeError(
            f"capcode must be up to 7 digits, got {text!r}"
        )
    try:
        return validate_capcode(int(text))
    except ValidationError as exc:
        raise argparse.ArgumentTypeError(str(exc)) from None


def base_number(text: str) -> int:
    if not text.isdigit():
        raise argparse.ArgumentTypeError(
            f"base ID must be digits, e.g. 087, got {text!r}"
        )
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
        usage=(
            "%(prog)s [-a | -n] (-p N | -c CAPCODE) "
            "[-m MODE | -h HOST[:PORT] | -s DEVICE] "
            "[--base NNN] [-v | -q] [--config FILE] message ..."
        ),
        description=(
            "Send a numeric or alphanumeric page through the HME/JTECH "
            "iStation, over the network (HTTP) or a serial cable (RS-232)."
        ),
        add_help=False,  # -h is --host here; help is --help only
        epilog=(
            "Defaults come from ~/.hme-pager/config ([pager] section: mode, "
            "host, serial_port, base, type, verbose); options override them. "
            "HTTP sends by pager number and the transmitter adds its base ID. "
            "Serial sends by full capcode: give -c, or -p with the base ID. "
            "The message is everything that isn't an option; several words "
            "are joined with single spaces (quote it to keep extra spaces). "
            "If the message starts with '-', put '--' before it."
        ),
    )
    what = p.add_argument_group("what to send (default: type in the config)")
    what.add_argument(
        "-a",
        "--alpha",
        action="store_true",
        help="send an alphanumeric (text) page",
    )
    what.add_argument(
        "-n",
        "--numeric",
        action="store_true",
        help="send a numeric page (digits, space, - [ ] U; max 20)",
    )
    who = p.add_argument_group("who to page")
    who.add_argument(
        "-p",
        "--pager",
        type=pager_number,
        metavar="N",
        help=f"pager number, {PAGER_MIN}-{PAGER_MAX}",
    )
    who.add_argument(
        "-c",
        "--capcode",
        type=capcode_number,
        metavar="CAPCODE",
        help="full 7-digit capcode, e.g. 0870008 (serial only)",
    )
    who.add_argument(
        "--base",
        type=base_number,
        metavar="NNN",
        help=(
            f"base ID ({BASE_MIN:03d}-{BASE_MAX:03d}), needed with -p over "
            "serial (default: base in the config)"
        ),
    )
    how = p.add_argument_group("how to send (default: mode in the config)")
    how.add_argument(
        "-m",
        "--mode",
        choices=hconfig.MODES,
        help="network or serial, using the config's host or serial_port",
    )
    how.add_argument(
        "-h",
        "--host",
        metavar="HOST[:PORT]",
        help=(
            "send over the network to this transmitter "
            "(port 80 unless given)"
        ),
    )
    how.add_argument(
        "-s",
        "--serial",
        metavar="DEVICE",
        help="send over this serial port, e.g. /dev/ttyS0",
    )
    other = p.add_argument_group("other")
    other.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help=(
            "show what is sent and what the transmitter replies "
            "(on stderr)"
        ),
    )
    other.add_argument(
        "-q",
        "--quiet",
        action="store_true",
        help="not verbose, even if the config says verbose = true",
    )
    other.add_argument(
        "--config",
        metavar="FILE",
        help="read defaults from FILE instead of ~/.hme-pager/config",
    )
    other.add_argument(
        "--help", action="help", help="show this help and exit"
    )
    p.add_argument("message", nargs="+", help="the message to send")
    return p


def main(argv: Optional[list] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.verbose and args.quiet:
        parser.error(
            "-v/--verbose and -q/--quiet are mutually exclusive; use one"
        )
    try:
        settings = hconfig.load(args.config)
    except hconfig.ConfigError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    verbose = args.verbose or (settings.verbose and not args.quiet)
    if not verbose:
        return _run(parser, args, settings)
    # Verbose: debug messages from this script and the hmew library go to
    # stderr.
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(logging.Formatter("%(name)s: %(message)s"))
    loggers = [logging.getLogger("pager"), logging.getLogger("hmew")]
    for lg in loggers:
        lg.setLevel(logging.DEBUG)
        lg.addHandler(handler)
    try:
        return _run(parser, args, settings)
    finally:
        for lg in loggers:
            lg.removeHandler(handler)
            lg.setLevel(logging.NOTSET)


def _usage_error(message: str) -> int:
    print(f"error: {message}\n{HELP_HINT}", file=sys.stderr)
    return 2


def _run(
    parser: argparse.ArgumentParser,
    args: argparse.Namespace,
    settings: hconfig.Settings,
) -> int:
    cfg_name = str(settings.path) if settings.path else "~/.hme-pager/config"
    if settings.path:
        log.debug(
            "config %s: %s",
            settings.path,
            ", ".join(f"{k}={v}" for k, v in settings.set_in_file.items())
            or "no settings",
        )
    else:
        log.debug("config: none (%s not found)", hconfig.DEFAULT_PATH)

    def source(flag_given: bool, flag: str) -> str:
        return flag if flag_given else "config"

    # What to send: -a/-n, else the config's type.
    if args.alpha and args.numeric:
        parser.error(
            "-a/--alpha and -n/--numeric are mutually exclusive; use one"
        )
    if args.alpha or args.numeric:
        kind = "alpha" if args.alpha else "numeric"
    elif settings.type:
        kind = settings.type
    else:
        parser.error(
            "say what kind of page: -a/--alpha or -n/--numeric "
            f"(or set type in {cfg_name})"
        )
    log.debug(
        "type %s (from %s)", kind, source(args.alpha or args.numeric, "-a/-n")
    )

    # Who to page.
    if args.pager is not None and args.capcode is not None:
        parser.error(
            "-p/--pager and -c/--capcode are mutually exclusive; use one"
        )
    if args.pager is None and args.capcode is None:
        parser.error("say who to page: -p/--pager N or -c/--capcode NNNNNNN")

    # How to send: -h or -s (address given), else -m, else the config's mode.
    given = [
        flag
        for flag, val in (
            ("-m/--mode", args.mode),
            ("-h/--host", args.host),
            ("-s/--serial", args.serial),
        )
        if val
    ]
    if len(given) > 1:
        parser.error(f"{' and '.join(given)} are mutually exclusive; use one")
    if args.host:
        mode = "network"
    elif args.serial:
        mode = "serial"
    else:
        mode = args.mode or settings.mode
    if not mode:
        return _usage_error(
            f"say how to send: -h/--host, -s/--serial or -m/--mode "
            f"(or set mode in {cfg_name})"
        )
    log.debug("mode %s (from %s)", mode, given[0] if given else "config")

    msg = " ".join(args.message)
    page_type = PageType.ALPHA if kind == "alpha" else PageType.VIBE_NUMERIC

    # Check the message before anything about the transmitter, so a bad
    # message is reported first.
    try:
        validate_message(msg, page_type)
    except ValidationError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    page_kwargs = (
        {"pagers": (args.pager,)}
        if args.pager is not None
        else {"capcodes": (args.capcode,)}
    )
    page = Page(kind=page_type, msg=msg, **page_kwargs)

    try:
        if mode == "network":
            if args.capcode is not None:
                return _usage_error(
                    "the network interface sends by pager number and the "
                    "transmitter adds its base ID; use -p/--pager, or serial "
                    "to send by capcode"
                )
            host_text = args.host or settings.host
            if not host_text:
                return _usage_error(
                    f"network mode needs a transmitter: -h/--host HOST "
                    f"(or set host in {cfg_name})"
                )
            host, port = split_host(host_text)
            log.debug(
                "transmitter %s port %d (from %s)",
                host,
                port,
                source(bool(args.host), "-h/--host"),
            )
            transmitter = HttpTransmitter(host, port=port)
            via = f"network {host_text}"
            target = f"pager {args.pager}"
        else:
            device = args.serial or settings.serial_port
            if not device:
                return _usage_error(
                    f"serial mode needs a port: -s/--serial DEVICE "
                    f"(or set serial_port in {cfg_name})"
                )
            log.debug(
                "serial port %s (from %s)",
                device,
                source(bool(args.serial), "-s/--serial"),
            )
            base = args.base if args.base is not None else settings.base
            if args.pager is not None:
                if base is None:
                    return _usage_error(
                        "serial sends by capcode: add --base NNN (or set base "
                        f"in {cfg_name}) to page by pager number, or use "
                        "-c/--capcode"
                    )
                log.debug(
                    "base ID %03d (from %s)",
                    base,
                    source(args.base is not None, "--base"),
                )
            transmitter = SerialTransmitter(device, base=base)
            via = f"serial {device}"
            if args.pager is not None:
                capcode = transmitter.capcode_for(args.pager)
                target = f"pager {args.pager} (capcode {capcode:07d})"
            else:
                target = f"capcode {args.capcode:07d}"
        result = transmitter.send(page)
    except ValidationError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    except PagerError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    print(
        f"sent {kind} page to {target} via {via}: {msg!r} "
        f"(transmitter replied {result.raw})"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
