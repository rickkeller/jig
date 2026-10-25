"""Telegram door. A message becomes an event. The reply uses the same chat.

The engine does not live here. This module does not mark work done.
"""

import sqlite3


class DoorDown(Exception):
    """The door cannot take a reply right now."""


_SCHEMA = """
CREATE TABLE IF NOT EXISTS replies (
  id INTEGER PRIMARY KEY,
  door TEXT NOT NULL,
  chat_id TEXT NOT NULL,
  item_id INTEGER NOT NULL,
  short TEXT NOT NULL,
  where_to_read TEXT NOT NULL,
  state TEXT NOT NULL CHECK (state IN ('held', 'sent'))
);
"""


def open_door(path=":memory:"):
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.executescript(_SCHEMA)
    return conn


def admit(work, door, message):
    """An arrived message is one ask. A message that never arrived is not work."""
    if not message or message.get("door") != door or not message.get("text"):
        return None
    from jig.worklist import add_ask

    key = "door:%s:%s:%s" % (door, message["chat_id"], message["message_id"])
    return add_ask(work, message["text"], key)


def hold_reply(door_conn, door, chat_id, item_id, short, where):
    """Keep the short result for this door. The long record stays out of the send."""
    if not short or not where:
        raise ValueError("the door gets the short result and where to read the rest")
    cur = door_conn.execute(
        """
        INSERT INTO replies (door, chat_id, item_id, short, where_to_read, state)
        VALUES (?, ?, ?, ?, ?, 'held')
        """,
        (door, str(chat_id), item_id, short, where),
    )
    door_conn.commit()
    return cur.lastrowid


def send_held(door_conn, door, transport):
    """Send held replies on this door. If the door is down, they stay."""
    rows = door_conn.execute(
        "SELECT * FROM replies WHERE door = ? AND state = 'held' ORDER BY id",
        (door,),
    ).fetchall()
    sent = []
    for row in rows:
        text = "%s\n%s" % (row["short"], row["where_to_read"])
        try:
            transport.send(row["chat_id"], text)
        except DoorDown:
            return {"sent": sent, "held": True}
        door_conn.execute("UPDATE replies SET state = 'sent' WHERE id = ?", (row["id"],))
        door_conn.commit()
        sent.append(row["id"])
    return {"sent": sent, "held": False}


def held(door_conn, door):
    return [
        dict(row)
        for row in door_conn.execute(
            "SELECT * FROM replies WHERE door = ? AND state = 'held'",
            (door,),
        )
    ]
