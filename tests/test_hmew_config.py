"""Tests for ~/.hme-pager/config.

Covers the loader and how pager.py combines it with options.

Uses temporary files only; the real ~/.hme-pager/config is never read.
"""

import contextlib
import io
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import pager
from hmew import config
from tests.test_hmew import FakeTransmitter


class LoaderTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "config"

    def tearDown(self):
        self.tmp.cleanup()

    def load(self, text):
        self.path.write_text(text, encoding="utf-8")
        return config.load(self.path)

    def bad(self, text, fragment):
        with self.assertRaises(config.ConfigError) as cm:
            self.load(text)
        self.assertIn(fragment, str(cm.exception))

    def test_all_settings_with_comments(self):
        s = self.load(
            "# defaults for this machine\n"
            "[pager]\n"
            "mode = Serial            # network or serial\n"
            "host = 192.168.1.100:8080\n"
            "serial_port = /dev/ttyS0\n"
            "base = 087\n"
            "type = numeric\n"
            "verbose = yes\n"
        )
        self.assertEqual(
            (s.mode, s.host, s.serial_port, s.base, s.type, s.verbose),
            (
                "serial",
                "192.168.1.100:8080",
                "/dev/ttyS0",
                87,
                "numeric",
                True,
            ),
        )
        self.assertEqual(s.path, self.path)

    def test_defaults_when_empty(self):
        s = self.load("[pager]\n")
        self.assertEqual(
            (s.mode, s.host, s.type, s.verbose), (None, None, None, False)
        )

    def test_missing_default_file_is_fine(self):
        with mock.patch("hmew.config.DEFAULT_PATH", self.path):
            s = config.load()
        self.assertIsNone(s.path)

    def test_missing_explicit_file_is_an_error(self):
        with self.assertRaisesRegex(config.ConfigError, "not found"):
            config.load(self.path)

    def test_typos_and_bad_values(self):
        self.bad("[pager]\nhots = x\n", "unknown setting 'hots'")
        self.bad("[pagers]\nhost = x\n", "unknown section [pagers]")
        self.bad("host = x\n", "cannot read")  # no section header at all
        self.bad("[pager]\nmode = wifi\n", "network or serial")
        self.bad("[pager]\ntype = text\n", "alpha or numeric")
        self.bad("[pager]\nverbose = maybe\n", "true or false")
        self.bad("[pager]\nbase = 300\n", "base ID")
        self.bad("[pager]\nbase = 0x57\n", "digits")
        self.bad("[pager]\nhost =\n", "empty value")


class ConfigCommandLineTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "config"
        self.cfg = mock.patch("hmew.config.DEFAULT_PATH", self.path)
        self.cfg.start()
        self.tx = FakeTransmitter()

    def tearDown(self):
        self.tx.close()
        self.cfg.stop()
        self.tmp.cleanup()

    def write(self, text, path=None):
        (path or self.path).write_text("[pager]\n" + text, encoding="utf-8")

    def run_cli(self, *argv):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            try:
                code = pager.main(list(argv))
            except SystemExit as e:
                code = e.code
        return code, out.getvalue(), err.getvalue()

    def test_just_pager_and_message(self):
        self.write(f"mode = network\nhost = {self.tx.host}\ntype = alpha\n")
        code, out, _ = self.run_cli("-p", "3", "Test", "page")
        self.assertEqual(code, 0)
        q = self.tx.last_query()
        self.assertEqual(
            (q["pager"], q["type"], q["msg"]), ("3", "2", "Test page")
        )
        self.assertIn(f"alpha page to pager 3 via network {self.tx.host}", out)

    def test_options_override_config(self):
        self.write(
            "mode = serial\nserial_port = /dev/nowhere\n"
            "host = 192.0.2.1\ntype = alpha\n"
        )
        code, _, _ = self.run_cli("-n", "-p", "3", "-h", self.tx.host, "555")
        self.assertEqual(code, 0)
        self.assertEqual(self.tx.last_query()["type"], "1")

    def test_mode_network_uses_configured_host(self):
        self.write(f"mode = serial\nhost = {self.tx.host}\ntype = numeric\n")
        code, _, _ = self.run_cli("-m", "network", "-p", "3", "555")
        self.assertEqual(code, 0)

    def test_network_mode_without_host(self):
        self.write("mode = network\ntype = alpha\n")
        code, _, err = self.run_cli("-p", "3", "x")
        self.assertEqual(code, 2)
        self.assertIn("set host in", err)

    def test_no_type_anywhere(self):
        self.write(f"mode = network\nhost = {self.tx.host}\n")
        code, _, err = self.run_cli("-p", "3", "x")
        self.assertEqual(code, 2)
        self.assertIn("or set type in", err)

    def test_verbose_from_config_and_quiet_override(self):
        self.write(
            f"mode = network\nhost = {self.tx.host}\n"
            "type = alpha\nverbose = true\n"
        )
        code, _, err = self.run_cli("-p", "3", "x")
        self.assertEqual(code, 0)
        self.assertIn("type alpha (from config)", err)
        self.assertIn("mode network (from config)", err)
        self.assertIn("GET http://", err)
        code, _, err = self.run_cli("-q", "-p", "3", "x")
        self.assertEqual((code, err), (0, ""))

    def test_verbose_and_quiet_together(self):
        code, _, err = self.run_cli(
            "-v", "-q", "-p", "3", "-a", "-h", self.tx.host, "x"
        )
        self.assertEqual(code, 2)
        self.assertIn("mutually exclusive", err)

    def test_config_option_reads_other_file(self):
        other = Path(self.tmp.name) / "freepbx.conf"
        self.write(
            f"mode = network\nhost = {self.tx.host}\ntype = numeric\n",
            path=other,
        )
        code, _, _ = self.run_cli("--config", str(other), "-p", "3", "555")
        self.assertEqual(code, 0)
        code, _, err = self.run_cli(
            "--config", str(Path(self.tmp.name) / "missing"), "-p", "3", "555"
        )
        self.assertEqual(code, 2)
        self.assertIn("not found", err)

    def test_bad_config_reported_before_sending(self):
        self.write("mode = wifi\n")
        code, _, err = self.run_cli("-a", "-p", "3", "-h", self.tx.host, "x")
        self.assertEqual(code, 2)
        self.assertIn("network or serial", err)
        self.assertEqual(self.tx.requests, [])


if __name__ == "__main__":
    unittest.main()
