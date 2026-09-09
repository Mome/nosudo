#!/usr/bin/env bash
# Bring up a fresh provisioned VM: download base image (cached), make a clean
# overlay, build the cloud-init seed, boot, and wait until nosudo is installed.
set -euo pipefail
source "$(dirname "$0")/lib.sh"

mkdir -p "$WORK"

if [ ! -f "$BASE_IMG" ]; then
  echo ".. downloading Debian cloud image (once)…"
  wget -q --show-progress -O "$BASE_IMG" "$IMG_URL"
fi

# Tear down any previous instance and start from a clean overlay every time.
vm_poweroff
rm -f "$OVERLAY"
qemu-img create -q -f qcow2 -F qcow2 -b "$BASE_IMG" "$OVERLAY" >/dev/null
qemu-img resize -q "$OVERLAY" +4G >/dev/null   # room for python + uv

build_seed
echo ".. booting VM (ssh on port $SSH_PORT)…"
launch_vm

wait_ssh
provision_nosudo
echo "VM is up and nosudo is installed."
echo "  shell:   vm/ssh.sh"
echo "  run e2e: vm/e2e.sh"
echo "  destroy: vm/down.sh"
