import pytest

from unsudo import config


@pytest.fixture
def unsudo_dirs(tmp_path, monkeypatch):
    """Redirect all on-disk artifact dirs into a temp tree."""
    state = tmp_path / "state"
    sudoers = tmp_path / "sudoers.d"
    systemd = tmp_path / "systemd"
    for d in (state, sudoers, systemd):
        d.mkdir()
    monkeypatch.setattr(config, "STATE_DIR", state)
    monkeypatch.setattr(config, "SUDOERS_DIR", sudoers)
    monkeypatch.setattr(config, "SYSTEMD_DIR", systemd)
    return tmp_path
