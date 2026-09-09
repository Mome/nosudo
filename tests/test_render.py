from datetime import datetime

from nosudo import scheduler, sudoers


def test_sudoers_render_denies_user():
    lift = datetime(2026, 6, 12, 18, 0).astimezone()
    content = sudoers.render("alice", lift)
    assert "alice ALL=(ALL) !ALL" in content
    assert "Managed by nosudo" in content


def test_service_render_points_at_self_contained_script():
    content = scheduler.render_service("alice")
    assert "Type=oneshot" in content
    # Service runs the root-owned restore script, NOT nosudo itself.
    assert "restore-alice.sh" in content
    assert "nosudo restore" not in content


def test_restore_script_is_self_contained():
    content = scheduler.render_restore_script("alice")
    assert content.startswith("#!/bin/sh")
    # Critical step: give sudo back by deleting the deny drop-in, no python/nosudo.
    assert "rm -f /etc/sudoers.d/zz-nosudo-alice" in content
    # Must `stop` the timer, not just `disable` it, or a ghost unit lingers.
    assert "systemctl stop nosudo-restore-alice.timer" in content
    assert "systemctl daemon-reload" in content
    # It must not invoke the nosudo executable.
    assert "nosudo restore" not in content
    assert "nosudo extend" not in content


def test_timer_render_is_persistent_and_absolute():
    lift = datetime(2026, 6, 12, 18, 0, 0).astimezone()
    content = scheduler.render_timer("alice", lift)
    assert "OnCalendar=2026-06-12 18:00:00" in content
    assert "Persistent=true" in content
    assert "WantedBy=timers.target" in content
