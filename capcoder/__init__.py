"""Mockorola Capcoder: a virtual pager that shows POCSAG pages for one capcode
on a Motorola Advisor-style screen. (Formerly "vpager".)

Audio arrives over UDP (e.g. rtl_fm piped into netcat), multimon-ng
decodes it, and pages for the configured capcode are shown in a browser
page drawn to look like the pager.
Stdlib only.
"""

__version__ = "0.3"
