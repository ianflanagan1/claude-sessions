"""Summarising a session's transcript, ~/.claude/projects/<dir>/<session id>.jsonl."""

import json
from datetime import UTC, datetime

from claude_sessions import transcript
from claude_sessions.transcript import Transcript


def lines(*records: dict[str, object]) -> list[str]:
    return [json.dumps(r) for r in records]


def assistant(**fields: object) -> dict[str, object]:
    usage = {
        "input_tokens": 3,
        "cache_read_input_tokens": 50_000,
        "cache_creation_input_tokens": 2_000,
    }
    return {
        "type": "assistant",
        "timestamp": "2026-10-31T13:31:00.000Z",
        "cwd": "/home/me/projects/app",
        "gitBranch": "main",
        "isSidechain": False,
        "message": {"model": "claude-opus-5-5", "usage": usage},
    } | fields


def test_an_empty_transcript_tells_nothing():
    assert transcript.summarise([]) == transcript.UNKNOWN


def test_the_title_is_the_latest_one_claude_gave_it():
    summary = transcript.summarise(
        lines(
            {"type": "ai-title", "aiTitle": "First idea"},
            {"type": "ai-title", "aiTitle": "Where it went"},
        )
    )
    assert summary.ai_title == "Where it went"


def test_where_it_is_and_what_runs_it_come_from_its_latest_reply():
    summary = transcript.summarise(
        lines(
            assistant(cwd="/home/me/projects/old"),
            assistant(timestamp="2026-10-31T14:00:00.000Z"),
        )
    )
    assert summary == Transcript(
        ai_title=None,
        cwd="/home/me/projects/app",
        model="claude-opus-5-5",
        context_tokens=52_003,
        first_activity=datetime(2026, 10, 31, 13, 31, tzinfo=UTC),
        last_activity=datetime(2026, 10, 31, 14, 0, tzinfo=UTC),
        started=True,
        ended=False,
        subagents_stopped={},
    )


def test_a_prompt_after_the_latest_reply_is_its_latest_activity():
    summary = transcript.summarise(
        lines(
            assistant(),
            {"type": "user", "timestamp": "2026-10-31T15:00:00.000Z", "cwd": "/home/me/x"},
        )
    )
    assert summary.last_activity == datetime(2026, 10, 31, 15, 0, tzinfo=UTC)
    assert summary.cwd == "/home/me/x"


def test_its_first_prompt_or_reply_is_its_first_activity():
    summary = transcript.summarise(
        lines(
            {"type": "queue-operation", "timestamp": "2026-10-31T13:00:00.000Z"},
            assistant(isSidechain=True, timestamp="2026-10-31T13:10:00.000Z"),
            {"type": "user", "timestamp": "2026-10-31T13:20:00.000Z"},
            assistant(),
        )
    )
    assert summary.first_activity == datetime(2026, 10, 31, 13, 20, tzinfo=UTC)


def test_a_subagents_replies_say_nothing_about_the_sessions_context():
    summary = transcript.summarise(
        lines(
            assistant(),
            assistant(isSidechain=True, message={"model": "claude-haiku-5-5", "usage": {}}),
        )
    )
    assert summary.model == "claude-opus-5-5"
    assert summary.context_tokens == 52_003


def test_a_reply_made_up_by_claude_code_itself_has_no_model():
    summary = transcript.summarise(
        lines(assistant(), assistant(message={"model": "<synthetic>", "usage": {}}))
    )
    assert summary.model == "claude-opus-5-5"
    assert summary.context_tokens == 52_003


def test_a_line_that_is_not_a_record_is_skipped():
    summary = transcript.summarise(
        ["{not json", "[1, 2]", *lines({"type": "ai-title", "aiTitle": "Kept"})]
    )
    assert summary.ai_title == "Kept"


def test_a_record_that_only_mentions_a_title_in_its_text_is_not_one():
    summary = transcript.summarise(
        lines(
            {"type": "ai-title", "aiTitle": "Real"},
            {"type": "user", "message": {"content": '{"type":"ai-title","aiTitle":"Quoted"}'}},
        )
    )
    assert summary.ai_title == "Real"


def test_a_subagents_own_transcript_tells_what_runs_it_and_how_far_it_has_got():
    summary = transcript.summarise_subagent(
        lines(
            assistant(isSidechain=True, cwd="/home/me/projects/app/.claude/worktrees/a1"),
            {"type": "user", "isSidechain": True, "timestamp": "2026-10-31T13:32:00.000Z"},
        )
    )
    assert summary == Transcript(
        ai_title=None,
        cwd="/home/me/projects/app/.claude/worktrees/a1",
        model="claude-opus-5-5",
        context_tokens=52_003,
        first_activity=datetime(2026, 10, 31, 13, 31, tzinfo=UTC),
        last_activity=datetime(2026, 10, 31, 13, 32, tzinfo=UTC),
        started=True,
        ended=False,
        subagents_stopped={},
    )


def test_a_transcript_with_a_prompt_or_a_reply_has_started():
    prompt = {"type": "user", "timestamp": "2026-10-31T13:30:00.000Z"}
    assert transcript.summarise(lines(prompt)).started
    assert transcript.summarise(lines(assistant())).started


def test_a_transcript_with_only_records_about_it_has_not_started():
    summary = transcript.summarise(
        lines({"type": "session-owner"}, {"type": "ai-title", "aiTitle": "Kept"})
    )
    assert not summary.started


def test_a_subagents_message_in_a_sessions_transcript_does_not_start_it():
    assert not transcript.summarise(lines(assistant(isSidechain=True))).started


def test_a_transcript_whose_latest_reply_ended_its_turn_has_ended():
    finished = assistant(message={"model": "claude-opus-5-5", "stop_reason": "end_turn"})
    calling = assistant(message={"model": "claude-opus-5-5", "stop_reason": "tool_use"})
    answered = {"type": "user", "timestamp": "2026-10-31T13:32:00.000Z"}
    assert transcript.summarise(lines(calling, finished)).ended
    assert not transcript.summarise(lines(calling)).ended
    assert not transcript.summarise(lines(finished, answered)).ended


def notification(record_type: str, agent_id: str, at: str) -> dict[str, object]:
    """A record, of a type Claude Code writes one in, telling the session at the time at that its
    background subagent agent_id stopped."""
    text = f"<task-notification>\n<task-id>{agent_id}</task-id>\n<status>completed</status>"
    record: dict[str, object] = {"type": record_type, "timestamp": at}
    match record_type:
        case "queue-operation":
            return record | {"operation": "enqueue", "content": text}
        case "attachment":
            return record | {"attachment": {"type": "queued_command", "prompt": text}}
        case "user":
            return record | {"message": {"content": [{"type": "text", "text": text}]}}
        case "api-request-blob":
            return record | {"body": {"messages": [{"content": text}]}}
    raise ValueError(record_type)


def test_it_tells_when_each_background_subagent_last_stopped():
    summary = transcript.summarise(
        lines(
            notification("queue-operation", "a1", "2026-10-31T13:00:00.000Z"),
            notification("attachment", "a1", "2026-10-31T13:20:00.000Z"),
            notification("user", "a2", "2026-10-31T13:10:00.000Z"),
        )
    )
    assert summary.subagents_stopped == {
        "a1": datetime(2026, 10, 31, 13, 20, tzinfo=UTC),
        "a2": datetime(2026, 10, 31, 13, 10, tzinfo=UTC),
    }


def test_a_notification_repeated_in_a_record_of_a_request_sent_is_not_when_it_stopped():
    summary = transcript.summarise(
        lines(
            notification("queue-operation", "a1", "2026-10-31T13:00:00.000Z"),
            notification("api-request-blob", "a1", "2026-10-31T14:00:00.000Z"),
        )
    )
    assert summary.subagents_stopped == {"a1": datetime(2026, 10, 31, 13, 0, tzinfo=UTC)}
