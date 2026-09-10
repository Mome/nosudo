"""The reboot/crash-safe restore trigger: a systemd timer + oneshot service.

The timer uses an absolute ``OnCalendar`` plus ``Persistent=true`` so that a
reboot does not reset it and a trigger missed while the machine was off fires on
next boot (specs.md §3). Units live in ``/etc/systemd/system`` so they survive
reboot.

The service does **not** run ``nosudo``. Instead it runs a self-contained,
root-owned ``0700`` shell script generated at restrict time, using only
coreutils + systemctl. This means restore works even if nosudo/python/the venv
is broken or uninstalled by lift time, and root never executes user-writable
code (specs.md §6).
"""

from __future__ import annotations

from datetime import datetime

from . import config
from .runner import Runner
from .timeparse import format_oncalendar

UNIT_MODE = 0o644
SCRIPT_MODE = 0o700


def render_restore_script(user: str) -> str:
    sudoers = config.sudoers_file(user)
    state_f = config.state_file(user)
    script = config.restore_script(user)
    timer = config.timer_name(user)
    timer_p = config.timer_path(user)
    service_p = config.service_path(user)
    return (
        "#!/bin/sh\n"
        f"# Managed by nosudo. Restores sudo for {user}. Root-owned; do not edit.\n"
        "# Critical step first; everything else is best-effort cleanup.\n"
        f"rm -f {sudoers}\n"
        # `stop` (not just `disable`) so the running timer is dropped from memory;
        # `disable` alone only removes the enablement symlink and leaves a ghost.
        f"systemctl stop {timer} 2>/dev/null || true\n"
        f"systemctl disable {timer} 2>/dev/null || true\n"
        f"rm -f {timer_p} {service_p}\n"
        f"rm -f {state_f} {script}\n"
        "systemctl daemon-reload 2>/dev/null || true\n"
    )


def render_service(user: str) -> str:
    return (
        "[Unit]\n"
        f"Description=nosudo: restore sudo for {user}\n"
        "\n"
        "[Service]\n"
        "Type=oneshot\n"
        f"ExecStart={config.restore_script(user)}\n"
    )


def render_timer(user: str, lift_at: datetime) -> str:
    return (
        "[Unit]\n"
        f"Description=nosudo: restore timer for {user}\n"
        "\n"
        "[Timer]\n"
        f"OnCalendar={format_oncalendar(lift_at)}\n"
        "Persistent=true\n"
        "\n"
        "[Install]\n"
        "WantedBy=timers.target\n"
    )


def install(user: str, lift_at: datetime, runner: Runner) -> None:
    runner.write_file(
        config.restore_script(user), render_restore_script(user), mode=SCRIPT_MODE
    )
    runner.write_file(config.service_path(user), render_service(user), mode=UNIT_MODE)
    runner.write_file(
        config.timer_path(user), render_timer(user, lift_at), mode=UNIT_MODE
    )
    runner.run(["systemctl", "daemon-reload"])
    runner.run(["systemctl", "enable", config.timer_name(user)])
    # `restart` (not `enable --now`) so a pre-existing/active timer of the same
    # name is re-armed with the new OnCalendar. `enable --now` is a no-op on an
    # already-running unit and would leave the schedule stale -> no restore.
    runner.run(["systemctl", "restart", config.timer_name(user)])


def update_timer(user: str, lift_at: datetime, runner: Runner) -> None:
    """Rewrite only the timer's schedule (used by ``extend``)."""
    runner.write_file(
        config.timer_path(user), render_timer(user, lift_at), mode=UNIT_MODE
    )
    runner.run(["systemctl", "daemon-reload"])
    runner.run(["systemctl", "restart", config.timer_name(user)])


def remove(user: str, runner: Runner) -> None:
    """Disable and delete the units + restore script. Tolerant of missing state."""
    runner.run(
        ["systemctl", "disable", "--now", config.timer_name(user)], check=False
    )
    runner.remove_file(config.timer_path(user))
    runner.remove_file(config.service_path(user))
    runner.remove_file(config.restore_script(user))
    runner.run(["systemctl", "daemon-reload"], check=False)


def is_active(user: str) -> bool:
    return config.safe_exists(config.timer_path(user))
