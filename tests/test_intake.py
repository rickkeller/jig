import unittest

from jig.intake import apply, file_message, parse
from jig.worklist import open_list

POST_1 = (
    "Finalize the written tests, test the bus, read an export, and review the notes. "
    "Then try one fake todo, one fake idea, and one fake development item."
)
POST_2 = "Use a made-up export. Connect through a local bus copy. Also try the model list."
POST_3 = "Keep pushing"

NIGHT = [
    {"action": "file", "kind": "job", "title": "Finalize the written tests", "key": "job:tests"},
    {"action": "file", "kind": "job", "title": "Test the bus", "key": "job:bus"},
    {"action": "file", "kind": "job", "title": "Read an export through TeleScribe", "key": "job:export"},
    {"action": "file", "kind": "job", "title": "Review the project notes", "key": "job:review"},
    {"action": "file", "kind": "todo", "title": "Add a rule only if that review finds one", "key": "todo:rules", "waits_on": "job:review"},
    {"action": "file", "kind": "job", "title": "Run one fake todo, one fake idea, and one fake development item", "key": "job:fakes"},
]
FOLLOW = [
    {"action": "adjust", "key": "job:export", "title": "Read a made-up export through TeleScribe"},
    {"action": "adjust", "key": "job:bus", "title": "Reach Jig through a local bus copy"},
    {"action": "file", "kind": "job", "title": "Try the model manager and the router. Do not switch a model", "key": "job:router"},
]


class IntakeTest(unittest.TestCase):
    def test_three_posts_file_adjust_and_ignore(self):
        conn = open_list()
        apply(conn, NIGHT, POST_1)
        titles = [row[0] for row in conn.execute("SELECT title FROM items WHERE kind = 'ask' ORDER BY id")]
        self.assertEqual(titles[0], "Finalize the written tests")
        self.assertNotIn(POST_1, titles)
        self.assertEqual(conn.execute("SELECT state FROM todos WHERE dedupe_key = 'todo:rules'").fetchone()[0], "held")
        apply(conn, FOLLOW, POST_2)
        self.assertEqual(conn.execute("SELECT title FROM items WHERE dedupe_key = 'job:export'").fetchone()[0], "Read a made-up export through TeleScribe")
        self.assertEqual(conn.execute("SELECT title FROM items WHERE dedupe_key = 'job:bus'").fetchone()[0], "Reach Jig through a local bus copy")
        self.assertEqual(conn.execute("SELECT COUNT(*) FROM items WHERE dedupe_key = 'job:tests'").fetchone()[0], 1)
        before = conn.execute("SELECT COUNT(*) FROM items").fetchone()[0]
        apply(conn, [{"action": "nothing"}], POST_3)
        self.assertEqual(conn.execute("SELECT COUNT(*) FROM items").fetchone()[0], before)

    def test_raw_message_and_copy_are_refused(self):
        conn = open_list()
        apply(conn, [{"action": "file", "kind": "job", "title": POST_3, "key": "job:prod"}], POST_3)
        self.assertIsNone(conn.execute("SELECT id FROM items WHERE dedupe_key = 'job:prod'").fetchone())
        apply(conn, NIGHT[:1], POST_1)
        apply(conn, NIGHT[:1], POST_1)
        self.assertEqual(conn.execute("SELECT COUNT(*) FROM items WHERE dedupe_key = 'job:tests'").fetchone()[0], 1)

    def test_unknown_action_is_refused(self):
        with self.assertRaises(RuntimeError):
            parse('[{"action":"start","title":"now","key":"job:now"}]')

    def test_stub_judge_does_not_file_keep_pushing(self):
        conn = open_list()

        def judge(prompt):
            self.assertIn("keep pushing", prompt.lower())
            return '[{"action":"nothing"}]'

        self.assertEqual(file_message(conn, POST_3, judge), [])
        self.assertIsNone(conn.execute("SELECT id FROM items WHERE kind = 'ask'").fetchone())
