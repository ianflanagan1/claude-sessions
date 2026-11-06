"""Choosing which running sessions to close because they're archived."""

from dataclasses import replace
from datetime import timedelta

from claude_sessions import closing
from claude_sessions.processes import Process
from claude_sessions.registry import Entry

STARTED = "Fri Oct 30 06:38:10 2026"
ENTRY = Entry(
    pid=4242,
    session_id="s1",
    cwd="/home/me/projects/app",
    status="idle",
    name="app-86",
    named_by="derived",
    updated=None,
    entrypoint="claude-vscode",
    process_started=STARTED,
)
SETTLED = Process(age=timedelta(minutes=1), started=STARTED)


def close(entry: Entry, process: Process | None) -> bool:
    return closing.closable([entry], frozenset({"s1"}), {entry.pid: process}) == [entry]


def test_an_idle_archived_editor_session_whose_process_has_run_a_minute_is_closed():
    assert close(ENTRY, SETTLED)


def test_a_session_whose_process_has_run_under_a_minute_is_kept():
    assert not close(ENTRY, replace(SETTLED, age=timedelta(seconds=59)))


def test_the_start_is_compared_ignoring_how_ps_pads_it():
    assert close(ENTRY, replace(SETTLED, started="Fri Oct 30  06:38:10 2026   "))


def test_a_session_that_isnt_archived_is_kept():
    assert not close(replace(ENTRY, session_id="s2"), SETTLED)


def test_a_session_busy_or_waiting_for_you_is_kept():
    assert not close(replace(ENTRY, status="busy"), SETTLED)
    assert not close(replace(ENTRY, status="waiting"), SETTLED)
    assert not close(replace(ENTRY, status=None), SETTLED)


def test_a_session_resumed_in_a_terminal_is_kept():
    assert not close(replace(ENTRY, entrypoint="cli"), SETTLED)
    assert not close(replace(ENTRY, entrypoint=None), SETTLED)


def test_a_process_that_started_after_the_record_was_written_is_kept():
    assert not close(ENTRY, replace(SETTLED, started="Sat Oct 31 09:00:00 2026"))


def test_a_session_whose_process_cant_be_told_is_kept():
    assert not close(ENTRY, None)
    assert not close(replace(ENTRY, process_started=None), SETTLED)
