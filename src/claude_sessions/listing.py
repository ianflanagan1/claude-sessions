"""The list claude-sessions prints: one line for each session, those needing you first."""

from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import assert_never, final

from cli_kit.colour import BOLD, CYAN, GREEN, GREY, RED, YELLOW, Style

from claude_sessions import subagents
from claude_sessions.registry import Entry
from claude_sessions.transcript import Transcript

# Statuses in the order they're listed and counted; any other comes after them.
_ORDER = ("waiting", "busy", "done", "idle")
_ACTIVE = ("waiting", "done", "busy")
_UNKNOWN = "unknown"
_IDLE = "idle"
_DONE = "done"
# How long a session that has finished a turn is listed as done, for you to look at, before it's
# idle again.
_DONE_FOR = timedelta(minutes=2)
_BLANK = "blank"
# Ends the status of a session archived in its editor.
_ARCHIVED = "-archived"
# A subagent listed is running; only its session can be waiting for you.
_SUBAGENT_STATUS = "busy"
_SUBAGENT_MARK = "↳ "
_SUBAGENT_TITLE = "subagent"
_GAP = "  "
# Where a row in the directory listed works, when other rows work below it.
_HERE = "."
# Columns, by position on the line.
_STATUS, _CONTEXT, _TITLE = 0, 3, 4
_COLUMNS = 7
# The fewest characters where a session is is cut to.
_PROJECT_MIN = 35
# Context used, in tokens, from which a session is large enough that answers start to suffer, and
# from which it's better scrapped for a new one. Absolute, not a share of the model's window:
# attention thins with length even in a 1M window, and a 200k one compacts at about 160k.
_CONTEXT_LARGE = 100_000
_CONTEXT_RESTART = 150_000


@final
@dataclass(frozen=True)
class Subagent:
    location: str
    branch: str | None
    model: str | None
    context_tokens: int | None
    title: str
    first_active: datetime | None
    """When it started: its first prompt or reply."""
    last_active: datetime | None


@final
@dataclass(frozen=True)
class Session:
    status: str | None
    """Claude Code's status for it, or done for _DONE_FOR after it finishes a turn."""
    location: str
    """Where it works, as location gives it."""
    branch: str | None
    model: str | None
    context_tokens: int | None
    title: str
    user_named: bool
    last_active: datetime | None
    subagents: tuple[Subagent, ...]
    """Its subagents still running, in the order they started."""
    blank: bool
    """Whether it's idle with nothing said in it yet, as when just opened: counted, not listed."""
    archived: bool
    """Whether it's archived in the editor's panel that started it, and so hidden there."""


type Row = Session | Subagent
"""A line of the list: a session, or one of its subagents under it."""


def directory(entry: Entry, transcript: Transcript) -> str | None:
    """The directory the session last worked in, else the one it started in."""
    return transcript.cwd or entry.cwd


def location(directory: str | None, resolved: str | None, root: str | None, home: str) -> str:
    """Where a row works, as listed: below root, its path from root, and empty in root itself,
    so a list of only the sessions working in root leaves the column out; anywhere else,
    directory with home written as ~. resolved is directory with its symbolic links resolved, as
    root's are, to compare with root."""
    if root is not None and resolved is not None and within(resolved, root):
        return resolved[len(root.rstrip("/")) :].lstrip("/")
    return from_home(directory or "?", home)


def title(entry: Entry, transcript: Transcript) -> str:
    """The name you or Claude Code gave the session, else the name its transcript records you gave
    it, else the title Claude gave the conversation, else the name taken from its directory."""
    named = entry.name if entry.named_by not in (None, "derived") else None
    return named or transcript.custom_title or transcript.ai_title or entry.name or "?"


def _user_named(entry: Entry, transcript: Transcript) -> bool:
    """Whether the title is a name you gave the session."""
    if entry.named_by not in (None, "derived") and entry.name:
        return entry.named_by == "user"
    return transcript.custom_title is not None


def session(
    entry: Entry,
    transcript: Transcript,
    location: str,
    branch: str | None,
    running: Sequence[Subagent],
    archived: bool,
    now: datetime,
) -> Session:
    """A session as listed: at location, on branch, under its title, with the subagents it
    has running, and archived or not. It's blank when idle with no prompt or reply in its
    transcript and no subagent running; one busy or waiting has been given its first prompt.
    It's done, as of now, for _DONE_FOR after it goes idle with a turn finished, and no subagent
    still running."""
    times = [t for t in (transcript.last_activity, entry.updated) if t is not None]
    return Session(
        status=_DONE if _done(entry, transcript, running, now) else entry.status,
        location=location,
        branch=branch,
        model=transcript.model,
        context_tokens=transcript.context_tokens,
        title=title(entry, transcript),
        user_named=_user_named(entry, transcript),
        last_active=max(times, default=None),
        subagents=tuple(_by_start(running)),
        blank=entry.status == _IDLE and not transcript.started and not running,
        archived=archived,
    )


def _done(entry: Entry, transcript: Transcript, running: Sequence[Subagent], now: datetime) -> bool:
    return (
        entry.status == _IDLE
        and transcript.started
        and not running
        and entry.status_changed is not None
        and now - entry.status_changed < _DONE_FOR
    )


def subagent_directory(found: subagents.Subagent, session_directory: str | None) -> str | None:
    """The directory the subagent last worked in, such as a worktree of its own, else its
    session's."""
    return found.transcript.cwd or session_directory


def subagent(found: subagents.Subagent, location: str, branch: str | None) -> Subagent:
    """A subagent as listed: at location, on branch, under what it was asked to do."""
    return Subagent(
        location=location,
        branch=branch,
        model=found.transcript.model,
        context_tokens=found.transcript.context_tokens,
        title=found.meta.title or _SUBAGENT_TITLE,
        first_active=found.transcript.first_activity,
        last_active=found.transcript.last_activity,
    )


def ordered(sessions: Sequence[Session]) -> list[Session]:
    """Waiting for you, then busy, then done, then idle, then any other status; within each, the
    most recently active first."""
    return sorted(_by_recency(sessions), key=lambda s: _rank(s.status))


def started(sessions: Sequence[Session]) -> list[Session]:
    """The sessions to list: all but the blank ones."""
    return [s for s in sessions if not s.blank]


def active(sessions: Sequence[Session]) -> list[Session]:
    """The sessions waiting for you, done, or busy, or with subagents running."""
    return [s for s in sessions if s.status in _ACTIVE or s.subagents]


def within(path: str, root: str) -> bool:
    """Whether path is root or a directory below it."""
    return path == root or path.startswith(root.rstrip("/") + "/")


def in_scope(directory: str | None, root: str | None) -> bool:
    """Whether a session working in directory is one to list, count and close: with no root
    given, every session is; with one, those working in it or below it."""
    if root is None:
        return True
    return directory is not None and within(directory, root)


def rows(sessions: Sequence[Session]) -> list[Row]:
    """The lines of the list: each session, followed by its subagents."""
    return [row for s in sessions for row in (s, *s.subagents)]


def render(rows: Sequence[Row], now: datetime, colour: Style, width: int | None) -> list[str]:
    """A line for each row, in aligned columns: status, ending in -archived for an archived
    session, how long since it was last active, model, context used, title, where and branch.
    A subagent is marked as one under its session's title. Where is _HERE for a row in the
    directory listed, unless every row is, and cut from the left to no fewer than _PROJECT_MIN
    characters, as far as keeps different places apart. With a width, the titles are cut so each
    line fits it."""
    projects = _abbreviated(_here([r.location for r in rows]), _PROJECT_MIN)
    cells = [
        [
            _status(r),
            age(r.last_active, now),
            (r.model or "").removeprefix("claude-"),
            _tokens(r.context_tokens),
            _title(r),
            project,
            r.branch or "",
        ]
        for r, project in zip(rows, projects, strict=True)
    ]
    # A column empty on every line, such as branch when no session is in a repository, is left out.
    shown = [i for i in range(_COLUMNS) if any(row[i] for row in cells)]
    widths = {i: max(len(row[i]) for row in cells) for i in shown}
    if width is not None and _TITLE in widths:
        others = sum(widths[i] for i in shown if i != _TITLE) + len(_GAP) * (len(shown) - 1)
        widths[_TITLE] = min(widths[_TITLE], max(width - others, 1))
    lines = []
    for r, row in zip(rows, cells, strict=True):
        row[_TITLE] = _fit(row[_TITLE], widths[_TITLE])
        cells_shown = [_styled(i, r, row[i], widths[i], colour) for i in shown]
        # Stripped, so a line doesn't end in the padding of its last columns.
        lines.append(_GAP.join(cells_shown).rstrip())
    return lines


def fitting(total: int, rows: int) -> int:
    """How many of total lines fit on a terminal rows high, above the summary and, when some
    don't fit, the line that says how many."""
    room = max(rows - 1, 0)
    return total if total <= room else max(room - 1, 0)


def screen(lines: Sequence[str], total: int, summary: str, rows: int) -> list[str]:
    """What shows on a terminal rows high: lines, the first of total as many as fitting gives,
    then how many more there are when some don't fit, then summary on the last row."""
    hidden = total - len(lines)
    if not hidden:
        return [*lines, summary]
    return [*lines, f"… {hidden} more", summary] if rows > 1 else [summary]


def age(when: datetime | None, now: datetime) -> str:
    """How long ago, in the largest whole unit: now, 5m, 3h or 2d."""
    if when is None:
        return "?"
    seconds = int((now - when).total_seconds())
    if seconds < 60:
        return "now"
    if seconds < 3600:
        return f"{seconds // 60}m"
    if seconds < 86400:
        return f"{seconds // 3600}h"
    return f"{seconds // 86400}d"


def count(sessions: Sequence[Session]) -> str:
    """How many sessions there are, and how many in each status, then how many are blank, apart
    from their status."""
    if not sessions:
        return "No sessions running."
    return f"{len(sessions)} {_sessions(len(sessions))} ({_statuses(sessions)})."


def count_within(sessions: Sequence[Session], place: str | None) -> str:
    """How many sessions there are working in place, and how many in each status, then how many
    are blank, apart from their status. With no place, sessions are every session running,
    counted as count counts them."""
    if place is None:
        return count(sessions)
    if not sessions:
        return f"{place}: No sessions."
    n = len(sessions)
    return f"{place}: {n} {_sessions(n)} ({_statuses(sessions)})."


def _sessions(n: int) -> str:
    return "session" if n == 1 else "sessions"


def _statuses(sessions: Sequence[Session]) -> str:
    """How many of sessions are in each status, then how many are blank."""
    listed = started(sessions)
    statuses = Counter(s.status or _UNKNOWN for s in listed)
    parts = [f"{statuses[s]} {s}" for s in sorted(statuses, key=_rank)]
    blank = len(sessions) - len(listed)
    if blank:
        parts.append(f"{blank} {_BLANK}")
    return ", ".join(parts)


_STATUS_COLOUR = {"waiting": YELLOW, "done": GREEN, "busy": CYAN, "idle": GREY}


def _status(row: Row) -> str:
    return _plain_status(row) + _archived(row)


def _plain_status(row: Row) -> str:
    match row:
        case Session():
            return row.status or _UNKNOWN
        case Subagent():
            return _SUBAGENT_STATUS
        case _:
            assert_never(row)


def _archived(row: Row) -> str:
    match row:
        case Session() if row.archived:
            return _ARCHIVED
        case Session() | Subagent():
            return ""
        case _:
            assert_never(row)


def _title(row: Row) -> str:
    match row:
        case Session():
            return row.title
        case Subagent():
            return _SUBAGENT_MARK + row.title
        case _:
            assert_never(row)


def _by_recency(rows: Sequence[Session]) -> list[Session]:
    """rows, the most recently active first."""
    return sorted(
        rows, key=lambda r: r.last_active.timestamp() if r.last_active else 0, reverse=True
    )


def _by_start(rows: Sequence[Subagent]) -> list[Subagent]:
    """rows in the order they started, so that their order holds as they take turns being the
    latest active. One whose start isn't known comes last."""
    return sorted(
        rows,
        key=lambda r: (r.first_active is None, r.first_active.timestamp() if r.first_active else 0),
    )


def _rank(status: str | None) -> tuple[int, str]:
    if status in _ORDER:
        return _ORDER.index(status), ""
    if status is None or status == _UNKNOWN:
        return len(_ORDER) + 1, ""
    return len(_ORDER), status


def from_home(path: str, home: str) -> str:
    """path, with home written as ~."""
    if path == home:
        return "~"
    if path.startswith(home.rstrip("/") + "/"):
        return "~" + path[len(home.rstrip("/")) :]
    return path


def _tokens(n: int | None) -> str:
    if n is None:
        return ""
    return str(n) if n < 1000 else f"{n // 1000}k"


def _here(locations: Sequence[str]) -> list[str]:
    """locations, each empty one, in the directory listed, as _HERE, unless every one is."""
    if not any(locations):
        return list(locations)
    return [loc or _HERE for loc in locations]


def _abbreviated(locations: Sequence[str], minimum: int) -> list[str]:
    """Each location cut from the left to the narrowest width, of at least minimum, at which
    different locations still read differently."""
    distinct = set(locations)
    for size in range(minimum, max(map(len, distinct), default=0)):
        cut = [_tail(location, size) for location in locations]
        if len(set(cut)) == len(distinct):
            return cut
    return list(locations)


def _tail(text: str, size: int) -> str:
    return text if len(text) <= size else "…" + text[len(text) - size + 1 :]


def _cell(text: str, width: int, right: bool, colour: Style, code: str) -> str:
    """text padded to width, coloured but not its padding."""
    padding = " " * (width - len(text))
    styled = colour(code, text) if code else text
    return padding + styled if right else styled + padding


def _styled(column: int, row: Row, text: str, width: int, colour: Style) -> str:
    """The cell in column of row's line, text padded to width and coloured."""
    if column == _STATUS:
        return _status_cell(row, width, colour)
    if column == _TITLE:
        return _title_cell(row, text, width, colour)
    code = _context_colour(row.context_tokens) if column == _CONTEXT else ""
    return _cell(text, width, column == _CONTEXT, colour, code)


def _status_cell(row: Row, width: int, colour: Style) -> str:
    """The row's status padded to width, coloured for what it is, and -archived after it grey."""
    status, archived = _plain_status(row), _archived(row)
    padding = " " * (width - len(status) - len(archived))
    shown = colour(_STATUS_COLOUR[status], status) if status in _STATUS_COLOUR else status
    return shown + (colour(GREY, archived) if archived else "") + padding


def _title_cell(row: Row, text: str, width: int, colour: Style) -> str:
    """The row's title, text as fitted, padded to width: bold when you named the session, and
    a subagent's mark grey, as long as it's not been cut away."""
    match row:
        case Session():
            return _cell(text, width, False, colour, BOLD if row.user_named else "")
        case Subagent() if text.startswith(_SUBAGENT_MARK):
            rest = _cell(
                text.removeprefix(_SUBAGENT_MARK), width - len(_SUBAGENT_MARK), False, colour, ""
            )
            return colour(GREY, _SUBAGENT_MARK) + rest
        case Subagent():
            return _cell(text, width, False, colour, "")
        case _:
            assert_never(row)


def _context_colour(tokens: int | None) -> str:
    if tokens is None or tokens < _CONTEXT_LARGE:
        return GREEN
    return YELLOW if tokens < _CONTEXT_RESTART else RED


def _fit(text: str, room: int) -> str:
    if len(text) <= room:
        return text
    return text[: max(room - 1, 0)] + "…"
