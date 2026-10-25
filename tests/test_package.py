import tempfile
import unittest
from pathlib import Path

from jig.door import DoorDown, held
from jig.package import Package


class Up:
    def __init__(self):
        self.sent = []

    def send(self, chat_id, text):
        self.sent.append((chat_id, text))


class Down:
    def send(self, chat_id, text):
        raise DoorDown()


class PackageTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = self.temp.name
        self.package = Package(self.root)
        self.package.add_profile("rick", "rick-door", admin=True)
        self.package.add_profile("amanda", "amanda-door", admin=True)
        self.assertEqual(self.package.work.execute("SELECT COUNT(*) FROM items WHERE kind = 'duty'").fetchone()[0], 5)

    def tearDown(self):
        self.package.close()
        self.temp.cleanup()

    def test_exclusive_package_and_admin_profiles_have_independent_models(self):
        with self.assertRaises(RuntimeError):
            Package(self.root)
        with self.assertRaises(PermissionError):
            self.package.add_profile("nope", "nope")
        self.assertIsNone(self.package.profile("rick")["model"])
        self.package.set_model("rick", "p", "one")
        self.package.add_profile("later", "later-door", admin=True)
        self.assertIsNone(self.package.profile("later")["model"])
        self.package.set_model("amanda", "p", "one")
        self.package.set_engine_model("engine-provider", "engine-model")
        self.assertEqual(self.package.profile("rick")["model"], "one")
        self.assertEqual(self.package.profile("amanda")["model"], "one")
        self.assertEqual(self.package.engine_model(), {"provider": "engine-provider", "model": "engine-model"})
        self.package.set_model("rick", "p2", "two")
        self.assertEqual(self.package.profile("amanda")["model"], "one")
        self.assertEqual(self.package.engine_model()["model"], "engine-model")
        self.package.set_reasoning_model("reason-provider", "reason-model")
        self.assertEqual(self.package.reasoning_model()["model"], "reason-model")
        self.assertEqual(self.package.profile("rick")["model"], "two")
        self.assertEqual(self.package.engine_model()["model"], "engine-model")

    def test_notes_and_memory_are_separate_and_append_only(self):
        self.package.write_note("rick", "plan", "Rick visible")
        self.package.write_note("amanda", "plan", "Amanda visible")
        self.assertEqual(self.package.read_note("rick", "plan"), "Rick visible")
        self.assertEqual(self.package.read_note("amanda", "plan"), "Amanda visible")
        first = self.package.remember("rick", "shared rick fact")
        second = self.package.remember("rick", "replacement fact", replaces=first)
        self.package.remember("amanda", "shared amanda fact")
        self.package.remember("engine", "engine only fact")
        rick = self.package.search("rick", "fact")
        self.assertEqual({row["kind"] for row in rick}, {"fact", "event"})
        self.assertIn(second, [row["id"] for row in rick if row["kind"] == "fact"])
        self.assertEqual(self.package.search("amanda", "rick"), [])
        self.assertEqual(self.package.search("rick", "engine"), [])
        self.assertTrue((Path(self.root) / "memory" / "rick.sqlite").exists())
        self.assertTrue((Path(self.root) / "memory" / "amanda.sqlite").exists())

    def test_doors_pollers_and_long_reply_are_isolated(self):
        self.package.claim_poller("rick-bot")
        with self.assertRaises(RuntimeError):
            self.package.claim_poller("rick-bot")
        self.assertIsNone(self.package.admit("rick", {"door": "amanda-door", "chat_id": "a", "message_id": "1", "text": "wrong"}))
        item = self.package.admit("rick", {"door": "rick-door", "chat_id": "r", "message_id": "1", "text": "hello"})
        self.package.run("2026-10-23T00:00:00Z")
        self.package.reply("rick", "r", item, "Short", "very long result", "result")
        self.package.transport = Down()
        self.assertTrue(self.package.send("rick")["held"])
        self.assertEqual(len(held(self.package.door, "rick-door")), 1)
        self.assertEqual(self.package.work.execute("SELECT state FROM items WHERE id = ?", (item,)).fetchone()["state"], "running")
        transport = Up()
        self.package.transport = transport
        self.package.send("rick")
        self.assertEqual(transport.sent, [("r", "Short\n" + str(Path(self.root) / "vault" / "rick" / "result.md"))])
        self.assertEqual(self.package.read_note("rick", "result"), "very long result")

    def test_work_dedup_events_and_checked_finish(self):
        direct = self.package.talk("direct", "same")
        self.assertEqual(direct, self.package.handoff("handoff copy", "same"))
        clock = self.package.note_missed("missed", "clock:missed")
        self.assertEqual(clock, self.package.note_missed("missed", "clock:missed"))
        self.assertEqual(clock, self.package.note_missed("missed", "clock:missed"))
        found = self.package.found("urgent", "found:urgent")
        self.assertEqual(self.package.run("2026-10-23T00:00:00Z")["claimed"], found)
        self.assertEqual(self.package.finish(found, False), "open")
        self.assertEqual(self.package.finish(found, True), "closed")
        self.package.note_finished(found)
        self.package.note_finished(found)
        self.assertEqual(self.package.events(found), [{"item_id": found, "kind": "improvement"}])
        self.assertEqual(self.package.work.execute("SELECT COUNT(*) FROM items WHERE dedupe_key = ?", ("improvement:%s" % found,)).fetchone()[0], 1)
        self.package.fail(direct)
        self.package.fail(direct)
        self.assertEqual(self.package.events(direct), [{"item_id": direct, "kind": "failure"}])
        self.assertEqual(self.package.work.execute("SELECT state FROM items WHERE id = ?", (direct,)).fetchone()["state"], "failed")
        self.assertEqual(self.package.work.execute("SELECT COUNT(*) FROM items WHERE dedupe_key = ?", ("failure:%s" % direct,)).fetchone()[0], 1)

    def test_reasoner_only_gets_plain_event_and_decisions_block_advice(self):
        clock = self.package.note_missed("clock", "clock:one")
        with self.assertRaises(RuntimeError):
            self.package.run("2026-10-23T00:00:00Z")
        seen = []

        def reasoner(event):
            seen.append(event)
            self.assertEqual(set(event), {"id", "title", "kind", "rules"})
            self.assertEqual(event["rules"][0]["activity"], "development")
            return {"action": "enqueue", "title": "would add", "dedupe_key": "found:new", "against": "keep"}

        self.package.record_decision("keep")
        result = self.package.run("2026-10-23T00:00:00Z", reasoner)
        self.assertEqual(result["reason"], "not_applied")
        self.assertEqual(seen[0]["id"], clock)
        self.assertEqual(self.package.work.execute("SELECT COUNT(*) FROM items WHERE dedupe_key = 'found:new'").fetchone()[0], 0)
        self.package.note_missed("clock two", "clock:two")
        result = self.package.run(
            "2026-10-23T00:00:00Z",
            lambda event: {"action": "enqueue", "title": "applied", "dedupe_key": "found:applied"},
        )
        self.assertEqual(result["reason"], "enqueued")
        self.assertEqual(self.package.work.execute("SELECT COUNT(*) FROM items WHERE dedupe_key = 'found:applied'").fetchone()[0], 1)

    def test_due_duty_needs_reasoner_and_nothing_sleeps_without_skipping_user(self):
        with self.assertRaises(RuntimeError):
            self.package.run("2026-10-23T00:00:00Z")
        self.package.talk("waiting user", "ask:user")
        result = self.package.run("2026-10-23T00:00:00Z")
        self.assertEqual(result["title"], "waiting user")
        self.package.finish(result["claimed"], True)
        result = self.package.run("2026-10-23T00:00:00Z", lambda event: {"action": "nothing"})
        self.assertEqual(result["reason"], "slept")
        duties = self.package.work.execute("SELECT COUNT(*) FROM items WHERE kind = 'duty' AND state = 'waiting'").fetchone()[0]
        self.package.run(
            "2026-10-23T00:00:01Z",
            lambda event: {"action": "enqueue", "title": "a real change", "dedupe_key": "found:change"},
        )
        self.assertEqual(self.package.work.execute("SELECT COUNT(*) FROM items WHERE kind = 'duty' AND state != 'closed'").fetchone()[0], duties)
        self.assertEqual(self.package.work.execute("SELECT COUNT(*) FROM items WHERE dedupe_key = 'found:change'").fetchone()[0], 1)

    def test_a_path_does_not_start_until_rules_are_reviewed(self):
        self.package.conn.execute("DELETE FROM rules")
        self.package.conn.commit()
        called = []
        with self.assertRaises(RuntimeError):
            self.package.run("2026-10-23T00:00:00Z", lambda event: called.append(event))
        self.assertEqual(called, [])


if __name__ == "__main__":
    unittest.main()
