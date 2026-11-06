"""Asking the operating system about a session's process, and ending it."""

import os
import signal
import subprocess
from dataclasses import dataclass
from datetime import timedelta
from typing import final


@final
@dataclass(frozen=True)
class Process:
    age: timedelta
    """How long the process has been running, to the second."""
    started: str
    """When it started, as `ps -o lstart=` gives it."""


def parse(output: str) -> Process | None:
    """The process `ps -o etime=,lstart=` describes, on macOS or Linux, or None when the output
    isn't one. etime is the age as [[dd-]hh:]mm:ss."""
    fields = output.split(maxsplit=1)
    if len(fields) != 2:
        return None
    elapsed, started = fields
    days, _, clock = elapsed.rpartition("-")
    parts = clock.split(":")
    if not (2 <= len(parts) <= 3) or not all(p.isdigit() for p in [*parts, days or "0"]):
        return None
    seconds = 0
    for part in parts:
        seconds = seconds * 60 + int(part)
    age = timedelta(days=int(days or "0"), seconds=seconds)
    return Process(age=age, started=" ".join(started.split()))


def describe(pid: int) -> Process | None:
    """The running process with this pid, or None when there's none or ps can't say."""
    try:
        result = subprocess.run(
            ["ps", "-o", "etime=,lstart=", "-p", str(pid)], capture_output=True, text=True
        )
    except OSError:
        return None
    return parse(result.stdout) if result.returncode == 0 else None


def terminate(pid: int) -> bool:
    """Asks the process to end, with SIGTERM, so it shuts down cleanly. False when it had
    already gone or isn't ours to end."""
    try:
        os.kill(pid, signal.SIGTERM)
    except (ProcessLookupError, PermissionError):
        return False
    return True
