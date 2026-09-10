from nosudo import notify


def _record_runs(monkeypatch):
    calls = []
    monkeypatch.setattr(notify.shutil, "which", lambda name: f"/usr/bin/{name}")
    monkeypatch.setattr(
        notify.subprocess, "run", lambda args, **kw: calls.append(list(args)) or None
    )
    return calls


def test_notify_send_skipped_without_session_bus(monkeypatch):
    calls = _record_runs(monkeypatch)
    monkeypatch.delenv("DBUS_SESSION_BUS_ADDRESS", raising=False)
    notify._broadcast("hello")
    cmds = [c[0] for c in calls]
    # No notify-send => no futile dbus-launch and no leaked error output.
    assert "notify-send" not in cmds
    assert not cmds


def test_notify_send_used_with_session_bus(monkeypatch):
    calls = _record_runs(monkeypatch)
    monkeypatch.setenv("DBUS_SESSION_BUS_ADDRESS", "unix:abstract=test")
    notify._broadcast("hello")
    cmds = [c[0] for c in calls]
    assert "notify-send" in cmds
