import unittest

from jig.worklist import add_ask, add_clock, add_development, add_found, fail, failures, finish, open_list, step


class WorkListTest(unittest.TestCase):
    def test_user_item_runs_before_standing_duty(self):
        conn = open_list()
        add_ask(conn, "fix the door", "ask:door")
        result = step(conn, "2026-10-22T21:00:00Z")
        self.assertEqual(result["title"], "fix the door")
        self.assertEqual(result["reason"], "running")

    def test_running_user_item_is_not_cut_in_front_of(self):
        conn = open_list()
        first = add_ask(conn, "first", "ask:1")
        step(conn, "2026-10-22T21:00:00Z")
        add_ask(conn, "second", "ask:2")
        result = step(conn, "2026-10-22T21:01:00Z")
        self.assertEqual(result["reason"], "busy")
        self.assertEqual(result["running"], first)

    def test_empty_user_source_is_not_idle(self):
        conn = open_list()
        result = step(conn, "2026-10-22T21:00:00Z")
        self.assertEqual(result["reason"], "slept")
        self.assertNotEqual(result["reason"], "idle")

    def test_sleep_does_not_skip_a_waiting_user_item(self):
        conn = open_list()
        step(conn, "2026-10-22T21:00:00Z")
        add_ask(conn, "now", "ask:now")
        result = step(conn, "2026-10-22T21:00:01Z")
        self.assertEqual(result["title"], "now")

    def test_same_ask_is_one_item(self):
        conn = open_list()
        first = add_ask(conn, "same", "ask:same")
        second = add_ask(conn, "same", "ask:same")
        self.assertEqual(first, second)

    def test_clock_judgment_is_passed_out(self):
        conn = open_list()
        seen = []

        def judge(event):
            seen.append(event)
            return {"action": "nothing"}

        add_clock(conn, "security-scan-due", "clock:security")
        result = step(conn, "2026-10-22T21:00:00Z", judge)
        self.assertEqual(seen[0]["kind"], "clock")
        self.assertEqual(result["reason"], "slept")

    def test_engine_does_not_judge_a_clock(self):
        conn = open_list()
        add_clock(conn, "security-scan-due", "clock:security")
        with self.assertRaises(RuntimeError):
            step(conn, "2026-10-22T21:00:00Z")

    def test_contradicting_advice_is_not_applied(self):
        conn = open_list()
        add_clock(conn, "security-scan-due", "clock:security")
        step(conn, "2026-10-22T21:00:00Z", lambda event: {"action": "contradict"})
        self.assertEqual(conn.execute("SELECT COUNT(*) FROM items WHERE kind = 'ask'").fetchone()[0], 0)

    def test_model_done_does_not_close(self):
        conn = open_list()
        item = add_ask(conn, "fix the door", "ask:door")
        step(conn, "2026-10-22T21:00:00Z")
        self.assertEqual(finish(conn, item, check_passed=False), "open")
        self.assertEqual(finish(conn, item, check_passed=True), "closed")

    def test_development_stays_open_until_the_records_exist(self):
        conn = open_list()
        item = add_development(conn, "fake project", "development:fake")
        step(conn, "2026-10-24T05:00:00Z")
        self.assertEqual(finish(conn, item, check_passed=True), "open")
        records = {"directory": True, "obsidian": True, "index": True, "github": True}
        self.assertEqual(finish(conn, item, check_passed=False, records=records), "closed")

    def test_failure_stays_visible(self):
        conn = open_list()
        item = add_ask(conn, "fix the door", "ask:door")
        step(conn, "2026-10-22T21:00:00Z")
        fail(conn, item)
        add_ask(conn, "another copy", "ask:copy")
        self.assertEqual(len(failures(conn)), 1)
        self.assertEqual(failures(conn)[0]["id"], item)

    def test_found_problem_runs_without_a_push(self):
        conn = open_list()
        add_found(conn, "open package hole", "found:hole")
        result = step(conn, "2026-10-22T21:00:00Z")
        self.assertEqual(result["title"], "open package hole")
        self.assertEqual(result["reason"], "running")

    def test_found_problem_beats_a_waiting_ask(self):
        conn = open_list()
        add_ask(conn, "write the note", "ask:note")
        add_found(conn, "open package hole", "found:hole")
        result = step(conn, "2026-10-22T21:00:00Z")
        self.assertEqual(result["title"], "open package hole")

    def test_a_ready_todo_is_one_job(self):
        from jig.worklist import add_todo

        conn = open_list()
        first = add_todo(conn, "download and test the package", "todo:package")
        second = add_todo(conn, "download and test the package", "todo:package")
        self.assertEqual(first, second)
        result = step(conn, "2026-10-22T21:00:00Z")
        self.assertEqual(result["title"], "download and test the package")
        self.assertEqual(result["reason"], "running")

    def test_a_todo_waits_until_its_prerequisite_finishes(self):
        from jig.worklist import add_todo

        conn = open_list()
        gate = add_ask(conn, "finish the prerequisite", "ask:gate")
        held = add_todo(conn, "start the new project", "todo:project", waits_on="ask:gate")
        self.assertEqual(conn.execute("SELECT state FROM todos WHERE id = ?", (held,)).fetchone()["state"], "held")
        step(conn, "2026-10-22T21:00:00Z")
        self.assertEqual(conn.execute("SELECT COUNT(*) FROM items WHERE dedupe_key = 'todo:project'").fetchone()[0], 0)
        finish(conn, gate, True)
        self.assertEqual(conn.execute("SELECT state FROM todos WHERE id = ?", (held,)).fetchone()["state"], "fed")
        result = step(conn, "2026-10-22T21:01:00Z")
        self.assertEqual(result["title"], "start the new project")

    def test_an_idea_is_kept_and_is_not_work_until_it_becomes_a_todo(self):
        from jig.worklist import add_idea, research_done

        conn = open_list()
        first = add_idea(conn, "maybe useful later", "idea:later")
        second = add_idea(conn, "maybe useful later", "idea:later")
        self.assertEqual(first, second)
        result = step(conn, "2026-10-22T21:00:00Z")
        self.assertNotEqual(result["reason"], "running")
        self.assertEqual(conn.execute("SELECT state FROM ideas WHERE id = ?", (first,)).fetchone()["state"], "kept")
        research_done(conn, "idea:later")
        research_done(conn, "idea:later")
        self.assertEqual(conn.execute("SELECT COUNT(*) FROM ideas").fetchone()[0], 1)
        self.assertEqual(conn.execute("SELECT COUNT(*) FROM todos").fetchone()[0], 1)
        self.assertEqual(conn.execute("SELECT COUNT(*) FROM items WHERE dedupe_key = 'idea:later'").fetchone()[0], 1)


if __name__ == "__main__":
    unittest.main()
