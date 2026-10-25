import tempfile
import unittest
from pathlib import Path

from jig.local import allow_ids, caller_paths, door_model, owner_name, token_path


class LocalConfigTest(unittest.TestCase):
    def test_files_in_the_data_directory(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            self.assertEqual(owner_name(root), "owner")
            self.assertEqual(token_path(root), root / "door.token")
            self.assertEqual(allow_ids(root), set())
            self.assertIsNone(door_model(root))
            self.assertIsNone(caller_paths(root))
            (root / "owner").write_text("ada\n", encoding="utf-8")
            (root / "door.token").write_text("secret\n", encoding="utf-8")
            (root / "alfred.token").write_text("old\n", encoding="utf-8")
            (root / "allow").write_text("# note\n1001\n", encoding="utf-8")
            (root / "door-model").write_text("example\nmodel-a\nmedium\n", encoding="utf-8")
            (root / "caller").write_text("/python\n/caller\n/home\n", encoding="utf-8")
            self.assertEqual(owner_name(root), "ada")
            self.assertEqual(token_path(root), root / "door.token")
            self.assertEqual(allow_ids(root), {1001})
            choice = door_model(root)
            paths = caller_paths(root)
            self.assertEqual(choice and choice["model"], "model-a")
            self.assertEqual(paths and paths["effort"], "xhigh")
            (root / "door.token").unlink()
            self.assertEqual(token_path(root), root / "alfred.token")
