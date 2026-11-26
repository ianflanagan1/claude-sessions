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
    status_changed=None,
    entrypoint="claude-vscode",
    process_started=STARTED,
)
SETTLED = Process(age=timedelta(minutes=1), started=STARTED)


def close(entry: Entry, process: Process | None) -> bool:
    return closing.closable([entry], frozenset({"s1"}), frozenset(), {entry.pid: process}) == [
        entry
    ]


def test_an_idle_session_with_a_subagent_still_running_is_kept():
    assert (
        closing.closable([ENTRY], frozenset({"s1"}), frozenset({"s1"}), {ENTRY.pid: SETTLED}) == []
    )


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


def test_one_closed_session_is_counted_singly():
    assert closing.summary(1) == "Closed 1 archived session."


def test_several_closed_sessions_are_counted():
    assert closing.summary(3) == "Closed 3 archived sessions."


def test_sessions_closed_within_a_directory_are_counted_there():
    assert (
        closing.summary_within(3, "~/projects/app")
        == "Closed 3 archived sessions in ~/projects/app."
    )


def test_none_to_close_says_so():
    assert closing.none_to_close(None) == "No archived sessions to close."


def test_none_to_close_within_a_directory_says_where():
    assert (
        closing.none_to_close("~/projects/app")
        == "No archived sessions in ~/projects/app to close."
    )


def test_sessions_closed_within_no_directory_are_counted_as_closed_anywhere():
    assert closing.summary_within(3, None) == "Closed 3 archived sessions."


def test_a_session_hidden_in_the_panel_that_started_it_is_archived():
    assert closing.archived_in_editor(ENTRY, frozenset({"s1"}))


def test_a_session_not_hidden_is_not_archived():
    assert not closing.archived_in_editor(ENTRY, frozenset({"s2"}))


def test_a_hidden_session_resumed_in_a_terminal_is_not_archived():
    assert not closing.archived_in_editor(replace(ENTRY, entrypoint="cli"), frozenset({"s1"}))
    assert not closing.archived_in_editor(replace(ENTRY, entrypoint=None), frozenset({"s1"}))
