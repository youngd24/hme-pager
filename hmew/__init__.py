"""Client for the HME Wireless iStation paging transmitter.

Sends pages over the network (HTTP) or a serial cable (RS-232).
"""

import logging

from .config import ConfigError
from .errors import (
    NoReply,
    NoReplyError,
    PageRejected,
    PageRejectedError,
    PagerError,
    QueueFull,
    QueueFullError,
    TransmitterHTTPError,
    TransmitterUnreachable,
    TransmitterUnreachableError,
    UnexpectedReply,
    UnexpectedReplyError,
    ValidationError,
)
from .http_client import HttpTransmitter, PagerClient, parse_reply
from .models import (
    Baud,
    PageType,
    SendResult,
    capcode_to_pager,
    pager_to_capcode,
)
from .page import Page, Transmitter
from .serial_client import SerialTransmitter

__all__ = [
    "HttpTransmitter",
    "SerialTransmitter",
    "PagerClient",
    "Page",
    "Transmitter",
    "parse_reply",
    "PageType",
    "Baud",
    "SendResult",
    "capcode_to_pager",
    "pager_to_capcode",
    "PagerError",
    "ValidationError",
    "TransmitterUnreachableError",
    "TransmitterHTTPError",
    "UnexpectedReplyError",
    "PageRejectedError",
    "QueueFullError",
    "NoReplyError",
    "ConfigError",
    # names used before 0.4
    "TransmitterUnreachable",
    "UnexpectedReply",
    "PageRejected",
    "QueueFull",
    "NoReply",
]

# Library logging (logger "hmew") is silent unless the application
# configures it.
logging.getLogger("hmew").addHandler(logging.NullHandler())
