import unittest

from jig.door import DoorDown
from jig.telegram import reply_prompt, take


class Transport:
    def __init__(self, down=False):
        self.sent = []
        self.advanced = []
        self.down = down

    def send(self, chat_id, text):
        if self.down:
            raise DoorDown("telegram down")
        self.sent.append((chat_id, text))

    def advance(self, update_id):
        self.advanced.append(update_id)


class TelegramDoorTest(unittest.TestCase):
    def test_reply_stays_on_the_same_chat(self):
        seen = []

        def ask(prompt):
            seen.append(prompt)
            return "heard"

        updates = [{"update_id": 4, "message": {"from": {"id": 1001}, "chat": {"id": 1001}, "text": "hi"}}]
        transport = Transport()
        sent = take(updates, ask, transport, allow=1001)
        self.assertEqual(sent, [1001])
        self.assertEqual(transport.sent, [(1001, "heard")])
        self.assertEqual(transport.advanced, [4])
        self.assertNotIn("token", seen[0])

    def test_other_user_is_not_answered(self):
        transport = Transport()
        updates = [{"update_id": 5, "message": {"from": {"id": 1}, "chat": {"id": 1}, "text": "no"}}]
        sent = take(updates, lambda prompt: "no", transport)
        self.assertEqual(sent, [])
        self.assertEqual(transport.sent, [])
        self.assertEqual(transport.advanced, [5])

    def test_failed_send_does_not_advance(self):
        updates = [{"update_id": 6, "message": {"from": {"id": 1001}, "chat": {"id": 1001}, "text": "hi"}}]
        transport = Transport(down=True)
        with self.assertRaises(DoorDown):
            take(updates, lambda prompt: "heard", transport, allow=1001)
        self.assertEqual(transport.advanced, [])

    def test_hold_does_not_send(self):
        held = []
        updates = [{"update_id": 7, "message": {"from": {"id": 1001}, "chat": {"id": 1001}, "text": "hold this"}}]
        transport = Transport()
        sent = take(updates, lambda prompt: "no", transport, allow=1001, hold=lambda chat_id, text, update_id: held.append((chat_id, text, update_id)))
        self.assertEqual(sent, [1001])
        self.assertEqual(transport.sent, [])
        self.assertEqual(held, [(1001, "hold this", 7)])
        self.assertEqual(transport.advanced, [7])

    def test_prompt_names_alfred(self):
        self.assertIn("blue-harbor", reply_prompt("what code word", ["code word blue-harbor"]))
        self.assertIn("empty", reply_prompt("hi"))
        self.assertNotIn("token", reply_prompt("hi"))


if __name__ == "__main__":
    unittest.main()
