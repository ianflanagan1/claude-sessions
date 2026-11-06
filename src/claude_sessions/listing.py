"""The list claude-sessions prints: one line for each session, those needing you first."""

from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import final

from cli_kit.colour import BOLD, GREEN, GREY, RED, YELLOW, Style

from claude_sessions.registry import Entry
from claude_sessions.transcript import Transcript

# Statuses in the order they're listed and counted; any other comes after them.
_ORDER = ("waiting", "busy", "idle")
_ACTIVE = ("waiting", "busy")
_UNKNOWN = "unknown"
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
class Session:
    status: str | None
    location: str
    branch: str | None
    model: str | None
    context_tokens: int | None
    title: str
    user_named: bool
    last_active: datetime | None


def directory(entry: Entry, transcript: Transcript) -> str | None:
    """The directory the session last worked in, else the one it started in."""
    return transcript.cwd or entry.cwd


def title(entry: Entry, transcript: Transcript) -> str:
    """The name you or Claude Code gave the session, else the title Claude gave the conversation,
    else the name taken from its directory."""
    named = entry.name if entry.named_by not in (None, "derived") else None
    return named or transcript.ai_title or entry.name or "?"


def session(entry: Entry, transcript: Transcript, branch: str | None, home: str) -> Session:
    """A session as listed: in its directory, on branch, under its title."""
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
    )


def ordered(sessions: Sequence[Session]) -> list[Session]:
    """Waiting for you, then busy, then idle, then any other status; within each, the most
    recently active first."""
    by_recency = sorted(
        sessions, key=lambda s: s.last_active.timestamp() if s.last_active else 0, reverse=True
    )
    return sorted(by_recency, key=lambda s: _rank(s.status))


def active(sessions: Sequence[Session]) -> list[Session]:
    """The sessions waiting for you or busy."""
    return [s for s in sessions if s.status in _ACTIVE]


def render(
    sessions: Sequence[Session], now: datetime, colour: Style, width: int | None
) -> list[str]:
    """A line for each session, in aligned columns: status, how long since it was last active,
    model, context used, title, where and branch. Where is cut from the left to no fewer than
    _PROJECT_MIN characters, as far as keeps different places apart. With a width, the titles are
    cut so each line fits it."""
    projects = _abbreviated([s.location for s in sessions], _PROJECT_MIN)
    cells = [
        [
            s.status or _UNKNOWN,
            age(s.last_active, now),
            (s.model or "").removeprefix("claude-"),
            _tokens(s.context_tokens),
            s.title,
            project,
            s.branch or "",
        ]
        for s, project in zip(sessions, projects, strict=True)
    ]
    # A column empty on every line, such as branch when no session is in a repository, is left out.
    shown = [i for i in range(_COLUMNS) if any(row[i] for row in cells)]
    widths = {i: max(len(row[i]) for row in cells) for i in shown}
    if width is not None and _TITLE in widths:
        others = sum(widths[i] for i in shown if i != _TITLE) + len(_GAP) * (len(shown) - 1)
        widths[_TITLE] = min(widths[_TITLE], max(width - others, 1))
    lines = []
    for s, row in zip(sessions, cells, strict=True):
        row[_TITLE] = _fit(row[_TITLE], widths[_TITLE])
        styles = {
            _STATUS: _STATUS_COLOUR.get(row[_STATUS], ""),
            _CONTEXT: _context_colour(s.context_tokens),
            _TITLE: BOLD if s.user_named else "",
        }
        # Stripped, so a line doesn't end in the padding of its last columns.
        lines.append(
            _GAP.join(
                _cell(row[i], widths[i], i == _CONTEXT, colour, styles.get(i, "")) for i in shown
            ).rstrip()
        )
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
    """How many sessions there are, and how many in each status."""
    if not sessions:
        return "No sessions running."
    statuses = Counter(s.status or _UNKNOWN for s in sessions)
    parts = [f"{statuses[s]} {s}" for s in sorted(statuses, key=_rank)]
    noun = "session" if len(sessions) == 1 else "sessions"
    return f"{len(sessions)} {noun}: {', '.join(parts)}."


_STATUS_COLOUR = {"waiting": YELLOW, "busy": GREEN, "idle": GREY}


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


def _context_colour(tokens: int | None) -> str:
    if tokens is None or tokens < _CONTEXT_LARGE:
        return GREEN
    return YELLOW if tokens < _CONTEXT_RESTART else RED


def _fit(text: str, room: int) -> str:
    if len(text) <= room:
        return text
    return text[: max(room - 1, 0)] + "…"
