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
        last_activity=datetime(2026, 10, 31, 14, 0, tzinfo=UTC),
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
