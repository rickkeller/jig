import unittest

from jig.door import DoorDown, admit, held, hold_reply, open_door, send_held
from jig.worklist import finish, open_list, step


class Down:
    def send(self, chat_id, text):
        raise DoorDown()


class Up:
    def __init__(self):
        self.sent = []

    def send(self, chat_id, text):
        self.sent.append((chat_id, text))


class DoorTest(unittest.TestCase):
    def test_arrived_message_is_one_ask(self):
        work = open_list()
        message = {"door": "ada", "chat_id": "1001", "message_id": "1", "text": "fix the door"}
        first = admit(work, "ada", message)
        second = admit(work, "ada", message)
        self.assertEqual(first, second)
        result = step(work, "2026-10-22T22:00:00Z")
        self.assertEqual(result["title"], "fix the door")

    def test_missing_message_is_not_work(self):
        work = open_list()
        self.assertIsNone(admit(work, "ada", None))
        result = step(work, "2026-10-22T22:00:00Z")
        self.assertNotEqual(result["reason"], "running")

    def test_amanda_message_stays_off_ricks_door(self):
        work = open_list()
        message = {"door": "amanda", "chat_id": "1", "message_id": "1", "text": "hers"}
        self.assertIsNone(admit(work, "ada", message))

    def test_reply_uses_the_same_chat_and_does_not_close_work(self):
        work = open_list()
        door = open_door()
        item = admit(work, "ada", {"door": "ada", "chat_id": "1001", "message_id": "9", "text": "status"})
        step(work, "2026-10-22T22:00:00Z")
        hold_reply(door, "ada", "1001", item, "Done.", "record:jig")
        transport = Up()
        send_held(door, "ada", transport)
        self.assertEqual(transport.sent, [("1001", "Done.\nrecord:jig")])
        self.assertEqual(finish(work, item, False), "open")
        self.assertEqual(work.execute("SELECT state FROM items WHERE id = ?", (item,)).fetchone()["state"], "running")

    def test_down_door_keeps_the_reply_and_the_item(self):
        work = open_list()
        door = open_door()
        item = admit(work, "ada", {"door": "ada", "chat_id": "1001", "message_id": "3", "text": "status"})
        step(work, "2026-10-22T22:00:00Z")
        hold_reply(door, "ada", "1001", item, "Done.", "record:jig")
        result = send_held(door, "ada", Down())
        self.assertTrue(result["held"])
        self.assertEqual(len(held(door, "ada")), 1)
        self.assertEqual(work.execute("SELECT state FROM items WHERE id = ?", (item,)).fetchone()["state"], "running")

    def test_long_record_is_not_what_the_door_sends(self):
        door = open_door()
        hold_reply(door, "ada", "1001", 1, "Short.", "record:jig")
        self.assertEqual(set(held(door, "ada")[0]), {"id", "door", "chat_id", "item_id", "short", "where_to_read", "state"})
        transport = Up()
        send_held(door, "ada", transport)
        self.assertEqual(transport.sent, [("1001", "Short.\nrecord:jig")])
