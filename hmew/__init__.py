"""Client for the HME Wireless iStation paging transmitter (HTTP interface)."""

import logging

from .client import PagerClient, parse_reply
from .errors import (
    PageRejected,
    PagerError,
    QueueFull,
    TransmitterHTTPError,
    TransmitterUnreachable,
    UnexpectedReply,
    ValidationError,
)
from .models import Baud, PageType, SendResult, capcode_to_pager, pager_to_capcode

# Library logging (logger "hmew") is silent unless the application configures it.
logging.getLogger("hmew").addHandler(logging.NullHandler())

__all__ = [
    "PagerClient",
    "parse_reply",
    "PageType",
    "Baud",
    "SendResult",
    "capcode_to_pager",
    "pager_to_capcode",
    "PagerError",
    "ValidationError",
    "TransmitterHTTPError",
    "TransmitterUnreachable",
    "UnexpectedReply",
    "PageRejected",
    "QueueFull",
]
