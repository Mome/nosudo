"""Library API: the orchestration behind each CLI command, callable directly.

Extracted from ``cli.py`` so other Python code (e.g. ``curfew``) can drive
restrict/restore/status/check without going through ``argparse``/subprocess.
Each function takes plain arguments; ``cli.py`` remains responsible only for
argument resolution and user-facing output formatting.
"""

from __future__ import annotations

from datetime import datetime

from . import audit, notify, scheduler, sessions, state, sudoers
from .runner import Runner


class CommandError(Exception):
    """User-facing error; printed without a traceback, exit code 1."""


def restrict(user: str, lift_at: datetime, runner: Runner | None = None) -> None:
    runner = runner or Runner()

    if state.exists(user) or sudoers.is_active(user) or scheduler.is_active(user):
        raise CommandError(
            f"{user} is already restricted; use `nosudo extend` to change the lift time"
        )

    # Warn-and-proceed: surface open root leaks without blocking (specs.md §6).
    opens = audit.open_findings(audit.check(user))
    if opens:
        runner.warn(
            f"{user} has open paths to root that could undo this restriction:"
        )
        for f in opens:
            runner.warn(f"  - {f.vector}: {f.detail}")
        runner.warn("proceeding anyway; run `nosudo check` for the full audit")

    created: list[str] = []
    try:
        sudoers.install(user, lift_at, runner)
        created.append("sudoers")
        sessions.warn_existing_sessions(user, runner)
        record = state.build(user, datetime.now().astimezone(), lift_at)
        state.write(record, runner)
        created.append("state")
        scheduler.install(user, lift_at, runner)
        created.append("scheduler")
    except Exception:
        runner.warn("restrict failed; rolling back partial changes")
        if "scheduler" in created:
            scheduler.remove(user, runner)
        if "state" in created:
            state.remove(user, runner)
        if "sudoers" in created:
            sudoers.remove(user, runner)
        raise

    notify.start(user, lift_at, runner)


def extend(user: str, lift_at: datetime, runner: Runner | None = None) -> None:
    runner = runner or Runner()

    record = state.read(user)
    if record is None:
        raise CommandError(f"{user} is not currently restricted")

    if lift_at <= record.lift_dt:
        raise CommandError(
            "extend is lengthen-only: the new lift time must be later than the "
            f"current one ({record.lift_dt.strftime('%Y-%m-%d %H:%M')})"
        )

    scheduler.update_timer(user, lift_at, runner)
    state.update_lift_time(record, lift_at, runner)


def restore(user: str, runner: Runner | None = None) -> None:
    runner = runner or Runner()

    # Idempotent: every step tolerates already-removed state.
    scheduler.remove(user, runner)
    sudoers.remove(user, runner)
    state.remove(user, runner)
    notify.end(user, runner)


def status() -> list[state.Restriction]:
    return state.list_all()


def check(user: str) -> list[audit.Finding]:
    return audit.check(user)
