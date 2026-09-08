#!/usr/bin/env bash
# Open a shell in the VM, or run a command: `vm/ssh.sh [cmd...]`
set -euo pipefail
source "$(dirname "$0")/lib.sh"
vm_ssh "$@"
