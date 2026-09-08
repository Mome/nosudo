from datetime import datetime, timedelta

from unsudo import state
from unsudo.cli import main
from unsudo.runner import Runner


def test_status_empty(unsudo_dirs, capsys):
    assert main(["status"]) == 0
    assert "No active restrictions." in capsys.readouterr().out


def test_restrict_dry_run_changes_nothing(unsudo_dirs, capsys):
    rc = main(["--dry-run", "restrict", "alice", "--for", "1h"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "[dry-run]" in out
    # Nothing was actually written.
    assert not state.exists("alice")


def test_restrict_rejects_when_already_restricted(unsudo_dirs, capsys):
    runner = Runner(dry_run=False)
    now = datetime.now().astimezone()
    state.write(state.build("alice", now, now + timedelta(hours=1)), runner)

    rc = main(["--dry-run", "restrict", "alice", "--for", "1h"])
    assert rc == 1
    assert "already restricted" in capsys.readouterr().err


def test_extend_is_lengthen_only(unsudo_dirs, capsys):
    runner = Runner(dry_run=False)
    now = datetime.now().astimezone()
    # Current lift is far in the future.
    state.write(state.build("alice", now, now + timedelta(hours=10)), runner)

    # Trying to set a sooner lift time must be rejected.
    rc = main(["--dry-run", "extend", "alice", "--for", "1m"])
    assert rc == 1
    assert "lengthen-only" in capsys.readouterr().err


def test_extend_requires_active_restriction(unsudo_dirs, capsys):
    rc = main(["--dry-run", "extend", "ghost", "--for", "1h"])
    assert rc == 1
    assert "not currently restricted" in capsys.readouterr().err


def test_status_lists_active(unsudo_dirs, capsys):
    runner = Runner(dry_run=False)
    now = datetime.now().astimezone()
    state.write(state.build("alice", now, now + timedelta(hours=2)), runner)

    assert main(["status"]) == 0
    out = capsys.readouterr().out
    assert "alice: restricted" in out
