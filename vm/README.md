# unsudo VM test harness

End-to-end validation of unsudo on a **real QEMU/KVM VM** — the only way to test the
reboot- and crash-safety that unit tests and `--dry-run` can't cover.

## Why a VM (not a container)
The missed-downtime test needs to simulate "the machine was off when the restore was due."
That requires a real boot cycle and a manipulable clock; `systemd-nspawn` shares the host
`CLOCK_REALTIME` and can't do it faithfully. So: a full VM.

## Requirements (host)
- `qemu-system-x86_64`, `qemu-img`, KVM (`/dev/kvm`)
- a cloud-init **seed-ISO builder**: one of `cloud-image-utils` (`cloud-localds`), `xorriso`,
  or `genisoimage`. On Arch: `sudo pacman -S xorriso`.

## Usage
```sh
vm/up.sh        # download image (cached), boot, provision unsudo (first boot ~few min)
vm/e2e.sh       # run all phases; prints "<n> passed, <n> failed"
vm/ssh.sh       # interactive shell in the VM (or: vm/ssh.sh 'some command')
vm/down.sh      # power off + remove the per-run overlay
```

## What the e2e asserts
1. **functional** — `restrict` applies the deny drop-in, `sudo` is denied, and the restore
   timer is **armed** (`NextElapse > 0`); `restore` cleans everything up. The armed-timer check
   is the regression guard for the lockout bug (a stale timer that never fires).
2. **reboot** — restriction + armed timer survive `reboot`.
3. **missed-downtime + decoupling** — `restrict --until T`, **uninstall unsudo**, power off,
   then boot with `-rtc base=<past T>`. `Persistent=true` must fire the root-owned restore
   script on boot even with unsudo gone, removing the deny file and cleaning up.

## How the clock trick works
The guest runs in UTC. The e2e reads the guest's clock, sets the lift time a couple of minutes
out, powers the VM off, then relaunches QEMU with `-rtc base=<several minutes later>`. The guest
boots believing it is already past the lift time, so systemd treats the timer as having elapsed
during downtime and runs the restore immediately — deterministic, no real waiting.

## Notes
- Everything lives under `vm/.work/` (gitignored): the cached base image, per-run overlay, seed
  ISO, ssh keypair, and `serial.log`. Inspect boot/provisioning via `serial.log` or
  `vm/ssh.sh 'cloud-init status --long'`.
- The host repo is mounted read-only over 9p at `/mnt/unsudo` and installed with
  `uv tool install --editable`, so the VM tests the same code you're editing.
- `tester` has passwordless sudo **only so the e2e can run unattended**; it does not reflect the
  real self-control UX (where `restrict` prompts for a password).
