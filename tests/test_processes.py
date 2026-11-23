"""Reading what ps says about a process, and asking about and ending real ones."""

import os
import subprocess
import sys
from datetime import datetime, timedelta

from claude_sessions import processes
from claude_sessions.processes import Process

STARTED = "Fri Oct 30 06:38:10 2026"


def test_the_age_is_read_in_minutes_and_seconds():
    assert processes.parse(f"   01:05 {STARTED}   ") == Process(timedelta(seconds=65), STARTED)


def test_the_age_is_read_with_hours_and_days():
    assert processes.parse(f"02:00:01 {STARTED}").age == timedelta(hours=2, seconds=1)
    assert processes.parse(f"3-02:00:01 {STARTED}").age == timedelta(days=3, hours=2, seconds=1)


def test_the_start_is_kept_with_its_spacing_made_single():
    assert processes.parse("00:01 Sun Nov  1 20:33:39 2026").started == "Sun Nov 1 20:33:39 2026"


def test_output_that_isnt_a_process_is_none():
    assert processes.parse("") is None
    assert processes.parse("01:05") is None
    assert processes.parse(f"1:2:3:4 {STARTED}") is None
    assert processes.parse(f"a-01:05 {STARTED}") is None
    assert processes.parse(f"01:x5 {STARTED}") is None


def test_a_running_process_is_described_by_ps():
    process = processes.describe(os.getpid())
    assert process is not None
    assert process.age >= timedelta(0)
    datetime.strptime(process.started, "%a %b %d %H:%M:%S %Y")


def test_an_ended_process_is_not_described():
    process = subprocess.Popen([sys.executable, "-c", ""])
    process.wait()
    assert processes.describe(process.pid) is None


def test_terminating_ends_the_process():
    process = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
    try:
        assert processes.terminate(process.pid)
        assert process.wait(timeout=10) == -15
    finally:
        process.kill()
    assert not processes.terminate(process.pid)


def test_when_a_process_started_is_read_in_this_machines_time_zone():
    assert processes.started_at("Sun Nov  1 20:33:39 2026") == (
        datetime(2026, 11, 1, 20, 33, 39).astimezone()
    )


def test_a_start_that_isnt_a_time_is_none():
    assert processes.started_at("yesterday") is None
    assert processes.started_at(None) is None
