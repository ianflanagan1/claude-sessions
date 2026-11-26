"""Reading Claude Code's own record of a running session, from ~/.claude/sessions/<pid>.json."""

from datetime import UTC, datetime

from claude_sessions import registry


def record(**fields: object) -> dict[str, object]:
    return {
        "pid": 4242,
        "sessionId": "s1",
        "cwd": "/home/me/projects/app",
        "status": "idle",
        "name": "app-86",
        "nameSource": "derived",
        "startedAt": 1793342291298,
        "updatedAt": 1793342364673,
        "statusUpdatedAt": 1793342360000,
        "entrypoint": "claude-vscode",
        "procStart": "Fri Oct 30 06:38:10 2026",
    } | fields


def test_a_record_gives_where_the_session_started_and_its_status():
    entry = registry.parse(record())
    assert entry == registry.Entry(
        pid=4242,
        session_id="s1",
        cwd="/home/me/projects/app",
        status="idle",
        name="app-86",
        named_by="derived",
        updated=datetime.fromtimestamp(1793342364.673, UTC),
        status_changed=datetime.fromtimestamp(1793342360, UTC),
        entrypoint="claude-vscode",
        process_started="Fri Oct 30 06:38:10 2026",
    )


def test_a_record_without_a_pid_or_session_id_is_not_a_session():
    assert registry.parse(record(pid=None)) is None
    assert registry.parse(record(sessionId=None)) is None
    assert registry.parse(["not", "a", "record"]) is None


def test_a_missing_name_status_or_time_is_left_unknown():
    entry = registry.parse({"pid": 1, "sessionId": "s1"})
    assert entry == registry.Entry(
        pid=1,
        session_id="s1",
        cwd=None,
        status=None,
        name=None,
        named_by=None,
        updated=None,
        status_changed=None,
        entrypoint=None,
        process_started=None,
    )
