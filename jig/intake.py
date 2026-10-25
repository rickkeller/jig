"""A chat message becomes jobs. The raw message is not a job."""

import json

from jig.worklist import add_ask, add_idea, add_todo


def open_jobs(conn):
    rows = []
    for row in conn.execute(
        "SELECT dedupe_key, title, kind, state FROM items WHERE state != 'closed' AND dedupe_key NOT LIKE 'duty:%' AND dedupe_key NOT LIKE 'clock:%'"
    ):
        rows.append({"key": row["dedupe_key"], "title": row["title"], "kind": row["kind"], "state": row["state"]})
    for row in conn.execute("SELECT dedupe_key, title FROM todos WHERE state = 'held'"):
        rows.append({"key": row["dedupe_key"], "title": row["title"], "kind": "todo", "state": "held"})
    for row in conn.execute("SELECT dedupe_key, title FROM ideas WHERE state = 'kept'"):
        rows.append({"key": row["dedupe_key"], "title": row["title"], "kind": "idea", "state": "kept"})
    return rows


def prompt_for(message, jobs):
    return (
        "Return a JSON array and nothing else. Do not use tools. "
        'Each item is {"action":"file","kind":"job","title":"...","key":"job:..."} '
        'or {"action":"file","kind":"todo","title":"...","key":"todo:...","waits_on":"job:..."} '
        'or {"action":"file","kind":"idea","title":"...","key":"idea:..."} '
        'or {"action":"adjust","key":"...","title":"..."} '
        'or {"action":"nothing"}. '
        "A new ask is split into jobs. A follow-up may change an open job or add one. Do not copy a key. "
        "Do not use the raw message as a title. A question is not a job. "
        "Keep pushing, keep working, and happen tonight are not jobs. "
        "Open jobs: %s Message: %s" % (json.dumps(jobs, sort_keys=True), message)
    )


def parse(text):
    start = text.find("[")
    end = text.rfind("]")
    if start < 0 or end <= start:
        start = text.find("{")
        end = text.rfind("}")
        if start < 0 or end <= start:
            raise RuntimeError("intake was not actions")
        raw = json.loads(text[start : end + 1])
        items = [raw]
    else:
        raw = json.loads(text[start : end + 1])
        if not isinstance(raw, list):
            raise RuntimeError("intake was not actions")
        items = raw
    return [_one(item) for item in items]


def apply(conn, actions, message=""):
    applied = []
    for action in actions:
        if action["action"] == "nothing":
            continue
        if action["title"].strip() == message.strip() or not action["title"].strip():
            continue
        if action["key"].startswith(("duty:", "clock:")):
            continue
        if action["action"] == "adjust":
            if _adjust(conn, action["key"], action["title"]):
                applied.append(action["key"])
            continue
        if _exists(conn, action["key"]):
            continue
        if action["kind"] == "job":
            add_ask(conn, action["title"], action["key"])
        elif action["kind"] == "todo":
            add_todo(conn, action["title"], action["key"], action.get("waits_on"))
        elif action["kind"] == "idea":
            add_idea(conn, action["title"], action["key"])
        else:
            continue
        applied.append(action["key"])
    return applied


def file_message(conn, message, judge):
    try:
        actions = parse(judge(prompt_for(message, open_jobs(conn))))
    except Exception:
        return []
    return apply(conn, actions, message)


def _one(item):
    if not isinstance(item, dict):
        raise RuntimeError("intake was not actions")
    action = item.get("action")
    if action == "nothing":
        return {"action": "nothing"}
    title = item.get("title")
    key = item.get("key")
    if not title or not key:
        raise RuntimeError("intake was not actions")
    if action == "adjust":
        return {"action": "adjust", "key": key, "title": title}
    if action != "file" or item.get("kind") not in ("job", "todo", "idea"):
        raise RuntimeError("intake was not actions")
    parsed = {"action": "file", "kind": item["kind"], "key": key, "title": title}
    if item.get("waits_on"):
        parsed["waits_on"] = item["waits_on"]
    return parsed


def _exists(conn, key):
    if conn.execute("SELECT id FROM items WHERE dedupe_key = ? AND state != 'closed'", (key,)).fetchone():
        return True
    if conn.execute("SELECT id FROM todos WHERE dedupe_key = ?", (key,)).fetchone():
        return True
    return conn.execute("SELECT id FROM ideas WHERE dedupe_key = ?", (key,)).fetchone() is not None


def _adjust(conn, key, title):
    cur = conn.execute(
        "UPDATE items SET title = ? WHERE dedupe_key = ? AND state != 'closed'",
        (title, key),
    )
    if not cur.rowcount:
        cur = conn.execute(
            "UPDATE todos SET title = ? WHERE dedupe_key = ? AND state = 'held'",
            (title, key),
        )
    if not cur.rowcount:
        return False
    conn.commit()
    return True
