"""Reasoning caller. It returns advice. It does not write the work list."""

import json
import os
import subprocess


def prompt_for(event):
    return (
        "Return one JSON object and nothing else. Do not use tools. Do not write files. "
        'Allowed: {"action":"nothing"} or '
        '{"action":"enqueue","title":"...","dedupe_key":"found:..."} or '
        '{"action":"contradict","against":"..."}. '
        "Review these rules and follow them before choosing a path. Do not skip one. "
        "Event: %s" % json.dumps(
            {
                "id": event["id"],
                "title": event["title"],
                "kind": event["kind"],
                "rules": event.get("rules") or [],
            },
            sort_keys=True,
        )
    )


def parse_advice(text):
    start = text.find("{")
    end = text.rfind("}")
    if start < 0 or end <= start:
        raise RuntimeError("judgment was not advice")
    try:
        raw = json.loads(text[start : end + 1])
    except json.JSONDecodeError:
        raise RuntimeError("judgment was not advice")
    action = raw.get("action")
    if action == "nothing":
        return {"action": "nothing"}
    if action == "enqueue" and raw.get("title") and raw.get("dedupe_key"):
        return {"action": "enqueue", "title": raw["title"], "dedupe_key": raw["dedupe_key"]}
    if action == "contradict":
        advice = {"action": "contradict"}
        if raw.get("against"):
            advice["against"] = raw["against"]
        return advice
    raise RuntimeError("judgment was not advice")


def make_reasoner(ask, provider, model):
    def reasoner(event):
        return parse_advice(ask(prompt_for(event), provider, model))

    return reasoner


def hermes_ask(prompt, provider, model, effort="xhigh", python=None, root=None, home=None):
    """Call the configured program. The token stays with that program."""
    if not python or not root or not home:
        raise RuntimeError("judgment call failed")
    env = {
        "HOME": os.environ.get("HOME", ""),
        "PATH": os.environ.get("PATH", ""),
        "LANG": "C.UTF-8",
        "CALLER_HOME": home,
    }
    proc = subprocess.run(
        [python, provider, model, effort],
        input=prompt,
        capture_output=True,
        text=True,
        timeout=240,
        cwd=root,
        env=env,
    )
    if proc.returncode != 0 or not proc.stdout.strip():
        raise RuntimeError("judgment call failed")
    return proc.stdout
