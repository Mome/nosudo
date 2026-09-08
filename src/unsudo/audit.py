"""``check``: audit the alternative paths to root from specs.md §7.

v1 audits the cheaply-readable vectors: root-equivalent / sudo-granting group
membership, whether root has a usable password, ``PermitRootLogin``, and
pre-existing root sessions. Anything not cheaply checkable is reported
``unknown`` ("not checked"). Read-only; never mutates.
"""

from __future__ import annotations

import grp
import pwd
from dataclasses import dataclass
from pathlib import Path

from . import sessions

# Groups that grant (effectively) root, and the sudo-granting groups.
ROOT_EQUIVALENT_GROUPS = ("docker", "lxd", "incus", "disk", "kvm", "libvirt")
SUDO_GROUPS = ("sudo", "wheel", "admin")

OPEN = "open"
CLOSED = "closed"
UNKNOWN = "unknown"


@dataclass
class Finding:
    vector: str
    status: str  # OPEN / CLOSED / UNKNOWN
    detail: str


def user_groups(user: str) -> set[str]:
    info = pwd.getpwnam(user)
    names = {grp.getgrgid(info.pw_gid).gr_name}
    names.update(g.gr_name for g in grp.getgrall() if user in g.gr_mem)
    return names


def _check_groups(groups: set[str]) -> list[Finding]:
    findings = []
    risky = groups & set(ROOT_EQUIVALENT_GROUPS)
    findings.append(
        Finding(
            "root-equivalent groups",
            OPEN if risky else CLOSED,
            f"member of {sorted(risky)}" if risky else "none",
        )
    )
    sudo_groups = groups & set(SUDO_GROUPS)
    findings.append(
        Finding(
            "sudo-granting groups",
            OPEN if sudo_groups else CLOSED,
            f"member of {sorted(sudo_groups)}" if sudo_groups else "none",
        )
    )
    return findings


def _check_root_password() -> Finding:
    try:
        for line in Path("/etc/shadow").read_text().splitlines():
            if line.startswith("root:"):
                hashed = line.split(":")[1]
                if hashed and not hashed.startswith(("!", "*")):
                    return Finding("root password", OPEN, "root has a usable password (su)")
                return Finding("root password", CLOSED, "root login disabled")
        return Finding("root password", UNKNOWN, "no root entry found")
    except PermissionError:
        return Finding("root password", UNKNOWN, "not checked (needs root to read /etc/shadow)")
    except OSError:
        return Finding("root password", UNKNOWN, "not checked")


def _sshd_files() -> list[Path]:
    files = [Path("/etc/ssh/sshd_config")]
    files.extend(sorted(Path("/etc/ssh/sshd_config.d").glob("*.conf")))
    return files


def _check_root_ssh() -> Finding:
    value = None
    for path in _sshd_files():
        try:
            for line in path.read_text().splitlines():
                stripped = line.strip()
                if stripped.lower().startswith("permitrootlogin"):
                    value = stripped.split(None, 1)[1].strip().lower()
        except OSError:
            continue
    if value is None:
        return Finding("root SSH login", UNKNOWN, "PermitRootLogin not set (distro default)")
    if value == "no":
        return Finding("root SSH login", CLOSED, "PermitRootLogin no")
    return Finding("root SSH login", OPEN, f"PermitRootLogin {value}")


def _check_root_sessions(user: str) -> Finding:
    found = sessions.detect_root_sessions(user)
    if found:
        return Finding("existing root sessions", OPEN, "; ".join(found))
    return Finding("existing root sessions", CLOSED, "none detected")


def check(user: str) -> list[Finding]:
    try:
        groups = user_groups(user)
    except KeyError:
        return [Finding("user", UNKNOWN, f"no such user {user!r}")]
    findings = _check_groups(groups)
    findings.append(_check_root_password())
    findings.append(_check_root_ssh())
    findings.append(_check_root_sessions(user))
    return findings


def open_findings(findings: list[Finding]) -> list[Finding]:
    return [f for f in findings if f.status == OPEN]
