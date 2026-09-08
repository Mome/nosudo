#!/usr/bin/env bash
# End-to-end test of unsudo inside the VM. Assumes `vm/up.sh` has run.
#
# IMPORTANT: privileged actions (restrict/restore/inspect) are driven as ROOT,
# because once `tester` is restricted it has no sudo — so we can neither inspect
# root-only files as tester nor self-restore. We drive as root and only OBSERVE
# tester's sudo state (the thing under test).
#
# Phases:
#   1. functional      — restrict applies + sudo revoked + timer ARMED
#                        (the lockout-bug regression) + restore restores.
#   2. reboot          — restriction + armed timer survive a reboot.
#   3. missed-downtime — power off before lift, boot with the RTC past the lift;
#                        Persistent=true fires the restore on boot. unsudo is
#                        uninstalled first to prove the restore is self-contained.
set -uo pipefail
source "$(dirname "$0")/lib.sh"

PASS=0; FAIL=0
ok()  { echo "  PASS: $1"; PASS=$((PASS+1)); }
bad() { echo "  FAIL: $1"; FAIL=$((FAIL+1)); }
r_ok() { if vm_root "$2" >/dev/null 2>&1; then ok "$1"; else bad "$1"; fi; }  # root cmd must succeed
r_no() { if vm_root "$2" >/dev/null 2>&1; then bad "$1"; else ok "$1"; fi; }  # root cmd must fail
u_ok() { if vm_ssh  "$2" >/dev/null 2>&1; then ok "$1"; else bad "$1"; fi; }  # tester cmd must succeed
u_no() { if vm_ssh  "$2" >/dev/null 2>&1; then bad "$1"; else ok "$1"; fi; }  # tester cmd must fail

DENY=/etc/sudoers.d/zz-unsudo-tester
TIMER=unsudo-restore-tester.timer
# "armed" = timer active AND has a real next trigger (not n/a). This catches the
# lockout bug, where a ghost timer is "active" but has no scheduled elapse.
ARMED="systemctl is-active --quiet $TIMER && test \"\$(systemctl show -p NextElapseUSecRealtime --value $TIMER)\" != n/a"

echo "== Phase 0: sanity =="
r_ok "root ssh works (test driver)"             "true"
u_ok "tester has sudo before any restriction"   "sudo -n true"
r_ok "guest clock is UTC (needed for RTC test)" 'test "$(date +%Z)" = UTC'

echo "== Phase 1: functional + armed-timer regression =="
r_ok "restrict tester --for 30m"                "$UNSUDO restrict tester --for 30m"
r_ok "deny drop-in present"                     "test -f $DENY"
u_no "tester sudo is now denied"                "sudo -n true"
r_ok "restore timer is ARMED (NextElapse>0)"    "$ARMED"
r_ok "restore tester"                           "$UNSUDO restore tester"
r_no "deny drop-in gone after restore"          "test -f $DENY"
u_ok "tester sudo works again"                  "sudo -n true"
r_no "timer unit gone after restore"            "systemctl cat $TIMER"

echo "== Phase 2: survives reboot =="
r_ok "restrict tester --for 30m"                "$UNSUDO restrict tester --for 30m"
echo "  .. rebooting VM"
vm_root "systemctl reboot" >/dev/null 2>&1 || true
sleep 5; wait_ssh || { echo "VM did not come back"; exit 1; }
r_ok "still restricted after reboot"            "test -f $DENY"
u_no "tester sudo still denied after reboot"    "sudo -n true"
r_ok "timer still ARMED after reboot"           "$ARMED"
r_ok "restore after reboot"                     "$UNSUDO restore tester"
r_no "deny gone"                                "test -f $DENY"
u_ok "tester sudo restored"                     "sudo -n true"

echo "== Phase 3: missed-downtime (Persistent) + decoupling =="
# Compute times IN THE GUEST (UTC) to avoid host-timezone reinterpretation.
T="$(vm_root 'date -u -d "+2 minutes" +%Y-%m-%dT%H:%M')"
BASE="$(vm_root 'date -u -d "+6 minutes" +%Y-%m-%dT%H:%M:%S')"
echo "  .. lift(UTC)=$T  reboot-RTC(UTC)=$BASE"
r_ok "restrict tester --until $T"               "$UNSUDO restrict tester --until $T"
r_ok "deny present before downtime"             "test -f $DENY"
r_ok "restore timer armed"                       "$ARMED"
echo "  .. uninstalling unsudo to prove restore is self-contained"
vm_ssh "$UV tool uninstall unsudo" >/dev/null 2>&1 || true
u_no "unsudo is gone"                            "test -x $UNSUDO"

echo "  .. powering off, then booting with RTC past the lift time"
vm_poweroff
launch_vm "-rtc" "base=$BASE,clock=rt"
wait_ssh || { echo "VM did not come back"; exit 1; }

restored=1
for _ in $(seq 1 20); do
  if ! vm_root "test -f $DENY" 2>/dev/null; then restored=0; break; fi
  sleep 2
done
[ "$restored" -eq 0 ] && ok "deny removed on boot by Persistent timer (unsudo absent)" \
                      || bad "restore did NOT fire on boot — deny still present"
r_no "timer unit cleaned up"                     "systemctl cat $TIMER"
u_ok "tester has sudo back"                       "sudo -n true"

echo
echo "==================  $PASS passed, $FAIL failed  =================="
[ "$FAIL" -eq 0 ]
