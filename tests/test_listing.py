"""Turning sessions into the list claude-sessions prints."""

import re
from dataclasses import replace
from datetime import UTC, datetime, timedelta

from cli_kit.colour import BOLD, CYAN, GREEN, GREY, RED, RESET, YELLOW, Style

from claude_sessions import listing, subagents
from claude_sessions.listing import Session, Subagent
from claude_sessions.registry import Entry
from claude_sessions.subagents import Meta
from claude_sessions.transcript import UNKNOWN, Transcript

NOW = datetime(2026, 10, 31, 12, 0, tzinfo=UTC)
PLAIN = Style(enabled=False)

ENTRY = Entry(
    pid=1,
    session_id="s1",
    cwd="/home/me/projects/app",
    status="idle",
    name="app-86",
    named_by="derived",
    updated=NOW - timedelta(hours=3),
    status_changed=NOW - timedelta(hours=3),
    entrypoint="claude-vscode",
    process_started="Fri Oct 30 06:38:10 2026",
)
TRANSCRIPT = Transcript(
    ai_title="Fixing the login form",
    cwd="/home/me/projects/app/src",
    model="claude-opus-5-5",
    context_tokens=52_003,
    last_activity=NOW - timedelta(minutes=5),
    started=True,
    ended=False,
    subagents_stopped={},
)
SESSION = Session(
    status="idle",
    location="~/projects/app/src",
    branch="main",
    model="claude-opus-5-5",
    context_tokens=52_003,
    title="Fixing the login form",
    user_named=False,
    last_active=NOW - timedelta(minutes=5),
    subagents=(),
    blank=False,
    archived=False,
)


def test_a_session_is_titled_by_claude_and_found_where_it_last_worked():
    assert (
        listing.session(ENTRY, TRANSCRIPT, "~/projects/app/src", "main", [], False, NOW) == SESSION
    )


HELPER = Subagent(
    location="~/projects/app/src",
    branch="main",
    model="claude-sonnet-5-5",
    context_tokens=9_000,
    title="Find the callers",
    last_active=NOW - timedelta(minutes=1),
)


def test_its_directory_is_where_it_last_worked_else_where_it_started():
    assert listing.directory(ENTRY, TRANSCRIPT) == "/home/me/projects/app/src"
    assert listing.directory(ENTRY, UNKNOWN) == "/home/me/projects/app"


def test_a_name_you_gave_the_session_is_its_title():
    entry = replace(ENTRY, name="list sessions", named_by="user")
    session = listing.session(entry, TRANSCRIPT, "~/projects/app/src", "main", [], False, NOW)
    assert (session.title, session.user_named) == ("list sessions", True)


def test_a_name_claude_code_gave_it_is_its_title_but_not_yours():
    entry = replace(ENTRY, name="Assess PHP", named_by="auto")
    session = listing.session(entry, TRANSCRIPT, "~/projects/app/src", "main", [], False, NOW)
    assert (session.title, session.user_named) == ("Assess PHP", False)


def test_without_a_transcript_it_is_where_it_started_and_named_after_its_directory():
    session = listing.session(ENTRY, UNKNOWN, "~/projects/app", None, [], False, NOW)
    assert session == Session(
        status="idle",
        location="~/projects/app",
        branch=None,
        model=None,
        context_tokens=None,
        title="app-86",
        user_named=False,
        last_active=NOW - timedelta(hours=3),
        subagents=(),
        blank=True,
        archived=False,
    )


def test_an_idle_session_with_nothing_said_in_it_is_blank():
    unsaid = replace(TRANSCRIPT, started=False)
    assert listing.session(ENTRY, unsaid, "~/projects/app", None, [], False, NOW).blank


def test_a_session_with_a_prompt_or_reply_in_it_is_not_blank():
    assert not listing.session(ENTRY, TRANSCRIPT, "~/projects/app/src", None, [], False, NOW).blank


def test_a_session_busy_or_waiting_on_its_first_prompt_is_not_blank():
    for status in ("busy", "waiting", None):
        entry = replace(ENTRY, status=status)
        assert not listing.session(entry, UNKNOWN, "~/projects/app", None, [], False, NOW).blank


def test_a_session_with_subagents_running_is_not_blank():
    assert not listing.session(ENTRY, UNKNOWN, "~/projects/app", None, [HELPER], False, NOW).blank


def test_blank_sessions_are_not_listed():
    blank = replace(SESSION, title="blank", blank=True)
    assert listing.started([SESSION, blank]) == [SESSION]


def test_a_session_idle_for_under_two_minutes_is_done():
    entry = replace(ENTRY, status_changed=NOW - timedelta(seconds=119))
    assert listing.session(
        entry, TRANSCRIPT, "~/projects/app/src", "main", [], False, NOW
    ) == replace(SESSION, status="done")


def test_a_session_idle_for_two_minutes_or_more_is_idle():
    entry = replace(ENTRY, status_changed=NOW - timedelta(minutes=2))
    assert (
        listing.session(entry, TRANSCRIPT, "~/projects/app/src", "main", [], False, NOW).status
        == "idle"
    )


def test_a_session_busy_or_waiting_since_a_moment_ago_is_not_done():
    for status in ("busy", "waiting"):
        entry = replace(ENTRY, status=status, status_changed=NOW - timedelta(seconds=5))
        assert (
            listing.session(entry, TRANSCRIPT, "~/projects/app/src", "main", [], False, NOW).status
            == status
        )


def test_a_session_just_opened_with_nothing_said_in_it_is_not_done():
    entry = replace(ENTRY, status_changed=NOW - timedelta(seconds=5))
    unsaid = replace(TRANSCRIPT, started=False)
    assert listing.session(entry, unsaid, "~/projects/app", "main", [], False, NOW).status == "idle"


def test_a_session_whose_subagent_is_still_at_work_is_not_done():
    entry = replace(ENTRY, status_changed=NOW - timedelta(seconds=5))
    assert (
        listing.session(
            entry, TRANSCRIPT, "~/projects/app/src", "main", [HELPER], False, NOW
        ).status
        == "idle"
    )


def test_a_session_whose_status_change_is_unknown_is_not_done():
    entry = replace(ENTRY, status_changed=None)
    assert (
        listing.session(entry, TRANSCRIPT, "~/projects/app/src", "main", [], False, NOW).status
        == "idle"
    )


def test_done_sessions_come_after_those_busy_and_before_those_idle():
    waiting = replace(SESSION, status="waiting", title="waiting")
    done = replace(SESSION, status="done", title="done")
    busy = replace(SESSION, status="busy", title="busy", last_active=NOW - timedelta(days=1))
    titles = [s.title for s in listing.ordered([SESSION, done, busy, waiting])]
    assert titles == ["waiting", "busy", "done", "Fixing the login form"]


def test_a_done_session_is_active():
    assert listing.active([SESSION, replace(SESSION, status="done")]) == [
        replace(SESSION, status="done")
    ]


def test_the_count_says_how_many_are_done():
    sessions = [SESSION, replace(SESSION, status="done"), replace(SESSION, status="busy")]
    assert listing.count(sessions) == "3 sessions (1 busy, 1 done, 1 idle)."


def test_each_status_has_its_colour():
    colours = {"waiting": YELLOW, "done": GREEN, "busy": CYAN, "idle": GREY}
    for status, code in colours.items():
        session = replace(SESSION, status=status)
        [line] = listing.render([session], NOW, Style(enabled=True), None)
        assert line.startswith(f"{code}{status}{RESET}")


def test_a_session_archived_in_its_editor_is_marked_archived():
    session = listing.session(ENTRY, TRANSCRIPT, "~/projects/app/src", "main", [], True, NOW)
    assert session == replace(SESSION, archived=True)


def test_an_archived_sessions_status_ends_in_archived():
    for status in ("waiting", "done", "busy", "idle"):
        archived = replace(SESSION, status=status, archived=True)
        [line] = listing.render([archived], NOW, PLAIN, None)
        assert line.startswith(f"{status}-archived  ")


def test_an_archived_session_whose_status_is_unknown_is_unknown_archived():
    [line] = listing.render([replace(SESSION, status=None, archived=True)], NOW, PLAIN, None)
    assert line.startswith("unknown-archived  ")


def test_an_archived_status_keeps_its_colour_with_archived_in_grey():
    archived = replace(SESSION, status="busy", archived=True)
    [line] = listing.render([archived], NOW, Style(enabled=True), None)
    assert line.startswith(f"{CYAN}busy{RESET}{GREY}-archived{RESET}  ")


def test_the_status_column_is_as_wide_as_an_archived_status_in_it():
    archived = replace(SESSION, status="busy", archived=True, title="archived")
    lines = listing.render([archived, SESSION], NOW, PLAIN, None)
    assert [line.index("5m") for line in lines] == [len("busy-archived  ")] * 2


def test_an_archived_sessions_subagents_are_busy_without_archived():
    archived = replace(SESSION, archived=True, subagents=(HELPER,))
    [_, helper] = listing.render(listing.rows([archived]), NOW, PLAIN, None)
    assert helper.startswith("busy  ")


def test_an_archived_session_is_ordered_and_counted_by_its_status():
    archived = replace(SESSION, status="waiting", title="archived", archived=True)
    busy = replace(SESSION, status="busy", title="busy")
    assert [s.title for s in listing.ordered([busy, archived])] == ["archived", "busy"]
    assert listing.count([busy, archived]) == "2 sessions (1 waiting, 1 busy)."


def test_an_archived_session_waiting_or_busy_is_active():
    archived = replace(SESSION, status="busy", archived=True)
    assert listing.active([archived]) == [archived]


def test_a_status_change_after_its_latest_message_is_its_latest_activity():
    entry = replace(ENTRY, updated=NOW - timedelta(minutes=1))
    assert (
        listing.session(entry, TRANSCRIPT, "~/projects/app/src", "main", [], False, NOW).last_active
        == entry.updated
    )


def test_a_directory_in_home_is_shown_from_it():
    where = "/home/me/projects/app"
    assert listing.location(where, where, None, "/home/me") == "~/projects/app"
    assert listing.location("/home/me", "/home/me", None, "/home/me") == "~"


def test_a_directory_outside_home_is_shown_in_full():
    assert listing.location("/srv/app", "/srv/app", None, "/home/me") == "/srv/app"


def test_a_directory_beside_home_with_the_same_prefix_is_not_in_it():
    assert listing.location("/home/meg/app", "/home/meg/app", None, "/home/me") == "/home/meg/app"


def test_an_unknown_directory_is_a_question_mark():
    assert listing.location(None, None, None, "/home/me") == "?"


def test_a_directory_below_the_one_listed_is_shown_from_it():
    where = "/home/me/projects/app/src"
    assert listing.location(where, where, "/home/me/projects", "/home/me") == "app/src"


def test_the_directory_listed_is_shown_as_nothing():
    where = "/home/me/projects/app"
    assert listing.location(where, where, where, "/home/me") == ""


def test_a_directory_is_compared_with_the_one_listed_by_its_resolved_path():
    shown = listing.location("/var/app/src", "/private/var/app/src", "/private/var/app", "/home/me")
    assert shown == "src"


def test_a_directory_outside_the_one_listed_is_shown_from_home():
    where = "/home/me/projects/apple"
    assert listing.location(where, where, "/home/me/projects/app", "/home/me") == "~/projects/apple"


def test_below_the_root_of_the_filesystem_a_directory_is_shown_from_it():
    assert listing.location("/srv/app", "/srv/app", "/", "/home/me") == "srv/app"


def test_sessions_needing_you_come_first_then_working_then_the_most_recently_active():
    old_idle = replace(SESSION, title="old", last_active=NOW - timedelta(days=2))
    new_idle = replace(SESSION, title="new")
    busy = replace(SESSION, status="busy", title="busy", last_active=NOW - timedelta(hours=1))
    waiting = replace(
        SESSION, status="waiting", title="waiting", last_active=NOW - timedelta(days=1)
    )
    unknown = replace(SESSION, status=None, title="unknown", last_active=None)
    titles = [s.title for s in listing.ordered([unknown, old_idle, busy, new_idle, waiting])]
    assert titles == ["waiting", "busy", "new", "old", "unknown"]


def test_only_the_waiting_and_busy_sessions_are_active():
    sessions = [SESSION, replace(SESSION, status="busy"), replace(SESSION, status="waiting")]
    assert [s.status for s in listing.active(sessions)] == ["busy", "waiting"]


def test_each_session_is_a_line_in_aligned_columns():
    other = replace(
        SESSION,
        status="waiting",
        location="~/projects/longer-name",
        branch=None,
        model="claude-sonnet-5-5",
        context_tokens=800,
        title="Another",
        last_active=NOW - timedelta(days=3),
    )
    assert listing.render([SESSION, other], NOW, PLAIN, None) == [
        "idle     5m  opus-5-5    52k  Fixing the login form  ~/projects/app/src      main",
        "waiting  3d  sonnet-5-5  800  Another                ~/projects/longer-name",
    ]


def test_a_column_empty_on_every_line_is_left_out():
    bare = replace(SESSION, branch=None, model=None, context_tokens=None)
    assert listing.render([bare], NOW, PLAIN, None) == [
        "idle  5m  Fixing the login form  ~/projects/app/src"
    ]


def test_the_column_of_where_is_left_out_when_every_line_is_in_the_directory_listed():
    here = replace(SESSION, location="")
    assert listing.render([here, replace(HELPER, location="")], NOW, PLAIN, None) == [
        "idle  5m  opus-5-5    52k  Fixing the login form  main",
        "busy  1m  sonnet-5-5   9k  ↳ Find the callers     main",
    ]


def test_a_line_in_the_directory_listed_is_marked_here_beside_one_below_it():
    here = replace(SESSION, location="")
    below = replace(SESSION, location="src", title="Below")
    assert listing.render([here, below], NOW, PLAIN, None) == [
        "idle  5m  opus-5-5  52k  Fixing the login form  .    main",
        "idle  5m  opus-5-5  52k  Below                  src  main",
    ]


def test_no_sessions_is_no_lines():
    assert listing.render([], NOW, PLAIN, None) == []


def test_a_title_too_long_for_the_terminal_is_cut_to_fit():
    [line] = listing.render([SESSION], NOW, PLAIN, 60)
    assert line == "idle  5m  opus-5-5  52k  Fixing t…  ~/projects/app/src  main"
    assert len(line) == 60


def test_titles_cut_to_fit_stay_aligned():
    short = replace(SESSION, title="Short")
    assert listing.render([SESSION, short], NOW, PLAIN, 60) == [
        "idle  5m  opus-5-5  52k  Fixing t…  ~/projects/app/src  main",
        "idle  5m  opus-5-5  52k  Short      ~/projects/app/src  main",
    ]


def test_a_long_directory_is_cut_from_the_left_to_35_characters():
    deep = replace(SESSION, location="~/projects/clients/acme/services/billing-api")
    [line] = listing.render([deep], NOW, PLAIN, None)
    assert line.endswith("  …/clients/acme/services/billing-api  main")


def test_long_directories_are_cut_only_as_far_as_keeps_them_apart():
    one = replace(SESSION, location="~/work/one/clients/acme/services/billing-api")
    two = replace(SESSION, location="~/work/two/clients/acme/services/billing-api")
    lines = listing.render([one, two], NOW, PLAIN, None)
    assert [line.split("  ")[-2] for line in lines] == [
        "…e/clients/acme/services/billing-api",
        "…o/clients/acme/services/billing-api",
    ]


def test_the_same_long_directory_twice_is_still_cut():
    deep = replace(SESSION, location="~/projects/clients/acme/services/billing-api")
    lines = listing.render([deep, deep], NOW, PLAIN, None)
    assert lines == [lines[0], lines[0]]
    assert "  …/clients/acme/services/billing-api  " in lines[0]


def test_a_name_you_gave_is_bold():
    [line] = listing.render([replace(SESSION, user_named=True)], NOW, Style(enabled=True), None)
    assert f"  {BOLD}Fixing the login form{RESET}  " in line


def test_the_context_used_is_green_while_healthy_yellow_when_large_and_red_when_time_to_restart():
    def coloured(tokens: int) -> str:
        session = replace(SESSION, context_tokens=tokens)
        [line] = listing.render([session], NOW, Style(enabled=True), None)
        return line

    assert f"{GREEN}99k{RESET}" in coloured(99_999)
    assert f"{YELLOW}100k{RESET}" in coloured(100_000)
    assert f"{YELLOW}149k{RESET}" in coloured(149_999)
    assert f"{RED}150k{RESET}" in coloured(150_000)


def test_coloured_columns_stay_aligned():
    small = replace(SESSION, context_tokens=800)
    lines = listing.render([SESSION, small], NOW, Style(enabled=True), None)
    plain = [re.sub(r"\x1b\[[0-9;]*m", "", line) for line in lines]
    assert plain == listing.render([SESSION, small], NOW, PLAIN, None)


def test_how_long_ago_reads_in_the_largest_whole_unit():
    def age(delta: timedelta) -> str:
        return listing.age(NOW - delta, NOW)

    assert age(timedelta(seconds=59)) == "now"
    assert age(timedelta(minutes=59)) == "59m"
    assert age(timedelta(hours=23)) == "23h"
    assert age(timedelta(days=9)) == "9d"
    assert listing.age(None, NOW) == "?"


def test_the_count_says_how_many_are_in_each_status():
    sessions = [SESSION, SESSION, replace(SESSION, status="busy"), replace(SESSION, status=None)]
    assert listing.count(sessions) == "4 sessions (1 busy, 2 idle, 1 unknown)."


def test_the_count_says_how_many_are_blank_apart_from_their_status():
    sessions = [SESSION, replace(SESSION, blank=True), replace(SESSION, status="busy")]
    assert listing.count(sessions) == "3 sessions (1 busy, 1 idle, 1 blank)."


def test_the_count_of_only_blank_sessions_says_so():
    assert listing.count([replace(SESSION, blank=True)]) == "1 session (1 blank)."


def test_the_count_of_one_session_is_singular():
    assert listing.count([SESSION]) == "1 session (1 idle)."


def test_the_count_of_no_sessions_says_none_are_running():
    assert listing.count([]) == "No sessions running."


def test_on_screen_every_line_shows_above_the_summary_when_they_fit():
    assert listing.fitting(2, 3) == 2
    assert listing.screen(["a", "b"], 2, "2 sessions.", 3) == ["a", "b", "2 sessions."]


def test_on_screen_lines_that_dont_fit_are_counted_in_their_place():
    assert listing.fitting(5, 4) == 2
    assert listing.screen(["a", "b"], 5, "5 sessions.", 4) == ["a", "b", "… 3 more", "5 sessions."]


def test_on_a_screen_two_rows_high_only_the_count_of_lines_fits_above_the_summary():
    assert listing.fitting(2, 2) == 0
    assert listing.screen([], 2, "2 sessions.", 2) == ["… 2 more", "2 sessions."]


def test_on_a_screen_one_row_high_only_the_summary_shows():
    assert listing.fitting(1, 1) == 0
    assert listing.screen([], 1, "1 session.", 1) == ["1 session."]


def test_a_subagent_is_titled_by_what_it_was_asked_to_do_and_found_where_it_last_worked():
    found = subagents.Subagent(
        "a1",
        Meta("Find the callers", background=False),
        replace(
            TRANSCRIPT,
            cwd="/home/me/projects/app/.claude/worktrees/a1",
            model="claude-sonnet-5-5",
            context_tokens=9_000,
        ),
    )
    assert listing.subagent_directory(found, "/home/me/projects/app") == (
        "/home/me/projects/app/.claude/worktrees/a1"
    )
    assert listing.subagent(
        found, "~/projects/app/.claude/worktrees/a1", "worktree-a1"
    ) == Subagent(
        location="~/projects/app/.claude/worktrees/a1",
        branch="worktree-a1",
        model="claude-sonnet-5-5",
        context_tokens=9_000,
        title="Find the callers",
        last_active=NOW - timedelta(minutes=5),
    )


def test_a_subagent_that_hasnt_said_where_it_is_works_where_its_session_does():
    found = subagents.Subagent("a1", Meta(None, background=True), UNKNOWN)
    assert listing.subagent_directory(found, "/home/me/projects/app") == "/home/me/projects/app"
    assert listing.subagent(found, "~/projects/app", None).title == "subagent"


def test_a_sessions_subagents_are_listed_the_most_recently_active_first():
    older = replace(HELPER, title="older", last_active=NOW - timedelta(minutes=9))
    session = listing.session(
        ENTRY, TRANSCRIPT, "~/projects/app/src", "main", [older, HELPER], False, NOW
    )
    assert session.subagents == (HELPER, older)


def test_each_session_is_followed_by_its_subagents():
    other = replace(SESSION, title="other")
    with_helper = replace(SESSION, subagents=(HELPER,))
    assert listing.rows([with_helper, other]) == [with_helper, HELPER, other]


def test_a_subagent_is_a_busy_line_under_its_session():
    assert listing.render([SESSION, HELPER], NOW, PLAIN, None) == [
        "idle  5m  opus-5-5    52k  Fixing the login form  ~/projects/app/src  main",
        "busy  1m  sonnet-5-5   9k  ↳ Find the callers     ~/projects/app/src  main",
    ]


def test_the_mark_of_a_subagent_is_grey_and_its_title_plain():
    lines = listing.render([SESSION, HELPER], NOW, Style(enabled=True), None)
    assert f"  {GREY}↳ {RESET}Find the callers  " in lines[1]
    plain = [re.sub(r"\x1b\[[0-9;]*m", "", line) for line in lines]
    assert plain == listing.render([SESSION, HELPER], NOW, PLAIN, None)


def test_a_session_with_subagents_running_is_active_whatever_its_own_status():
    with_helper = replace(SESSION, subagents=(HELPER,))
    assert listing.active([SESSION, with_helper]) == [with_helper]


def test_subagents_arent_counted_as_sessions():
    assert listing.count([replace(SESSION, subagents=(HELPER,))]) == "1 session (1 idle)."


def test_a_directory_is_within_itself():
    assert listing.within("/home/me/app", "/home/me/app")


def test_a_directory_below_another_is_within_it():
    assert listing.within("/home/me/app/src", "/home/me/app")


def test_a_directory_beside_another_with_the_same_prefix_is_not_within_it():
    assert not listing.within("/home/me/apple", "/home/me/app")


def test_every_directory_is_within_the_root():
    assert listing.within("/home/me", "/")


def test_with_no_directory_given_every_session_is_in_scope():
    assert listing.in_scope("/srv/app", None)


def test_a_session_working_below_the_directory_given_is_in_scope():
    assert listing.in_scope("/home/me/app/src", "/home/me/app")


def test_a_session_working_elsewhere_is_out_of_scope():
    assert not listing.in_scope("/home/me/apple", "/home/me/app")


def test_a_session_whose_directory_is_unknown_is_out_of_scope_of_a_directory():
    assert not listing.in_scope(None, "/home/me/app")


def test_the_count_within_a_directory_is_of_only_the_sessions_there():
    sessions = [replace(SESSION, status="busy"), SESSION]
    assert (
        listing.count_within(sessions, "~/projects/app")
        == "~/projects/app: 2 sessions (1 busy, 1 idle)."
    )


def test_the_count_within_a_directory_says_how_many_there_are_blank():
    sessions = [SESSION, replace(SESSION, blank=True)]
    assert (
        listing.count_within(sessions, "~/projects/app")
        == "~/projects/app: 2 sessions (1 idle, 1 blank)."
    )


def test_the_count_of_one_session_within_a_directory_is_singular():
    assert (
        listing.count_within([SESSION], "~/projects/app") == "~/projects/app: 1 session (1 idle)."
    )


def test_the_count_within_a_directory_with_no_sessions_there_says_so():
    assert listing.count_within([], "~/projects/app") == "~/projects/app: No sessions."


def test_the_count_within_no_directory_is_the_count_of_every_session():
    sessions = [replace(SESSION, status="busy"), SESSION]
    assert listing.count_within(sessions, None) == "2 sessions (1 busy, 1 idle)."
