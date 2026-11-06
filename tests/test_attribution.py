"""Telling which running sessions made a repository's uncommitted changes."""

from dataclasses import replace
from datetime import UTC, datetime, timedelta

from claude_sessions import attribution
from claude_sessions.activity import Edited, RanIn
from claude_sessions.attribution import File, Report, Session, Worker
from claude_sessions.git import Change

REPO = "/home/me/app"
COMMITTED = datetime(2026, 11, 5, 9, 0, tzinfo=UTC)
AFTER = COMMITTED + timedelta(minutes=5)
BEFORE = COMMITTED - timedelta(minutes=5)
EDITED = Change(" M", "src/a.py")
UNTRACKED = Change("??", "notes.txt")
BUSY = Session(pid=4242, session_id="s1", title="Fix the form", status="busy", own=False)
IDLE = Session(pid=4343, session_id="s2", title="Tidy up", status="idle", own=False)


def report(changes: list[Change], *workers: Worker) -> Report:
    committed = {"src/a.py": COMMITTED, "notes.txt": None}
    return attribution.report(REPO, changes, committed, COMMITTED, list(workers))


def edited(session: Session, path: str, at: datetime) -> Worker:
    return Worker(session, (Edited(path, at),))


def test_a_file_a_session_edited_since_it_was_last_committed_is_that_sessions():
    assert report([EDITED], edited(BUSY, "/home/me/app/src/a.py", AFTER)) == Report(
        REPO, (File(EDITED, (BUSY,)),), ()
    )


def test_an_edit_before_the_file_was_last_committed_is_not_its_change():
    found = report([EDITED], edited(BUSY, "/home/me/app/src/a.py", BEFORE))
    assert found.files == (File(EDITED, ()),)


def test_any_edit_to_a_file_never_committed_is_its_change():
    found = report([UNTRACKED], edited(BUSY, "/home/me/app/notes.txt", BEFORE))
    assert found.files == (File(UNTRACKED, (BUSY,)),)


def test_an_edit_to_another_file_or_another_repository_is_not_its_change():
    found = report(
        [EDITED],
        edited(BUSY, "/home/me/app/src/b.py", AFTER),
        edited(IDLE, "/home/me/other/src/a.py", AFTER),
    )
    assert found.files == (File(EDITED, ()),)


def test_every_session_that_edited_a_file_shares_it():
    found = report(
        [EDITED],
        edited(BUSY, "/home/me/app/src/a.py", AFTER),
        edited(IDLE, "/home/me/app/src/a.py", AFTER),
    )
    assert found.files == (File(EDITED, (BUSY, IDLE)),)


def test_a_session_that_ran_commands_in_the_repository_since_its_last_commit_may_have_changed_it():
    found = report(
        [EDITED],
        Worker(BUSY, (RanIn("/home/me/app/src", AFTER),)),
        Worker(IDLE, (RanIn("/home/me/app", BEFORE),)),
        Worker(replace(IDLE, session_id="s3"), (RanIn("/home/me/apple", AFTER),)),
    )
    assert found.commands_by == (BUSY,)


def test_with_no_commit_any_command_run_in_the_repository_counts():
    found = attribution.report(REPO, [UNTRACKED], {}, None, [Worker(IDLE, (RanIn(REPO, BEFORE),))])
    assert found.commands_by == (IDLE,)


def test_the_files_no_session_edited_are_unattributed():
    found = report([EDITED, UNTRACKED], edited(BUSY, "/home/me/app/src/a.py", AFTER))
    assert attribution.unattributed(found) == [UNTRACKED]


def test_it_lists_each_file_with_the_sessions_that_edited_it():
    own = replace(IDLE, own=True)
    found = report(
        [EDITED, UNTRACKED],
        edited(BUSY, "/home/me/app/src/a.py", AFTER),
        Worker(own, (Edited("/home/me/app/src/a.py", AFTER), RanIn(REPO, AFTER))),
    )
    assert attribution.lines(found) == [
        " M src/a.py   Fix the form (busy), Tidy up (idle, this session)",
        "?? notes.txt  no running session",
        "Commands run here since the last commit: Tidy up (idle, this session)",
    ]


def test_it_sums_up_whats_uncommitted_and_how_much_sessions_edited():
    found = report([EDITED, UNTRACKED], edited(BUSY, "/home/me/app/src/a.py", AFTER))
    assert attribution.summary(found, "/home/me") == (
        "2 files uncommitted in ~/app, 1 edited by a running session."
    )
    assert attribution.summary(report([]), "/home/me") == "Nothing uncommitted in ~/app."


def test_as_json_it_gives_each_file_its_sessions_and_the_unattributed_files():
    found = report([EDITED, UNTRACKED], edited(BUSY, "/home/me/app/src/a.py", AFTER))
    busy = {"session_id": "s1", "pid": 4242, "title": "Fix the form", "status": "busy"}
    assert attribution.as_json(found) == {
        "repo": REPO,
        "files": [
            {"path": "src/a.py", "status": " M", "edited_by": [busy | {"own": False}]},
            {"path": "notes.txt", "status": "??", "edited_by": []},
        ],
        "commands_by": [],
        "unattributed": ["notes.txt"],
    }
