"""Client for the HME Wireless iStation paging transmitter, over HTTP or serial (RS-232)."""

import logging

from .config import ConfigError
from .errors import (
    NoReply,
    PageRejected,
    PagerError,
    QueueFull,
    TransmitterHTTPError,
    TransmitterUnreachable,
    UnexpectedReply,
    ValidationError,
)
from .http_client import HttpTransmitter, PagerClient, parse_reply
from .models import Baud, PageType, SendResult, capcode_to_pager, pager_to_capcode
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
    "TransmitterUnreachable",
    "TransmitterHTTPError",
    "UnexpectedReply",
    "PageRejected",
    "QueueFull",
    "NoReply",
    "ConfigError",
]

# Library logging (logger "hmew") is silent unless the application configures it.
logging.getLogger("hmew").addHandler(logging.NullHandler())
