"""Work list. One SQLite file. Two sources. Two intake queues. One worker. Replaced later."""

import sqlite3

DUTIES = (
    "improve-owned-projects",
    "correct-failures",
    "security-updates",
    "database-management",
    "server-management",
)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS items (
  id INTEGER PRIMARY KEY,
  source TEXT NOT NULL CHECK (source IN ('other', 'standing')),
  kind TEXT NOT NULL,
  title TEXT NOT NULL,
  priority INTEGER NOT NULL CHECK (priority IN (0, 1, 2)),
  state TEXT NOT NULL CHECK (state IN ('waiting', 'running', 'failed', 'closed')),
  dedupe_key TEXT,
  sleep_until TEXT,
  check_passed INTEGER NOT NULL DEFAULT 0
);
CREATE UNIQUE INDEX IF NOT EXISTS items_open_dedupe ON items(dedupe_key)
  WHERE dedupe_key IS NOT NULL AND state != 'closed';
CREATE TABLE IF NOT EXISTS todos (
  id INTEGER PRIMARY KEY,
  title TEXT NOT NULL,
  dedupe_key TEXT NOT NULL UNIQUE,
  waits_on TEXT,
  state TEXT NOT NULL CHECK (state IN ('held', 'fed')),
  job_id INTEGER
);
CREATE TABLE IF NOT EXISTS ideas (
  id INTEGER PRIMARY KEY,
  title TEXT NOT NULL,
  dedupe_key TEXT NOT NULL UNIQUE,
  state TEXT NOT NULL CHECK (state IN ('kept', 'became_todo'))
);
"""


def open_list(path=":memory:"):
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.executescript(_SCHEMA)
    for title in DUTIES:
        conn.execute(
            "INSERT OR IGNORE INTO items (source, kind, title, priority, state, dedupe_key) VALUES ('standing', 'duty', ?, 2, 'waiting', ?)",
            (title, "duty:" + title),
        )
    conn.commit()
    return conn


def add_ask(conn, title, dedupe_key):
    return _add(conn, "other", "ask", title, dedupe_key, 1)


def add_found(conn, title, dedupe_key):
    return _add(conn, "other", "found", title, dedupe_key, 0)


def add_clock(conn, title, dedupe_key):
    return _add(conn, "standing", "clock", title, dedupe_key, 2)


def add_development(conn, title, dedupe_key):
    return _add(conn, "other", "development", title, dedupe_key, 1)


def add_todo(conn, title, dedupe_key, waits_on=None):
    existing = conn.execute("SELECT id FROM todos WHERE dedupe_key = ?", (dedupe_key,)).fetchone()
    if existing:
        return existing["id"]
    if waits_on and not _closed(conn, waits_on):
        cur = conn.execute(
            "INSERT INTO todos (title, dedupe_key, waits_on, state) VALUES (?, ?, ?, 'held')",
            (title, dedupe_key, waits_on),
        )
        conn.commit()
        return cur.lastrowid
    job_id = add_ask(conn, title, dedupe_key)
    cur = conn.execute(
        "INSERT INTO todos (title, dedupe_key, waits_on, state, job_id) VALUES (?, ?, ?, 'fed', ?)",
        (title, dedupe_key, waits_on, job_id),
    )
    conn.commit()
    return cur.lastrowid


def add_idea(conn, title, dedupe_key):
    existing = conn.execute("SELECT id FROM ideas WHERE dedupe_key = ?", (dedupe_key,)).fetchone()
    if existing:
        return existing["id"]
    cur = conn.execute(
        "INSERT INTO ideas (title, dedupe_key, state) VALUES (?, ?, 'kept')",
        (title, dedupe_key),
    )
    conn.commit()
    return cur.lastrowid


def research_done(conn, dedupe_key):
    row = conn.execute("SELECT id, title, state FROM ideas WHERE dedupe_key = ?", (dedupe_key,)).fetchone()
    if row is None:
        raise RuntimeError("idea is missing")
    if row["state"] == "became_todo":
        return conn.execute("SELECT id FROM todos WHERE dedupe_key = ?", (dedupe_key,)).fetchone()["id"]
    todo_id = add_todo(conn, row["title"], dedupe_key)
    conn.execute("UPDATE ideas SET state = 'became_todo' WHERE id = ?", (row["id"],))
    conn.commit()
    return todo_id


def _closed(conn, dedupe_key):
    return conn.execute(
        "SELECT 1 FROM items WHERE dedupe_key = ? AND state = 'closed'",
        (dedupe_key,),
    ).fetchone() is not None


def _release(conn, finished_key):
    rows = conn.execute(
        "SELECT id, title, dedupe_key FROM todos WHERE state = 'held' AND waits_on = ?",
        (finished_key,),
    ).fetchall()
    for row in rows:
        job_id = add_ask(conn, row["title"], row["dedupe_key"])
        conn.execute(
            "UPDATE todos SET state = 'fed', job_id = ? WHERE id = ?",
            (job_id, row["id"]),
        )
    if rows:
        conn.commit()


def _add(conn, source, kind, title, dedupe_key, priority):
    existing = conn.execute(
        "SELECT id FROM items WHERE dedupe_key = ? AND state != 'closed'",
        (dedupe_key,),
    ).fetchone()
    if existing:
        return existing["id"]
    cur = conn.execute(
        "INSERT INTO items (source, kind, title, priority, state, dedupe_key) VALUES (?, ?, ?, ?, 'waiting', ?)",
        (source, kind, title, priority, dedupe_key),
    )
    conn.commit()
    return cur.lastrowid


def step(conn, now, judge=None):
    running = conn.execute("SELECT id FROM items WHERE state = 'running'").fetchone()
    if running:
        return {"claimed": None, "reason": "busy", "running": running["id"]}
    row = conn.execute(
        """
        SELECT * FROM items
        WHERE state = 'waiting' AND (sleep_until IS NULL OR sleep_until <= ?)
        ORDER BY priority,
                 CASE kind WHEN 'clock' THEN 0 ELSE 1 END,
                 id
        LIMIT 1
        """,
        (now,),
    ).fetchone()
    if row is None:
        return {"claimed": None, "reason": "idle"}
    if row["kind"] == "clock":
        if judge is None:
            raise RuntimeError("clock judgment is not the engine's")
        advice = judge({"id": row["id"], "title": row["title"], "kind": "clock"})
        return _apply(conn, row, advice, now)
    if row["kind"] == "duty":
        conn.execute(
            "UPDATE items SET state = 'waiting', sleep_until = ? WHERE id = ?",
            (_later(now), row["id"]),
        )
        conn.commit()
        return {"claimed": row["id"], "reason": "slept", "title": row["title"]}
    conn.execute("UPDATE items SET state = 'running' WHERE id = ?", (row["id"],))
    conn.commit()
    return {"claimed": row["id"], "reason": "running", "source": row["source"], "title": row["title"]}


def _apply(conn, row, advice, now):
    action = advice.get("action")
    if action == "contradict":
        conn.execute(
            "UPDATE items SET state = 'closed', check_passed = 1 WHERE id = ?",
            (row["id"],),
        )
        conn.commit()
        return {"claimed": row["id"], "reason": "not_applied"}
    if action == "nothing":
        conn.execute(
            "UPDATE items SET state = 'waiting', sleep_until = ? WHERE id = ?",
            (_later(now), row["id"]),
        )
        conn.commit()
        return {"claimed": row["id"], "reason": "slept"}
    if action == "enqueue":
        add_found(conn, advice["title"], advice["dedupe_key"])
        conn.execute(
            "UPDATE items SET state = 'closed', check_passed = 1 WHERE id = ?",
            (row["id"],),
        )
        conn.commit()
        return {"claimed": row["id"], "reason": "enqueued"}
    raise RuntimeError("advice has no action the engine may invent")


def finish(conn, item_id, check_passed, records=None):
    row = conn.execute("SELECT kind, state FROM items WHERE id = ?", (item_id,)).fetchone()
    if row is None:
        raise KeyError(item_id)
    if row["kind"] == "development":
        needed = ("directory", "obsidian", "index", "github")
        if not records or not all(records.get(name) for name in needed):
            return "open"
        check_passed = True
    if not check_passed:
        return "open"
    conn.execute(
        "UPDATE items SET state = 'closed', check_passed = 1 WHERE id = ? AND state = 'running'",
        (item_id,),
    )
    conn.commit()
    row = conn.execute("SELECT state, dedupe_key FROM items WHERE id = ?", (item_id,)).fetchone()
    if row["state"] == "closed" and row["dedupe_key"]:
        _release(conn, row["dedupe_key"])
    return row["state"]


def fail(conn, item_id):
    conn.execute("UPDATE items SET state = 'failed', check_passed = 0 WHERE id = ?", (item_id,))
    conn.commit()


def failures(conn):
    return [dict(row) for row in conn.execute("SELECT * FROM items WHERE state = 'failed'")]


def count_open(conn, dedupe_key):
    row = conn.execute(
        "SELECT COUNT(*) AS n FROM items WHERE dedupe_key = ? AND state != 'closed'",
        (dedupe_key,),
    ).fetchone()
    return row["n"]


def _later(now):
    return now + "~"
