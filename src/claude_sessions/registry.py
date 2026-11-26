"""Claude Code's own record of each session it's running: ~/.claude/sessions/<pid>.json, written
by the session and removed when it ends. A session that crashes leaves its record behind, so only
those whose process is still running count."""

import json
import os
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import final


@final
@dataclass(frozen=True)
class Entry:
    pid: int
    session_id: str
    cwd: str | None
    """The directory the session started in."""
    status: str | None
    """idle, busy or waiting, as Claude Code says."""
    name: str | None
    named_by: str | None
    """Who chose the name: derived from the directory, auto by Claude Code, or user."""
    updated: datetime | None
    status_changed: datetime | None
    """When its status last changed, as to idle when a turn ends."""
    entrypoint: str | None
    """What started the session: claude-vscode for a VS Code or Cursor panel, cli for a terminal."""
    process_started: str | None
    """When its process started, as `ps -o lstart=` gives it, to tell it from a later process
    given the same pid."""


def parse(record: object) -> Entry | None:
    """The session a record describes, or None when it has no pid or session id. Any other field
    it lacks, or holds as the wrong type, is unknown."""
    if not isinstance(record, dict):
        return None
    pid = record.get("pid")
    session_id = record.get("sessionId")
    if not isinstance(pid, int) or not isinstance(session_id, str):
        return None
    return Entry(
        pid=pid,
        session_id=session_id,
        cwd=_text(record, "cwd"),
        status=_text(record, "status"),
        name=_text(record, "name"),
        named_by=_text(record, "nameSource"),
        updated=_time(record, "updatedAt"),
        status_changed=_time(record, "statusUpdatedAt"),
        entrypoint=_text(record, "entrypoint"),
        process_started=_text(record, "procStart"),
    )


def running(sessions_dir: Path) -> list[Entry]:
    """The sessions recorded in sessions_dir whose process is still running. A file that can't be
    read as a record is skipped."""
    entries = []
    for file in sorted(sessions_dir.glob("*.json")):
        try:
            entry = parse(json.loads(file.read_text()))
        except (OSError, ValueError):
            continue
        if entry is not None and _alive(entry.pid):
            entries.append(entry)
    return entries


def _text(record: dict[str, object], key: str) -> str | None:
    value = record.get(key)
    return value if isinstance(value, str) else None


def _time(record: dict[str, object], key: str) -> datetime | None:
    """A time Claude Code records in milliseconds since the epoch."""
    value = record.get(key)
    return datetime.fromtimestamp(value / 1000, UTC) if isinstance(value, int | float) else None


def _alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True
