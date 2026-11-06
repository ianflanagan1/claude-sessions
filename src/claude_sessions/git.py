"""What git says about a directory: the branch it has checked out, the repository it's in, and
what's uncommitted there."""

import os
import subprocess
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import final

# A rename or copy is followed in `git status -z` by the path it came from.
_FROM_ANOTHER = ("R", "C")


@final
@dataclass(frozen=True, order=True)
class Change:
    status: str
    """Its two status letters, as `git status --porcelain` gives them: ` M`, `??`, `R `..."""
    path: str
    """From the repository's top level; for a rename, the new path."""


def branch(directory: str) -> str | None:
    """The branch checked out in directory, @ and the commit for a detached HEAD, or None when
    it isn't in a git repository or git can't say."""
    name = _git(directory, "symbolic-ref", "--short", "-q", "HEAD")
    if name:
        return name
    commit = _git(directory, "rev-parse", "--short", "HEAD")
    return f"@{commit}" if commit else None


def toplevel(directory: str) -> str | None:
    """The top level of the repository or worktree directory is in, with symbolic links
    resolved, or None when it isn't in one."""
    top = _git(directory, "rev-parse", "--show-toplevel")
    return os.path.realpath(top) if top else None


def changed(repo: str) -> list[Change]:
    """Every file uncommitted in repo: modified, added, deleted, renamed or untracked, each
    untracked file listed rather than its directory."""
    listed = _output(repo, "status", "--porcelain=v1", "-z", "--untracked-files=all")
    entries = iter(listed.split("\0") if listed else [])
    changes = []
    for entry in entries:
        if len(entry) < 4:
            continue
        changes.append(Change(entry[:2], entry[3:]))
        if entry[0] in _FROM_ANOTHER:
            next(entries, None)
    return changes


def last_commit(repo: str) -> datetime | None:
    """When the commit checked out in repo was made, or None when it has none."""
    return _when(_git(repo, "log", "-1", "--format=%ct"))


def last_commit_to(repo: str, path: str) -> datetime | None:
    """When the last commit that changed path, from repo's top level, was made, or None when
    none has."""
    return _when(_git(repo, "log", "-1", "--format=%ct", "--", path))


def _when(stamp: str | None) -> datetime | None:
    return datetime.fromtimestamp(int(stamp), UTC) if stamp and stamp.isdigit() else None


def _git(directory: str, *args: str) -> str | None:
    output = _output(directory, *args)
    return output.strip() if output is not None else None


def _output(directory: str, *args: str) -> str | None:
    """What git prints, as it prints it, or None when it fails or can't be run."""
    try:
        result = subprocess.run(
            ["git", "-C", directory, *args], capture_output=True, text=True, check=False
        )
    except OSError:
        return None
    return result.stdout if result.returncode == 0 else None
