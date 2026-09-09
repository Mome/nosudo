"""Warn about pre-existing privileged sessions when a restriction starts.

A cached sudo *timestamp* is NOT an undo window: sudo re-evaluates the sudoers
*policy* on every invocation (it only caches authentication, not authorization),
so the deny drop-in takes effect immediately regardless of any cached credential.
The real residual risk is an **already-open root shell** (e.g. ``sudo -s`` started
before the restriction), which keeps root until it is closed. We warn about those;
killing them is deferred (specs.md §6).
"""

from __future__ import annotations

import subprocess

from .runner import Runner


def _user_ttys(user: str) -> list[str]:
    try:
        out = subprocess.run(
            ["who"], text=True, capture_output=True, check=True
        ).stdout
    except (OSError, subprocess.SubprocessError):
        return []
    ttys = []
    for line in out.splitlines():
        parts = line.split()
        if len(parts) >= 2 and parts[0] == user:
            ttys.append(parts[1])
    return ttys


def detect_root_sessions(user: str) -> list[str]:
    """Best-effort detection of root processes on the user's terminals.

    Catches the common case of an open ``sudo -s``/``sudo -i`` shell sharing a
    tty with the user. Returns human-readable descriptions; never raises.
    """
    findings: list[str] = []
    for tty in _user_ttys(user):
        try:
            out = subprocess.run(
                ["ps", "-t", tty, "-o", "user=,comm="],
                text=True,
                capture_output=True,
                check=True,
            ).stdout
        except (OSError, subprocess.SubprocessError):
            continue
        for line in out.splitlines():
            parts = line.split(None, 1)
            if len(parts) == 2 and parts[0] == "root":
                findings.append(f"root process {parts[1]!r} on {tty}")
    return findings


def warn_existing_sessions(user: str, runner: Runner) -> None:
    """Warn about pre-existing root shells that keep root despite the deny."""
    for finding in detect_root_sessions(user):
        runner.warn(
            f"{finding}: it keeps root until closed — close it to fully apply the restriction"
        )
