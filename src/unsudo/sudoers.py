"""The sudo restriction itself: a deny drop-in in ``/etc/sudoers.d``.

An explicit ``<user> ALL=(ALL) !ALL`` in a late-loading (``zz-``) file wins by
sudo's last-match rule. Being a file on disk, it survives reboot, so a reboot
cannot be used to escape the restriction (specs.md §3).
"""

from __future__ import annotations

import subprocess
from datetime import datetime
from pathlib import Path

from . import config
from .runner import Runner

SUDOERS_MODE = 0o440


class SudoersError(RuntimeError):
    pass


def render(user: str, lift_at: datetime) -> str:
    return (
        "# Managed by unsudo. Do not edit.\n"
        f"# Auto-restores at {lift_at.isoformat()}.\n"
        f"{user} ALL=(ALL) !ALL\n"
    )


def _validate(tmp: Path) -> None:
    result = subprocess.run(
        ["visudo", "-cf", str(tmp)],
        text=True,
        capture_output=True,
    )
    if result.returncode != 0:
        raise SudoersError(
            f"visudo rejected the generated sudoers file: {result.stderr.strip()}"
        )


def install(user: str, lift_at: datetime, runner: Runner) -> None:
    runner.write_file(
        config.sudoers_file(user),
        render(user, lift_at),
        mode=SUDOERS_MODE,
        validate=_validate,
    )


def remove(user: str, runner: Runner) -> None:
    runner.remove_file(config.sudoers_file(user))


def is_active(user: str) -> bool:
    return config.safe_exists(config.sudoers_file(user))
