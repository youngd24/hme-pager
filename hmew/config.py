"""Installation defaults for sending pages, from ~/.hme-pager/config.

INI format, one [pager] section. Every setting is optional; command-line
options override them.

    [pager]
    mode = serial              # network or serial
    host = 192.168.1.100       # for network: host or host:port
    serial_port = /dev/ttyS0   # for serial
    base = 087                 # base ID, to page by pager number over serial
    type = alpha               # alpha or numeric
    verbose = false            # true or false
"""

from __future__ import annotations

import configparser
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Optional, Union

from .errors import PagerError, ValidationError
from .models import validate_base

SECTION = "pager"
MODES = ("network", "serial")
TYPES = ("alpha", "numeric")
KEYS = ("mode", "host", "serial_port", "base", "type", "verbose")

# Looked up when load() runs, so tests can point it elsewhere.
DEFAULT_PATH = Path.home() / ".hme-pager" / "config"


class ConfigError(PagerError):
    """The config file is missing (when asked for explicitly), unreadable or has a bad setting."""


@dataclass
class Settings:
    mode: Optional[str] = None          # "network" or "serial"
    host: Optional[str] = None          # "host" or "host:port"
    serial_port: Optional[str] = None
    base: Optional[int] = None
    type: Optional[str] = None          # "alpha" or "numeric"
    verbose: bool = False
    path: Optional[Path] = None         # the file these came from; None if no file
    set_in_file: Dict[str, str] = field(default_factory=dict)   # key -> raw value, for -v


def load(path: Union[str, Path, None] = None) -> Settings:
    """Read settings. With no path, a missing ~/.hme-pager/config just means no defaults."""
    explicit = path is not None
    path = Path(path) if explicit else DEFAULT_PATH
    if not path.is_file():
        if explicit:
            raise ConfigError(f"config file {path} not found")
        return Settings()

    cp = configparser.ConfigParser(inline_comment_prefixes=("#", ";"), interpolation=None)
    try:
        with open(path, encoding="utf-8") as f:
            cp.read_file(f)
    except (OSError, UnicodeDecodeError, configparser.Error) as exc:
        raise ConfigError(f"cannot read {path}: {exc}") from exc

    extra = [s for s in cp.sections() if s != SECTION]
    if extra:
        raise ConfigError(f"{path}: unknown section [{extra[0]}]; settings go under [{SECTION}]")
    if not cp.has_section(SECTION):
        if cp.defaults():
            raise ConfigError(f"{path}: settings must be under a [{SECTION}] section")
        return Settings(path=path)

    s = Settings(path=path)
    section = cp[SECTION]
    for key in section:
        raw = section[key].strip()
        where = f"{path}: {key} = {raw!r}"
        if key not in KEYS:
            raise ConfigError(f"{path}: unknown setting {key!r}; known settings: {', '.join(KEYS)}")
        if not raw:
            raise ConfigError(f"{where}: empty value")
        if key == "mode":
            if raw.lower() not in MODES:
                raise ConfigError(f"{where}: must be network or serial")
            s.mode = raw.lower()
        elif key == "type":
            if raw.lower() not in TYPES:
                raise ConfigError(f"{where}: must be alpha or numeric")
            s.type = raw.lower()
        elif key == "host":
            s.host = raw
        elif key == "serial_port":
            s.serial_port = raw
        elif key == "base":
            try:
                if not raw.isdigit():
                    raise ValidationError("must be digits, e.g. 087")
                s.base = validate_base(int(raw))
            except ValidationError as exc:
                raise ConfigError(f"{where}: {exc}") from None
        elif key == "verbose":
            try:
                s.verbose = section.getboolean(key)
            except ValueError:
                raise ConfigError(f"{where}: must be true or false") from None
        s.set_in_file[key] = raw
    return s
