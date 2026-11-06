"""The claude-sessions command that uv installs into .venv/bin, run against a home directory
laid out as Claude Code lays out ~/.claude."""

import json
import os
import select
import signal
import sqlite3
import subprocess
import sys
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

BIN = Path(sys.prefix) / "bin" / "claude-sessions"
WAIT_SECONDS = 10
OWN_SESSION = "CLAUDE_CODE_SESSION_ID"


def launch(home: Path, *args: str) -> subprocess.CompletedProcess[str]:
    env = os.environ | {"HOME": str(home), "NO_COLOR": "1"}
    env.pop("XDG_CONFIG_HOME", None)
    env.pop(OWN_SESSION, None)
    return subprocess.run([BIN, *args], capture_output=True, text=True, env=env)


def launch_from(home: Path, session_id: str, *args: str) -> subprocess.CompletedProcess[str]:
    """claude-sessions run by session_id, as Claude Code runs a command."""
    env = os.environ | {"HOME": str(home), "NO_COLOR": "1", OWN_SESSION: session_id}
    env.pop("XDG_CONFIG_HOME", None)
    return subprocess.run([BIN, *args], capture_output=True, text=True, env=env)


def session(home: Path, pid: int, session_id: str, status: str, title: str) -> None:
    sessions = home / ".claude" / "sessions"
    sessions.mkdir(parents=True, exist_ok=True)
    record = {"pid": pid, "sessionId": session_id, "cwd": str(home), "status": status}
    (sessions / f"{pid}.json").write_text(json.dumps(record))
    transcripts = home / ".claude" / "projects" / "-home"
    transcripts.mkdir(parents=True, exist_ok=True)
    (transcripts / f"{session_id}.jsonl").write_text(
        json.dumps({"type": "ai-title", "aiTitle": title}) + "\n"
    )


def ended_pid() -> int:
    process = subprocess.Popen([sys.executable, "-c", ""])
    process.wait()
    return process.pid


def test_it_lists_the_running_sessions_with_their_titles(tmp_path: Path):
    session(tmp_path, os.getpid(), "s1", "busy", "Fixing the login form")
    result = launch(tmp_path)
    assert result.returncode == 0, result.stderr
    [line, count] = result.stdout.splitlines()
    assert line.startswith("busy  ")
    assert line.endswith("  Fixing the login form  ~")
    assert count == "➖ 1 session: 1 busy."


def test_a_session_whose_process_has_ended_is_not_listed(tmp_path: Path):
    session(tmp_path, os.getpid(), "s1", "idle", "Running")
    session(tmp_path, ended_pid(), "s2", "busy", "Crashed")
    assert "Crashed" not in launch(tmp_path).stdout


def test_active_lists_only_the_sessions_waiting_or_busy_but_counts_them_all(tmp_path: Path):
    session(tmp_path, os.getpid(), "s1", "idle", "Resting")
    session(tmp_path, os.getppid(), "s2", "waiting", "Asking")
    lines = launch(tmp_path, "--active").stdout.splitlines()
    assert len(lines) == 2
    assert "Asking" in lines[0]
    assert lines[1] == "➖ 2 sessions: 1 waiting, 1 idle."


def test_with_no_sessions_it_says_so(tmp_path: Path):
    assert launch(tmp_path).stdout == "➖ No sessions running.\n"


def test_on_a_terminal_it_redraws_the_list_as_sessions_change_until_interrupted(tmp_path: Path):
    session(tmp_path, os.getpid(), "s1", "busy", "Fixing the login form")
    terminal, its_end = os.openpty()
    env = os.environ | {"HOME": str(tmp_path), "NO_COLOR": "1"}
    process = subprocess.Popen([BIN], stdin=its_end, stdout=its_end, stderr=its_end, env=env)
    os.close(its_end)
    try:
        first = read_until(terminal, "1 session: 1 busy.")
        assert first.startswith("\x1b[?1049h")
        assert "Fixing the login form" in first

        session(tmp_path, os.getpid(), "s1", "waiting", "Fixing the login form")
        read_until(terminal, "1 session: 1 waiting.")

        process.send_signal(signal.SIGINT)
        # Read before the process ends: macOS drops what's unread once it closes the terminal.
        last = read_until(terminal, "➖ 1 session: 1 waiting.")
        assert "\x1b[?1049l➖ 1 session: 1 waiting." in last
        assert process.wait(timeout=WAIT_SECONDS) == 0
    finally:
        process.kill()
        os.close(terminal)


def read_until(terminal: int, marker: str) -> str:
    seen = b""
    deadline = time.monotonic() + WAIT_SECONDS
    while marker.encode() not in seen:
        assert time.monotonic() < deadline, f"no {marker!r} in {seen!r}"
        if select.select([terminal], [], [], 0.1)[0]:
            seen += os.read(terminal, 65536)
    return seen.decode()


def test_close_archived_keeps_an_archived_session_whose_process_has_just_started(
    tmp_path: Path,
):
    process = sleeper()
    try:
        editor_session(tmp_path, process.pid, "s1", "idle")
        archive_in_editor(tmp_path, ["s1"])
        result = launch(tmp_path, "close-archived")
        assert result.returncode == 0, result.stderr
        assert result.stdout == "➖ No archived sessions to close.\n"
        assert process.poll() is None
    finally:
        process.kill()


def test_close_archived_with_no_editor_state_closes_nothing(tmp_path: Path):
    process = sleeper()
    try:
        editor_session(tmp_path, process.pid, "s1", "idle")
        result = launch(tmp_path, "close-archived")
        assert result.stdout == "➖ No archived sessions to close.\n"
        assert process.poll() is None
    finally:
        process.kill()


def sleeper() -> subprocess.Popen[bytes]:
    return subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])


def editor_session(home: Path, pid: int, session_id: str, status: str) -> None:
    started = subprocess.run(
        ["ps", "-o", "lstart=", "-p", str(pid)], capture_output=True, text=True, check=True
    ).stdout.strip()
    sessions = home / ".claude" / "sessions"
    sessions.mkdir(parents=True, exist_ok=True)
    record = {
        "pid": pid,
        "sessionId": session_id,
        "status": status,
        "name": f"session {session_id}",
        "entrypoint": "claude-vscode",
        "procStart": started,
    }
    (sessions / f"{pid}.json").write_text(json.dumps(record))


def archive_in_editor(home: Path, session_ids: list[str]) -> None:
    root = (
        home / "Library" / "Application Support" if sys.platform == "darwin" else home / ".config"
    )
    database = root / "Code" / "User" / "globalStorage" / "state.vscdb"
    database.parent.mkdir(parents=True)
    with sqlite3.connect(database) as connection:
        connection.execute(
            "CREATE TABLE ItemTable (key TEXT UNIQUE ON CONFLICT REPLACE, value BLOB)"
        )
        connection.execute(
            "INSERT INTO ItemTable VALUES (?, ?)",
            ("Anthropic.claude-code", json.dumps({"hiddenSessionIds": session_ids})),
        )
    connection.close()


def test_changes_tells_which_running_session_edited_each_uncommitted_file(tmp_path: Path):
    repo = committed_repository(tmp_path / "repo")
    (repo / "a.py").write_text("changed")
    (repo / "notes.txt").write_text("mine")
    session(tmp_path, os.getpid(), "s1", "busy", "Fixing the login form")
    edit(tmp_path, "s1", repo / "a.py")
    result = launch_from(tmp_path, "s1", "changes", str(repo), "--json")
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == {
        "repo": str(repo),
        "files": [
            {
                "path": "a.py",
                "status": " M",
                "edited_by": [
                    {
                        "session_id": "s1",
                        "pid": os.getpid(),
                        "title": "Fixing the login form",
                        "status": "busy",
                        "own": True,
                    }
                ],
            },
            {"path": "notes.txt", "status": "??", "edited_by": []},
        ],
        "commands_by": [],
        "unattributed": ["notes.txt"],
    }


def test_changes_lists_each_file_with_who_edited_it(tmp_path: Path):
    repo = committed_repository(tmp_path / "repo")
    (repo / "a.py").write_text("changed")
    session(tmp_path, os.getpid(), "s1", "busy", "Fixing the login form")
    edit(tmp_path, "s1", repo / "a.py")
    result = launch(tmp_path, "changes", str(repo / "src"))
    assert result.returncode == 0, result.stderr
    assert result.stdout.splitlines() == [
        " M a.py  Fixing the login form (busy)",
        "➖ 1 file uncommitted in ~/repo, 1 edited by a running session.",
    ]


def test_changes_outside_a_repository_says_so(tmp_path: Path):
    result = launch(tmp_path, "changes", str(tmp_path), "--json")
    assert result.returncode == 1
    assert result.stdout == ""
    assert result.stderr == f"⚠️ {tmp_path} isn't in a git repository.\n"


def committed_repository(directory: Path) -> Path:
    (directory / "src").mkdir(parents=True)
    (directory / "a.py").write_text("a")
    for args in (
        ["init", "-q"],
        ["add", "a.py"],
        ["-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", "c"],
    ):
        subprocess.run(["git", "-C", str(directory), *args], capture_output=True, check=True)
    return Path(os.path.realpath(directory))


def edit(home: Path, session_id: str, path: Path) -> None:
    """Records in session_id's transcript that it edited path, a minute from now."""
    soon = (datetime.now(UTC) + timedelta(minutes=1)).isoformat()
    use = {"type": "tool_use", "id": "toolu_1", "name": "Edit", "input": {"file_path": str(path)}}
    record = {
        "type": "assistant",
        "timestamp": soon,
        "cwd": str(home),
        "message": {"content": [use]},
    }
    with (home / ".claude" / "projects" / "-home" / f"{session_id}.jsonl").open("a") as file:
        file.write(json.dumps(record) + "\n")
