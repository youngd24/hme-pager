import json
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

from vpager.core import Core, Hub
from vpager.decode import parse_line
from vpager.store import MAX_LOCKED, MAX_PERSONAL, MAX_SLOTS, Store, StoreError


def line(capcode=870024, function=1, kind="Alpha", text="555-1212"):
    return f"POCSAG1200: Address: {capcode:>7}  Function: {function}  {kind}:   {text}<NUL>"


class DecodeTests(unittest.TestCase):
    def test_alpha(self):
        p = parse_line(line())
        self.assertEqual((p.capcode, p.function, p.kind, p.text), (870024, 1, "alpha", "555-1212"))

    def test_numeric(self):
        p = parse_line(line(function=0, kind="Numeric", text="555 1212"))
        self.assertEqual((p.kind, p.text), ("numeric", "555 1212"))

    def test_timestamp_prefix(self):
        p = parse_line("2026-10-10 12:00:01: " + line(text="HELLO"))
        self.assertEqual(p.text, "HELLO")

    def test_address_only_is_tone(self):
        p = parse_line("POCSAG1200: Address:  870024  Function: 1 ")
        self.assertEqual((p.kind, p.text), ("tone", ""))

    def test_charset_fixups(self):
        p = parse_line(line(text="ÄOKÜ<ETX>"))
        self.assertEqual(p.text, "[OK]")

    def test_not_a_page(self):
        self.assertIsNone(parse_line("multimon-ng 1.4.1"))
        self.assertIsNone(parse_line("FLEX|1600/2|..."))


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "state.json"
        self.store = Store(self.path)

    def tearDown(self):
        self.tmp.cleanup()

    def add(self, text="x"):
        return self.store.add(parse_line(line(text=text)), datetime.now().astimezone())

    def test_oldest_unlocked_dropped_when_full(self):
        first = self.add("first")
        second = self.add("second")
        self.store.apply("lock", first["id"])
        for i in range(MAX_SLOTS - 1):
            self.add(f"m{i}")
        ids = [m["id"] for m in self.store.messages]
        self.assertEqual(len(ids), MAX_SLOTS)
        self.assertIn(first["id"], ids)          # locked, kept
        self.assertNotIn(second["id"], ids)      # oldest unlocked, dropped

    def test_lock_limit(self):
        msgs = [self.add(str(i)) for i in range(MAX_LOCKED + 1)]
        for m in msgs[:MAX_LOCKED]:
            self.store.apply("lock", m["id"])
        with self.assertRaisesRegex(StoreError, "LOCK FULL"):
            self.store.apply("lock", msgs[-1]["id"])

    def test_personal_file_limit_and_not_counted_in_slots(self):
        msgs = [self.add(str(i)) for i in range(MAX_PERSONAL + 1)]
        for m in msgs[:MAX_PERSONAL]:
            self.store.apply("file", m["id"])
        with self.assertRaisesRegex(StoreError, "FILE FULL"):
            self.store.apply("file", msgs[-1]["id"])
        for i in range(MAX_SLOTS):
            self.add(f"r{i}")
        self.assertEqual(sum(m["personal"] for m in self.store.messages), MAX_PERSONAL)

    def test_settings_validated(self):
        self.store.apply("settings", value={"speaker": "silent"})
        self.assertEqual(self.store.settings["speaker"], "silent")
        with self.assertRaises(StoreError):
            self.store.apply("settings", value={"speaker": "loud"})
        with self.assertRaises(StoreError):
            self.store.apply("settings", value={"alarm_hour": 24})

    def test_persists(self):
        self.store.apply("capcode", value=870024)
        self.add("saved")
        again = Store(self.path)
        self.assertEqual(again.capcode, 870024)
        self.assertEqual(again.messages[0]["text"], "saved")
        self.assertEqual(json.loads(self.path.read_text())["capcode"], 870024)

    def test_bad_capcode(self):
        for bad in (0, -1, 2_097_152, "abc"):
            with self.assertRaises(StoreError):
                self.store.apply("capcode", value=bad)


class CoreTests(unittest.TestCase):
    def setUp(self):
        self.store = Store(None)
        self.store.apply("capcode", value=870024)
        self.hub = Hub()
        self.events = self.hub.subscribe()
        self.core = Core(self.store, self.hub, dedupe_seconds=10, log_file=None)

    def test_filters_by_capcode(self):
        self.assertEqual(self.core.handle_line(line(capcode=874440), "test"), "ignored: other capcode")
        self.assertEqual(self.core.handle_line(line(), "test"), "stored")
        self.assertEqual(len(self.store.messages), 1)

    def test_duplicate_suppressed(self):
        self.core.handle_line(line(), "test")
        self.assertEqual(self.core.handle_line(line(), "test"), "ignored: duplicate")
        self.assertEqual(self.core.handle_line(line(text="other"), "test"), "stored")

    def test_power_off_ignores(self):
        self.store.apply("power", value=False)
        self.assertEqual(self.core.handle_line(line(), "test"), "ignored: pager is off")

    def test_page_event_published(self):
        self.core.handle_line(line(), "test")
        events = []
        while not self.events.empty():
            events.append(self.events.get_nowait()[0])
        self.assertEqual(events, ["decode", "page"])


if __name__ == "__main__":
    unittest.main()
