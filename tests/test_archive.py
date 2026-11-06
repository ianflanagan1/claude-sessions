"""Reading which sessions are archived in VS Code and its forks, from each editor's state."""

import json
import sqlite3
from pathlib import Path

from claude_sessions import archive


def state_database(path: Path, key: str, value: object) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(path) as connection:
        connection.execute(
            "CREATE TABLE ItemTable (key TEXT UNIQUE ON CONFLICT REPLACE, value BLOB)"
        )
        connection.execute("INSERT INTO ItemTable VALUES (?, ?)", (key, json.dumps(value)))
    connection.close()
    return path


def test_the_archived_sessions_are_the_extensions_hidden_session_ids():
    state = json.dumps({"hiddenSessionIds": ["s1", "s2"], "showTerminalBanner": False})
    assert archive.parse(state) == {"s1", "s2"}


def test_state_without_a_list_of_ids_archives_none():
    assert archive.parse("not json") == frozenset()
    assert archive.parse(json.dumps(["s1"])) == frozenset()
    assert archive.parse(json.dumps({"hiddenSessionIds": "s1"})) == frozenset()
    assert archive.parse(json.dumps({})) == frozenset()


def test_an_id_that_isnt_text_is_skipped():
    assert archive.parse(json.dumps({"hiddenSessionIds": ["s1", 2, None]})) == {"s1"}


def test_on_macos_each_editors_state_is_under_application_support():
    [code, insiders, cursor, codium] = archive.databases("darwin", Path("/Users/me"), None)
    assert code == Path("/Users/me/Library/Application Support/Code/User/globalStorage/state.vscdb")
    assert insiders.parts[5] == "Code - Insiders"
    assert cursor.parts[5] == "Cursor"
    assert codium.parts[5] == "VSCodium"


def test_on_linux_each_editors_state_is_under_the_config_home():
    assert archive.databases("linux", Path("/home/me"), None)[2] == Path(
        "/home/me/.config/Cursor/User/globalStorage/state.vscdb"
    )
    assert archive.databases("linux", Path("/home/me"), "/xdg")[0] == Path(
        "/xdg/Code/User/globalStorage/state.vscdb"
    )


def test_other_platforms_have_no_editor_state():
    assert archive.databases("win32", Path("/home/me"), None) == []


def test_sessions_archived_in_any_editor_count(tmp_path: Path):
    code = state_database(
        tmp_path / "Code.vscdb", "Anthropic.claude-code", {"hiddenSessionIds": ["s1"]}
    )
    cursor = state_database(
        tmp_path / "Cursor.vscdb", "anthropic.claude-code", {"hiddenSessionIds": ["s2"]}
    )
    assert archive.archived([code, cursor, tmp_path / "missing.vscdb"]) == {"s1", "s2"}


def test_a_database_without_the_extensions_state_archives_none(tmp_path: Path):
    other = state_database(tmp_path / "a.vscdb", "other.extension", {"hiddenSessionIds": ["s1"]})
    broken = tmp_path / "b.vscdb"
    broken.write_text("not a database")
    assert archive.archived([other, broken]) == frozenset()
