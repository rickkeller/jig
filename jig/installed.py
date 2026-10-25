"""Calls installed packages. Does not copy them. Does not use a Hermes path."""

from pathlib import Path

_HERMES = (".hermes", ".hermes-telegram-archive")


def reject_hermes(path):
    text = str(path)
    if any(mark in Path(text).parts or mark in text for mark in _HERMES):
        raise RuntimeError("a Hermes path is not Jig's")
    return Path(path)


def open_bus(root):
    root = reject_hermes(root)
    from agent_bus_mcp import DurableQueue

    return DurableQueue(root / "bus", producer_id="jig", worker_id="jig-worker")


def archive_state(root):
    root = reject_hermes(root)
    path = root / "telescribe-state.sqlite3"
    return reject_hermes(path)


def archive_config(root, export_path):
    root = reject_hermes(root)
    export_path = reject_hermes(export_path)
    from telescribe.config import AppConfig, SourceConfig

    return AppConfig(
        sources=(
            SourceConfig(
                id="jig",
                telegram_names=("Jig",),
                export_path=export_path,
                attachment_dir=export_path,
            ),
        ),
        archive_root=root / "archive",
        state_path=archive_state(root),
    )
