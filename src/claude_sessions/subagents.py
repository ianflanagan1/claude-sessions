"""A session's subagents, whether started with the Agent tool or by a skill. Each keeps its own
transcript, ~/.claude/projects/<dir>/<session id>/subagents/agent-<id>.jsonl, beside
agent-<id>.meta.json saying what it was asked to do and whether to run in the background.

They run in the session's process, with no record of their own in ~/.claude/sessions, so whether
one is still running is told from its transcript and the session's. The format is Claude Code's
own and may change, so a file or field that isn't as expected is skipped, not an error: a
subagent left out, never one listed as running for good.
"""

import json
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import final

from claude_sessions import transcript
from claude_sessions.transcript import Transcript

_ACTIVE = ("busy", "waiting")
_BACKGROUND = "background"
_PREFIX = "agent-"
_META = ".meta.json"


@final
@dataclass(frozen=True)
class Meta:
    title: str | None
    """What it was asked to do, else its kind of agent."""
    background: bool


@final
@dataclass(frozen=True)
class Subagent:
    agent_id: str
    meta: Meta
    transcript: Transcript


def meta(record: object) -> Meta | None:
    """What a subagent's metadata says, or None when it isn't a record."""
    if not isinstance(record, dict):
        return None
    return Meta(
        title=_text(record, "description") or _text(record, "agentType"),
        background=record.get("requestShape") == _BACKGROUND,
    )


def running(
    subagents: Iterable[Subagent], status: str | None, session: Transcript, since: datetime | None
) -> list[Subagent]:
    """The subagents still running, of a session whose status is status, whose own transcript
    tells session, and whose process started at since.

    A subagent ends with the process that ran it, so one last active before since is taken to have
    ended then, and without since none is known to be running. A background subagent runs until
    its session is told it stopped, and again once it's active after that, as when sent a message.
    A foreground one runs while its session is mid-turn and waiting on it: until its reply ends
    its turn, or the session moves on without it, as when interrupted.
    """
    if since is None:
        return []
    return [s for s in subagents if _running(s, status, session, since)]


def read(projects_dir: Path, session_id: str, since: datetime | None) -> list[Subagent]:
    """The subagents of session_id that may still be running in its process, started at since,
    from whichever directory under projects_dir holds them. Those whose transcript was last
    written before since, so can't be, aren't read. A file that can't be read is skipped."""
    if since is None:
        return []
    found = []
    for path in sorted(projects_dir.glob(f"*/{session_id}/subagents/{_PREFIX}*{_META}")):
        agent_id = path.name.removeprefix(_PREFIX).removesuffix(_META)
        log = path.with_name(f"{_PREFIX}{agent_id}.jsonl")
        try:
            if datetime.fromtimestamp(log.stat().st_mtime, UTC) < since:
                continue
            about = meta(json.loads(path.read_text()))
            if about is None:
                continue
            with log.open(encoding="utf-8", errors="replace") as lines:
                found.append(Subagent(agent_id, about, transcript.summarise_subagent(lines)))
        except (OSError, ValueError):
            continue
    return found


def _running(subagent: Subagent, status: str | None, session: Transcript, since: datetime) -> bool:
    last = subagent.transcript.last_activity
    if last is None or last < since:
        return False
    if subagent.meta.background:
        stopped = session.subagents_stopped.get(subagent.agent_id)
        return stopped is None or stopped < last
    moved_on = session.last_activity is not None and session.last_activity > last
    return status in _ACTIVE and not subagent.transcript.ended and not moved_on


def _text(record: dict[str, object], key: str) -> str | None:
    value = record.get(key)
    return value if isinstance(value, str) and value else None
