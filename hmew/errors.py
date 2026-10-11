"""Exception hierarchy for the HMEW iStation pager client.

Names follow PEP 8 (an ``Error`` suffix). The names used before 0.4
(TransmitterUnreachable, NoReply, UnexpectedReply, PageRejected, QueueFull)
are kept as aliases at the bottom, so existing code keeps working.
"""


class PagerError(Exception):
    """Base class for all errors raised by this package."""


class ValidationError(PagerError, ValueError):
    """Input rejected locally, before anything is sent to the transmitter."""


class TransmitterUnreachableError(PagerError):
    """Timeout, connection refused, or other network-level failure."""


class TransmitterHTTPError(PagerError):
    """The transmitter answered with an HTTP error status (e.g. 404, 500).

    Distinct from TransmitterUnreachableError: the network path works, the
    unit (or something at that address) refused or failed the request.
    """

    def __init__(self, status: int, reason: str, url: str, body: str = ""):
        detail = f": {body.strip()[:200]!r}" if body.strip() else ""
        super().__init__(
            f"transmitter answered HTTP {status} {reason}{detail}"
        )
        self.status = status
        self.reason = reason
        self.url = url
        self.body = body


class NoReplyError(PagerError):
    """Serial: the transmitter didn't say OK in time.

    The unit only ever answers OK, so silence is the only failure serial
    can report. It answers OK for any valid capcode (even one no pager
    uses), so in practice this means a cable, port or unit-setting
    problem. ``sent`` is how many commands were acknowledged before this
    one, so callers can avoid double-paging.
    """

    def __init__(self, message: str, sent: int, raw: bytes):
        super().__init__(message)
        self.sent = sent
        self.raw = raw


class UnexpectedReplyError(PagerError):
    """Reply did not match the documented ``!s<code><n>`` format."""

    def __init__(self, raw: str):
        super().__init__(f"unexpected reply from transmitter: {raw!r}")
        self.raw = raw


class PageRejectedError(PagerError):
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


class QueueFullError(PagerError):
    """Transmitter's internal queue is full (!sg<n>).

    ``processed`` is how many pagers in the request were accepted before
    the queue filled, so callers can avoid double-paging them.
    """

    def __init__(self, processed: int, raw: str):
        super().__init__(
            f"transmitter queue full ({raw}); {processed} pager(s) accepted"
        )
        self.processed = processed
        self.raw = raw


# Names used before 0.4.
TransmitterUnreachable = TransmitterUnreachableError
NoReply = NoReplyError
UnexpectedReply = UnexpectedReplyError
PageRejected = PageRejectedError
QueueFull = QueueFullError
