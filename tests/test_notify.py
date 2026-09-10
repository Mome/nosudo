from types import SimpleNamespace

from nosudo import notify


def _record_runs(monkeypatch, *, has_notify_send=True, has_sudo=True):
    calls = []

    def fake_which(name):
        if name == "notify-send":
            return "/usr/bin/notify-send" if has_notify_send else None
        if name == "sudo":
            return "/usr/bin/sudo" if has_sudo else None
        return None

    monkeypatch.setattr(notify.shutil, "which", fake_which)
    monkeypatch.setattr(
        notify.subprocess, "run", lambda args, **kw: calls.append(list(args)) or None
    )
    return calls


def _fake_uid(monkeypatch, uid=1000):
    monkeypatch.setattr(notify.pwd, "getpwnam", lambda user: SimpleNamespace(pw_uid=uid))


def test_skipped_when_user_unknown(monkeypatch):
    calls = _record_runs(monkeypatch)

    def raise_key_error(user):
        raise KeyError(user)

    monkeypatch.setattr(notify.pwd, "getpwnam", raise_key_error)
    notify._broadcast("ghost", "hello")
    assert not calls


def test_skipped_without_active_session(monkeypatch):
    calls = _record_runs(monkeypatch)
    _fake_uid(monkeypatch)
    monkeypatch.setattr(notify.Path, "exists", lambda self: False)
    notify._broadcast("alice", "hello")
    assert not calls


def test_skipped_without_notify_send(monkeypatch):
    calls = _record_runs(monkeypatch, has_notify_send=False)
    _fake_uid(monkeypatch)
    monkeypatch.setattr(notify.Path, "exists", lambda self: True)
    notify._broadcast("alice", "hello")
    assert not calls


def test_sent_to_target_users_session_bus(monkeypatch):
    calls = _record_runs(monkeypatch)
    _fake_uid(monkeypatch, uid=1000)
    monkeypatch.setattr(notify.Path, "exists", lambda self: True)
    notify._broadcast("alice", "hello")
    assert len(calls) == 1
    cmd = calls[0]
    assert cmd[:3] == ["sudo", "-u", "alice"]
    assert "DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/1000/bus" in cmd
    assert "XDG_RUNTIME_DIR=/run/user/1000" in cmd
    assert cmd[-3:] == ["notify-send", "nosudo", "hello"]
