# claude-sessions

Every Claude Code session running on this machine, in any terminal or editor: where it is, what it's on, and whether it needs you.

```
$ claude-sessions
waiting  14h  opus-5-5   58k  dog-cafe-db                                       ~/projects/dog-cafe             main
busy     now  opus-5-5  105k  list claude sessions                              ~/projects/cli/claude-sessions  main
busy     3m   opus-5-5   66k  Repo-fix integration setting failure              ~/projects/cli/repo-tools       main
idle     8m   opus-5-5   35k  Repo-fix git init behavior                        ~/projects/cli/repo-tools       main
idle     29m  opus-5-5   33k  Named parameters across TypeScript, Java, C#, Go  ~/projects
➖ 64 sessions: 1 waiting, 4 busy, 59 idle.
```

Each line is a session's status, how long since it was last active, its model, how much of its context it has used, its title, the directory it last worked in, and the branch checked out there. A directory longer than 35 characters is cut from the left, but no further than keeps different directories apart. Sessions waiting for you come first, then busy ones, then idle ones, each most recently active first. `--active` lists only those waiting or busy, or with subagents running.

`claude-sessions <path>` lists only the sessions working in that directory or below it, so `claude-sessions .` lists those working here. The path can be relative or absolute. A session's directory is the one shown, where it last worked, and both are compared with symbolic links resolved. It combines with `--active`, and the count is still of every session running.

A session's subagents that are still running are listed under it, most recently active first, as `busy`, titled `↳` and what they were asked to do, in the directory each last worked in, such as a worktree of its own:

```
idle     now  opus-5-5    66k  Repo-fix integration setting failure  ~/projects/cli/repo-tools  main
busy     now  sonnet-5-5  31k  ↳ Transition fields on move           ~/projects/cli/repo-tools  main
```

They aren't counted as sessions. A subagent runs inside its session's process, with no record of its own, so whether it's running is worked out:

- A background subagent runs until its session is told it stopped, and again once it's active after that, as when sent a message. Its session can be idle meanwhile.
- A foreground subagent runs while its session is busy or waiting on it, until its reply ends its turn or the session moves on without it, as when you interrupt it.
- Either ends with its session's process, so one last active before that process started isn't running.

On a terminal the list stays on screen and is redrawn every 2 seconds, cut to fit the window (only the sessions on screen set the columns' widths), until you press Ctrl-C; it then prints the last count. Before each redraw it closes the archived sessions `--close-archived` would, whatever path or `--active` limits the list to, without reporting them. Piped or captured, it's printed once, as above, and closes nothing.

The title is the name you gave the session, in bold, or one Claude Code gave it; otherwise the title Claude gave the conversation, which it updates as the conversation moves on.

Built on [cli-kit](../cli-kit).

## Closing archived sessions

Archiving a session in VS Code or Cursor's Claude Code panel hides it from the list but leaves its process running, holding a couple of hundred MB. `claude-sessions --close-archived` ends them, with SIGTERM, and lists each one it closed. Watching the list on a terminal does the same every 2 seconds. Each session's history stays in its transcript, to open again from the editor's past sessions.

It closes a session only when all of these hold, and keeps it otherwise:

- it's archived in VS Code, VS Code Insiders, Cursor or VSCodium
- it's idle, not busy or waiting for you
- an editor's panel started it: a session you've resumed in a terminal keeps its archived id, but isn't closed
- its process has run for at least a minute, so one you've just opened, even from the archived list, is left alone; how long ago it was archived doesn't matter
- its process is still the one its record names, started when the record says, not a later process given the same pid

The editors keep what's archived in their own state, `User/globalStorage/state.vscdb` under `~/Library/Application Support/<editor>` on macOS and `$XDG_CONFIG_HOME/<editor>`, or `~/.config/<editor>`, on Linux, as the `hiddenSessionIds` in the extension's row. That's read read-only, and a database that's missing or laid out otherwise counts as archiving nothing. Both commands stop with a ⚠️ on any system but macOS and Linux.

## Who changed what

`claude-sessions --changes [<path>]` lists what's uncommitted in the git repository at path, here by default, and which running sessions edited each file since it was last committed. Use it before committing, or before changing files a session may still be working on.

```
$ claude-sessions --changes
 M src/listing.py  Fix the listing (busy)
?? notes.txt       no running session
Commands run here since the last commit: Fix the listing (busy)
➖ 2 files uncommitted in ~/projects/app, 1 edited by a running session.
```

- **Edited** means the session's transcript, or one of its subagents', has a `Write`, `Edit`, `MultiEdit` or `NotebookEdit` call on the file, made after the last commit that changed the file. Any edit to a file never committed counts.
- **Commands run here** lists the sessions that ran a shell command in the repository since its last commit. A command can change any file without naming it, so these may have changed files listed as edited by no running session.
- A busy or waiting session is mid-turn: still working on what it changed. An idle one has stopped, but may not be done.
- Only running sessions are counted. Paths are compared with symbolic links resolved, and each worktree is its own repository.

`--json` prints the same, alone on stdout, for other tools to read: each file's `path`, `status` (git's two letters) and `edited_by`, then `commands_by` and the `unattributed` paths. Each session has its `session_id`, `pid`, `title`, `status`, and `own`, which marks the session running the command, from `CLAUDE_CODE_SESSION_ID`.

## Where it comes from

Claude Code's own files, read directly:

| What | From |
|---|---|
| Sessions running, their status, name and who named them | `~/.claude/sessions/<pid>.json`, one per session; a file whose process has gone is skipped |
| Title, directory, model, context used, last activity | The session's transcript, `~/.claude/projects/<dir>/<session id>.jsonl` |
| Its subagents, what each was asked to do, and whether in the background | `~/.claude/projects/<dir>/<session id>/subagents/agent-<id>.jsonl` and `agent-<id>.meta.json` |
| When a background subagent stopped | The task notification it sends its session, in the session's transcript |
| When a session's process started, to leave out subagents of an earlier one | `procStart` in `~/.claude/sessions/<pid>.json` |
| What each session edited, and where it ran commands | The tool calls in its transcript, and its subagents' in `~/.claude/projects/<dir>/<session id>/subagents/` |
| Which sessions are archived | Each editor's `state.vscdb`; see [Closing archived sessions](#closing-archived-sessions) |
| Branch, uncommitted files, when each was last committed | `git` in the session's directory, or the repository given to `--changes`. The transcript's own `gitBranch` is the branch it started on, so isn't used |

These formats are Claude Code's and may change. A record or field it can't read is shown as unknown rather than failing. `claude agents --json` lists the same sessions, but without who named them or the transcript's details.

## Install

```sh
cd ~/projects/cli/claude-sessions
devbox run -- task setup   # uv sync, then links claude-sessions into ~/.local/bin
```

## Development

```sh
devbox run -- task check   # ruff, then pytest
```

## License

MIT
