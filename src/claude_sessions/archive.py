"""The sessions archived in the Claude Code extension for VS Code and its forks. The extension keeps
them in the editor's own state, a SQLite database under the editor's user data directory, as the
hiddenSessionIds list in the extension's row. Archiving, by hand or after the extension's
archiveInactiveSessions days, adds to that list; it doesn't end the session's process."""

import json
import sqlite3
from pathlib import Path

_EDITORS = ("Code", "Code - Insiders", "Cursor", "VSCodium")
_STATE = Path("User") / "globalStorage" / "state.vscdb"
# The extension's id, which VS Code has stored with a capital A.
_EXTENSION = "anthropic.claude-code"


def parse(state: str) -> frozenset[str]:
    """The ids in the extension's state's hiddenSessionIds, or none when it can't be read as a
    list of them. An entry that isn't text is skipped."""
    try:
        record = json.loads(state)
    except ValueError:
        return frozenset()
    ids = record.get("hiddenSessionIds") if isinstance(record, dict) else None
    if not isinstance(ids, list):
        return frozenset()
    return frozenset(i for i in ids if isinstance(i, str))


def databases(platform: str, home: Path, config_home: str | None) -> list[Path]:
    """Where each editor keeps its state on this platform, as sys.platform names it: under
    ~/Library/Application Support on macOS, and $XDG_CONFIG_HOME, or ~/.config, on Linux. Other
    platforms have none, so nothing there counts as archived."""
    match platform:
        case "darwin":
            root = home / "Library" / "Application Support"
        case "linux":
            root = Path(config_home) if config_home else home / ".config"
        case _:
            return []
    return [root / editor / _STATE for editor in _EDITORS]


def archived(databases: list[Path]) -> frozenset[str]:
    """Every session archived in any of these editors' databases. A database that's missing,
    locked or not laid out as expected adds none."""
    ids: frozenset[str] = frozenset()
    for database in databases:
        if database.is_file():
            ids |= parse(_state(database) or "")
    return ids


def _state(database: Path) -> str | None:
    try:
        # Read-only, so the editor, which holds it open, is never disturbed.
        with sqlite3.connect(f"{database.as_uri()}?mode=ro", uri=True) as connection:
            row = connection.execute(
                "SELECT value FROM ItemTable WHERE lower(key) = ?", (_EXTENSION,)
            ).fetchone()
    except sqlite3.Error:
        return None
    return row[0] if row is not None and isinstance(row[0], str) else None
