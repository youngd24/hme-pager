"""Virtual pager: shows POCSAG pages for one capcode on a Motorola Advisor-style screen.

Audio arrives over UDP (e.g. from SDR++), multimon-ng decodes it, and pages for
the configured capcode are shown in a browser page drawn to look like the pager.
Stdlib only.
"""

__version__ = "0.1.0"
