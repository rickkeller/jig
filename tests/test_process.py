import tempfile
import threading
import time
import unittest
from pathlib import Path

from jig.package import Package
from jig.process import CLOCK_KEY, emit_clock, once, serve, should_hold, wait


class ProcessTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = self.temp.name
        self.package = Package(self.root)

    def tearDown(self):
        if self.package is not None:
            self.package.close()
        self.temp.cleanup()

    def test_missed_start_is_one_clock(self):
        first = emit_clock(self.package)
        self.assertEqual(first, emit_clock(self.package))
        self.assertEqual(first, emit_clock(self.package))
        self.assertEqual(
            self.package.work.execute(
                "SELECT COUNT(*) FROM items WHERE dedupe_key = ?", (CLOCK_KEY,)
            ).fetchone()[0],
            1,
        )

    def test_standing_pass_stays_visible_without_a_reasoner(self):
        result = once(self.package, "2026-10-23T13:40:00Z")
        self.assertEqual(result["reason"], "judgment_missing")
        note = Path(self.root) / "vault" / "engine" / "judgment-missing.md"
        self.assertTrue(note.exists())
        once(self.package, "2026-10-23T13:41:00Z")
        self.assertEqual(note.read_text(encoding="utf-8").count("judgment"), 1)
        self.assertEqual(
            self.package.work.execute(
                "SELECT state FROM items WHERE dedupe_key = ?", (CLOCK_KEY,)
            ).fetchone()["state"],
            "waiting",
        )

    def test_a_judged_clock_is_not_asked_again_inside_the_hold(self):
        self.assertTrue(should_hold("clock", "2026-10-23T17:00:00Z", "2026-10-23T17:15:00Z"))
        self.assertFalse(should_hold("ask", "2026-10-23T17:00:00Z", "2026-10-23T17:15:00Z"))
        self.assertFalse(should_hold("clock", "2026-10-23T17:15:00Z", "2026-10-23T17:15:00Z"))
        def touch():
            time.sleep(0.1)
            (Path(self.root) / "wake").write_text("1", encoding="utf-8")

        threading.Thread(target=touch).start()
        self.assertEqual(wait(self.root, 5), "wake")

    def test_one_process_holds_the_root(self):
        self.package.close()
        self.package = None
        thread = threading.Thread(target=serve, args=(self.root,), kwargs={"interval": 30})
        thread.start()
        deadline = time.monotonic() + 5
        pid = Path(self.root) / "process.pid"
        while not pid.exists() and time.monotonic() < deadline:
            time.sleep(0.05)
        self.assertTrue(pid.exists())
        with self.assertRaises(RuntimeError):
            Package(self.root)
        (Path(self.root) / "stop").write_text("1", encoding="utf-8")
        thread.join(5)
        self.assertFalse(thread.is_alive())


if __name__ == "__main__":
    unittest.main()
