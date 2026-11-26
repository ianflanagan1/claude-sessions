"""What a session's transcript says it changed, and where it ran commands."""

import json
from datetime import UTC, datetime
from pathlib import Path

from claude_sessions import activity
from claude_sessions.activity import Edited, RanIn

AT = "2026-11-05T10:00:00.000Z"
WHEN = datetime(2026, 11, 5, 10, 0, tzinfo=UTC)


def lines(*records: dict[str, object]) -> list[str]:
    return [json.dumps(r) for r in records]


def call(name: str, tool_input: dict[str, object], **fields: object) -> dict[str, object]:
    use = {"type": "tool_use", "id": "toolu_1", "name": name, "input": tool_input}
    return {
        "type": "assistant",
        "timestamp": AT,
        "cwd": "/home/me/app",
        "message": {"content": [use]},
    } | fields


def result(cwd: str, tool_use_id: str = "toolu_1") -> dict[str, object]:
    answer = {"type": "tool_result", "tool_use_id": tool_use_id, "content": "ok"}
    return {"type": "user", "timestamp": AT, "cwd": cwd, "message": {"content": [answer]}}


def test_an_empty_transcript_changed_nothing():
    assert activity.touches([]) == []


def test_a_file_written_or_edited_is_changed():
    assert activity.touches(
        lines(
            call("Edit", {"file_path": "/home/me/app/a.py"}),
            call("Write", {"file_path": "/home/me/app/b.py"}),
            call("MultiEdit", {"file_path": "/home/me/app/c.py"}),
            call("NotebookEdit", {"notebook_path": "/home/me/app/d.ipynb"}),
        )
    ) == [
        Edited("/home/me/app/a.py", WHEN),
        Edited("/home/me/app/b.py", WHEN),
        Edited("/home/me/app/c.py", WHEN),
        Edited("/home/me/app/d.ipynb", WHEN),
    ]


def test_a_relative_path_is_from_the_directory_it_was_edited_in():
    assert activity.touches(lines(call("Edit", {"file_path": "src/a.py"}))) == [
        Edited("/home/me/app/src/a.py", WHEN)
    ]


def test_a_command_ran_where_it_was_called_and_where_it_left_the_session():
    assert activity.touches(
        lines(call("Bash", {"command": "cd ../lib && make"}), result("/home/me/lib"))
    ) == [RanIn("/home/me/app", WHEN), RanIn("/home/me/lib", WHEN)]


def test_another_tools_result_is_not_a_command():
    assert activity.touches(
        lines(call("Bash", {"command": "ls"}), result("/home/me/lib", tool_use_id="toolu_2"))
    ) == [RanIn("/home/me/app", WHEN)]


def test_reading_and_searching_change_nothing():
    assert (
        activity.touches(
            lines(
                call("Read", {"file_path": "/home/me/app/a.py"}),
                call("Grep", {"pattern": "x", "path": "/home/me/app"}),
            )
        )
        == []
    )


def test_a_record_that_cant_be_read_is_skipped():
    assert activity.touches(
        [
            "not json",
            json.dumps([1, 2]),
            json.dumps(call("Edit", {"file_path": 7})),
            json.dumps(call("Edit", {"file_path": "/home/me/app/a.py"}, timestamp="soon")),
            json.dumps(call("Edit", {"file_path": "/home/me/app/a.py"}, message="text")),
            json.dumps(call("Edit", {"file_path": "/home/me/app/b.py"})),
        ]
    ) == [Edited("/home/me/app/b.py", WHEN)]


def test_what_its_subagents_did_counts_as_the_sessions_own(tmp_path: Path):
    project = tmp_path / "-home-me-app"
    (project / "s1" / "subagents").mkdir(parents=True)
    (project / "s1.jsonl").write_text(
        "\n".join(lines(call("Edit", {"file_path": "/home/me/app/a.py"})))
    )
    (project / "s1" / "subagents" / "agent-1.jsonl").write_text(
        "\n".join(lines(call("Write", {"file_path": "/home/me/app/b.py"})))
    )
    (project / "s2.jsonl").write_text(
        "\n".join(lines(call("Write", {"file_path": "/home/me/app/c.py"})))
    )
    assert sorted(t.path for t in activity.read(tmp_path, "s1") if isinstance(t, Edited)) == [
        "/home/me/app/a.py",
        "/home/me/app/b.py",
    ]


def test_what_the_subagents_of_its_workflows_did_counts_as_the_sessions_own(tmp_path: Path):
    run = tmp_path / "-home-me-app" / "s1" / "subagents" / "workflows" / "wf_1"
    run.mkdir(parents=True)
    (run / "agent-1.jsonl").write_text(
        "\n".join(lines(call("Write", {"file_path": "/home/me/app/b.py"})))
    )
    assert [t.path for t in activity.read(tmp_path, "s1") if isinstance(t, Edited)] == [
        "/home/me/app/b.py"
    ]


def test_a_session_with_no_transcript_did_nothing(tmp_path: Path):
    assert activity.read(tmp_path, "s1") == []
