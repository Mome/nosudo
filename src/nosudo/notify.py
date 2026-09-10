"""Best-effort start/end notifications.

Delivery is best-effort over local channels and must never block or fail the
restrict/restore action (specs.md §5). All errors are swallowed.

notify.start/end always run as root (self-elevated via ``sudo`` for ``restrict``,
or from the root-owned systemd restore unit for the crash/reboot-safe path), so
there is never a usable ``DBUS_SESSION_BUS_ADDRESS`` in our own environment —
sudo's default ``env_reset`` strips it, and a bare systemd unit has no desktop
session at all. Instead we resolve the *target* user's own session bus at
``/run/user/<uid>/bus`` and run ``notify-send`` as that user against it.
"""

from __future__ import annotations

import contextlib
import pwd
import shutil
import subprocess
from datetime import datetime
from pathlib import Path

from .runner import Runner


def _broadcast(user: str, message: str) -> None:
    if not shutil.which("notify-send") or not shutil.which("sudo"):
        return
    try:
        uid = pwd.getpwnam(user).pw_uid
    except KeyError:
        return
    bus_path = Path(f"/run/user/{uid}/bus")
    if not bus_path.exists():
        # No active session for this user (e.g. no desktop, or logged out) —
        # nothing to notify.
        return
    with contextlib.suppress(OSError, subprocess.SubprocessError):
        subprocess.run(
            [
                "sudo",
                "-u",
                user,
                "env",
                f"DBUS_SESSION_BUS_ADDRESS=unix:path={bus_path}",
                f"XDG_RUNTIME_DIR=/run/user/{uid}",
                "notify-send",
                "nosudo",
                message,
            ],
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )


def start(user: str, lift_at: datetime, runner: Runner) -> None:
    if runner.dry_run:
        runner.info(f"[dry-run] would notify {user}: restriction starts")
        return
    _broadcast(
        user,
        f"nosudo: sudo rights for {user} are restricted until "
        f"{lift_at.strftime('%Y-%m-%d %H:%M')} and will be restored automatically.",
    )


def end(user: str, runner: Runner) -> None:
    if runner.dry_run:
        runner.info(f"[dry-run] would notify {user}: restriction ended")
        return
    _broadcast(user, f"nosudo: sudo rights for {user} have been restored.")
