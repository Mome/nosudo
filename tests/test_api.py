from datetime import datetime, timedelta

import pytest

from nosudo import api, audit, state
from nosudo.runner import Runner


def test_status_empty(nosudo_dirs):
    assert api.status() == []


def test_status_lists_active(nosudo_dirs):
    runner = Runner(dry_run=False)
    now = datetime.now().astimezone()
    state.write(state.build("alice", now, now + timedelta(hours=2)), runner)

    records = api.status()
    assert [r.user for r in records] == ["alice"]


def test_restrict_dry_run_changes_nothing(nosudo_dirs):
    lift_at = datetime.now().astimezone() + timedelta(hours=1)

    api.restrict("alice", lift_at, Runner(dry_run=True))

    assert not state.exists("alice")


def test_restrict_rejects_when_already_restricted(nosudo_dirs):
    runner = Runner(dry_run=False)
    now = datetime.now().astimezone()
    state.write(state.build("alice", now, now + timedelta(hours=1)), runner)

    with pytest.raises(api.CommandError, match="already restricted"):
        api.restrict("alice", now + timedelta(hours=2), Runner(dry_run=True))


def test_restrict_uses_real_runner_by_default(nosudo_dirs):
    # No runner passed -> defaults to a real (non-dry-run) Runner(). Exercise
    # the "already restricted" rejection path, which raises before any
    # sudoers/systemd writes happen, so this stays safe without root.
    now = datetime.now().astimezone()
    state.write(state.build("alice", now, now + timedelta(hours=1)), Runner())

    with pytest.raises(api.CommandError, match="already restricted"):
        api.restrict("alice", now + timedelta(hours=2))


def test_extend_requires_active_restriction(nosudo_dirs):
    lift_at = datetime.now().astimezone() + timedelta(hours=1)
    with pytest.raises(api.CommandError, match="not currently restricted"):
        api.extend("ghost", lift_at, Runner(dry_run=True))


def test_extend_is_lengthen_only(nosudo_dirs):
    runner = Runner(dry_run=False)
    now = datetime.now().astimezone()
    state.write(state.build("alice", now, now + timedelta(hours=10)), runner)

    with pytest.raises(api.CommandError, match="lengthen-only"):
        api.extend("alice", now + timedelta(minutes=1), Runner(dry_run=True))


def test_restore_is_idempotent(nosudo_dirs):
    runner = Runner(dry_run=False)
    now = datetime.now().astimezone()
    state.write(state.build("alice", now, now + timedelta(hours=1)), runner)

    api.restore("alice", runner)
    assert not state.exists("alice")

    # Second call tolerates already-removed state instead of raising.
    api.restore("alice", runner)


def test_check_returns_findings_for_unknown_user(nosudo_dirs):
    findings = api.check("no-such-user-xyz")
    assert findings == [
        audit.Finding("user", audit.UNKNOWN, "no such user 'no-such-user-xyz'")
    ]
