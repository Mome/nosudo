"""Best-effort start/end notifications.

Delivery is best-effort over local channels and must never block or fail the
restrict/restore action (specs.md §5). All errors are swallowed.
"""

from __future__ import annotations

import contextlib
import os
import shutil
import subprocess
from datetime import datetime

from .runner import Runner


def _broadcast(message: str) -> None:
    # ``wall`` reaches the user's terminals; ``notify-send`` is attempted for a
    # desktop session if available. Both are best-effort and fully silenced:
    # failures must never leak output (specs.md §5).
    if shutil.which("wall"):
        with contextlib.suppress(OSError, subprocess.SubprocessError):
            subprocess.run(
                ["wall"],
                input=message,
                text=True,
                check=False,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
    # Only try notify-send when a session bus actually exists. Otherwise glib
    # tries `dbus-launch --autolaunch`, which fails noisily — and as root (after
    # self-elevation) there is no session bus anyway.
    if shutil.which("notify-send") and os.environ.get("DBUS_SESSION_BUS_ADDRESS"):
        with contextlib.suppress(OSError, subprocess.SubprocessError):
            subprocess.run(
                ["notify-send", "unsudo", message],
                check=False,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )


def start(user: str, lift_at: datetime, runner: Runner) -> None:
    if runner.dry_run:
        runner.info(f"[dry-run] would notify {user}: restriction starts")
        return
    _broadcast(
        f"unsudo: sudo rights for {user} are restricted until "
        f"{lift_at.strftime('%Y-%m-%d %H:%M')} and will be restored automatically."
    )


def end(user: str, runner: Runner) -> None:
    if runner.dry_run:
        runner.info(f"[dry-run] would notify {user}: restriction ended")
        return
    _broadcast(f"unsudo: sudo rights for {user} have been restored.")
