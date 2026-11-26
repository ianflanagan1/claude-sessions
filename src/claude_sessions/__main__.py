"""`claude-sessions`: every Claude Code session running on this machine.

Lists each session on its own line: its status, how long since it was last active, its model,
how much of its context it has used, its title, the directory it last worked in, cut from the left
when long, and its git branch. Sessions waiting for you come first, then busy ones, then idle
ones, each most recently active first. A session's subagents still running are listed under it,
marked ↳, but aren't counted as sessions.

The title is the name you gave the session, in bold, or one Claude Code gave it; otherwise the
title Claude gave the conversation, which it updates as the conversation moves on.

On a terminal the list stays on screen, redrawn every 2 seconds, until you press Ctrl-C, and the
archived sessions --close-archived would close are closed before each redraw. Piped or captured,
it's printed once, and closes nothing. `claude-sessions <path>` lists only the sessions working
in path or below it: `claude-sessions .` those working here.

`claude-sessions --close-archived` ends the sessions you've archived in VS Code or Cursor's Claude
Code panel: archiving there hides a session but leaves it running. Only idle ones are closed,
never one busy or waiting for you, nor one you've since resumed in a terminal, nor one whose
process has run for under a minute. Each closed
session's history stays on disk, to open again from the editor's list of past sessions.

`claude-sessions --changes [<path>]` lists what's uncommitted in the git repository at path, here by
default, and which running sessions edited each file since it was last committed, so you, or a
tool such as one that commits, can leave alone what a session is still working on. A shell command
can change any file without naming it, so the sessions that ran commands in the repository since
its last commit are listed for the whole repository. --json gives the same for other tools.

It reads Claude Code's own files, ~/.claude/sessions for the sessions running and
~/.claude/projects for their transcripts. Their format is Claude Code's and may change, so
anything it can't read is shown as unknown rather than failing. Colour is used on a terminal, or
with FORCE_COLOR set, unless NO_COLOR is set.
"""

import json
import os
import shutil
import signal
import sys
import time
from collections.abc import Callable
from dataclasses import replace
from datetime import UTC, datetime
from functools import partial
from pathlib import Path
from typing import assert_never

from cli_kit import cli, outcome
from cli_kit.colour import GREY, Style

from claude_sessions import (
    activity,
    archive,
    attribution,
    closing,
    git,
    listing,
    processes,
    registry,
    subagents,
    transcript,
)
from claude_sessions.activity import Edited, RanIn, Touch

# The session running a command, as Claude Code tells the commands it runs.
_OWN_SESSION = "CLAUDE_CODE_SESSION_ID"
# Where it's been tried. Elsewhere asking whether a process runs can end it: Windows's os.kill
# ends a process whatever the signal.
_PLATFORMS = ("darwin", "linux")


def main(argv: list[str] | None = None) -> int:
    parser = cli.ArgumentParser(prog="claude-sessions", description=__doc__)
    parser.add_argument(
        "path",
        nargs="?",
        help="list only sessions working in this directory or below it, . for here; with "
        "--changes, a directory in the repository, here by default",
    )
    parser.add_argument(
        "-a",
        "--active",
        action="store_true",
        help="list only sessions waiting for you or busy, or with subagents running",
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--changes",
        action="store_true",
        help="which running sessions edited the uncommitted files in the repository at path",
    )
    mode.add_argument(
        "--close-archived",
        action="store_true",
        help="end the idle sessions archived in VS Code or Cursor's Claude Code panel",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="with --changes, print it as JSON, alone, for other tools to read",
    )
    args = parser.parse_args(sys.argv[1:] if argv is None else argv)
    if args.json and not args.changes:
        parser.error("--json goes with --changes")
    if args.active and (args.changes or args.close_archived):
        parser.error("--active goes only with the list of sessions")
    if args.close_archived and args.path is not None:
        parser.error("--close-archived takes no path")
    if args.close_archived:
        return cli.finish("claude-sessions --close-archived", _close_archived)
    if args.changes:
        repo = args.path or "."
        if args.json:
            return _json("claude-sessions --changes", lambda: attribution.as_json(_attribute(repo)))
        return cli.finish("claude-sessions --changes", lambda: _show_changes(repo))
    show = _watch if sys.stdout.isatty() else _print
    return cli.finish("claude-sessions", lambda: show(args.active, _root(args.path)))


def _root(path: str | None) -> str | None:
    """The directory path names, symbolic links resolved, as each session's is to compare."""
    if path is None:
        return None
    if not os.path.isdir(path):
        raise outcome.Precondition(f"{path} isn't a directory.")
    return os.path.realpath(path)


def _close_archived() -> outcome.Done | outcome.NothingToDo:
    _check_platform()
    closed = _close(Path.home())
    if not closed:
        return outcome.NothingToDo("No archived sessions to close.")
    return outcome.Done(
        closing.summary(len(closed)),
        *(f"{entry.name or entry.session_id} (pid {entry.pid})" for entry in closed),
    )


def _close(home: Path) -> list[registry.Entry]:
    """Ends the running sessions archived in an editor that closing.closable picks, and gives
    those it ended."""
    entries = registry.running(home / ".claude" / "sessions")
    found = archive.archived(
        archive.databases(sys.platform, home, os.environ.get("XDG_CONFIG_HOME"))
    )
    archived = [entry for entry in entries if entry.session_id in found]
    described = {entry.pid: processes.describe(entry.pid) for entry in archived}
    return [
        entry
        for entry in closing.closable(archived, found, described)
        if processes.terminate(entry.pid)
    ]


def _show_changes(path: str) -> outcome.NothingToDo:
    report = _attribute(path)
    for line in attribution.lines(report):
        print(line)
    return outcome.NothingToDo(attribution.summary(report, str(Path.home())))


def _attribute(path: str) -> attribution.Report:
    """Who made the uncommitted changes in the repository path is in."""
    _check_platform()
    repo = git.toplevel(path)
    if repo is None:
        raise outcome.Precondition(f"{path} isn't in a git repository.")
    changes = git.changed(repo)
    committed = {change.path: git.last_commit_to(repo, change.path) for change in changes}
    claude = Path.home() / ".claude"
    own = os.environ.get(_OWN_SESSION)
    workers = []
    for entry in registry.running(claude / "sessions"):
        told = transcript.read(claude / "projects", entry.session_id)
        session = attribution.Session(
            pid=entry.pid,
            session_id=entry.session_id,
            title=listing.title(entry, told),
            status=entry.status,
            own=entry.session_id == own,
        )
        touches = activity.read(claude / "projects", entry.session_id)
        workers.append(attribution.Worker(session, tuple(_resolved(t) for t in touches)))
    return attribution.report(repo, changes, committed, git.last_commit(repo), workers)


def _resolved(touch: Touch) -> Touch:
    """touch, with symbolic links in its path resolved, as git resolves the repository's."""
    match touch:
        case Edited():
            return replace(touch, path=os.path.realpath(touch.path))
        case RanIn():
            return replace(touch, directory=os.path.realpath(touch.directory))
        case _:
            assert_never(touch)


def _json(command: str, build: Callable[[], object]) -> int:
    """Prints what build gives as JSON, alone on stdout for a tool to read. A problem is shown
    as cli.finish shows it."""
    try:
        value = build()
    except outcome.Problem as problem:
        return cli.finish(command, partial(_raise, problem))
    print(json.dumps(value, indent=2))
    return 0


def _raise(problem: outcome.Problem) -> None:
    raise problem


def _check_platform() -> None:
    if sys.platform not in _PLATFORMS:
        raise outcome.Precondition(f"claude-sessions runs on macOS and Linux, not {sys.platform}.")


_REFRESH_SECONDS = 2
# Escape codes: switch to the terminal's alternate screen with the cursor hidden, and back; move
# to the top left; clear to the end of the line, and from the cursor to the end of the screen.
_ENTER = "\x1b[?1049h\x1b[?25l"
_LEAVE = "\x1b[?25h\x1b[?1049l"
_HOME = "\x1b[H"
_CLEAR_LINE_END = "\x1b[K"
_CLEAR_BELOW = "\x1b[J"


def _print(only_active: bool, root: str | None) -> outcome.NothingToDo:
    _check_platform()
    shown, sessions = _gather(only_active, root)
    rows = listing.rows(shown)
    for line in listing.render(rows, datetime.now(UTC), Style.for_stream(sys.stdout), None):
        print(line)
    return outcome.NothingToDo(listing.count(sessions))


def _watch(only_active: bool, root: str | None) -> outcome.NothingToDo:
    """Closes the archived sessions closing.closable picks and redraws the list on the alternate
    screen, until Ctrl-C or SIGTERM, then leaves the screen as it was, for cli.finish to print
    the last count under."""
    _check_platform()
    signal.signal(signal.SIGTERM, _interrupt)
    colour = Style.for_stream(sys.stdout)
    home = Path.home()
    summary = "Stopped."
    sys.stdout.write(_ENTER)
    try:
        while True:
            _close(home)
            shown, sessions = _gather(only_active, root)
            rows = listing.rows(shown)
            summary = listing.count(sessions)
            size = shutil.get_terminal_size()
            # Only the lines on screen set the columns' widths.
            fit = rows[: listing.fitting(len(rows), size.lines)]
            lines = listing.render(fit, datetime.now(UTC), colour, size.columns)
            frame = listing.screen(lines, len(rows), colour(GREY, summary), size.lines)
            sys.stdout.write(
                _HOME + "\n".join(line + _CLEAR_LINE_END for line in frame) + _CLEAR_BELOW
            )
            sys.stdout.flush()
            time.sleep(_REFRESH_SECONDS)
    except KeyboardInterrupt:
        pass  # How you stop watching.
    finally:
        sys.stdout.write(_LEAVE)
        sys.stdout.flush()
    return outcome.NothingToDo(summary)


def _interrupt(signum: int, frame: object) -> None:
    """SIGTERM stops watching as Ctrl-C does, so the screen is restored."""
    raise KeyboardInterrupt


def _gather(
    only_active: bool, root: str | None
) -> tuple[list[listing.Session], list[listing.Session]]:
    """The sessions to show, in order, and every session running, to count. With a root, only
    those working in it or below it are shown."""
    home = Path.home()
    claude = home / ".claude"
    sessions = []
    placed = []
    branches: dict[str, str | None] = {}  # Many sessions share a directory; ask git once for each.

    def branch(directory: str | None) -> str | None:
        if directory is None:
            return None
        if directory not in branches:
            branches[directory] = git.branch(directory)
        return branches[directory]

    for entry in registry.running(claude / "sessions"):
        told = transcript.read(claude / "projects", entry.session_id)
        directory = listing.directory(entry, told)
        since = processes.started_at(entry.process_started)
        found = subagents.read(claude / "projects", entry.session_id, since)
        running = [
            listing.subagent(
                s, directory, branch(listing.subagent_directory(s, directory)), str(home)
            )
            for s in subagents.running(found, entry.status, told, since)
        ]
        listed = listing.session(entry, told, branch(directory), str(home), running)
        sessions.append(listed)
        if root is None or (
            directory is not None and listing.within(os.path.realpath(directory), root)
        ):
            placed.append(listed)
    shown = listing.ordered(listing.active(placed) if only_active else placed)
    return shown, sessions


if __name__ == "__main__":
    sys.exit(main())
