"""Per-user state records under ``/var/lib/unsudo/<user>.json``.

The file is root-owned but world-readable (0644) so the blocked user can read
their own lift time without the sudo they just gave up (specs.md §5).
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import datetime

from . import config
from .runner import Runner

STATE_MODE = 0o644


@dataclass
class Restriction:
    user: str
    created_at: str  # ISO-8601, local tz
    lift_at: str  # ISO-8601, local tz
    sudoers_file: str
    timer_unit: str
    service_unit: str
    version: int = 1

    @property
    def lift_dt(self) -> datetime:
        return datetime.fromisoformat(self.lift_at)


def build(user: str, created_at: datetime, lift_at: datetime) -> Restriction:
    return Restriction(
        user=user,
        created_at=created_at.isoformat(),
        lift_at=lift_at.isoformat(),
        sudoers_file=str(config.sudoers_file(user)),
        timer_unit=config.timer_name(user),
        service_unit=config.service_name(user),
    )


def write(record: Restriction, runner: Runner) -> None:
    if not runner.dry_run:
        config.STATE_DIR.mkdir(parents=True, exist_ok=True)
    content = json.dumps(asdict(record), indent=2) + "\n"
    runner.write_file(config.state_file(record.user), content, mode=STATE_MODE)


def read(user: str) -> Restriction | None:
    path = config.state_file(user)
    if not path.exists():
        return None
    data = json.loads(path.read_text())
    return Restriction(**data)


def remove(user: str, runner: Runner) -> None:
    runner.remove_file(config.state_file(user))


def exists(user: str) -> bool:
    return config.safe_exists(config.state_file(user))


def list_all() -> list[Restriction]:
    if not config.STATE_DIR.exists():
        return []
    records = []
    for path in sorted(config.STATE_DIR.glob("*.json")):
        try:
            records.append(Restriction(**json.loads(path.read_text())))
        except (json.JSONDecodeError, TypeError, OSError):
            continue
    return records


def update_lift_time(record: Restriction, lift_at: datetime, runner: Runner) -> None:
    record.lift_at = lift_at.isoformat()
    write(record, runner)
