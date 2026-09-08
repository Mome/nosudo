#!/usr/bin/env bash
# Power off the VM and remove the per-run overlay (keeps the cached base image).
set -euo pipefail
source "$(dirname "$0")/lib.sh"
vm_poweroff
rm -f "$OVERLAY"
echo "VM down; overlay removed (base image cached at $BASE_IMG)."
