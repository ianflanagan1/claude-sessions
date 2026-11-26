"""What a session's transcript tells about it: ~/.claude/projects/<dir>/<session id>.jsonl, one
JSON record a line, appended to as the session goes on.

The format is Claude Code's own and may change, so a record or field that isn't as expected is
skipped, not an error.
"""

import json
import re
from collections.abc import Iterable, Iterator, Mapping
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import final

# Replies Claude Code makes up itself, such as for an interrupted turn, name this model.
_SYNTHETIC = "<synthetic>"
_USAGE = ("input_tokens", "cache_read_input_tokens", "cache_creation_input_tokens")
_END_TURN = "end_turn"
# What tells a session one of its background subagents stopped, and the kinds of record it's
# written in: queued, then attached to a turn, or given as a prompt. Others, such as a record of an
# API request, can repeat it later.
_STOPPED = re.compile(r"<task-notification>\s*<task-id>([^<\s]+)</task-id>")
_TOLD_IN = ("queue-operation", "attachment", "user")


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
    first_activity: datetime | None
    """When its first prompt or reply was written, so when it started."""
    last_activity: datetime | None
    started: bool
    """Whether it holds a message of its own, a prompt or a reply. One just opened holds none."""
    ended: bool
    """Whether its latest message is a reply that ended its turn."""
    subagents_stopped: Mapping[str, datetime]
    """When it was last told each of its background subagents had stopped, by agent id."""


UNKNOWN = Transcript(None, None, None, None, None, None, False, False, {})


def summarise(lines: Iterable[str]) -> Transcript:
    """What the lines of a session's transcript tell, the latest of each. Its subagents' messages,
    which it can carry too, are left out."""
    return _summarise(lines, False)


def summarise_subagent(lines: Iterable[str]) -> Transcript:
    """What the lines of a subagent's own transcript tell, the latest of each. All its messages
    are marked as a sidechain, the subagent's."""
    return _summarise(lines, True)


def _summarise(lines: Iterable[str], sidechain: bool) -> Transcript:
    ai_title = cwd = model = None
    context_tokens = first_activity = last_activity = None
    started = ended = False
    stopped: dict[str, datetime] = {}
    for line in lines:
        record = _record(line)
        if record is None:
            continue
        kind = record.get("type")
        at = _time(record)
        if kind in _TOLD_IN and at is not None:
            for agent_id in _stopped_in(record):
                stopped[agent_id] = max(at, stopped.get(agent_id, at))
        match kind:
            case "ai-title":
                ai_title = _text(record, "aiTitle") or ai_title
            case "user" | "assistant" if bool(record.get("isSidechain")) == sidechain:
                cwd = _text(record, "cwd") or cwd
                first_activity = first_activity or at
                last_activity = at or last_activity
                started = True
                ended = False
                if kind == "assistant":
                    ended = _stop_reason(record) == _END_TURN
                    reply = _reply(record)
                    if reply is not None:
                        model, context_tokens = reply
            case _:  # Other kinds of record, an open set Claude Code adds to.
                pass
    return Transcript(
        ai_title, cwd, model, context_tokens, first_activity, last_activity, started, ended, stopped
    )


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


def _stopped_in(record: dict[str, object]) -> list[str]:
    """The agent ids of the background subagents the record tells have stopped."""
    return [agent_id for text in _strings(record) for agent_id in _STOPPED.findall(text)]


def _strings(value: object) -> Iterator[str]:
    """Every string in value, however deep."""
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for item in value.values():
            yield from _strings(item)
    elif isinstance(value, list):
        for item in value:
            yield from _strings(item)


def _stop_reason(record: dict[str, object]) -> object:
    message = record.get("message")
    return message.get("stop_reason") if isinstance(message, dict) else None


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
