"""What a session's transcript says it changed: the files it wrote or edited with Claude Code's
own tools, and the directories it ran shell commands in, whose changes the transcript can't name.

A session's subagents keep their own transcripts, in ~/.claude/projects/<dir>/<session id>/
subagents/, and what they did counts as the session's. The format is Claude Code's own and may
change, so a record or field that isn't as expected is skipped, not an error.
"""

import json
import os
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import final

# The tools that change a file, and the input naming it.
_EDITS = {
    "Edit": "file_path",
    "MultiEdit": "file_path",
    "Write": "file_path",
    "NotebookEdit": "notebook_path",
}
_COMMAND = "Bash"


@final
@dataclass(frozen=True)
class Edited:
    path: str
    """The file, absolute, as the session named it."""
    at: datetime


@final
@dataclass(frozen=True)
class RanIn:
    directory: str
    """Where a command was run from, or where it left the session, as by a `cd` that lasts."""
    at: datetime


type Touch = Edited | RanIn


def touches(lines: Iterable[str]) -> list[Touch]:
    """What the lines of a transcript changed, in order."""
    found: list[Touch] = []
    commands: set[str] = set()  # The ids of the commands run, to find where each left it.
    for line in lines:
        record = _record(line)
        if record is None:
            continue
        cwd = _text(record, "cwd")
        at = _time(record)
        if cwd is None or at is None:
            continue
        for part in _content(record):
            match part.get("type"):
                case "tool_use":
                    touch = _use(part, cwd, at)
                    if touch is not None:
                        found.append(touch)
                    if part.get("name") == _COMMAND and isinstance(part.get("id"), str):
                        commands.add(str(part["id"]))
                case "tool_result" if part.get("tool_use_id") in commands:
                    found.append(RanIn(cwd, at))
                case _:  # Text, thinking and other parts, an open set Claude Code adds to.
                    pass
    return found


def read(projects_dir: Path, session_id: str) -> list[Touch]:
    """What session_id and its subagents changed, from whichever directory under projects_dir
    holds its transcript, or nothing when none does. A file that can't be read is skipped."""
    found: list[Touch] = []
    paths = [
        *projects_dir.glob(f"*/{session_id}.jsonl"),
        *projects_dir.glob(f"*/{session_id}/subagents/*.jsonl"),
    ]
    for path in paths:
        try:
            with path.open(encoding="utf-8", errors="replace") as lines:
                found.extend(touches(lines))
        except OSError:
            continue
    return found


def _use(part: dict[str, object], cwd: str, at: datetime) -> Touch | None:
    name = part.get("name")
    tool_input = part.get("input")
    if not isinstance(name, str) or not isinstance(tool_input, dict):
        return None
    if name == _COMMAND:
        return RanIn(cwd, at)
    key = _EDITS.get(name)
    path = tool_input.get(key) if key is not None else None
    if not isinstance(path, str) or not path:
        return None
    return Edited(os.path.normpath(os.path.join(cwd, path)), at)


def _content(record: dict[str, object]) -> list[dict[str, object]]:
    message = record.get("message")
    content = message.get("content") if isinstance(message, dict) else None
    if not isinstance(content, list):
        return []
    return [part for part in content if isinstance(part, dict)]


def _record(line: str) -> dict[str, object] | None:
    try:
        record = json.loads(line)
    except ValueError:
        return None
    return record if isinstance(record, dict) else None


def _time(record: dict[str, object]) -> datetime | None:
    stamp = _text(record, "timestamp")
    if stamp is None:
        return None
    try:
        return datetime.fromisoformat(stamp)
    except ValueError:
        return None


def _text(record: dict[str, object], key: str) -> str | None:
    value = record.get(key)
    return value if isinstance(value, str) and value else None
