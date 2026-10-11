"""UDP audio in, multimon-ng decode lines out.

Adapted from mmng-ui by lingfish (https://github.com/lingfish/mmng-ui),
GPL-3.0: UDPHandler and PocsagFeed.stream_subprocess in mmng_ui/pocsag.py,
and its multimon-ng arguments.

Changes from the original:
- no Textual; status and decoded lines go to Core through plain calls
- checks the pipe's write buffer instead of calling stdin.drain() without
  awaiting it, and drops audio (logged) if multimon-ng falls behind
- reads stderr while multimon-ng runs, not only after stdout closes
- restarts multimon-ng if it exits; keeps listening if it is missing
- listens on a dual-stack socket so IPv4 and IPv6 senders both work
- POCSAG only (no FLEX), no sox stage, no JSON mode, no -u
"""

from __future__ import annotations

import asyncio
import logging
import os
import shutil
import socket
import sys
import threading
from asyncio.subprocess import PIPE
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from .core import Core

log = logging.getLogger("capcoder.receiver")
mmng_log = logging.getLogger("capcoder.multimon")

IDLE_AFTER = 5.0            # seconds without packets before we call the feed idle
RESTART_DELAY = 3.0         # seconds before restarting multimon-ng after it exits
MAX_PIPE_BUFFER = 4 << 20   # bytes queued for multimon-ng before we start dropping audio
STATS_EVERY = 60.0
BIND_RETRY = 5.0            # seconds between attempts to open a busy UDP port

DECODE_MODES = ("alpha", "numeric", "auto", "standard")

# Searched after PATH when the binary is given by bare name.
EXTRA_DIRS = [r"C:\rtl-sdr"] if sys.platform == "win32" else []


def find_binary(binary: str):
    """Full path to binary: on PATH, as given, or in EXTRA_DIRS. None if not found."""
    found = shutil.which(binary)
    if found is None and EXTRA_DIRS and os.path.basename(binary) == binary:
        found = shutil.which(binary, path=os.pathsep.join(EXTRA_DIRS))
    return found


def multimon_args(mode: str = "alpha", charset: str = "US") -> list[str]:
    """mmng-ui's arguments, POCSAG only. mode 'standard' leaves out -f."""
    args = ["-a", "POCSAG512", "-a", "POCSAG1200", "-a", "POCSAG2400"]
    if mode != "standard":
        args += ["-f", mode]
    # mmng-ui also passes -u (prune unlikely POCSAG decodes); left out, it made the output messier here.
    args += ["-t", "raw", "-q", "--timestamp", "-p", "-C", charset, "-"]
    return args


def _check_ipv4_free(port: int) -> None:
    """Raise OSError if something already has the IPv4 side of the port.

    Windows lets a dual-stack socket bind a port that another program holds on
    IPv4 only; IPv4 audio would then go to that program, not to us.
    """
    probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        if sys.platform == "win32":
            probe.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        probe.bind(("0.0.0.0", port))
    finally:
        probe.close()


def _udp_socket(bind: str, port: int) -> socket.socket:
    sock = None
    if bind == "::":
        _check_ipv4_free(port)
        try:
            sock = socket.socket(socket.AF_INET6, socket.SOCK_DGRAM)
            sock.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_V6ONLY, 0)
        except (OSError, AttributeError) as e:
            log.info("IPv6 dual-stack not available (%s), listening on IPv4 only", e)
            if sock is not None:
                sock.close()
            sock, bind = None, "0.0.0.0"
    if sock is None:
        family = socket.AF_INET6 if ":" in bind else socket.AF_INET
        sock = socket.socket(family, socket.SOCK_DGRAM)
    try:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 1 << 20)
        if sys.platform == "win32":
            # Stop another program from binding the same port alongside us.
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        sock.bind((bind, port))
    except OSError:
        sock.close()
        raise
    return sock


class _AudioProtocol(asyncio.DatagramProtocol):
    def __init__(self, receiver: "Receiver"):
        self.r = receiver

    def datagram_received(self, data: bytes, addr) -> None:
        self.r.on_audio(data, addr)

    def error_received(self, exc: Exception) -> None:
        log.warning("UDP error: %s", exc)


class Receiver:
    def __init__(self, core: "Core", port: int, bind: str, binary: str, args: list[str]):
        self.core = core
        self.port = port
        self.bind = bind
        self.binary = binary
        self.args = args
        self._thread: Optional[threading.Thread] = None
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._stop: Optional[asyncio.Event] = None
        self._proc: Optional[asyncio.subprocess.Process] = None
        self._transport: Optional[asyncio.DatagramTransport] = None
        self._warned_missing = False
        self._receiving = False
        self._sender: Optional[str] = None
        self._last_audio = 0.0
        self.packets = 0
        self.bytes = 0
        self.dropped = 0
        self._dropping = False

    # ---- thread control (called from the main thread) ----

    def start(self) -> None:
        self._thread = threading.Thread(target=self._thread_main, name="receiver", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        loop, stop = self._loop, self._stop
        if loop is not None and stop is not None and not loop.is_closed():
            try:
                loop.call_soon_threadsafe(stop.set)
            except RuntimeError:
                pass
        if self._thread is not None:
            self._thread.join(timeout=5)

    def _thread_main(self) -> None:
        try:
            asyncio.run(self._main())
        except Exception:
            log.exception("receiver crashed")
            self.core.set_status(udp="error", decoder="error")

    # ---- asyncio side ----

    async def _main(self) -> None:
        self._loop = asyncio.get_running_loop()
        self._stop = asyncio.Event()
        self._transport = None
        listener = asyncio.create_task(self._listen())
        monitor = asyncio.create_task(self._monitor())
        try:
            while not self._stop.is_set():
                await self._run_decoder()
                if self._stop.is_set():
                    break
                try:
                    await asyncio.wait_for(self._stop.wait(), RESTART_DELAY)
                except asyncio.TimeoutError:
                    pass
        finally:
            listener.cancel()
            monitor.cancel()
            if self._transport is not None:
                self._transport.close()
            proc = self._proc
            if proc is not None and proc.returncode is None:
                proc.kill()
            log.info("receiver stopped")

    async def _listen(self) -> None:
        """Open the UDP port, retrying until it is free (e.g. another program still holds it)."""
        failures = 0
        while not self._stop.is_set():
            try:
                sock = _udp_socket(self.bind, self.port)
                self._transport, _ = await self._loop.create_datagram_endpoint(
                    lambda: _AudioProtocol(self), sock=sock)
            except OSError as e:
                failures += 1
                if failures == 1:
                    log.error(
                        "cannot listen on UDP port %d: %s. Is another program (or another capcoder) "
                        "using it? Retrying every %.0f s.", self.port, e, BIND_RETRY)
                else:
                    log.debug("UDP port %d still unavailable (attempt %d): %s", self.port, failures, e)
                self.core.set_status(udp=f"port {self.port} in use, retrying", udp_port=self.port)
                try:
                    await asyncio.wait_for(self._stop.wait(), BIND_RETRY)
                except asyncio.TimeoutError:
                    pass
                continue
            if failures:
                log.info("UDP port %d is free now (after %d failed attempts)", self.port, failures)
            log.info("listening for audio on UDP port %d (bind %s)", self.port, self.bind)
            self.core.set_status(udp="idle", udp_port=self.port)
            return

    async def _run_decoder(self) -> None:
        exe = find_binary(self.binary)
        if exe is None:
            if not self._warned_missing:
                where = " or ".join(["PATH"] + EXTRA_DIRS)
                log.error(
                    "multimon-ng not found (%r in %s). Pass --mmng PATH. "
                    "Decoding is off until it is found; injected test pages still work.",
                    self.binary, where,
                )
                self._warned_missing = True
            self.core.set_status(decoder="missing")
            try:   # look again in ~10 s, counting the restart delay in _main
                await asyncio.wait_for(self._stop.wait(), 10 - RESTART_DELAY)
            except asyncio.TimeoutError:
                pass
            return
        self._warned_missing = False

        log.info("starting multimon-ng: %s %s", exe, " ".join(self.args))
        try:
            proc = await asyncio.create_subprocess_exec(exe, *self.args, stdin=PIPE, stdout=PIPE, stderr=PIPE)
        except OSError as e:
            log.error("could not start multimon-ng: %s", e)
            self.core.set_status(decoder="error")
            return
        self._proc = proc
        log.info("multimon-ng running, pid %d", proc.pid)
        self.core.set_status(decoder="running")

        pumps = asyncio.ensure_future(asyncio.gather(
            self._pump(proc.stdout, self._on_stdout),
            self._pump(proc.stderr, self._on_stderr),
        ))
        stopper = asyncio.ensure_future(self._stop.wait())
        await asyncio.wait({pumps, stopper}, return_when=asyncio.FIRST_COMPLETED)
        if stopper.done() and proc.returncode is None:
            proc.kill()
        stopper.cancel()
        try:
            await asyncio.wait_for(pumps, 5)
        except asyncio.TimeoutError:
            pumps.cancel()
        rc = await proc.wait()
        self._proc = None
        if self._stop.is_set():
            log.info("multimon-ng stopped")
        else:
            log.warning("multimon-ng exited with code %s; restarting in %.0f s", rc, RESTART_DELAY)
            self.core.set_status(decoder="exited")

    async def _pump(self, stream: asyncio.StreamReader, handle) -> None:
        while True:
            raw = await stream.readline()
            if not raw:
                break
            line = raw.decode("utf-8", "replace").rstrip("\r\n")
            if line.strip():
                handle(line)

    def _on_stdout(self, line: str) -> None:
        try:
            self.core.handle_line(line, "multimon-ng")
        except Exception:
            log.exception("error handling decode line %r", line)

    def _on_stderr(self, line: str) -> None:
        mmng_log.info("stderr: %s", line)

    def on_audio(self, data: bytes, addr) -> None:
        self.packets += 1
        self.bytes += len(data)
        self._last_audio = self._loop.time()
        host = addr[0]
        if host.startswith("::ffff:"):
            host = host[7:]
        if host != self._sender:
            self._sender = host
            log.info("audio from %s port %d", host, addr[1])
            self.core.set_status(sender=host)
        if not self._receiving:
            self._receiving = True
            log.info("audio started")
            self.core.set_status(udp="receiving")

        proc = self._proc
        stdin = proc.stdin if proc is not None else None
        if stdin is None or stdin.is_closing():
            self.dropped += 1
            return
        if stdin.transport.get_write_buffer_size() > MAX_PIPE_BUFFER:
            self.dropped += 1
            if not self._dropping:
                log.warning("multimon-ng is not keeping up, dropping audio")
                self._dropping = True
            return
        self._dropping = False
        stdin.write(data)

    async def _monitor(self) -> None:
        last_stats = self._loop.time()
        while True:
            await asyncio.sleep(1)
            now = self._loop.time()
            if self._receiving and now - self._last_audio > IDLE_AFTER:
                self._receiving = False
                log.info("audio stopped (no packets for %.0f s)", IDLE_AFTER)
                self.core.set_status(udp="idle")
            self.core.set_status(publish=False, packets=self.packets)
            if now - last_stats >= STATS_EVERY:
                last_stats = now
                log.debug(
                    "audio stats: %d packets, %d bytes, %d dropped since start",
                    self.packets, self.bytes, self.dropped,
                )
