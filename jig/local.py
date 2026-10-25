"""Files in the data directory. None of these belong in the repository."""

from pathlib import Path


def owner_name(root):
    path = Path(root) / "owner"
    if path.exists():
        name = path.read_text(encoding="utf-8").strip()
        if name:
            return name
    return "owner"


def token_path(root):
    root = Path(root)
    door = root / "door.token"
    if door.exists():
        return door
    legacy = root / "alfred.token"
    if legacy.exists():
        return legacy
    return door


def allow_ids(root):
    path = Path(root) / "allow"
    if not path.exists():
        return set()
    found = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        found.add(int(line))
    return found


def door_model(root):
    path = Path(root) / "door-model"
    if not path.exists():
        return None
    lines = [line.strip() for line in path.read_text(encoding="utf-8").splitlines() if line.strip() and not line.startswith("#")]
    if len(lines) < 2:
        return None
    return {"provider": lines[0], "model": lines[1], "effort": lines[2] if len(lines) > 2 else "medium"}


def caller_paths(root):
    path = Path(root) / "caller"
    if not path.exists():
        return None
    lines = [line.strip() for line in path.read_text(encoding="utf-8").splitlines() if line.strip() and not line.startswith("#")]
    if len(lines) < 3:
        return None
    return {
        "python": lines[0],
        "root": lines[1],
        "home": lines[2],
        "effort": lines[3] if len(lines) > 3 else "xhigh",
    }
