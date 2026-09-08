from datetime import datetime, timedelta

from unsudo import scheduler
from unsudo.runner import Runner


def test_install_restarts_timer_to_rearm(unsudo_dirs, capsys):
    """install must `restart` the timer, not `enable --now`.

    `enable --now` is a no-op on an already-running timer of the same name, which
    would leave a stale schedule and skip the restore entirely (the lockout bug).
    """
    lift = datetime.now().astimezone() + timedelta(minutes=5)
    scheduler.install("alice", lift, Runner(dry_run=True))
    out = capsys.readouterr().out
    assert "systemctl restart unsudo-restore-alice.timer" in out
    assert "enable --now" not in out
