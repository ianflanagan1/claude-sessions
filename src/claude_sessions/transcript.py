"""What a session's transcript tells about it: ~/.claude/projects/<dir>/<session id>.jsonl, one
JSON record a line, appended to as the session goes on.

The format is Claude Code's own and may change, so a record or field that isn't as expected is
skipped, not an error.
"""

import json
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import final

# Replies Claude Code makes up itself, such as for an interrupted turn, name this model.
_SYNTHETIC = "<synthetic>"
_USAGE = ("input_tokens", "cache_read_input_tokens", "cache_creation_input_tokens")


@final
@dataclass(frozen=True)
class Transcript:
    ai_title: str | None
    """The title Claude gave the conversation, the latest of the ones it gave as it went on."""
    cwd: str | None
    """The directory it last worked in. (Its gitBranch is the one it started on, so isn't used.)"""
    model: str | None
    context_tokens: int | None
    """How much of the context window the latest reply used."""
    last_activity: datetime | None


UNKNOWN = Transcript(None, None, None, None, None)


def summarise(lines: Iterable[str]) -> Transcript:
    """What the lines of a transcript tell, the latest of each."""
    ai_title = cwd = model = None
    context_tokens = last_activity = None
    for line in lines:
        record = _record(line)
        if record is None:
            continue
        match record.get("type"):
            case "ai-title":
                ai_title = _text(record, "aiTitle") or ai_title
            case "user" | "assistant" if not record.get("isSidechain"):
                cwd = _text(record, "cwd") or cwd
                last_activity = _time(record) or last_activity
                if record["type"] == "assistant":
                    reply = _reply(record)
                    if reply is not None:
                        model, context_tokens = reply
            case _:  # Other kinds of record, an open set Claude Code adds to.
                pass
    return Transcript(ai_title, cwd, model, context_tokens, last_activity)


def read(projects_dir: Path, session_id: str) -> Transcript:
    """The transcript of session_id, from whichever directory under projects_dir holds it, or
    UNKNOWN when none does."""
    for path in projects_dir.glob(f"*/{session_id}.jsonl"):
        try:
            with path.open(encoding="utf-8", errors="replace") as lines:
                return summarise(lines)
        except OSError:
            continue
    return UNKNOWN


def _record(line: str) -> dict[str, object] | None:
    try:
        record = json.loads(line)
    except ValueError:
        return None
    return record if isinstance(record, dict) else None


def _reply(record: dict[str, object]) -> tuple[str, int] | None:
    """The model of a real reply, and the tokens of context it was given."""
    message = record.get("message")
    if not isinstance(message, dict):
        return None
    model = message.get("model")
    usage = message.get("usage")
    if not isinstance(model, str) or model == _SYNTHETIC or not isinstance(usage, dict):
        return None
    return model, sum(n for key in _USAGE if isinstance(n := usage.get(key), int))


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
