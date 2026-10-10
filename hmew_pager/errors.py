"""Exception hierarchy for the HMEW iStation HTTP pager client."""


class PagerError(Exception):
    """Base class for all errors raised by this package."""


class ValidationError(PagerError, ValueError):
    """Input rejected locally, before anything is sent to the transmitter."""


class TransmitterUnreachable(PagerError):
    """Timeout, connection refused, or other network-level failure."""


class UnexpectedReply(PagerError):
    """Reply did not match the documented ``!s<code><n>`` format."""

    def __init__(self, raw: str):
        super().__init__(f"unexpected reply from transmitter: {raw!r}")
        self.raw = raw


class PageRejected(PagerError):
    """Transmitter rejected the request (!sd0, !se0, !sf0, !sh0).

    These indicate the request was built wrong, so they are not retryable.
    """

    MEANINGS = {
        "d": "bad parameter label",
        "e": "bad parameter value",
        "f": "unsupported .php page",
        "h": "good URL+data, but pager number was not included",
    }

    def __init__(self, code: str, raw: str):
        meaning = self.MEANINGS.get(code, "unknown rejection")
        super().__init__(f"transmitter rejected page ({raw}): {meaning}")
        self.code = code
        self.raw = raw


class QueueFull(PagerError):
    """Transmitter's internal queue is full (!sg<n>).

    ``processed`` is how many pagers in the request were accepted before the
    queue filled, so callers can avoid double-paging them.
    """

    def __init__(self, processed: int, raw: str):
        super().__init__(
            f"transmitter queue full ({raw}); {processed} pager(s) accepted"
        )
        self.processed = processed
        self.raw = raw
