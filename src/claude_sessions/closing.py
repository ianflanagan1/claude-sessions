"""Which running sessions to close because they're archived in the editor that started them."""

from collections.abc import Mapping
from datetime import timedelta

from claude_sessions.processes import Process
from claude_sessions.registry import Entry

MINIMUM_AGE = timedelta(minutes=1)
"""How long a session's process must have run before it's closed, however long ago the session
was archived, so one just opened, even from the archived list, is left to settle."""


def closable(
    entries: list[Entry],
    archived: frozenset[str],
    working: frozenset[str],
    processes: Mapping[int, Process | None],
) -> list[Entry]:
    """The sessions safe to close: archived, idle with no subagent running (working holds the
    ids of those with one), started by an editor's Claude Code panel, and still the process their
    record names, which started when the record says and has run for MINIMUM_AGE (processes
    gives each pid's process). A session resumed in a terminal keeps its archived id, so isn't
    one of them; nor is one busy or waiting for you, one whose background subagent is still at
    work, since it runs in the session's process, or one whose process can't be told."""
    return [
        entry
        for entry in entries
        if entry.session_id in archived
        and entry.status == "idle"
        and entry.session_id not in working
        and entry.entrypoint == "claude-vscode"
        and _settled(entry, processes.get(entry.pid))
    ]


def _settled(entry: Entry, process: Process | None) -> bool:
    return (
        process is not None
        and entry.process_started is not None
        and entry.process_started.split() == process.started.split()
        and process.age >= MINIMUM_AGE
    )


def summary(closed: int) -> str:
    """How many archived sessions were closed."""
    noun = "session" if closed == 1 else "sessions"
    return f"Closed {closed} archived {noun}."


def summary_within(closed: int, place: str | None) -> str:
    """How many archived sessions working in place, or anywhere when there's none, were closed."""
    if place is None:
        return summary(closed)
    noun = "session" if closed == 1 else "sessions"
    return f"Closed {closed} archived {noun} in {place}."


def none_to_close(place: str | None) -> str:
    """That no archived session, or none working in place, was there to close."""
    if place is None:
        return "No archived sessions to close."
    return f"No archived sessions in {place} to close."
