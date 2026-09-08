from datetime import datetime, timedelta

from unsudo import config, state
from unsudo.runner import Runner


def test_state_round_trip(unsudo_dirs):
    runner = Runner(dry_run=False)
    created = datetime(2026, 6, 12, 16, 0).astimezone()
    lift = created + timedelta(hours=2)
    record = state.build("alice", created, lift)
    state.write(record, runner)

    assert state.exists("alice")
    loaded = state.read("alice")
    assert loaded == record
    assert loaded.lift_dt == lift

    # File is world-readable so the blocked user can read their own lift time.
    mode = config.state_file("alice").stat().st_mode & 0o777
    assert mode == 0o644


def test_list_all_and_remove(unsudo_dirs):
    runner = Runner(dry_run=False)
    now = datetime.now().astimezone()
    for name in ("alice", "bob"):
        state.write(state.build(name, now, now + timedelta(hours=1)), runner)

    users = {r.user for r in state.list_all()}
    assert users == {"alice", "bob"}

    state.remove("alice", runner)
    assert not state.exists("alice")
    assert {r.user for r in state.list_all()} == {"bob"}


def test_update_lift_time(unsudo_dirs):
    runner = Runner(dry_run=False)
    now = datetime.now().astimezone()
    record = state.build("alice", now, now + timedelta(hours=1))
    state.write(record, runner)

    new_lift = now + timedelta(hours=3)
    state.update_lift_time(record, new_lift, runner)
    assert state.read("alice").lift_dt == new_lift
