# unsudo — Specification

> A CLI tool that **restricts a user's privileges for a bounded period of time** and
> automatically restores them afterwards. The restore is **reboot- and crash-safe**.

This document is the living specification. It records *what* the software does and *every
important decision together with the reason for it*. It is updated as the design evolves.

---

## 1. Goal

Provide a command-line program that can temporarily strip a user of certain rights and give
them back automatically at a chosen time, in a way that cannot be defeated by rebooting or by
the machine crashing.

**Scope (current):** the only restricted right is **sudo access**, implemented through a
systemd timer that removes sudo rights now and restores them later.

The design is intended to generalize to other kinds of restrictions later, but only sudo is in
scope today.

### Primary use case: self-control (Ulysses contract)

The tool's primary purpose is **self-binding** — a user voluntarily removes their own sudo
rights to enforce discipline, and cannot give them back early.

This works because of a self-reinforcing property: **`unsudo` needs root to alter the
restriction (the deny file and timer units are root-owned in root-only directories), so once a
user's sudo is removed they have also lost the ability to delete the deny file or disable the
restore timer.** The same privilege being surrendered is the one required to undo the surrender.
The automatic restore is unaffected because the systemd timer fires as **root (the system
manager)**, independent of the user's sudo.

Consequence: for the *restricted person*, self-control mode and "administering someone else"
mode are nearly identical. The binding holds **only under the assumption that sudo is the user's
sole path to root** (see Threat model below).

---

## 2. Core requirements

| # | Requirement                                                                                  |
|---|----------------------------------------------------------------------------------------------|
| 1 | A CLI program restricts a given user's rights for a given duration.                          |
| 2 | First restriction type: remove the user's sudo rights.                                       |
| 3 | Rights are restored automatically at a later time via a systemd timer.                       |
| 4 | The whole mechanism must be **reboot-safe** — a reboot must not lose the scheduled restore.  |
| 5 | The mechanism must be **crash-safe** — if the machine is off when restore is due, it must    |
|   | still happen (at the next boot at the latest).                                               |
| 6 | A reboot must **not** be an escape hatch — the restriction stays applied until restore time. |

---

## 3. How reboot / crash safety works

Safety rests on two pieces of **on-disk** state, both of which survive reboot:

1. **The restriction itself** is a file: `/etc/sudoers.d/zz-unsudo-<user>` containing an explicit
   deny rule. Because it is a file on disk, the restriction remains in force across reboots until
   it is deleted — satisfying requirement #6 (rebooting is not an escape hatch).

2. **The restore trigger** is a real systemd `.timer` + `.service` unit pair installed in
   `/etc/systemd/system/`, using:
   - `OnCalendar=<absolute wall-clock timestamp>` — an *absolute realtime* schedule (not a
     monotonic countdown), so a reboot does not reset it.
   - `Persistent=true` — if the trigger time passed while the machine was powered off, systemd
     runs the restore service **immediately on next boot**. This is the crash-safety guarantee
     (requirement #5).

The restore service does **not** run `unsudo`. It runs a self-contained, root-owned `0700` shell
script (`/var/lib/unsudo/restore-<user>.sh`) generated at restrict time, using only coreutils +
`systemctl`. Its first action is the safety-critical one — `rm -f` the deny drop-in — followed by
best-effort cleanup of the units, state file and itself. This means restore works **even if
unsudo / python / the venv is broken, edited, or uninstalled** by lift time, and root never
executes user-writable code. (See §6 for why this matters: unsudo is a *user-installed* tool.)

The restore action is **idempotent**: delete the sudoers file, delete the state record, disable
and remove the units and script, reload systemd. Running it more than once is harmless.

A per-user **state file** at `/var/lib/unsudo/<user>.json` records the restore time, creation
time, and the managed file/unit paths, so status can be reported and restore can clean up
deterministically.

---

## 4. Threat model

The adversary is the **user themselves in a moment of weakness** — someone trying to give their
own rights back *before* the restore time. The tool aims to make that as hard as relinquishing
root, not to defend against a sophisticated attacker with physical access.

The self-binding holds **only if sudo is the user's only path to root**. Known escape hatches,
and how they are handled:

| Escape hatch                                  | Handling                                                                       |
|-----------------------------------------------|--------------------------------------------------------------------------------|
| Cached sudo credentials after `restrict`      | **Not a hole** — sudo re-checks the sudoers *policy* on every call (it caches    |
|   (timestamp)                                 | authentication, not authorization), so the deny is immediate. No action needed. |
| Already-open root shell at restrict time      | **The real residual risk.** A root shell started before the restriction keeps   |
|                                               | root until closed; we **warn** about it (killing is deferred).                  |
| `su` with a known root password               | Out of tool scope; documented. User must not know/keep a usable root password.  |
| `pkexec` / polkit, root SSH, other SUID paths | Out of tool scope; documented assumption that these are not available.          |
| Physical access (GRUB `init=/bin/bash`,       | **Cannot be prevented by software.** Requires BIOS/GRUB password + full-disk    |
|   live USB, mount disk, delete file)          | encryption to mitigate; explicitly out of scope, documented as a limitation.    |

**The one real difference vs. administering someone else:** an admin keeps a *separate,
unaffected* privileged account — an external override. Self-control keeps none by design, which
makes it strictly more binding. The tool therefore does not need a different code path for the
two modes.

> **Correction (validated in the VM e2e):** an earlier design assumed a cached sudo timestamp
> created a ~15-minute self-undo window that `restrict` had to close with `sudo -K`. That was
> wrong — sudo re-evaluates the sudoers policy on every invocation, so the deny is effective
> immediately. The VM test confirms it: `tester` has *passwordless* sudo yet is denied the instant
> the deny drop-in is written. The `sudo -K` step (which was also malformed) was removed.

---

## 5. Command surface

| Command                                       | Description                                                       |
|-----------------------------------------------|------------------------------------------------------------------|
| `unsudo restrict <user> --for <duration>`     | Restrict for a relative duration, e.g. `--for 2h`, `--for 90m`.  |
| `unsudo restrict <user> --until <timestamp>`  | Restrict until an absolute time, e.g. `--until 18:00`.           |
| `unsudo extend <user> --for/--until <t>`      | Lengthen an active restriction (≥ current lift time). Root-only. |
| `unsudo restore <user>`                       | Manually restore early (root). The unattended restore is a script, not this. |
| `unsudo status`                               | Show active restrictions, the absolute lift time, and time left. |
| `unsudo check <user>`                         | Audit the §7 root-access vectors and report which leaks are open.|
| `--dry-run` (global flag)                     | Show intended sudoers/unit actions without changing the system.  |

If `<user>` is omitted, the **invoking user** (`SUDO_USER`) is the target — ergonomic for the
primary self-control use case. An explicit `<user>` is still accepted for administering others.

### Installation & privilege

`unsudo` is a **user-installed tool** (`uv tool install --editable .`), not installed as root.
The privileged commands (`restrict`, `extend`, `restore`) **self-elevate**: when run by a non-root
user they re-exec under `sudo`, which prompts for a password. This is good UX and does **not**
weaken self-control — the prompt only succeeds at *bind time*, when the user still has sudo; once
restricted they have no sudo, so trying to self-`restore` early simply fails to elevate. The
unattended restore needs no password (systemd runs it as root). `status` and `check` need no
privilege at all.

Because unsudo is user-installed (and its source is therefore user-writable), the unattended
restore is deliberately **decoupled from unsudo**: see the root-owned restore script in §3.

Behavior when the user is already restricted: refuse with a clear message (`extend` is the
intended way to change an active restriction; see below).

### `extend` semantics (lengthen-only)

`unsudo extend <user>` changes the lift time of an **active** restriction. It is **monotonic and
lengthen-only**: the new lift time must be **≥ the current one**. Rationale:
- **Lengthening** tightens the contract — it can never be used to cheat, only to punish more —
  so it is always safe, even for the blocked user.
- **Shortening** would loosen the contract (early escape) and is therefore disallowed in
  self-control mode. It is also *naturally* prevented, since rewriting the root-owned timer needs
  root the blocked user no longer has.

**Can a blocked user extend their own block?** Not in v1: `extend` modifies the root-owned timer
and sudoers files, and the blocked user has no sudo. v1 `extend` is therefore **root-only**.

**Planned (later):** a *self-service lengthen-only* path via one narrow privileged hook — a
tightly-scoped `sudoers` NOPASSWD entry (or a small setuid helper) allowing **only**
`unsudo extend`, with the binary enforcing `new_time ≥ current_time`. This grants a one-line sudo
rule precisely while general sudo is removed, which is consistent with the self-control model.
Deferred because any privileged helper is attack surface (a bug could set an earlier time or exec
as root) and needs careful validation.

### Checking when the block lifts

A restricted user has no sudo, but must still be able to see when their rights return **without
any privilege**. Therefore:
- `unsudo status` is **read-only and non-privileged** — runnable by the restricted user.
  It prints the absolute lift time and remaining time, e.g.
  `alice: restricted — lifts at 2026-06-12 18:00 (2h 13m left)`.
- It derives this from the per-user state file plus the systemd timer's next-elapse.
- As a fallback that needs neither root nor `unsudo`, the schedule is visible via
  `systemctl list-timers unsudo-restore-<user>.timer`.

### `unsudo check`

Read-only audit of the alternative-root vectors in §7 (group membership such as `docker`/`disk`/
`lxd`, set root password, SUID/capability binaries, root SSH, pre-existing root sessions, etc.).
It reports, per vector, whether that leak is currently **open** for the target user, so the user
understands how binding a restriction would actually be.

`restrict` runs the same audit automatically: if any leak is open it **warns and lists them but
still proceeds** (no `--force` required). Rationale: surface the false-confidence risk (a contract
the user can trivially undo via `docker` or `su`) without blocking the common case; the user
decides whether the open leaks matter.

### Notifications

The affected user is notified when a restriction **starts** and when it **ends**:
- **Start:** emitted by `restrict` after the restriction is in place.
- **End:** emitted by the restore service/`restore` command after rights are returned (this also
  covers the crash-recovery case where restore fires on next boot).

Delivery uses best-effort local channels (e.g. `wall`, and `notify-send` to the user's desktop
session if present); failure to notify never blocks or fails the restrict/restore action itself.

---

## 6. Decisions and rationale

| Decision                         | Choice                                  | Why                                                                                                   |
|----------------------------------|-----------------------------------------|-------------------------------------------------------------------------------------------------------|
| Language / runtime               | Python 3                                | Fast to write; calling `systemctl`/`visudo` via subprocess is trivial; Python is present on Linux.    |
| Sudo removal mechanism           | `/etc/sudoers.d` deny drop-in           | Takes effect immediately for already-running sessions; group removal only affects new logins.         |
| Restriction persistence          | A file on disk in `/etc/sudoers.d`      | Survives reboot, so a reboot cannot be used to escape the restriction.                                 |
| Scheduling mechanism             | Persistent systemd timer (`OnCalendar`) | On-disk unit + absolute time + `Persistent=true` => survives reboot and fires after missed downtime.  |
| Rejected scheduling alternatives | not `systemd-run --on-active`, not `at` | Transient/monotonic timers reset on reboot; `at`/atd may be absent and is not reboot-persistent.       |
| Time input                       | accept duration OR absolute time        | Convenience; both are normalized to a single absolute restore timestamp that is persisted/scheduled.   |
| Install model                    | user tool (`uv tool install -e`)        | Not installed as root; lives in `~/.local`. Keeps install simple; the root-run restore is decoupled (below).|
| Privilege model                  | self-elevate via `sudo` (prompts)       | `restrict`/`extend`/`restore` re-exec under `sudo` when not root; better UX than manual `sudo unsudo`.   |
| Elevation doesn't weaken binding | prompt only at bind time                | The user has sudo when restricting; once restricted they have no sudo, so self-`restore` fails to elevate.|
| Restore is unsudo-independent    | root-owned `0700` coreutils script      | Restore must not depend on user-writable code/python/venv at lift time (robustness) and root must not run |
|                                  |                                         | user-writable code (hygiene). Generated at restrict time; systemd runs the script, not `unsudo`.        |
| Timer must be re-armed           | `enable` + `restart`, not `enable --now`| `--now` is a no-op on an already-active timer of the same name → stale schedule → **no restore (lockout)**.|
| Restore script stops the timer   | `systemctl stop` before removing units  | `disable` only removes the symlink; a running timer must be stopped or it lingers as a not-found ghost.  |
| Self-binding enforcement         | root-owned deny file + units + script   | Losing sudo also removes the ability to edit them, so the contract is self-reinforcing (no extra guard).|
| No timestamp invalidation        | warn on root sessions only              | sudo re-checks policy each call, so the deny is immediate — no `sudo -K` needed (earlier `sudo -K`       |
|                                  |                                         | decision was wrong *and* malformed; removed). Pre-existing root shells are warned about, not killed.     |
| Default target = invoking user   | `<user>` optional, defaults to SUDO_USER| Self-control is the primary use case; explicit `<user>` still supported for admin mode.                  |
| Open leaks don't block restrict  | warn-and-proceed, no `--force`          | Surface false-confidence risk without friction; the user judges whether the open leaks matter.          |
| Same code path for both modes    | no separate "admin" vs "self" logic     | For the restricted user the modes are identical; the only difference (a separate admin account) is external.|
| `unsudo check` audit             | planned feature, also auto-run          | A contract trivially undoable via `docker`/`su` gives false confidence; surface open leaks before committing.|
| Notifications                    | best-effort, non-blocking               | User should know when a restriction starts/ends; but notification failure must never block restrict/restore.|
| `extend` is lengthen-only        | new lift time must be ≥ current         | Lengthening only tightens the contract (safe); shortening would be an early escape and is disallowed.    |
| `extend` is root-only in v1      | self-service lengthen deferred          | Modifying root-owned units needs root; a constrained self-service hook is attack surface, deferred.      |
| Restore idempotency              | required                                | Persistent timer, manual restore, and boot reconciliation can race; an idempotent restore is safe.     |
| State location                   | `/var/lib/unsudo/<user>.json`           | Standard location for variable program state; lets `status` and restore work deterministically.        |
| State file is user-readable      | mode `0644` (root-owned, world-read)    | The restricted user has no sudo but must still read their own lift time; only root may write it.        |
| `status` is non-privileged       | no root required, read-only             | The whole point is the blocked user can check when rights return without the rights they just gave up.  |
| Command naming caveat            | command is `unsudo`                     | Note: name clashes with the PyPI BDD tool `unsudo`; acceptable for local install, flagged for awareness.|

---

## 7. Alternative paths to root (reference for future versions)

The current version only revokes `sudo`. The self-binding therefore leaks if the user has any
*other* route to root. The table below catalogues those routes so a later, more thorough version
can detect and/or close them. **None of these are handled today** — they are documented so the
user knows what the v1 guarantee does and does not cover.

### Local software / configuration

| Vector                                    | Why it grants root                                              | Possible future mitigation                                  |
|-------------------------------------------|----------------------------------------------------------------|-------------------------------------------------------------|
| `su` to root                              | Direct root shell if the root password is known.               | Lock root account (`passwd -l root`) / detect a set root pw.|
| `pkexec` / polkit                         | polkit can grant admin actions independently of sudoers.       | Add a deny polkit rule for the user during restriction.     |
| SUID-root binaries                        | Any SUID-root binary (incl. exploitable ones) can elevate.     | `find / -perm -4000` audit; warn on unexpected SUID bins.   |
| File capabilities (`cap_setuid`, etc.)    | A capability-endowed binary can elevate without SUID.          | `getcap -r /` audit at restrict time.                       |
| Other `sudoers`/`sudoers.d` NOPASSWD rules| A separate grant elsewhere may still match before our deny.    | Parse full sudoers; warn if other grants for the user exist.|
| Writable sudoers / unit dirs              | If the user can write `/etc/sudoers.d` or unit dirs, they undo.| Verify directory ownership/permissions before relying on it.|

### Group membership = root-equivalent

| Group                                     | Why it grants root                                             | Possible future mitigation                                  |
|-------------------------------------------|---------------------------------------------------------------|-------------------------------------------------------------|
| `docker`                                  | Can mount the host filesystem in a container → full root.     | Temporarily remove from `docker` group during restriction.  |
| `lxd` / `incus`                           | Same idea via container/VM management.                        | Temporarily remove from the group.                          |
| `disk`                                    | Raw block-device access → read/write any file incl. shadow.   | Temporarily remove from the group.                          |
| `wheel` / `sudo` / `admin`                | The sudo-granting groups themselves.                          | Also remove from these as belt-and-suspenders to the deny.   |
| `kvm` / `libvirt`                         | VM access can be leveraged to reach host root in some setups. | Audit / document.                                           |

### Sessions, credentials, scheduling

| Vector                                    | Why it grants root                                            | Possible future mitigation                                  |
|-------------------------------------------|--------------------------------------------------------------|-------------------------------------------------------------|
| Cached sudo timestamp                     | **Not a vector** — sudo re-checks policy each call; deny is immediate. | n/a (verified in VM e2e).                          |
| Pre-existing root shell / tmux / screen   | A root session opened before restriction keeps root.         | v1 **warns**; enumerate-and-terminate is future work.       |
| Root SSH / authorized_keys                | Logging in as root over SSH bypasses local sudo entirely.    | Check `PermitRootLogin` / root's authorized_keys; document. |
| Another local account with sudo           | Lateral move: log into a second privileged account.          | Out of scope; single-user assumption documented.            |
| root's crontab / `at` jobs                | Jobs in root's crontab run as root (user crontab does not).  | Only relevant if the user can already edit root's crontab.  |

### Physical / boot (cannot be fixed in software)

| Vector                                    | Why it grants root                                           | Mitigation (out of tool scope)                              |
|-------------------------------------------|-------------------------------------------------------------|-------------------------------------------------------------|
| GRUB edit → `init=/bin/bash`, single-user | Boots a root shell, bypassing all userspace restrictions.   | GRUB password.                                              |
| Live USB / external boot, mount disk      | Mount the disk from another OS and delete the deny file.    | Full-disk encryption + BIOS/boot-order lock.                |
| Disk snapshots / backups / VM host        | Restore or edit the filesystem from outside the running OS. | Out of scope; depends on environment.                       |

Note: local kernel privilege-escalation exploits are an inherent risk for any local restriction
and are explicitly out of scope.

---

## 8. Open questions / future work

- Self-service *lengthen-only* `extend` for the blocked user (constrained sudoers/setuid hook),
  so they can add time to their own block without restoring general sudo.
- Restriction types beyond sudo (general framework).
- Actually *closing* §7 leaks during a restriction (e.g. temporarily removing `docker`/`disk`
  group membership), not just reporting them via `unsudo check`.
