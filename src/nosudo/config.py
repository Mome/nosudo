"""Filesystem paths and naming helpers.

The directory paths are module-level so tests can monkeypatch them onto temp
directories. Production code always reads them through this module.
"""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

# Locations of the on-disk artifacts (see specs.md §2 / implementation-plan §2).
STATE_DIR = Path("/var/lib/nosudo")
SUDOERS_DIR = Path("/etc/sudoers.d")
SYSTEMD_DIR = Path("/etc/systemd/system")

# Fallback used when we cannot resolve our own absolute path at runtime.
DEFAULT_EXECUTABLE = "/usr/local/bin/nosudo"


def sudoers_file(user: str) -> Path:
    # ``zz-`` so the drop-in loads last and its deny wins (sudo = last match).
    return SUDOERS_DIR / f"zz-nosudo-{user}"


def service_name(user: str) -> str:
    return f"nosudo-restore-{user}.service"


def timer_name(user: str) -> str:
    return f"nosudo-restore-{user}.timer"


def service_path(user: str) -> Path:
    return SYSTEMD_DIR / service_name(user)


def timer_path(user: str) -> Path:
    return SYSTEMD_DIR / timer_name(user)


def state_file(user: str) -> Path:
    return STATE_DIR / f"{user}.json"


def restore_script(user: str) -> Path:
    # Root-owned 0700 script run by the systemd service at lift time. Self-
    # contained (coreutils only) so restore never depends on nosudo/python.
    return STATE_DIR / f"restore-{user}.sh"


def safe_exists(path: Path) -> bool:
    """``path.exists()`` that returns False when the parent isn't readable.

    Non-root callers (e.g. ``--dry-run``) cannot stat inside ``/etc/sudoers.d``;
    treat "can't tell" as "not present" so previews still work.
    """
    try:
        return path.exists()
    except OSError:
        return False


def executable() -> str:
    """Absolute path to the ``nosudo`` entry point for the systemd unit.

    Resolve dynamically so the installed unit points at wherever nosudo really
    lives; fall back to a conventional path if resolution fails.
    """
    found = shutil.which("nosudo")
    if found:
        return str(Path(found).resolve())
    argv0 = Path(sys.argv[0])
    if argv0.name == "nosudo" and argv0.exists():
        return str(argv0.resolve())
    return DEFAULT_EXECUTABLE
