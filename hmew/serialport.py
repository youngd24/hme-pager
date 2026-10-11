"""Serial port access for the transmitter: 9600 baud, 8N1, no flow control.

Per the HMEW doc: RS-232 at 9600 baud, 8 data bits, 1 stop bit.

Linux/macOS use the standard library only (termios). Elsewhere (Windows) the
pyserial package is used if it is installed. While a port is open it holds an
exclusive lock, so two senders can't interleave commands.
"""

from __future__ import annotations

import errno
import logging
import os
import select
import time

from .errors import TransmitterUnreachableError

log = logging.getLogger("hmew")

BAUD = 9600
LOCK_TIMEOUT = (
    10.0  # seconds to wait for another sender to finish with the port
)


class Port:
    """The operations the sender needs. open_port() returns one of these."""

    def flush_input(self) -> None: ...
    def write(self, data: bytes) -> None: ...
    def read(self, timeout: float) -> bytes: ...
    def close(self) -> None: ...

    def __enter__(self):
        return self

    def __exit__(self, *exc) -> None:
        self.close()


def open_port(device: str, lock_timeout: float = LOCK_TIMEOUT) -> Port:
    if os.name == "posix":
        return PosixPort(device, lock_timeout)
    return PySerialPort(device)


class PosixPort(Port):
    def __init__(self, device: str, lock_timeout: float = LOCK_TIMEOUT):
        import termios  # noqa: F401  (POSIX only; fail here, not at package import)

        self.device = device
        try:
            self.fd = os.open(device, os.O_RDWR | os.O_NOCTTY | os.O_NONBLOCK)
        except OSError as exc:
            hint = ""
            if exc.errno == errno.EACCES:
                hint = (
                    f"; on Ubuntu/Debian add yourself to the dialout group "
                    f"(sudo usermod -aG dialout $USER, then log in again), "
                    f"or check the group with ls -l {device}"
                )
            raise TransmitterUnreachableError(
                f"cannot open serial port {device}: {exc.strerror}{hint}"
            ) from exc
        try:
            self._lock(lock_timeout)
            self._configure()
        except BaseException:
            os.close(self.fd)
            raise
        log.debug("opened %s at %d baud, 8N1, no flow control", device, BAUD)

    def _lock(self, timeout: float) -> None:
        import fcntl

        deadline = time.monotonic() + timeout
        waited = False
        while True:
            try:
                fcntl.flock(self.fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                if waited:
                    log.debug("got the lock on %s", self.device)
                return
            except BlockingIOError:
                if time.monotonic() >= deadline:
                    raise TransmitterUnreachableError(
                        f"serial port {self.device} is in use by another "
                        "sender "
                        f"(waited {timeout:.0f} s)"
                    ) from None
                if not waited:
                    log.debug(
                        "%s is in use by another sender; waiting", self.device
                    )
                    waited = True
                time.sleep(0.1)

    def _configure(self) -> None:
        import termios

        iflag, oflag, cflag, lflag, _ispeed, _ospeed, cc = termios.tcgetattr(
            self.fd
        )
        # Raw mode: no line editing, echo, signals, CR/LF translation or
        # software flow control.
        iflag &= ~(
            termios.IGNBRK
            | termios.BRKINT
            | termios.PARMRK
            | termios.ISTRIP
            | termios.INLCR
            | termios.IGNCR
            | termios.ICRNL
            | termios.IXON
            | termios.IXOFF
            | termios.IXANY
        )
        oflag &= ~termios.OPOST
        lflag &= ~(
            termios.ECHO
            | termios.ECHONL
            | termios.ICANON
            | termios.ISIG
            | termios.IEXTEN
        )
        # 8 data bits, no parity, 1 stop bit, no hardware flow control,
        # ignore modem lines.
        cflag &= ~(
            termios.CSIZE
            | termios.PARENB
            | termios.CSTOPB
            | getattr(termios, "CRTSCTS", 0)
        )
        cflag |= termios.CS8 | termios.CREAD | termios.CLOCAL
        cc[termios.VMIN] = 0
        cc[termios.VTIME] = 0
        termios.tcsetattr(
            self.fd,
            termios.TCSANOW,
            [iflag, oflag, cflag, lflag, termios.B9600, termios.B9600, cc],
        )

    def flush_input(self) -> None:
        import termios

        termios.tcflush(self.fd, termios.TCIFLUSH)

    def write(self, data: bytes) -> None:
        import termios

        view = memoryview(data)
        while view:
            _, ready, _ = select.select([], [self.fd], [], 5.0)
            if not ready:
                raise TransmitterUnreachableError(
                    f"serial port {self.device}: write timed out"
                )
            n = os.write(self.fd, view)
            view = view[n:]
        termios.tcdrain(self.fd)  # wait until the bytes have actually gone out

    def read(self, timeout: float) -> bytes:
        ready, _, _ = select.select([self.fd], [], [], max(0.0, timeout))
        if not ready:
            return b""
        try:
            return os.read(self.fd, 256)
        except BlockingIOError:
            return b""

    def close(self) -> None:
        if self.fd is not None:
            os.close(self.fd)  # also releases the lock
            self.fd = None


class PySerialPort(Port):
    """Fallback for platforms without termios (Windows). Needs pyserial."""

    def __init__(self, device: str):
        try:
            import serial  # pyserial
        except ImportError:
            raise TransmitterUnreachableError(
                "serial sending on this platform needs the pyserial package "
                "(pip install pyserial); on Linux it works without it"
            ) from None
        self.device = device
        try:
            self.s = serial.Serial(
                device,
                BAUD,
                bytesize=8,
                parity="N",
                stopbits=1,
                rtscts=False,
                xonxoff=False,
                timeout=0.2,
            )
        except serial.SerialException as exc:
            raise TransmitterUnreachableError(
                f"cannot open serial port {device}: {exc}"
            ) from exc
        log.debug(
            "opened %s at %d baud, 8N1, no flow control (pyserial)",
            device,
            BAUD,
        )

    def flush_input(self) -> None:
        self.s.reset_input_buffer()

    def write(self, data: bytes) -> None:
        self.s.write(data)
        self.s.flush()

    def read(self, timeout: float) -> bytes:
        self.s.timeout = max(0.0, timeout)
        return self.s.read(256)

    def close(self) -> None:
        self.s.close()
