import unittest

from jig.reasoner import make_reasoner, parse_advice, prompt_for


class ReasonerTest(unittest.TestCase):
    def test_advice_is_only_the_allowed_actions(self):
        self.assertEqual(parse_advice('session_id: x\n{"action":"nothing"}'), {"action": "nothing"})
        self.assertEqual(
            parse_advice('{"action":"enqueue","title":"fix the lock","dedupe_key":"found:lock","extra":1}'),
            {"action": "enqueue", "title": "fix the lock", "dedupe_key": "found:lock"},
        )
        self.assertEqual(
            parse_advice('{"action":"contradict","against":"keep"}'),
            {"action": "contradict", "against": "keep"},
        )
        with self.assertRaises(RuntimeError):
            parse_advice("looks fine")

    def test_caller_sends_the_event_and_returns_advice(self):
        seen = {}

        def ask(prompt, provider, model):
            seen["prompt"] = prompt
            seen["provider"] = provider
            seen["model"] = model
            return '{"action":"nothing"}'

        reasoner = make_reasoner(ask, "example", "model-a")
        self.assertEqual(reasoner({"id": 3, "title": "clock due", "kind": "clock"}), {"action": "nothing"})
        self.assertEqual(seen["provider"], "example")
        self.assertEqual(seen["model"], "model-a")
        self.assertIn('"kind": "clock"', seen["prompt"])
        self.assertIn("Review these rules", seen["prompt"])
        self.assertNotIn("token", seen["prompt"])
        self.assertEqual(
            prompt_for({"id": 3, "title": "clock due", "kind": "clock", "secret": "no"}),
            prompt_for({"id": 3, "title": "clock due", "kind": "clock"}),
        )


if __name__ == "__main__":
    unittest.main()
