"""Which running sessions made a repository's uncommitted changes, for tools that must not commit
work a session hasn't finished, nor change files under one still working.

A file is a session's when its transcript says it wrote or edited the file since the last commit
that changed it. A shell command can change any file without naming it, so a session that ran
commands in the repository since its last commit is listed for the whole repository instead.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import assert_never, final

from claude_sessions.activity import Edited, RanIn, Touch
from claude_sessions.git import Change
from claude_sessions.listing import from_home

_NONE = "no running session"


@final
@dataclass(frozen=True)
class Session:
    pid: int
    session_id: str
    title: str
    status: str | None
    """idle, busy or waiting, as Claude Code says: busy or waiting is mid-turn."""
    own: bool
    """Whether it's the session asking."""


@final
@dataclass(frozen=True)
class Worker:
    """A running session and what its transcript says it did, with symbolic links resolved."""

    session: Session
    touches: tuple[Touch, ...]


@final
@dataclass(frozen=True)
class File:
    change: Change
    edited_by: tuple[Session, ...]


@final
@dataclass(frozen=True)
class Report:
    repo: str
    files: tuple[File, ...]
    commands_by: tuple[Session, ...]
    """The sessions that ran commands in the repository since its last commit."""


def report(
    repo: str,
    changes: Sequence[Change],
    committed: Mapping[str, datetime | None],
    repo_committed: datetime | None,
    workers: Sequence[Worker],
) -> Report:
    """Who made each of repo's changes. committed gives when each changed path was last
    committed, None or missing for never; repo_committed when the repository last was."""
    files = tuple(
        File(
            change,
            tuple(
                w.session
                for w in workers
                if _edited(w, f"{repo}/{change.path}", committed.get(change.path))
            ),
        )
        for change in changes
    )
    commands_by = tuple(w.session for w in workers if _ran_in(w, repo, repo_committed))
    return Report(repo, files, commands_by)


def unattributed(report: Report) -> list[Change]:
    """The changes no running session edited: yours, or made by a command."""
    return [f.change for f in report.files if not f.edited_by]


def lines(report: Report) -> list[str]:
    """Each changed file and who edited it, then who ran commands in the repository."""
    width = max((len(f.change.path) for f in report.files), default=0)
    found = [
        f"{f.change.status} {f.change.path.ljust(width)}  {_names(f.edited_by)}".rstrip()
        for f in report.files
    ]
    if report.files and report.commands_by:
        found.append(f"Commands run here since the last commit: {_names(report.commands_by)}")
    return found


def summary(report: Report, home: str) -> str:
    where = from_home(report.repo, home)
    if not report.files:
        return f"Nothing uncommitted in {where}."
    total = len(report.files)
    edited = total - len(unattributed(report))
    noun = "file" if total == 1 else "files"
    by = "a running session" if edited == 1 else "running sessions"
    return f"{total} {noun} uncommitted in {where}, {edited} edited by {by}."


def as_json(report: Report) -> dict[str, object]:
    return {
        "repo": report.repo,
        "files": [
            {
                "path": f.change.path,
                "status": f.change.status,
                "edited_by": [_session_json(s) for s in f.edited_by],
            }
            for f in report.files
        ],
        "commands_by": [_session_json(s) for s in report.commands_by],
        "unattributed": [c.path for c in unattributed(report)],
    }


def _edited(worker: Worker, path: str, since: datetime | None) -> bool:
    return any(_edits(touch, path, since) for touch in worker.touches)


def _edits(touch: Touch, path: str, since: datetime | None) -> bool:
    match touch:
        case Edited():
            return touch.path == path and _after(touch.at, since)
        case RanIn():
            return False
        case _:
            assert_never(touch)


def _ran_in(worker: Worker, repo: str, since: datetime | None) -> bool:
    return any(_runs_in(touch, repo, since) for touch in worker.touches)


def _runs_in(touch: Touch, repo: str, since: datetime | None) -> bool:
    match touch:
        case RanIn():
            inside = touch.directory == repo or touch.directory.startswith(f"{repo}/")
            return inside and _after(touch.at, since)
        case Edited():
            return False
        case _:
            assert_never(touch)


def _after(at: datetime, since: datetime | None) -> bool:
    return since is None or at > since


def _names(sessions: Sequence[Session]) -> str:
    return ", ".join(_name(s) for s in sessions) or _NONE


def _name(session: Session) -> str:
    status = session.status or "unknown"
    mine = ", this session" if session.own else ""
    return f"{session.title} ({status}{mine})"


def _session_json(session: Session) -> dict[str, object]:
    return {
        "session_id": session.session_id,
        "pid": session.pid,
        "title": session.title,
        "status": session.status,
        "own": session.own,
    }
