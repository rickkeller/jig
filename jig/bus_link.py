"""Optional bus link. It stays off until the data directory has bus.json."""

import json
from pathlib import Path

from jig.installed import reject_hermes
from jig.worklist import add_ask


def load_bus(root):
    path = Path(root) / "bus.json"
    if not path.exists():
        return None
    document = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(document, dict):
        raise RuntimeError("bus config refused")
    state = reject_hermes(Path(root) / document["state_dir"])
    config = reject_hermes(Path(root) / document["config"])
    endpoint_id = document["endpoint_id"]
    if not isinstance(endpoint_id, str) or not endpoint_id:
        raise RuntimeError("bus config refused")
    return {"state_dir": state, "config": config, "endpoint_id": endpoint_id}


def take_bus(root, work):
    """Claim one chat addressed to this endpoint and file it as an ask."""
    spec = load_bus(root)
    if spec is None or work is None:
        return None
    try:
        from agent_bus_mcp.endpoints import open_endpoint
    except ImportError:
        return None
    claimed = open_endpoint(spec["state_dir"], spec["config"], spec["endpoint_id"]).claim_question()
    if claimed is None:
        return None
    return add_ask(work, claimed["question"], "bus:%s" % claimed["consultation_id"])
