# unsudo — Implementation Plan (v1)

Implements the specification in [specs.md](specs.md). v1 scope: revoke **sudo** for a bounded
time with a reboot/crash-safe restore. `extend` is root-only; self-service extend, leak-closing,
and non-sudo restrictions are out of scope (see specs §8).

---

## 1. Tech & layout

- **Language:** Python 3 (stdlib only where possible; `subprocess` for `systemctl`/`visudo`).
- **Tooling:** `uv` for env/deps/running (`uv run`, `uv add`, `uv sync`); committed `uv.lock`. No
  bare `pip`/`venv`/`pipx`. See [CLAUDE.md](CLAUDE.md).
- **Packaging:** `pyproject.toml` with a console-script entry point `unsudo = unsudo.cli:main`.
- **Install model:** a **user tool** — `uv tool install --editable .` (lands in `~/.local/bin`).
  Not installed as root.
- **Privilege:** `restrict`/`extend`/`restore` self-elevate by re-exec under `sudo` when not root
  (prompts for a password); `status`/`check` need no privilege.
- **Unattended restore is decoupled from unsudo:** the systemd service runs a generated root-owned
  `0700` coreutils script, never `unsudo` — robust even if the user-installed tool/venv is broken
  at lift time.

```
specs.md
implementation-plan.md
pyproject.toml
README.md
src/unsudo/
  __init__.py
  cli.py          # argparse, --dry-run, sudo self-elevation, dispatch
  config.py       # artifact paths + naming; executable(); safe_exists()
  runner.py       # dry-run-aware command/file execution
  timeparse.py    # --for / --until -> absolute aware datetime
  sudoers.py      # render/validate/install/remove the deny drop-in
  scheduler.py    # render/install/remove timer+service + root-owned restore script
  state.py        # read/write /var/lib/unsudo/<user>.json; status listing
  sessions.py     # sudo -K + warn on existing privileged sessions
  notify.py       # best-effort wall / notify-send
  audit.py        # `check`: enumerate open root-access vectors
tests/
  conftest.py         # unsudo_dirs fixture (temp artifact dirs)
  test_timeparse.py
  test_render.py      # sudoers + unit + restore-script rendering
  test_state.py       # state (de)serialization, listing, lift-time update
  test_cli.py         # status, dry-run, lengthen-only extend, guards
```

---

## 2. On-disk artifacts

| Artifact       | Path                                      | Mode | Owner | Notes                                  |
|----------------|-------------------------------------------|------|-------|----------------------------------------|
| Deny drop-in   | `/etc/sudoers.d/zz-unsudo-<user>`         | 0440 | root  | `zz-` => loads last, last-match-wins.   |
| State file     | `/var/lib/unsudo/<user>.json`             | 0644 | root  | World-readable so blocked user reads it.|
| Restore script | `/var/lib/unsudo/restore-<user>.sh`       | 0700 | root  | Coreutils-only; what the service runs.  |
| Restore timer  | `/etc/systemd/system/unsudo-restore-<user>.timer`   | 0644 | root | `OnCalendar` + `Persistent=true`. |
| Restore svc    | `/etc/systemd/system/unsudo-restore-<user>.service` | 0644 | root | `Type=oneshot`, runs the script. |

**Deny drop-in content**
```
# Managed by unsudo. Do not edit. Auto-restores at <lift_at>.
<user> ALL=(ALL) !ALL
```

**State schema**
```json
{
  "version": 1,
  "user": "alice",
  "created_at": "2026-06-12T16:00:00+02:00",
  "lift_at": "2026-06-12T18:00:00+02:00",
  "sudoers_file": "/etc/sudoers.d/zz-unsudo-alice",
  "timer_unit": "unsudo-restore-alice.timer",
  "service_unit": "unsudo-restore-alice.service"
}
```

**Restore script** (`/var/lib/unsudo/restore-alice.sh`, root-owned 0700)
```sh
#!/bin/sh
# Managed by unsudo. Root-owned; do not edit. Critical step first.
rm -f /etc/sudoers.d/zz-unsudo-alice
systemctl disable unsudo-restore-alice.timer 2>/dev/null || true
rm -f /etc/systemd/system/unsudo-restore-alice.timer /etc/systemd/system/unsudo-restore-alice.service
rm -f /var/lib/unsudo/alice.json /var/lib/unsudo/restore-alice.sh
systemctl daemon-reload 2>/dev/null || true
command -v wall >/dev/null 2>&1 && echo "unsudo: sudo rights for alice have been restored." | wall || true
```

**Service unit** (runs the script, not unsudo)
```
[Unit]
Description=unsudo: restore sudo for alice
[Service]
Type=oneshot
ExecStart=/var/lib/unsudo/restore-alice.sh
```

**Timer unit**
```
[Unit]
Description=unsudo: restore timer for alice
[Timer]
OnCalendar=2026-06-12 18:00:00
Persistent=true
[Install]
WantedBy=timers.target
```

---

## 3. Command flows

**Elevation (centralized in `main`):** for `restrict`/`extend`/`restore`, if not `--dry-run` and
`euid != 0`, re-exec under `sudo` (`os.execvp("sudo", [exe, *raw_argv])`) — prompts for a password,
does not return on success. After elevation the flows below run as root.

### `restrict [<user>] (--for D | --until T)`
0. Resolve target: explicit `<user>`, else the invoking user via `SUDO_USER`.
1. `timeparse` -> absolute aware `lift_at`; reject past/invalid times.
2. If already restricted (state file or deny file present): refuse, point to `extend`.
3. `audit.check(user)`; if any leak is **open**: print a warning listing them, then **continue**
   (warn-and-proceed; no `--force` gate).
4. `sudoers.install`: write atomically to a temp file, `visudo -cf <temp>`, then move into place 0440.
5. `sessions.lock(user)`: `sudo -K -u <user>` (clear cached timestamp). If the user has existing
   root sessions, **warn** but do not kill them. Failures here are warnings, not fatal.
6. `state.write(user, ...)` (0644).
7. `scheduler.install`: write the root-owned `0700` restore script + service+timer, `daemon-reload`,
   `enable --now` the timer.
8. `notify.start(user, lift_at)` (best-effort).
9. On failure between 4–7: best-effort rollback so the user is never "restricted with no restore."

### `extend <user> (--for D | --until T)`  *(root-only in v1)*
1. Require an active restriction.
2. Compute new `lift_at`; **require `new >= current`** (lengthen-only) else refuse.
3. Rewrite timer `OnCalendar`, `daemon-reload`, `restart` the timer, update state file.

### `restore <user>`  *(manual early restore; idempotent)*
- The unattended lift-time restore is the **root-owned script**, not this command. This is for
  manual/admin early restore. Each step tolerates "already gone":
1. `scheduler.remove` (disable + delete units **and the restore script**, `daemon-reload`).
2. `sudoers.remove` (delete deny file if present).
3. `state.remove`.
4. `notify.end(user)` (best-effort). Running twice is a clean no-op.

### `status`  *(non-privileged, read-only)*
- List every `/var/lib/unsudo/*.json`; print `user — lifts at <lift_at> (<remaining> left)`.
- Cross-check the timer's next-elapse where readable; note drift if any.

### `check [<user>]`  *(non-privileged, read-only)*
- Report per vector whether the leak is **open**: group membership (`docker`/`disk`/`lxd`/`wheel`/
  `sudo` via `id`/`getent`), root password set, `PermitRootLogin`, pre-existing root sessions
  (`loginctl`/`who`). Vectors not cheaply checkable are labeled "not checked." Non-destructive.

---

## 4. Key implementation notes

- **timeparse:** `--for` accepts `90m`, `2h`, `1h30m`, `3d`; `--until` accepts `HH:MM` (today/next
  occurrence) and ISO `YYYY-MM-DDTHH:MM`. Normalize everything to a tz-aware local `datetime`;
  `OnCalendar` is rendered in local time (matches systemd default). Document the DST caveat.
- **subprocess wrapper:** one helper that, under `--dry-run`, prints the command and the file
  contents it would write instead of executing — enables full testing without root.
- **atomicity:** sudoers and unit files written to a temp file then `os.replace`d; `visudo -cf`
  gates the sudoers file before it goes live.
- **rollback:** `restrict` tracks what it created and undoes it on any later-step failure.

---

## 5. Verification

- **Unit:** `uv run pytest` — `timeparse`, sudoers/unit rendering, state round-trip, the
  `extend` monotonic invariant. No root needed.
- **Dry run:** `unsudo restrict alice --for 2h --dry-run` prints sudoers + units, touches nothing.
- **End-to-end (disposable VM, throwaway user):**
  1. `unsudo restrict testuser --for 2m` (as a sudo-capable user) -> prompts for password via the
     self-elevation, then deny file present, `sudo -l -U testuser` shows deny, `sudo` refused as
     testuser; `systemctl list-timers | grep unsudo` shows the absolute elapse.
  2. `unsudo status` as **testuser** (no sudo) prints the lift time -> confirms non-priv read.
  3. **Decoupling test:** confirm the service `ExecStart` is the root-owned script (not unsudo);
     uninstall unsudo, then verify restore still fires (the script has no unsudo/python dependency).
  4. **Reboot test:** `--for 10m`, reboot now -> still restricted after boot, timer still scheduled.
  5. **Missed-downtime test:** `--for 2m`, power off before elapse, boot after lift time ->
     `Persistent=true` runs the script on boot (deny gone, units/script cleaned, `status` empty).
  6. **extend:** `unsudo extend testuser --for 30m` moves lift later; verify a sooner time is refused.
  7. **Idempotency:** `unsudo restore testuser` twice -> second run is a clean no-op.

### VM harness (built — see `vm/`)

A real **QEMU/KVM VM** (not a container) because the reboot/missed-downtime tests need a true boot
cycle and a manipulable clock (nspawn shares the host `CLOCK_REALTIME`).

- **Layout:** `vm/lib.sh` (shared config + qemu/ssh helpers), `vm/up.sh`, `vm/e2e.sh`, `vm/ssh.sh`,
  `vm/down.sh`, `vm/cloud-init/{user-data,meta-data}`, `vm/README.md`. Artifacts in `vm/.work/`.
- **Base:** Debian 12 *generic cloud* qcow2; cloud-init creates `tester` (passwordless sudo, for
  unattended runs), installs `uv`, mounts the host repo read-only over **9p** at `/mnt/unsudo`, and
  `uv tool install --editable`s it. SSH via `hostfwd tcp::2222-:22`.
- **e2e phases:** (1) functional incl. the **armed-timer regression** (`NextElapse > 0`) that guards
  the lockout bug; (2) survives reboot; (3) **missed-downtime via the RTC trick** —
  `restrict --until T`, **uninstall unsudo**, power off, relaunch with `-rtc base=<past T>`;
  `Persistent=true` must fire the root-owned restore script on boot with unsudo gone (also proves
  decoupling).
- **Reset:** clean qcow2 overlay over a cached base each `up`.
- **Run:** `vm/up.sh && vm/e2e.sh`. **Host prereq:** a seed-ISO builder (`xorriso` /
  `cloud-image-utils` / `genisoimage`) — not yet installed; on Arch `sudo pacman -S xorriso`.
