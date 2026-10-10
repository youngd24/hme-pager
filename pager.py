import sys

from hmew_pager import PagerClient, PagerError

USAGE = "usage: python pager.py <numeric|alpha> <message> [pager]"


def main() -> None:
    if len(sys.argv) < 3:
        print(USAGE, file=sys.stderr)
        sys.exit(1)

    mode, msg = sys.argv[1], sys.argv[2]
    pager = int(sys.argv[3]) if len(sys.argv) > 3 else 3

    try:
        c = PagerClient()
        if mode == "numeric":
            result = c.send_numeric(pager=pager, msg=msg)
        elif mode == "alpha":
            result = c.send_alpha(pager=pager, msg=msg)
        else:
            print(f"unknown mode {mode!r}, expected 'numeric' or 'alpha'", file=sys.stderr)
            sys.exit(1)
    except PagerError as exc:
        print(f"error: {exc}", file=sys.stderr)
        sys.exit(1)

    print(f"Successfully sent message to pager {pager}")


if __name__ == "__main__":
    main()
