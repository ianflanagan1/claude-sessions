"""A session's subagents, whether started with the Agent tool, by a skill or by a workflow. Each
keeps its own transcript, ~/.claude/projects/<dir>/<session id>/subagents/agent-<id>.jsonl, beside
agent-<id>.meta.json saying what it was asked to do and whether to run in the background. A
workflow's are in subagents/workflows/<run id>/ instead, beside the run's journal.jsonl, which
records what each returned, and once the run has ended it is recorded in
<session id>/workflows/<run id>.json.

They run in the session's process, with no record of their own in ~/.claude/sessions, so whether
one is still running is told from its transcript and the session's, and a workflow's from its
run's. The format is Claude Code's own and may change, so a file or field that isn't as expected
is skipped, not an error: a subagent left out, never one listed as running for good.
"""

import json
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import Enum, auto
from pathlib import Path
from typing import assert_never, final

from claude_sessions import transcript
from claude_sessions.transcript import Transcript

_ACTIVE = ("busy", "waiting")
_BACKGROUND = "background"
_PREFIX = "agent-"
_META = ".meta.json"
_WORKFLOWS = "workflows"
_JOURNAL = "journal.jsonl"
_RESULT = "result"


class Shape(Enum):
    """How a subagent was started, which tells how long it runs."""

    FOREGROUND = auto()
    BACKGROUND = auto()
    WORKFLOW = auto()


@final
@dataclass(frozen=True)
class Meta:
    title: str | None
    """What it was asked to do, else its kind of agent."""
    shape: Shape


@final
@dataclass(frozen=True)
class Subagent:
    agent_id: str
    meta: Meta
    transcript: Transcript
    finished: bool
    """Whether its workflow's run says it has finished: its journal records what the subagent
    returned, or the run has ended. Only a workflow's subagent is known to have finished."""


def meta(record: object) -> Meta | None:
    """What a subagent's metadata says, or None when it isn't a record."""
    if not isinstance(record, dict):
        return None
    if record.get("inWorkflowRun") is True:
        shape = Shape.WORKFLOW
    elif record.get("requestShape") == _BACKGROUND:
        shape = Shape.BACKGROUND
    else:
        shape = Shape.FOREGROUND
    return Meta(title=_text(record, "description") or _text(record, "agentType"), shape=shape)


def returned(journal: Iterable[str]) -> frozenset[str]:
    """The agent ids of the subagents whose result the lines of a workflow run's journal record."""
    found: set[str] = set()
    for line in journal:
        try:
            record = json.loads(line)
        except ValueError:
            continue
        if isinstance(record, dict) and record.get("type") == _RESULT:
            agent_id = _text(record, "agentId")
            if agent_id is not None:
                found.add(agent_id)
    return frozenset(found)


def running(
    subagents: Iterable[Subagent], status: str | None, session: Transcript, since: datetime | None
) -> list[Subagent]:
    """The subagents still running, of a session whose status is status, whose own transcript
    tells session, and whose process started at since.

    A subagent ends with the process that ran it, so one last active before since is taken to have
    ended then, and without since none is known to be running. A background subagent runs until
    its session is told it stopped, and again once it's active after that, as when sent a message.
    A foreground one runs while its session is mid-turn and waiting on it: until its reply ends
    its turn, or the session moves on without it, as when interrupted. A workflow's runs, whatever
    its session is doing, until it has finished.
    """
    if since is None:
        return []
    return [s for s in subagents if _running(s, status, session, since)]


def read(projects_dir: Path, session_id: str, since: datetime | None) -> list[Subagent]:
    """The subagents of session_id that may still be running in its process, started at since,
    from whichever directory under projects_dir holds them, its workflows' among them. Those whose
    transcript was last written before since, so can't be, aren't read. A file that can't be read
    is skipped."""
    if since is None:
        return []
    found: list[Subagent] = []
    for session_dir in sorted(projects_dir.glob(f"*/{session_id}")):
        folder = session_dir / "subagents"
        found.extend(_read(folder, since, lambda _: False))
        for run in sorted(p for p in folder.glob(f"{_WORKFLOWS}/*") if p.is_dir()):
            found.extend(_read(run, since, _finished(session_dir, run)))
    return found


def _read(folder: Path, since: datetime, finished: Callable[[str], bool]) -> list[Subagent]:
    found = []
    for path in sorted(folder.glob(f"{_PREFIX}*{_META}")):
        agent_id = path.name.removeprefix(_PREFIX).removesuffix(_META)
        log = path.with_name(f"{_PREFIX}{agent_id}.jsonl")
        try:
            if datetime.fromtimestamp(log.stat().st_mtime, UTC) < since:
                continue
            about = meta(json.loads(path.read_text()))
            if about is None:
                continue
            with log.open(encoding="utf-8", errors="replace") as lines:
                summary = transcript.summarise_subagent(lines)
            found.append(Subagent(agent_id, about, summary, finished(agent_id)))
        except (OSError, ValueError):
            continue
    return found


def _finished(session_dir: Path, run: Path) -> Callable[[str], bool]:
    """Which of the subagents of the workflow run in run have finished: all of them once the run
    has ended, else those its journal says returned. A journal that can't be read tells none."""
    if (session_dir / _WORKFLOWS / f"{run.name}.json").exists():
        return lambda _: True
    try:
        with (run / _JOURNAL).open(encoding="utf-8", errors="replace") as lines:
            done = returned(lines)
    except OSError:
        done = frozenset()
    return lambda agent_id: agent_id in done


def _running(subagent: Subagent, status: str | None, session: Transcript, since: datetime) -> bool:
    last = subagent.transcript.last_activity
    if last is None or last < since:
        return False
    match subagent.meta.shape:
        case Shape.BACKGROUND:
            stopped = session.subagents_stopped.get(subagent.agent_id)
            return stopped is None or stopped < last
        case Shape.FOREGROUND:
            moved_on = session.last_activity is not None and session.last_activity > last
            return status in _ACTIVE and not subagent.transcript.ended and not moved_on
        case Shape.WORKFLOW:
            return not subagent.finished
        case _:
            assert_never(subagent.meta.shape)


def _text(record: dict[str, object], key: str) -> str | None:
    value = record.get(key)
    return value if isinstance(value, str) and value else None
