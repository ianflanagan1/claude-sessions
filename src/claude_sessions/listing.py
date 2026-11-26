"""The list claude-sessions prints: one line for each session, those needing you first."""

from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import assert_never, final

from cli_kit.colour import BOLD, GREEN, GREY, RED, YELLOW, Style

from claude_sessions import subagents
from claude_sessions.registry import Entry
from claude_sessions.transcript import Transcript

# Statuses in the order they're listed and counted; any other comes after them.
_ORDER = ("waiting", "busy", "idle")
_ACTIVE = ("waiting", "busy")
_UNKNOWN = "unknown"
_IDLE = "idle"
_BLANK = "blank"
# A subagent listed is running; only its session can be waiting for you.
_SUBAGENT_STATUS = "busy"
_SUBAGENT_MARK = "↳ "
_SUBAGENT_TITLE = "subagent"
_GAP = "  "
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
    last_active: datetime | None


@final
@dataclass(frozen=True)
class Session:
    status: str | None
    location: str
    branch: str | None
    model: str | None
    context_tokens: int | None
    title: str
    user_named: bool
    last_active: datetime | None
    subagents: tuple[Subagent, ...]
    """Its subagents still running, the most recently active first."""
    blank: bool
    """Whether it's idle with nothing said in it yet, as when just opened: counted, not listed."""


type Row = Session | Subagent
"""A line of the list: a session, or one of its subagents under it."""


def directory(entry: Entry, transcript: Transcript) -> str | None:
    """The directory the session last worked in, else the one it started in."""
    return transcript.cwd or entry.cwd


def title(entry: Entry, transcript: Transcript) -> str:
    """The name you or Claude Code gave the session, else the title Claude gave the conversation,
    else the name taken from its directory."""
    named = entry.name if entry.named_by not in (None, "derived") else None
    return named or transcript.ai_title or entry.name or "?"


def session(
    entry: Entry,
    transcript: Transcript,
    branch: str | None,
    home: str,
    running: Sequence[Subagent],
) -> Session:
    """A session as listed: in its directory, on branch, under its title, with the subagents it
    has running. It's blank when idle with no prompt or reply in its transcript and no subagent
    running; one busy or waiting has been given its first prompt."""
    times = [t for t in (transcript.last_activity, entry.updated) if t is not None]
    return Session(
        status=entry.status,
        location=from_home(directory(entry, transcript) or "?", home),
        branch=branch,
        model=transcript.model,
        context_tokens=transcript.context_tokens,
        title=title(entry, transcript),
        user_named=entry.named_by == "user",
        last_active=max(times, default=None),
        subagents=tuple(_by_recency(running)),
        blank=entry.status == _IDLE and not transcript.started and not running,
    )


def subagent_directory(found: subagents.Subagent, session_directory: str | None) -> str | None:
    """The directory the subagent last worked in, such as a worktree of its own, else its
    session's."""
    return found.transcript.cwd or session_directory


def subagent(
    found: subagents.Subagent, session_directory: str | None, branch: str | None, home: str
) -> Subagent:
    """A subagent as listed: in its directory, on branch, under what it was asked to do."""
    return Subagent(
        location=from_home(subagent_directory(found, session_directory) or "?", home),
        branch=branch,
        model=found.transcript.model,
        context_tokens=found.transcript.context_tokens,
        title=found.meta.title or _SUBAGENT_TITLE,
        last_active=found.transcript.last_activity,
    )


def ordered(sessions: Sequence[Session]) -> list[Session]:
    """Waiting for you, then busy, then idle, then any other status; within each, the most
    recently active first."""
    return sorted(_by_recency(sessions), key=lambda s: _rank(s.status))


def started(sessions: Sequence[Session]) -> list[Session]:
    """The sessions to list: all but the blank ones."""
    return [s for s in sessions if not s.blank]


def active(sessions: Sequence[Session]) -> list[Session]:
    """The sessions waiting for you or busy, or with subagents running."""
    return [s for s in sessions if s.status in _ACTIVE or s.subagents]


def within(path: str, root: str) -> bool:
    """Whether path is root or a directory below it."""
    return path == root or path.startswith(root.rstrip("/") + "/")


def rows(sessions: Sequence[Session]) -> list[Row]:
    """The lines of the list: each session, followed by its subagents."""
    return [row for s in sessions for row in (s, *s.subagents)]


def render(rows: Sequence[Row], now: datetime, colour: Style, width: int | None) -> list[str]:
    """A line for each row, in aligned columns: status, how long since it was last active,
    model, context used, title, where and branch. A subagent is marked as one under its session's
    title. Where is cut from the left to no fewer than _PROJECT_MIN characters, as far as keeps
    different places apart. With a width, the titles are cut so each line fits it."""
    projects = _abbreviated([r.location for r in rows], _PROJECT_MIN)
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
        styles = {
            _STATUS: _STATUS_COLOUR.get(row[_STATUS], ""),
            _CONTEXT: _context_colour(r.context_tokens),
        }
        cells_shown = [
            _title_cell(r, row[i], widths[i], colour)
            if i == _TITLE
            else _cell(row[i], widths[i], i == _CONTEXT, colour, styles.get(i, ""))
            for i in shown
        ]
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
    listed = started(sessions)
    statuses = Counter(s.status or _UNKNOWN for s in listed)
    parts = [f"{statuses[s]} {s}" for s in sorted(statuses, key=_rank)]
    blank = len(sessions) - len(listed)
    if blank:
        parts.append(f"{blank} {_BLANK}")
    noun = "session" if len(sessions) == 1 else "sessions"
    return f"{len(sessions)} {noun}: {', '.join(parts)}."


_STATUS_COLOUR = {"waiting": YELLOW, "busy": GREEN, "idle": GREY}


def _status(row: Row) -> str:
    match row:
        case Session():
            return row.status or _UNKNOWN
        case Subagent():
            return _SUBAGENT_STATUS
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


def _by_recency[T: (Session, Subagent)](rows: Sequence[T]) -> list[T]:
    """rows, the most recently active first."""
    return sorted(
        rows, key=lambda r: r.last_active.timestamp() if r.last_active else 0, reverse=True
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
