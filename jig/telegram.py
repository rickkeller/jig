"""Telegram poller. The token stays in the data directory."""

import json
import sqlite3
import urllib.request
from pathlib import Path

from jig.door import DoorDown


def load_facts(root, owner="owner"):
    path = Path(root) / "memory" / (owner + ".sqlite")
    if not path.exists():
        return []
    conn = sqlite3.connect(path)
    try:
        return [row[0] for row in conn.execute("SELECT text FROM facts ORDER BY id")]
    except sqlite3.Error:
        return []
    finally:
        conn.close()


def store_fact(root, text, owner="owner"):
    path = Path(root) / "memory" / (owner + ".sqlite")
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    try:
        conn.executescript(
            """
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
        )
        found = conn.execute("SELECT 1 FROM facts WHERE text = ?", (text,)).fetchone()
        if found is None:
            conn.execute("INSERT INTO facts (text) VALUES (?)", (text,))
            conn.execute("INSERT INTO events (text) VALUES (?)", (text,))
            conn.commit()
    finally:
        conn.close()


def reply_prompt(text, facts=(), name="owner"):
    lines = ["You are %s. Reply in plain text. Do not use tools." % name]
    if facts:
        lines.append("Your store:")
        lines.extend("- %s" % item for item in facts)
    else:
        lines.append("Your store is empty.")
    lines.append("Message: %s" % text)
    return "\n".join(lines)


class Telegram:
    def __init__(self, token_path, offset_path):
        self.token_path = Path(token_path)
        self.offset_path = Path(offset_path)

    def _token(self):
        if not self.token_path.exists():
            raise DoorDown("token missing")
        token = self.token_path.read_text(encoding="utf-8").strip()
        if not token:
            raise DoorDown("token missing")
        return token

    def _call(self, method, payload, timeout):
        token = self._token()
        url = "https://api.telegram.org/bot%s/%s" % (token, method)
        req = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                body = json.load(resp)
        except Exception:
            raise DoorDown("telegram down")
        if not body.get("ok"):
            raise DoorDown("telegram refused")
        return body.get("result")

    def start(self):
        self._call("deleteWebhook", {"drop_pending_updates": False}, 20)

    def updates(self):
        offset = 0
        if self.offset_path.exists():
            raw = self.offset_path.read_text(encoding="utf-8").strip()
            offset = int(raw) if raw else 0
        result = self._call(
            "getUpdates",
            {"timeout": 0, "offset": offset, "allowed_updates": ["message"]},
            20,
        )
        return result or []

    def advance(self, update_id):
        self.offset_path.write_text(str(int(update_id) + 1), encoding="utf-8")

    def send(self, chat_id, text):
        self._call("sendMessage", {"chat_id": chat_id, "text": text[:4000]}, 20)


def allowed(user, allow):
    if user is None or allow is None:
        return False
    if isinstance(allow, (set, frozenset, list, tuple)):
        return user in allow
    return user == allow


def take(updates, ask, transport, allow=None, facts=(), remember=None, hold=None, on_text=None):
    """Reply on the same chat. Do not put the message on the job list."""
    sent = []
    last = None
    known = list(facts)
    for update in updates:
        last = update.get("update_id")
        message = update.get("message") or {}
        user = (message.get("from") or {}).get("id")
        text = message.get("text")
        chat_id = (message.get("chat") or {}).get("id")
        if not allowed(user, allow) or not text or chat_id is None:
            if last is not None:
                transport.advance(last)
            continue
        if hold is not None:
            hold(chat_id, text, last)
            transport.advance(last)
            sent.append(chat_id)
            continue
        kept = text.strip()
        if on_text is not None:
            try:
                on_text(kept)
            except Exception:
                pass
        if kept.lower().startswith("remember ") and remember is not None:
            remembered = kept[9:].strip()
            if remembered and remembered not in known:
                remember(remembered)
                known.append(remembered)
        reply = ask(reply_prompt(text, known)).strip()
        if not reply:
            raise DoorDown("empty reply")
        transport.send(chat_id, reply)
        transport.advance(last)
        sent.append(chat_id)
    return sent
