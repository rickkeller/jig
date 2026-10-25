"""The single-process Jig essential package."""

import fcntl
import os
from pathlib import Path
import sqlite3

from jig import door as doors
from jig import worklist


_PACKAGE_SCHEMA = """
CREATE TABLE IF NOT EXISTS profiles (
  person TEXT PRIMARY KEY,
  door TEXT NOT NULL,
  provider TEXT,
  model TEXT,
  admin INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS engine_model (
  singleton INTEGER PRIMARY KEY CHECK (singleton = 1),
  provider TEXT NOT NULL,
  model TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS reasoning_model (
  singleton INTEGER PRIMARY KEY CHECK (singleton = 1),
  provider TEXT NOT NULL,
  model TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS pollers (
  bot TEXT PRIMARY KEY
);
CREATE TABLE IF NOT EXISTS decisions (
  key TEXT PRIMARY KEY
);
CREATE TABLE IF NOT EXISTS rules (
  activity TEXT PRIMARY KEY,
  body TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS work_events (
  id INTEGER PRIMARY KEY,
  item_id INTEGER NOT NULL,
  kind TEXT NOT NULL CHECK (kind IN ('failure', 'improvement')),
  UNIQUE (item_id, kind)
);
"""

_MEMORY_SCHEMA = """
CREATE TABLE IF NOT EXISTS events (
  id INTEGER PRIMARY KEY,
  text TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS facts (
  id INTEGER PRIMARY KEY,
  text TEXT NOT NULL,
  replaces INTEGER REFERENCES facts(id)
);
"""


class Package:
    """Own the work list, doors, per-owner memory, and profile records."""

    def __init__(self, root, transport=None):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self._lock = open(self.root / "package.lock", "a+")
        try:
            fcntl.flock(self._lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            self._lock.close()
            raise RuntimeError("another Package owns this root")
        try:
            self.transport = transport
            self.conn = sqlite3.connect(self.root / "package.sqlite")
            self.conn.row_factory = sqlite3.Row
            self.conn.executescript(_PACKAGE_SCHEMA)
            self.conn.execute(
                "INSERT OR IGNORE INTO rules (activity, body) VALUES ('development', ?)",
                (
                    "New development is not done until a project directory, an Obsidian project record, "
                    "a Project Index entry, and a private GitHub repository with its URL recorded exist. "
                    "Reuse an existing record. Do not open a second one.",
                ),
            )
            self.conn.commit()
            self.work = worklist.open_list(str(self.root / "work.sqlite"))
            self.door = doors.open_door(str(self.root / "door.sqlite"))
        except Exception:
            self._lock.close()
            raise

    def close(self):
        for conn in (self.work, self.door, self.conn):
            conn.close()
        fcntl.flock(self._lock.fileno(), fcntl.LOCK_UN)
        self._lock.close()

    def __enter__(self):
        return self

    def __exit__(self, *unused):
        self.close()

    def add_profile(self, person, door, admin=False):
        if not admin:
            raise PermissionError("profile creation requires an admin")
        self.conn.execute(
            "INSERT INTO profiles (person, door, admin) VALUES (?, ?, 1)", (person, door)
        )
        self.conn.commit()

    def set_model(self, person, provider, model):
        cur = self.conn.execute(
            "UPDATE profiles SET provider = ?, model = ? WHERE person = ?",
            (provider, model, person),
        )
        if not cur.rowcount:
            raise KeyError(person)
        self.conn.commit()

    def profile(self, person):
        row = self.conn.execute("SELECT * FROM profiles WHERE person = ?", (person,)).fetchone()
        if row is None:
            raise KeyError(person)
        return dict(row)

    def set_engine_model(self, provider, model):
        self.conn.execute(
            "INSERT INTO engine_model (singleton, provider, model) VALUES (1, ?, ?) "
            "ON CONFLICT(singleton) DO UPDATE SET provider = excluded.provider, model = excluded.model",
            (provider, model),
        )
        self.conn.commit()

    def engine_model(self):
        row = self.conn.execute("SELECT provider, model FROM engine_model WHERE singleton = 1").fetchone()
        return None if row is None else dict(row)

    def set_reasoning_model(self, provider, model):
        self.conn.execute(
            "INSERT INTO reasoning_model (singleton, provider, model) VALUES (1, ?, ?) "
            "ON CONFLICT(singleton) DO UPDATE SET provider = excluded.provider, model = excluded.model",
            (provider, model),
        )
        self.conn.commit()

    def reasoning_model(self):
        row = self.conn.execute("SELECT provider, model FROM reasoning_model WHERE singleton = 1").fetchone()
        return None if row is None else dict(row)

    def _owner(self, owner):
        if owner != "engine":
            self.profile(owner)
        return owner

    @staticmethod
    def _part(value):
        if not value or Path(value).name != value or value in (".", ".."):
            raise ValueError("owner and note name must be single path components")
        return value

    def _memory(self, owner):
        owner = self._owner(owner)
        self._part(owner)
        path = self.root / "memory" / (owner + ".sqlite")
        path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(path)
        conn.row_factory = sqlite3.Row
        conn.executescript(_MEMORY_SCHEMA)
        return conn

    def write_note(self, owner, name, text):
        owner = self._owner(owner)
        self._part(owner)
        self._part(name)
        path = self.root / "vault" / owner / (name + ".md")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        return str(path)

    def read_note(self, owner, name):
        owner = self._owner(owner)
        self._part(owner)
        self._part(name)
        return (self.root / "vault" / owner / (name + ".md")).read_text(encoding="utf-8")

    def remember(self, owner, text, replaces=None):
        conn = self._memory(owner)
        try:
            cur = conn.execute("INSERT INTO facts (text, replaces) VALUES (?, ?)", (text, replaces))
            conn.execute("INSERT INTO events (text) VALUES (?)", (text,))
            conn.commit()
            return cur.lastrowid
        finally:
            conn.close()

    def search(self, owner, keyword):
        conn = self._memory(owner)
        try:
            pattern = "%" + keyword + "%"
            facts = [dict(row) | {"kind": "fact"} for row in conn.execute(
                "SELECT id, text, replaces FROM facts WHERE text LIKE ? ORDER BY id", (pattern,)
            )]
            events = [dict(row) | {"kind": "event"} for row in conn.execute(
                "SELECT id, text FROM events WHERE text LIKE ? ORDER BY id", (pattern,)
            )]
            return facts + events
        finally:
            conn.close()

    def claim_poller(self, bot):
        try:
            self.conn.execute("INSERT INTO pollers (bot) VALUES (?)", (bot,))
            self.conn.commit()
        except sqlite3.IntegrityError:
            raise RuntimeError("poller already claimed")

    def _door_for(self, person):
        return self.profile(person)["door"]

    def admit(self, person, message):
        return doors.admit(self.work, self._door_for(person), message)

    def reply(self, person, chat_id, item_id, short, text, name=None):
        name = name or "reply-%s" % item_id
        where = self.write_note(person, name, text)
        return doors.hold_reply(self.door, self._door_for(person), chat_id, item_id, short, where)

    def send(self, person):
        if self.transport is None:
            raise RuntimeError("a transport is required to send")
        return doors.send_held(self.door, self._door_for(person), self.transport)

    def talk(self, text, key):
        return worklist.add_ask(self.work, text, key)

    def handoff(self, text, key):
        return worklist.add_ask(self.work, text, key)

    def todo(self, title, key, waits_on=None):
        return worklist.add_todo(self.work, title, key, waits_on)

    def idea(self, title, key):
        return worklist.add_idea(self.work, title, key)

    def research_done(self, key):
        return worklist.research_done(self.work, key)

    def found(self, title, key):
        return worklist.add_found(self.work, title, key)

    def note_missed(self, title, key):
        return worklist.add_clock(self.work, title, key)

    def fail(self, item_id):
        row = self.work.execute("SELECT state FROM items WHERE id = ?", (item_id,)).fetchone()
        if row is None:
            raise KeyError(item_id)
        if row["state"] != "failed":
            worklist.fail(self.work, item_id)
            self.conn.execute("INSERT OR IGNORE INTO work_events (item_id, kind) VALUES (?, 'failure')", (item_id,))
            self.conn.commit()
            worklist.add_clock(self.work, "failure:%s" % item_id, "failure:%s" % item_id)

    def note_finished(self, item_id):
        row = self.work.execute("SELECT state FROM items WHERE id = ?", (item_id,)).fetchone()
        if row is None:
            raise KeyError(item_id)
        if row["state"] != "closed":
            raise ValueError("item is not finished")
        self.conn.execute("INSERT OR IGNORE INTO work_events (item_id, kind) VALUES (?, 'improvement')", (item_id,))
        self.conn.commit()
        worklist.add_clock(self.work, "improvement:%s" % item_id, "improvement:%s" % item_id)

    def events(self, item_id=None):
        query = "SELECT item_id, kind FROM work_events"
        values = () if item_id is None else (item_id,)
        if item_id is not None:
            query += " WHERE item_id = ?"
        return [dict(row) for row in self.conn.execute(query, values)]

    def record_decision(self, key):
        self.conn.execute("INSERT OR IGNORE INTO decisions (key) VALUES (?)", (key,))
        self.conn.commit()

    def _recorded(self, key):
        return self.conn.execute("SELECT 1 FROM decisions WHERE key = ?", (key,)).fetchone() is not None

    def rules(self):
        return [dict(row) for row in self.conn.execute("SELECT activity, body FROM rules ORDER BY activity")]

    def review_rules(self):
        rows = self.rules()
        if not rows:
            raise RuntimeError("rules were not reviewed")
        return rows

    def run(self, now, reasoner=None):
        rules = self.review_rules()
        running = self.work.execute("SELECT id FROM items WHERE state = 'running'").fetchone()
        if running:
            return worklist.step(self.work, now)
        row = self.work.execute(
            """SELECT * FROM items WHERE state = 'waiting'
               AND (sleep_until IS NULL OR sleep_until <= ?)
               ORDER BY priority, CASE kind WHEN 'clock' THEN 0 ELSE 1 END, id LIMIT 1""",
            (now,),
        ).fetchone()
        if row is None:
            return {"claimed": None, "reason": "idle"}
        if row["kind"] not in ("clock", "duty"):
            return worklist.step(self.work, now)
        if reasoner is None:
            raise RuntimeError("judgment requires a reasoner")
        advice = reasoner({"id": row["id"], "title": row["title"], "kind": row["kind"], "rules": rules})
        blocked = advice.get("action") == "contradict" or self._recorded(advice.get("against"))
        if row["kind"] == "duty":
            if not blocked and advice.get("action") == "enqueue":
                worklist.add_found(self.work, advice["title"], advice["dedupe_key"])
                reason = "enqueued"
            elif blocked:
                reason = "not_applied"
            else:
                return worklist._apply(self.work, row, advice, now)
            self.work.execute(
                "UPDATE items SET state = 'waiting', sleep_until = ? WHERE id = ?",
                (worklist._later(now), row["id"]),
            )
            self.work.commit()
            return {"claimed": row["id"], "reason": reason}
        if blocked:
            self.work.execute("UPDATE items SET state = 'closed', check_passed = 1 WHERE id = ?", (row["id"],))
            self.work.commit()
            return {"claimed": row["id"], "reason": "not_applied"}
        return worklist._apply(self.work, row, advice, now)

    def finish(self, item_id, check_passed, records=None):
        return worklist.finish(self.work, item_id, check_passed, records)
