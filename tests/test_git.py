"""Asking git about a directory: its branch, its repository and what's uncommitted there, from real
throwaway repositories."""

import os
import subprocess
from datetime import UTC, datetime
from pathlib import Path

from claude_sessions import git
from claude_sessions.git import Change

JANUARY = "2026-01-02T03:04:05Z"
FEBRUARY = "2026-02-01T00:00:00Z"


def run(directory: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(directory), *args], capture_output=True, text=True, check=True
    ).stdout.strip()


def repository(directory: Path) -> Path:
    run(directory, "init", "-q", "-b", "trunk")
    run(
        directory,
        "-c",
        "user.name=t",
        "-c",
        "user.email=t@t",
        "commit",
        "-q",
        "--allow-empty",
        "-m",
        "c",
    )
    return directory


def test_a_repository_is_on_its_checked_out_branch(tmp_path: Path):
    assert git.branch(str(repository(tmp_path))) == "trunk"


def test_a_subdirectory_is_on_its_repositorys_branch(tmp_path: Path):
    (repository(tmp_path) / "src").mkdir()
    assert git.branch(str(tmp_path / "src")) == "trunk"


def test_a_detached_head_is_its_commit(tmp_path: Path):
    commit = run(repository(tmp_path), "rev-parse", "--short", "HEAD")
    run(tmp_path, "checkout", "-q", "--detach")
    assert git.branch(str(tmp_path)) == f"@{commit}"


def test_a_repository_with_no_commits_is_on_its_first_branch(tmp_path: Path):
    run(tmp_path, "init", "-q", "-b", "trunk")
    assert git.branch(str(tmp_path)) == "trunk"


def test_a_directory_in_no_repository_has_no_branch(tmp_path: Path):
    assert git.branch(str(tmp_path)) is None


def test_a_directory_that_no_longer_exists_has_no_branch(tmp_path: Path):
    assert git.branch(str(tmp_path / "gone")) is None


def commit(directory: Path, date: str, *paths: str) -> None:
    run(directory, "add", *paths)
    subprocess.run(
        ["git", "-C", str(directory), "-c", "user.name=t", "-c", "user.email=t@t"]
        + ["commit", "-q", "-m", "c"],
        env=os.environ | {"GIT_AUTHOR_DATE": date, "GIT_COMMITTER_DATE": date},
        capture_output=True,
        check=True,
    )


def test_a_subdirectorys_top_level_is_its_repositorys(tmp_path: Path):
    (repository(tmp_path) / "src").mkdir()
    assert git.toplevel(str(tmp_path / "src")) == os.path.realpath(tmp_path)


def test_a_directory_in_no_repository_has_no_top_level(tmp_path: Path):
    assert git.toplevel(str(tmp_path)) is None
    assert git.toplevel(str(tmp_path / "gone")) is None


def test_a_worktree_is_its_own_top_level(tmp_path: Path):
    (tmp_path / "main").mkdir()
    repository(tmp_path / "main")
    run(tmp_path / "main", "worktree", "add", "-q", str(tmp_path / "other"))
    assert git.toplevel(str(tmp_path / "other")) == os.path.realpath(tmp_path / "other")


def test_the_changes_are_every_file_modified_added_deleted_renamed_or_untracked(tmp_path: Path):
    repository(tmp_path)
    for name in ("kept", "edited", "deleted", "moved"):
        (tmp_path / name).write_text(name)
    commit(tmp_path, JANUARY, ".")
    (tmp_path / "edited").write_text("more")
    (tmp_path / "deleted").unlink()
    run(tmp_path, "mv", "moved", "renamed")
    (tmp_path / "new dir").mkdir()
    (tmp_path / "new dir" / "untracked").write_text("x")
    assert sorted(git.changed(str(tmp_path))) == [
        Change(" D", "deleted"),
        Change(" M", "edited"),
        Change("??", "new dir/untracked"),
        Change("R ", "renamed"),
    ]


def test_a_clean_repository_has_no_changes(tmp_path: Path):
    assert git.changed(str(repository(tmp_path))) == []


def test_a_file_was_last_committed_with_the_last_commit_that_changed_it(tmp_path: Path):
    repository(tmp_path)
    (tmp_path / "a").write_text("a")
    commit(tmp_path, JANUARY, "a")
    (tmp_path / "b").write_text("b")
    commit(tmp_path, FEBRUARY, "b")
    assert git.last_commit_to(str(tmp_path), "a") == datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC)
    assert git.last_commit(str(tmp_path)) == datetime(2026, 2, 1, tzinfo=UTC)


def test_a_file_never_committed_has_no_last_commit(tmp_path: Path):
    assert git.last_commit_to(str(repository(tmp_path)), "new") is None


def test_a_repository_with_no_commits_has_no_last_commit(tmp_path: Path):
    run(tmp_path, "init", "-q", "-b", "trunk")
    assert git.last_commit(str(tmp_path)) is None
