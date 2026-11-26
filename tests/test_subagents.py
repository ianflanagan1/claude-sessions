"""Which of a session's subagents are running, from their transcripts and the session's."""

import json
import os
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

from claude_sessions import subagents
from claude_sessions.subagents import Meta, Shape, Subagent
from claude_sessions.transcript import UNKNOWN, Transcript

STARTED = datetime(2026, 11, 8, 9, 0, tzinfo=UTC)
"""When the session's process started."""
NOW = STARTED + timedelta(hours=1)

SESSION = replace(UNKNOWN, last_activity=NOW - timedelta(minutes=5))
WORKING = replace(UNKNOWN, model="claude-sonnet-5-5", last_activity=NOW - timedelta(minutes=1))
FOREGROUND = Subagent("a1", Meta("Find the callers", Shape.FOREGROUND), WORKING, finished=False)
BACKGROUND = Subagent(
    "a2", Meta("Transition fields on move", Shape.BACKGROUND), WORKING, finished=False
)
IN_WORKFLOW = Subagent("a3", Meta("write:csharp", Shape.WORKFLOW), WORKING, finished=False)


def test_a_subagent_is_titled_by_what_it_was_asked_to_do_else_its_kind_of_agent():
    assert subagents.meta(
        {"agentType": "general-purpose", "description": "Find the callers"}
    ) == Meta("Find the callers", Shape.FOREGROUND)
    assert subagents.meta({"agentType": "ianf-commit-worker"}) == Meta(
        "ianf-commit-worker", Shape.FOREGROUND
    )
    assert subagents.meta({}) == Meta(None, Shape.FOREGROUND)


def test_a_subagent_asked_to_run_in_the_background_is_one():
    assert subagents.meta({"requestShape": "background"}) == Meta(None, Shape.BACKGROUND)


def test_a_subagent_a_workflow_started_is_one_whatever_shape_it_was_asked_for():
    record = {"description": "write:csharp", "requestShape": "foreground", "inWorkflowRun": True}
    assert subagents.meta(record) == Meta("write:csharp", Shape.WORKFLOW)


def test_metadata_that_isnt_a_record_is_none():
    assert subagents.meta([]) is None


def test_a_foreground_subagent_runs_while_its_session_waits_on_it():
    assert subagents.running([FOREGROUND], "busy", SESSION, STARTED) == [FOREGROUND]
    assert subagents.running([FOREGROUND], "waiting", SESSION, STARTED) == [FOREGROUND]


def test_a_foreground_subagent_has_stopped_once_its_session_has():
    assert subagents.running([FOREGROUND], "idle", SESSION, STARTED) == []


def test_a_foreground_subagent_whose_reply_ended_its_turn_has_finished():
    finished = replace(FOREGROUND, transcript=replace(WORKING, ended=True))
    assert subagents.running([finished], "busy", SESSION, STARTED) == []


def test_a_foreground_subagent_its_session_has_moved_on_from_has_stopped():
    session = replace(SESSION, last_activity=NOW)
    assert subagents.running([FOREGROUND], "busy", session, STARTED) == []


def test_a_background_subagent_runs_whatever_its_session_is_doing():
    assert subagents.running([BACKGROUND], "idle", SESSION, STARTED) == [BACKGROUND]


def test_a_background_subagent_has_stopped_once_its_session_is_told_so():
    session = replace(SESSION, subagents_stopped={"a2": NOW})
    assert subagents.running([BACKGROUND], "idle", session, STARTED) == []


def test_a_background_subagent_sent_a_message_after_it_stopped_runs_again():
    session = replace(SESSION, subagents_stopped={"a2": NOW - timedelta(minutes=30)})
    assert subagents.running([BACKGROUND], "idle", session, STARTED) == [BACKGROUND]


def test_a_workflows_subagent_runs_whatever_its_session_is_doing():
    assert subagents.running([IN_WORKFLOW], "idle", SESSION, STARTED) == [IN_WORKFLOW]


def test_a_workflows_subagent_has_stopped_once_it_has_finished():
    finished = replace(IN_WORKFLOW, finished=True)
    assert subagents.running([finished], "idle", SESSION, STARTED) == []


def test_a_workflows_journal_tells_which_of_its_subagents_have_returned():
    journal = [
        json.dumps({"type": "launched"}),
        json.dumps({"type": "started", "agentId": "a3", "label": "write:csharp"}),
        json.dumps({"type": "started", "agentId": "a4", "label": "write:java"}),
        json.dumps({"type": "result", "agentId": "a3", "result": {}}),
        json.dumps({"type": "result"}),
        json.dumps(["result"]),
        "{not json",
    ]
    assert subagents.returned(journal) == frozenset({"a3"})


def test_a_subagent_last_active_before_its_sessions_process_started_ended_with_an_earlier_one():
    earlier = replace(WORKING, last_activity=STARTED - timedelta(seconds=1))
    stale = [replace(s, transcript=earlier) for s in (FOREGROUND, BACKGROUND, IN_WORKFLOW)]
    assert subagents.running(stale, "busy", SESSION, STARTED) == []


def test_without_knowing_when_its_session_started_no_subagent_is_running():
    assert subagents.running([FOREGROUND, BACKGROUND], "busy", SESSION, None) == []


def test_a_subagent_never_active_is_not_running():
    silent = replace(BACKGROUND, transcript=UNKNOWN)
    assert subagents.running([silent], "busy", SESSION, STARTED) == []


def test_a_sessions_subagents_are_read_from_their_transcripts_and_metadata(tmp_path: Path):
    folder = tmp_path / "-home-me-app" / "s1" / "subagents"
    folder.mkdir(parents=True)
    (folder / "agent-a2.meta.json").write_text(
        json.dumps({"description": "Transition fields on move", "requestShape": "background"})
    )
    (folder / "agent-a2.jsonl").write_text(
        json.dumps(
            {
                "type": "user",
                "isSidechain": True,
                "timestamp": "2026-11-08T09:59:00.000Z",
                "cwd": "/home/me/app",
            }
        )
        + "\n"
    )
    written = (NOW - timedelta(minutes=1)).timestamp()
    os.utime(folder / "agent-a2.jsonl", (written, written))
    (folder / "agent-a3.meta.json").write_text("{not json")
    (folder / "agent-a3.jsonl").write_text("")
    assert subagents.read(tmp_path, "s1", STARTED) == [
        Subagent(
            "a2",
            Meta("Transition fields on move", Shape.BACKGROUND),
            Transcript(
                ai_title=None,
                cwd="/home/me/app",
                model=None,
                context_tokens=None,
                first_activity=datetime(2026, 11, 8, 9, 59, tzinfo=UTC),
                last_activity=datetime(2026, 11, 8, 9, 59, tzinfo=UTC),
                started=True,
                ended=False,
                subagents_stopped={},
            ),
            finished=False,
        )
    ]


def test_a_subagent_whose_transcript_was_last_written_before_its_session_started_isnt_read(
    tmp_path: Path,
):
    folder = tmp_path / "-home-me-app" / "s1" / "subagents"
    folder.mkdir(parents=True)
    (folder / "agent-a1.meta.json").write_text("{}")
    written = folder / "agent-a1.jsonl"
    written.write_text("")
    before = (STARTED - timedelta(minutes=1)).timestamp()
    os.utime(written, (before, before))
    assert subagents.read(tmp_path, "s1", STARTED) == []


def _write_agent(folder: Path, agent_id: str, meta: dict[str, object]) -> None:
    folder.mkdir(parents=True, exist_ok=True)
    (folder / f"agent-{agent_id}.meta.json").write_text(json.dumps(meta))
    log = folder / f"agent-{agent_id}.jsonl"
    log.write_text("")
    written = (NOW - timedelta(minutes=1)).timestamp()
    os.utime(log, (written, written))


IN_RUN = {"description": "write:csharp", "requestShape": "foreground", "inWorkflowRun": True}


def test_a_workflows_subagents_are_read_with_whether_its_journal_says_each_returned(
    tmp_path: Path,
):
    run = tmp_path / "-home-me-app" / "s1" / "subagents" / "workflows" / "wf_1"
    _write_agent(run, "a3", IN_RUN)
    _write_agent(run, "a4", IN_RUN | {"description": "write:java"})
    (run / "journal.jsonl").write_text(json.dumps({"type": "result", "agentId": "a3"}) + "\n")
    assert [(s.agent_id, s.meta, s.finished) for s in subagents.read(tmp_path, "s1", STARTED)] == [
        ("a3", Meta("write:csharp", Shape.WORKFLOW), True),
        ("a4", Meta("write:java", Shape.WORKFLOW), False),
    ]


def test_every_subagent_of_a_workflow_that_has_ended_has_finished(tmp_path: Path):
    session = tmp_path / "-home-me-app" / "s1"
    _write_agent(session / "subagents" / "workflows" / "wf_1", "a3", IN_RUN)
    (session / "workflows").mkdir()
    (session / "workflows" / "wf_1.json").write_text(json.dumps({"status": "killed"}))
    assert [s.finished for s in subagents.read(tmp_path, "s1", STARTED)] == [True]


def test_a_session_without_subagents_has_none(tmp_path: Path):
    assert subagents.read(tmp_path, "s1", STARTED) == []
