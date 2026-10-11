"""Tests for hmew message checks and the pager.py command line.

The command-line tests send to a fake transmitter on 127.0.0.1, never the real unit.
"""

import contextlib
import io
import os
import threading
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer
from unittest import mock
from urllib.parse import parse_qs, urlsplit

import pager
from hmew import PageType, ValidationError
from hmew.models import validate_message


class MessageTests(unittest.TestCase):
    def ok(self, msg, kind):
        self.assertEqual(validate_message(msg, kind), msg)

    def bad(self, msg, kind, fragment):
        with self.assertRaises(ValidationError) as cm:
            validate_message(msg, kind)
        self.assertIn(fragment, str(cm.exception))

    def test_numeric_allowed(self):
        for msg in ("5551212", "555-1212", "[911] U", "", "1" * 20):
            self.ok(msg, PageType.VIBE_NUMERIC)

    def test_numeric_rejects_letters_with_hint(self):
        self.bad("555-CALL", PageType.VIBE_NUMERIC, "send text as alpha")
        self.bad("u", PageType.VIBE_NUMERIC, "'u'")   # only capital U means urgent

    def test_numeric_rejects_trailing_newline(self):
        # the old ^...$ regex let this through
        self.bad("5551212\n", PageType.VIBE_NUMERIC, "'\\n'")

    def test_numeric_rejects_other_symbols_and_length(self):
        self.bad("555.1212", PageType.VIBE_NUMERIC, "'.'")
        self.bad("1" * 21, PageType.VIBE_NUMERIC, "max 20")

    def test_alpha_allowed(self):
        for msg in ("hello", "Barcode Error Aisle 3", "5551212", "a~!@#$%^&*()", "x" * 128):
            self.ok(msg, PageType.ALPHA)

    def test_alpha_rejects_control_and_non_ascii(self):
        self.bad("line1\nline2", PageType.ALPHA, "'\\n'")
        self.bad("tab\there", PageType.ALPHA, "'\\t'")
        self.bad("café", PageType.ALPHA, "'é'")

    def test_alpha_rejects_empty_and_long(self):
        self.bad("", PageType.ALPHA, "empty")
        self.bad("   ", PageType.ALPHA, "empty")
        self.bad("x" * 129, PageType.ALPHA, "max 128")


class FakeTransmitter:
    """Answers send_page.php like the iStation and records each request."""

    def __init__(self, reply="!sc1", status=200):
        self.requests = []
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                outer.requests.append(self.path)
                body = reply.encode()
                self.send_response(status)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *a):
                pass

        self.server = HTTPServer(("127.0.0.1", 0), Handler)
        self.host = f"127.0.0.1:{self.server.server_address[1]}"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def close(self):
        self.server.shutdown()
        self.server.server_close()

    def last_query(self):
        q = urlsplit(self.requests[-1]).query
        return {k: v[0] for k, v in parse_qs(q).items()}


class CommandLineTests(unittest.TestCase):
    def setUp(self):
        self.tx = FakeTransmitter()
        env = {k: v for k, v in os.environ.items() if k != "HMEWHOST"}
        self.env = mock.patch.dict(os.environ, env, clear=True)
        self.env.start()

    def tearDown(self):
        self.env.stop()
        self.tx.close()

    def run_cli(self, *argv):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            try:
                code = pager.main(list(argv))
            except SystemExit as e:   # argparse usage errors
                code = e.code
        return code, out.getvalue(), err.getvalue()

    def test_numeric_page(self):
        code, out, _ = self.run_cli("-n", "-p", "3", "-h", self.tx.host, "555-1212")
        self.assertEqual(code, 0)
        q = self.tx.last_query()
        self.assertEqual((q["pager"], q["type"], q["msg"]), ("3", "1", "555-1212"))
        self.assertIn("!sc1", out)

    def test_alpha_page_long_options_and_words_joined(self):
        code, _, _ = self.run_cli("--alpha", "--pager", "7", "--host", self.tx.host, "Barcode", "Error", "Aisle", "3")
        self.assertEqual(code, 0)
        q = self.tx.last_query()
        self.assertEqual((q["pager"], q["type"], q["msg"]), ("7", "2", "Barcode Error Aisle 3"))

    def test_options_after_message(self):
        code, _, _ = self.run_cli("hello", "-a", "-p", "1", "-h", self.tx.host)
        self.assertEqual(code, 0)
        self.assertEqual(self.tx.last_query()["msg"], "hello")

    def test_host_from_environment(self):
        os.environ["HMEWHOST"] = self.tx.host
        code, _, _ = self.run_cli("-n", "-p", "1", "5551212")
        self.assertEqual(code, 0)

    def test_alpha_and_numeric_are_mutually_exclusive(self):
        code, _, err = self.run_cli("-a", "-n", "-p", "1", "-h", self.tx.host, "x")
        self.assertEqual(code, 2)
        self.assertIn("mutually exclusive", err)
        self.assertIn("--help", err)
        self.assertEqual(self.tx.requests, [])

    def test_kind_required(self):
        code, _, err = self.run_cli("-p", "1", "-h", self.tx.host, "x")
        self.assertEqual(code, 2)
        self.assertIn("-a/--alpha or -n/--numeric", err)

    def test_pager_required_and_checked(self):
        self.assertEqual(self.run_cli("-n", "-h", self.tx.host, "1")[0], 2)
        for bad in ("0", "1000", "three"):
            code, _, err = self.run_cli("-n", "-p", bad, "-h", self.tx.host, "1")
            self.assertEqual(code, 2, bad)
            self.assertIn("pager must be", err)
        self.assertEqual(self.tx.requests, [])

    def test_message_required(self):
        self.assertEqual(self.run_cli("-n", "-p", "1", "-h", self.tx.host)[0], 2)

    def test_bad_numeric_message_not_sent(self):
        code, _, err = self.run_cli("-n", "-p", "1", "-h", self.tx.host, "CALL", "ME")
        self.assertEqual(code, 2)
        self.assertIn("send text as alpha", err)
        self.assertEqual(self.tx.requests, [])

    def test_no_host(self):
        code, _, err = self.run_cli("-n", "-p", "1", "5551212")
        self.assertEqual(code, 2)
        self.assertIn("-h/--host", err)

    def test_http_error_status_is_not_called_unreachable(self):
        self.tx.close()
        self.tx = FakeTransmitter(reply="Not Found", status=404)
        code, _, err = self.run_cli("-n", "-p", "1", "-h", self.tx.host, "1")
        self.assertEqual(code, 1)
        self.assertIn("HTTP 404", err)
        self.assertNotIn("cannot reach", err)

    def test_unreachable(self):
        port = self.tx.host.rsplit(":", 1)[1]
        self.tx.close()   # nothing listens there now
        self.tx = FakeTransmitter()
        code, _, err = self.run_cli("-n", "-p", "1", "-h", f"127.0.0.1:{port}", "1")
        self.assertEqual(code, 1)
        self.assertIn("cannot reach", err)

    def test_verbose_shows_request_and_reply(self):
        code, out, err = self.run_cli("-v", "-n", "-p", "3", "-h", self.tx.host, "555-1212")
        self.assertEqual(code, 0)
        self.assertIn("from -h/--host", err)
        self.assertIn("GET http://127.0.0.1", err)
        self.assertIn("send_page.php?pager=3&type=1&msg=555-1212", err)
        self.assertIn("reply '!sc1' (HTTP 200)", err)
        self.assertIn("!sc1", out)   # result line stays on stdout

    def test_quiet_without_verbose(self):
        code, _, err = self.run_cli("-n", "-p", "3", "-h", self.tx.host, "555-1212")
        self.assertEqual((code, err), (0, ""))

    def test_transmitter_rejection_is_reported(self):
        self.tx.close()
        self.tx = FakeTransmitter(reply="!se0")
        code, _, err = self.run_cli("-n", "-p", "1", "-h", self.tx.host, "1")
        self.assertEqual(code, 1)
        self.assertIn("bad parameter value", err)


if __name__ == "__main__":
    unittest.main()
