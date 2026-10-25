import tempfile
import unittest
from pathlib import Path

from jig.installed import archive_config, archive_state, open_bus, reject_hermes


class InstalledTest(unittest.TestCase):
    def test_a_hermes_path_is_refused(self):
        with self.assertRaises(RuntimeError):
            reject_hermes("/tmp/example/.hermes/profiles/other")
        with self.assertRaises(RuntimeError):
            archive_state(Path(".hermes-telegram-archive"))

    def test_bus_and_archive_use_jig_paths(self):
        try:
            from agent_bus_mcp import DurableQueue  # noqa: F401
        except ImportError:
            self.skipTest("agent bus is optional")
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            export = root / "export.json"
            export.write_text("{}", encoding="utf-8")
            queue = open_bus(root)
            task = queue.enqueue(goal="keep the note", references=[], idempotency_key="note-1")
            self.assertTrue(task.startswith("task_"))
            self.assertIn("/bus", str(queue.root))
            config = archive_config(root, export)
            self.assertEqual(config.state_path, root / "telescribe-state.sqlite3")
            self.assertNotIn("hermes", str(config.state_path))

    def test_fake_export_is_read_and_not_stored(self):
        try:
            from telescribe.pipeline import ArchiveService
        except ImportError:
            self.skipTest("archive reader is optional")
            return

        export = Path(__file__).parent / "fixtures" / "jig-export.json"
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            config = archive_config(root, export)
            self.assertEqual(ArchiveService(config).validate(), 2)
            self.assertFalse((root / "telescribe-state.sqlite3").exists())
            wrong = root / "wrong.json"
            wrong.write_text(export.read_text(encoding="utf-8").replace('"Jig"', '"Otto"', 1), encoding="utf-8")
            with self.assertRaises(ValueError):
                ArchiveService(archive_config(root, wrong)).validate()


if __name__ == "__main__":
    unittest.main()
