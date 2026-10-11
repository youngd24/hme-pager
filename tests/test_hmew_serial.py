"""Tests for serial sending: Scope command bytes, SerialTransmitter, pager.py -s.

Nothing here touches a real serial port except PosixPortTests, which use a
pseudo-terminal pair (Linux/macOS only; skipped on Windows).
"""

import contextlib
import io
import os
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

import pager
from hmew import NoReply, Page, PageType, SerialTransmitter, ValidationError, HttpTransmitter
from hmew import scope
from hmew.models import Baud, validate_capcode


class FakePort:
    """Stands in for a serial port: records writes, answers each with ``reply``."""

    def __init__(self, replies=(b"OK\r\n",)):
        self.replies = list(replies)
        self.written = []
        self.pending = b""
        self.closed = False

    def __call__(self, device):        # used as the open_port factory
        self.device = device
        return self

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.closed = True

    def flush_input(self):
        self.pending = b""

    def write(self, data):
        self.written.append(data)
        self.pending = self.replies.pop(0) if self.replies else b""

    def read(self, timeout):
        data, self.pending = self.pending, b""
        if not data:
            time.sleep(min(timeout, 0.01))
        return data


class ScopeCommandTests(unittest.TestCase):
    def test_alpha(self):
        self.assertEqual(scope.build_command(PageType.ALPHA, 870008, "Test page"), b"AF0870008ATest page\r")

    def test_numeric_padding_and_beep_letters(self):
        self.assertEqual(scope.build_command(PageType.VIBE_NUMERIC, 8, "5551212", beep=4), b"NF0000008D5551212\r")
        self.assertEqual(scope.build_command(PageType.VIBE_NUMERIC, 870024, "1", beep=2), b"NF0870024B1\r")

    def test_512_baud_leaves_out_f(self):
        self.assertEqual(scope.build_command(PageType.ALPHA, 870008, "x", baud=Baud.B512), b"A0870008Ax\r")

    def test_cr_in_message_rejected(self):
        # a CR would end the command early; the alpha check refuses control characters
        with self.assertRaises(ValidationError):
            scope.build_command(PageType.ALPHA, 870008, "one\rtwo")

    def test_ack(self):
        self.assertTrue(scope.is_ack(b"OK\r\n"))
        self.assertFalse(scope.is_ack(b""))


class CapcodeTests(unittest.TestCase):
    def test_valid(self):
        for c in (8, 870008, 2007663, 2007672, 2097143):
            self.assertEqual(validate_capcode(c), c)

    def test_reserved_and_out_of_range(self):
        for c in (0, 7, 2007664, 2007671, 2045056, 2045063, 2097144, 9999999):
            with self.assertRaises(ValidationError, msg=c):
                validate_capcode(c)


class SerialTransmitterTests(unittest.TestCase):
    def test_send_by_capcode(self):
        port = FakePort()
        r = SerialTransmitter("/dev/x", open_port=port).send(
            Page(PageType.ALPHA, "Test page", capcodes=(870008,)))
        self.assertEqual(port.written, [b"AF0870008ATest page\r"])
        self.assertEqual((r.code, r.count), ("OK", 1))
        self.assertTrue(port.closed)

    def test_send_by_pager_needs_base(self):
        port = FakePort()
        SerialTransmitter("/dev/x", base=87, open_port=port).send(
            Page(PageType.VIBE_NUMERIC, "5551212", pagers=(1,)))
        self.assertEqual(port.written, [b"NF0870008A5551212\r"])
        with self.assertRaisesRegex(ValidationError, "base ID"):
            SerialTransmitter("/dev/x", open_port=FakePort()).send(
                Page(PageType.VIBE_NUMERIC, "1", pagers=(1,)))

    def test_group_is_one_command_per_capcode(self):
        port = FakePort(replies=[b"OK\r\n"] * 3)
        r = SerialTransmitter("/dev/x", base=87, open_port=port).send(
            Page(PageType.ALPHA, "hi", pagers=(1, 2, 3)))
        self.assertEqual(port.written, [b"AF0870008Ahi\r", b"AF0870016Ahi\r", b"AF0870024Ahi\r"])
        self.assertEqual(r.count, 3)

    def test_silence_is_no_reply_with_sent_count(self):
        port = FakePort(replies=[b"OK\r\n", b""])      # second command gets nothing back
        tx = SerialTransmitter("/dev/x", base=87, timeout=0.2, open_port=port)
        with self.assertRaises(NoReply) as cm:
            tx.send(Page(PageType.ALPHA, "hi", pagers=(1, 2, 3)))
        self.assertEqual(cm.exception.sent, 1)
        self.assertIn("capcode 0870016", str(cm.exception))
        self.assertIn("1 of 3 capcodes were sent", str(cm.exception))
        self.assertEqual(len(port.written), 2)        # stopped; the third wasn't sent

    def test_http_refuses_capcodes(self):
        with self.assertRaisesRegex(ValidationError, "pager number"):
            HttpTransmitter("h").send(Page(PageType.ALPHA, "x", capcodes=(870008,)))


class SerialCommandLineTests(unittest.TestCase):
    def setUp(self):
        # Never read the real ~/.hme-pager/config: point the default at an empty temp dir.
        self.tmp = tempfile.TemporaryDirectory()
        self.config_path = Path(self.tmp.name) / "config"
        self.cfg = mock.patch("hmew.config.DEFAULT_PATH", self.config_path)
        self.cfg.start()
        self.port = FakePort()
        self.patch = mock.patch("hmew.serialport.open_port", self.port)
        self.patch.start()

    def tearDown(self):
        self.patch.stop()
        self.cfg.stop()
        self.tmp.cleanup()

    def write_config(self, text):
        self.config_path.write_text("[pager]\n" + text, encoding="utf-8")

    def run_cli(self, *argv):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            try:
                code = pager.main(list(argv))
            except SystemExit as e:
                code = e.code
        return code, out.getvalue(), err.getvalue()

    def test_capcode_over_serial(self):
        code, out, _ = self.run_cli("-a", "-c", "0870008", "-s", "/dev/ttyS0", "Test", "page")
        self.assertEqual(code, 0)
        self.assertEqual(self.port.written, [b"AF0870008ATest page\r"])
        self.assertEqual(self.port.device, "/dev/ttyS0")
        self.assertIn("capcode 0870008 via serial /dev/ttyS0", out)

    def test_pager_with_base_over_serial(self):
        code, out, _ = self.run_cli("-n", "-p", "1", "--base", "087", "-s", "/dev/ttyS0", "5551212")
        self.assertEqual(code, 0)
        self.assertEqual(self.port.written, [b"NF0870008A5551212\r"])
        self.assertIn("pager 1 (capcode 0870008)", out)

    def test_everything_from_config(self):
        self.write_config("mode = serial\nserial_port = /dev/ttyUSB0\nbase = 087\ntype = numeric\n")
        code, out, _ = self.run_cli("-p", "1", "5551212")
        self.assertEqual(code, 0)
        self.assertEqual(self.port.device, "/dev/ttyUSB0")
        self.assertEqual(self.port.written, [b"NF0870008A5551212\r"])
        self.assertIn("numeric page to pager 1", out)

    def test_pager_over_serial_without_base(self):
        code, _, err = self.run_cli("-n", "-p", "1", "-s", "/dev/ttyS0", "5551212")
        self.assertEqual(code, 2)
        self.assertIn("--base", err)
        self.assertEqual(self.port.written, [])

    def test_capcode_over_http_refused(self):
        code, _, err = self.run_cli("-n", "-c", "0870008", "-h", "192.0.2.1", "5551212")
        self.assertEqual(code, 2)
        self.assertIn("use -p/--pager", err)

    def test_host_and_serial_mutually_exclusive(self):
        code, _, err = self.run_cli("-n", "-p", "1", "-h", "192.0.2.1", "-s", "/dev/ttyS0", "1")
        self.assertEqual(code, 2)
        self.assertIn("mutually exclusive", err)

    def test_pager_and_capcode_mutually_exclusive(self):
        code, _, err = self.run_cli("-n", "-p", "1", "-c", "0870008", "-s", "/dev/ttyS0", "1")
        self.assertEqual(code, 2)
        self.assertIn("mutually exclusive", err)

    def test_mode_and_address_flags_mutually_exclusive(self):
        code, _, err = self.run_cli("-n", "-p", "1", "-m", "serial", "-h", "192.0.2.1", "1")
        self.assertEqual(code, 2)
        self.assertIn("-m/--mode and -h/--host are mutually exclusive", err)

    def test_serial_flag_beats_config_network_mode(self):
        self.write_config("mode = network\nhost = 192.0.2.1\n")
        code, _, _ = self.run_cli("-a", "-c", "0870008", "-s", "/dev/ttyS1", "x")
        self.assertEqual(code, 0)
        self.assertEqual(self.port.device, "/dev/ttyS1")

    def test_mode_flag_uses_configured_port(self):
        self.write_config("mode = network\nhost = 192.0.2.1\nserial_port = /dev/ttyS3\n")
        code, _, _ = self.run_cli("-a", "-c", "0870008", "-m", "serial", "x")
        self.assertEqual(code, 0)
        self.assertEqual(self.port.device, "/dev/ttyS3")

    def test_serial_mode_without_port(self):
        self.write_config("mode = serial\n")
        code, _, err = self.run_cli("-a", "-c", "0870008", "x")
        self.assertEqual(code, 2)
        self.assertIn("set serial_port in", err)

    def test_base_flag_beats_config(self):
        self.write_config("base = 017\n")
        code, _, _ = self.run_cli("-n", "-p", "1", "--base", "087", "-s", "/dev/ttyS0", "1")
        self.assertEqual(code, 0)
        self.assertEqual(self.port.written, [b"NF0870008A1\r"])

    def test_bad_capcode_and_base(self):
        for argv in (("-c", "2097144"), ("-c", "12345678"), ("-c", "abc")):
            code, _, _ = self.run_cli("-n", *argv, "-s", "/dev/ttyS0", "1")
            self.assertEqual(code, 2, argv)
        code, _, err = self.run_cli("-n", "-p", "1", "--base", "300", "-s", "/dev/ttyS0", "1")
        self.assertEqual(code, 2)
        self.assertIn("base ID", err)

    def test_no_reply_exit_1(self):
        self.port.replies = [b""]
        code, _, err = self.run_cli_with_timeout("-a", "-c", "0870008", "-s", "/dev/ttyS0", "x")
        self.assertEqual(code, 1)
        self.assertIn("no OK from the transmitter", err)

    def run_cli_with_timeout(self, *argv):
        original = SerialTransmitter.__init__

        def short(s, device, base=None, timeout=3.0, open_port=None):
            original(s, device, base=base, timeout=0.2, open_port=open_port)

        with mock.patch.object(SerialTransmitter, "__init__", short):
            return self.run_cli(*argv)

    def test_verbose_shows_bytes(self):
        code, _, err = self.run_cli("-v", "-a", "-c", "0870008", "-s", "/dev/ttyS0", "Test")
        self.assertEqual(code, 0)
        self.assertIn("serial port /dev/ttyS0 (from -s/--serial)", err)
        self.assertIn("mode serial (from -s/--serial)", err)
        self.assertIn("write b'AF0870008ATest\\r'", err)
        self.assertIn("reply b'OK\\r\\n'", err)


@unittest.skipUnless(os.name == "posix", "needs termios and a pseudo-terminal (Linux/macOS)")
class PosixPortTests(unittest.TestCase):
    """Real termios code against a pty pair; a thread plays the transmitter."""

    def setUp(self):
        import pty
        self.master, self.slave = pty.openpty()
        self.device = os.ttyname(self.slave)
        # Keep the slave side open: on Linux, reading the master fails with EIO
        # while no slave is open, which would end the fake transmitter early.
        self.received = b""

    def tearDown(self):
        os.close(self.slave)
        os.close(self.master)

    def transmitter(self, reply=b"OK\r\n"):
        def run():
            buf = b""
            deadline = time.monotonic() + 3
            while b"\r" not in buf and time.monotonic() < deadline:
                try:
                    buf += os.read(self.master, 256)
                except OSError:
                    break
            self.received = buf
            if reply:
                os.write(self.master, reply)
        t = threading.Thread(target=run, daemon=True)
        t.start()
        return t

    def test_send_and_ack(self):
        t = self.transmitter()
        r = SerialTransmitter(self.device, timeout=2).send(
            Page(PageType.ALPHA, "Test page", capcodes=(870008,)))
        t.join(3)
        self.assertEqual(self.received, b"AF0870008ATest page\r")
        self.assertEqual(r.code, "OK")

    def test_port_settings(self):
        import termios
        from hmew.serialport import PosixPort
        with PosixPort(self.device) as port:
            iflag, oflag, cflag, lflag, ispeed, ospeed, cc = termios.tcgetattr(port.fd)
        self.assertEqual((ispeed, ospeed), (termios.B9600, termios.B9600))
        self.assertEqual(cflag & termios.CSIZE, termios.CS8)
        self.assertFalse(cflag & (termios.PARENB | termios.CSTOPB))
        self.assertFalse(lflag & (termios.ICANON | termios.ECHO))
        self.assertFalse(iflag & (termios.IXON | termios.IXOFF | termios.ICRNL))

    def test_silence_times_out(self):
        t = self.transmitter(reply=b"")
        with self.assertRaises(NoReply):
            SerialTransmitter(self.device, timeout=0.5).send(
                Page(PageType.ALPHA, "x", capcodes=(870008,)))
        t.join(3)

    def test_permission_denied_mentions_dialout(self):
        import errno
        from hmew import TransmitterUnreachable
        from hmew.serialport import PosixPort
        denied = PermissionError(errno.EACCES, "Permission denied")
        with mock.patch("os.open", side_effect=denied):
            with self.assertRaisesRegex(TransmitterUnreachable, "Permission denied; .*dialout"):
                PosixPort("/dev/ttyS0")

    def test_second_sender_waits_then_gives_up(self):
        from hmew import TransmitterUnreachable
        from hmew.serialport import PosixPort
        with PosixPort(self.device):
            start = time.monotonic()
            with self.assertRaisesRegex(TransmitterUnreachable, "in use by another sender"):
                PosixPort(self.device, lock_timeout=0.3)
            self.assertGreaterEqual(time.monotonic() - start, 0.3)


if __name__ == "__main__":
    unittest.main()
