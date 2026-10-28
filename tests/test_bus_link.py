import json
import tempfile
import unittest
from pathlib import Path

from jig.bus_link import load_bus, take_bus
from jig.worklist import open_list


class BusLinkTest(unittest.TestCase):
    def test_missing_config_does_nothing(self):
        with tempfile.TemporaryDirectory() as raw:
            self.assertIsNone(load_bus(raw))
            self.assertIsNone(take_bus(raw, None))

    def test_hermes_path_is_refused(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            (root / "bus.json").write_text(
                json.dumps({"state_dir": ".hermes/bus", "config": "endpoints.json", "endpoint_id": "jig"}),
                encoding="utf-8",
            )
            with self.assertRaises(RuntimeError):
                load_bus(root)

    def test_claimed_chat_becomes_an_ask(self):
        try:
            from agent_bus_mcp.endpoints import open_endpoint, post_chat
        except ImportError:
            self.skipTest("agent bus is optional")
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            state = root / "bus-state"
            config = root / "endpoints.json"
            config.write_text(
                json.dumps(
                    {
                        "endpoints": ["jig", "grokbot"],
                        "allow": [{"from": "grokbot", "to": "jig", "kinds": ["chat"]}],
                    }
                ),
                encoding="utf-8",
            )
            (root / "bus.json").write_text(
                json.dumps({"state_dir": "bus-state", "config": "endpoints.json", "endpoint_id": "jig"}),
                encoding="utf-8",
            )
            post_chat(open_endpoint(state, config, "grokbot"), to="jig", text="what version", key="once")
            work = open_list(str(root / "work.sqlite"))
            item = take_bus(root, work)
            self.assertIsNotNone(item)
            self.assertIsNone(take_bus(root, work))
            work.close()
