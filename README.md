# nosudo

A small CLI that **revokes a user's `sudo` rights for a bounded period and restores them
automatically** — in a way that survives reboots and crashes. Built for *self-control*: once you
drop your own sudo you also lose the ability to edit the restore timer, so you can't give the
rights back early.

See [specs.md](specs.md) for the full specification and the decisions behind it, and
[implementation-plan.md](implementation-plan.md) for the design.

## How it works

- The restriction is a deny drop-in at `/etc/sudoers.d/zz-nosudo-<user>` (`<user> ALL=(ALL) !ALL`).
  It is on disk, so a reboot does not lift it.
- The restore is a systemd timer + oneshot service in `/etc/systemd/system`, using an absolute
  `OnCalendar` time and `Persistent=true`. So a reboot doesn't reset the countdown, and if the
  machine was off when restore was due, it runs on next boot.

## Usage

`nosudo` is a user tool; `restrict`/`extend`/`restore` prompt for your password (they re-exec
under `sudo`). You don't need to type `sudo` yourself.

```sh
nosudo restrict --for 2h               # restrict yourself for 2 hours (prompts for password)
nosudo restrict alice --until 18:00
nosudo status                          # no password needed — see when rights return
nosudo extend --for 30m                # lengthen only (never shorten)
nosudo restore                         # manual early restore (idempotent)
nosudo check                           # audit other ways you could still reach root
nosudo restrict --for 2h --dry-run     # show what would happen, change nothing
```

The automatic restore at lift time needs no password — it runs as a root-owned systemd timer.

## Installation

```sh
pipx install git+https://github.com/mome/nosudo.git
```
in case you prefere uv

```sh
uv tool install git+https://github.com/mome/nosudo.git
```

## Development

This project uses [`uv`](https://docs.astral.sh/uv/):

```sh
uv sync
uv run pytest
uv run ruff check .
uv run mypy
uv run nosudo --help
```

CI (`.github/workflows/ci.yml`) runs the above on every push/PR. The VM e2e suite
(`.github/workflows/e2e.yml`) needs KVM and a base-image download, so it runs weekly and
on-demand rather than per-PR — see [vm/README.md](vm/README.md).
