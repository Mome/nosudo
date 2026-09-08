#!/usr/bin/env bash
# Shared configuration + helpers for the unsudo VM test harness.
# Sourced by up.sh / e2e.sh / down.sh.

set -euo pipefail

# --- paths & config --------------------------------------------------------
VM_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(cd "$VM_DIR/.." && pwd)"
WORK="$VM_DIR/.work"

IMG_URL="https://cloud.debian.org/images/cloud/bookworm/latest/debian-12-genericcloud-amd64.qcow2"
BASE_IMG="$WORK/debian-base.qcow2"     # cached download
OVERLAY="$WORK/disk.qcow2"             # per-run overlay (clean each `up`)
SEED="$WORK/seed.iso"
SSH_KEY="$WORK/id_ed25519"
SERIAL_LOG="$WORK/serial.log"
MONITOR="$WORK/monitor.sock"
PIDFILE="$WORK/qemu.pid"

SSH_PORT="${SSH_PORT:-2222}"
MEM="${MEM:-2048}"
CPUS="${CPUS:-2}"

# unsudo is installed for `tester`; call it by absolute path (self-elevates).
UNSUDO="/home/tester/.local/bin/unsudo"
UV="/home/tester/.local/bin/uv"

SSH_OPTS=(-i "$SSH_KEY" -p "$SSH_PORT"
  -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null
  -o LogLevel=ERROR -o ConnectTimeout=5)

# --- ssh / control ---------------------------------------------------------
# vm_ssh  -> as `tester` (the restricted subject; used to OBSERVE sudo state)
# vm_root -> as `root`   (the test driver; runs unsudo + inspects root files)
vm_ssh()  { ssh "${SSH_OPTS[@]}" tester@127.0.0.1 "$@"; }
vm_root() { ssh "${SSH_OPTS[@]}" root@127.0.0.1 "$@"; }

vm_running() { [ -f "$PIDFILE" ] && kill -0 "$(cat "$PIDFILE")" 2>/dev/null; }

vm_poweroff() {
  if vm_running; then
    vm_ssh "sudo poweroff" >/dev/null 2>&1 || true
    for _ in $(seq 1 60); do vm_running || return 0; sleep 1; done
    kill "$(cat "$PIDFILE")" 2>/dev/null || true
  fi
  return 0
}

wait_ssh() {
  local tries="${1:-120}"
  for _ in $(seq 1 "$tries"); do
    if vm_ssh true 2>/dev/null; then return 0; fi
    sleep 2
  done
  echo "!! timed out waiting for ssh; see $SERIAL_LOG" >&2
  return 1
}

# The Debian cloud kernel has no 9p, so we can't share the repo over virtfs.
# Instead copy it into the guest over ssh (tar stream) and install editable.
provision_unsudo() {
  echo ".. ensuring uv is installed in the guest"
  vm_ssh 'test -x ~/.local/bin/uv || (curl -LsSf https://astral.sh/uv/install.sh | sh -s -- -q || wget -qO- https://astral.sh/uv/install.sh | sh -s -- -q)'
  echo ".. copying repo into the guest (~/unsudo)"
  tar czf - -C "$REPO_DIR" \
      --exclude=.git --exclude=.venv --exclude=vm/.work \
      --exclude=__pycache__ --exclude='*.pyc' --exclude=.pytest_cache . \
    | vm_ssh 'rm -rf ~/unsudo && mkdir -p ~/unsudo && tar xzf - -C ~/unsudo'
  echo ".. installing unsudo as an editable uv tool"
  vm_ssh "$UV tool install --reinstall --editable ~/unsudo"
  vm_ssh "test -x $UNSUDO"
}

# --- seed (cloud-init NoCloud ISO) -----------------------------------------
build_seed() {
  mkdir -p "$WORK"
  [ -f "$SSH_KEY" ] || ssh-keygen -t ed25519 -N "" -f "$SSH_KEY" -q
  local pub; pub="$(cat "$SSH_KEY.pub")"
  sed "s|__SSH_PUBKEY__|$pub|" "$VM_DIR/cloud-init/user-data" > "$WORK/user-data"
  cp "$VM_DIR/cloud-init/meta-data" "$WORK/meta-data"

  if command -v cloud-localds >/dev/null 2>&1; then
    cloud-localds "$SEED" "$WORK/user-data" "$WORK/meta-data"
  elif command -v xorriso >/dev/null 2>&1; then
    xorriso -as mkisofs -output "$SEED" -volid cidata -joliet -rock \
      "$WORK/user-data" "$WORK/meta-data" >/dev/null 2>&1
  elif command -v genisoimage >/dev/null 2>&1; then
    genisoimage -output "$SEED" -volid cidata -joliet -rock \
      "$WORK/user-data" "$WORK/meta-data" >/dev/null 2>&1
  else
    echo "!! need a seed-ISO builder: install one of cloud-image-utils / xorriso / genisoimage" >&2
    echo "   Arch:  sudo pacman -S xorriso" >&2
    exit 1
  fi
}

# --- qemu launch -----------------------------------------------------------
# launch_vm [extra qemu args...]  — boots the EXISTING overlay (no reset), so it
# can be called again after vm_poweroff (e.g. with a different -rtc base).
launch_vm() {
  qemu-system-x86_64 \
    -enable-kvm -machine q35 -cpu host -smp "$CPUS" -m "$MEM" \
    -drive file="$OVERLAY",if=virtio,format=qcow2 \
    -drive file="$SEED",if=virtio,format=raw,readonly=on \
    -netdev user,id=net0,hostfwd=tcp::"$SSH_PORT"-:22 \
    -device virtio-net-pci,netdev=net0 \
    -display none -serial file:"$SERIAL_LOG" \
    -monitor unix:"$MONITOR",server,nowait \
    -pidfile "$PIDFILE" -daemonize \
    "$@"
}
