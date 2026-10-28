"""One process. It calls run. It is not a cron."""

import os
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from jig.package import Package
from jig.reasoner import hermes_ask, make_reasoner
from jig.door import hold_reply, open_door, send_held
from jig.telegram import Telegram, load_facts, store_fact, take
from jig.bus_link import take_bus
from jig.intake import file_message
from jig.local import allow_ids, caller_paths, door_model, owner_name, token_path

CLOCK_KEY = "clock:process"
FAILURE_NOTE = "judgment-missing"


def now_stamp():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def later_stamp(stamp, seconds):
    parsed = datetime.strptime(stamp, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    return (parsed + timedelta(seconds=seconds)).strftime("%Y-%m-%dT%H:%M:%SZ")


def should_hold(kind, stamp, hold_until):
    return kind in ("clock", "duty") and hold_until is not None and stamp < hold_until


def due_kind(package, now):
    row = package.work.execute(
        """SELECT kind FROM items
           WHERE state = 'waiting' AND (sleep_until IS NULL OR sleep_until <= ?)
           ORDER BY priority, CASE kind WHEN 'clock' THEN 0 ELSE 1 END, id
           LIMIT 1""",
        (now,),
    ).fetchone()
    return None if row is None else row["kind"]


def emit_clock(package):
    """One open clock. A missed start is one event, not one per missed tick."""
    return package.note_missed("clock due", CLOCK_KEY)


def once(package, now, reasoner=None):
    emit_clock(package)
    try:
        return package.run(now, reasoner)
    except RuntimeError as exc:
        if "judgment" not in str(exc) and "rules were not reviewed" not in str(exc):
            raise
        name = FAILURE_NOTE if "judgment" in str(exc) else "rules-not-reviewed"
        note = package.root / "vault" / "engine" / (name + ".md")
        if not note.exists():
            package.write_note("engine", name, str(exc))
        reason = "judgment_missing" if "judgment" in str(exc) else "rules_not_reviewed"
        return {"claimed": None, "reason": reason}


def wait(root, seconds, poll=None):
    root = Path(root)
    stop = root / "stop"
    wake = root / "wake"
    seen = wake.stat().st_mtime if wake.exists() else 0
    end = time.monotonic() + seconds
    next_poll = 0
    while time.monotonic() < end:
        if stop.exists():
            return "stop"
        if wake.exists() and wake.stat().st_mtime != seen:
            return "wake"
        if poll is not None and time.monotonic() >= next_poll:
            poll()
            next_poll = time.monotonic() + 2
        time.sleep(0.05)
    return "clock"


def poll_door(root, ask, work=None):
    root = Path(root)
    token = token_path(root)
    door = Telegram(token, root / "telegram.offset")
    if not token.exists():
        return
    paths = caller_paths(root)
    choice = door_model(root)
    if paths is None or choice is None:
        return
    person = owner_name(root)
    try:
        if not (root / "door-on").exists():
            door.start()
            (root / "door-on").write_text("polling\n", encoding="utf-8")
        held_conn = open_door(str(root / "door.sqlite"))
        try:
            if not (root / "door-hold").exists():
                send_held(held_conn, person, door)
            def keep(chat_id, text, update_id):
                hold_reply(held_conn, person, chat_id, int(update_id), "held", text)
            def call(prompt):
                return ask(
                    prompt,
                    choice["provider"],
                    choice["model"],
                    choice["effort"],
                    paths["python"],
                    paths["root"],
                    paths["home"],
                )
            def filed(text):
                if work is None:
                    return
                file_message(work, text, call)
            take(
                door.updates(),
                call,
                door,
                allow=allow_ids(root),
                facts=load_facts(root, person),
                remember=lambda text: store_fact(root, text, person),
                hold=keep if (root / "door-hold").exists() else None,
                on_text=None if (root / "door-hold").exists() else filed,
            )
        finally:
            held_conn.close()
    except Exception:
        return


def poll_bus(root, work):
    if work is None or not (Path(root) / "bus.json").exists():
        return
    try:
        take_bus(root, work)
    except Exception:
        return


def serve(root, reasoner=None, interval=60):
    root = Path(root)
    package = Package(root)
    pid = root / "process.pid"
    log = root / "process.log"
    hold_path = root / "reasoner-hold"
    pid.write_text(str(os.getpid()))
    hold_until = hold_path.read_text(encoding="utf-8").strip() if hold_path.exists() else None
    try:
        while not (root / "stop").exists():
            stamp = now_stamp()
            if reasoner is not None and should_hold(due_kind(package, stamp), stamp, hold_until):
                result = {"claimed": None, "reason": "held"}
            else:
                result = once(package, stamp, reasoner)
                if reasoner is not None and result.get("reason") in ("slept", "enqueued", "not_applied", "judgment_missing"):
                    hold_until = later_stamp(stamp, interval)
                    hold_path.write_text(hold_until, encoding="utf-8")
            with log.open("a", encoding="utf-8") as handle:
                handle.write("%s %s\n" % (stamp, result.get("reason")))
            if (root / "stop").exists():
                break
            pause = 1 if result.get("reason") == "running" else interval
            if wait(root, pause, poll=lambda: (poll_door(root, hermes_ask, package.work), poll_bus(root, package.work))) == "stop":
                break
    finally:
        pid.unlink(missing_ok=True)
        package.close()


def main(argv=None):
    if argv is None:
        argv = sys.argv
    root = Path(argv[1] if len(argv) > 1 else Path.home() / ".local/share/jig")
    interval = int(argv[2]) if len(argv) > 2 else 900
    package = Package(root)
    choice = package.reasoning_model()
    package.close()
    paths = caller_paths(root)
    reasoner = None
    if choice and paths:
        def ask(prompt, provider, model):
            return hermes_ask(prompt, provider, model, paths["effort"], paths["python"], paths["root"], paths["home"])
        reasoner = make_reasoner(ask, choice["provider"], choice["model"])
    serve(root, reasoner=reasoner, interval=interval)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
