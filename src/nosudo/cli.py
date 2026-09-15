"""Command-line interface and command flows.

Commands (specs.md §5): restrict, extend (root-only), restore, status, check.
A global ``--dry-run`` routes all mutations through the Runner's print path.
"""

from __future__ import annotations

import argparse
import getpass
import os
import sys

from . import api, config
from .api import CommandError
from .runner import Runner
from .sudoers import SudoersError
from .timeparse import TimeParseError, format_remaining, resolve_lift_time

# Commands that mutate privileged state and therefore need root.
ROOT_COMMANDS = {"restrict", "extend", "restore"}


def resolve_user(arg: str | None) -> str:
    """Default to the invoking user (SUDO_USER) per specs.md §5."""
    user = arg or os.environ.get("SUDO_USER") or getpass.getuser()
    if not user:
        raise CommandError("could not determine target user; pass it explicitly")
    return user


def reexec_with_sudo(raw_argv: list[str]) -> None:
    """Re-run ourselves under ``sudo`` (which prompts for a password).

    Used when a root command is invoked by a non-root user. Self-control is not
    weakened: this only fires at bind time while the user still has sudo; once
    restricted they have no sudo, so a later self-``restore`` simply fails to
    elevate. Does not return on success (replaces the process image).
    """
    exe = config.executable()
    print("nosudo needs root for this; re-running under sudo…", file=sys.stderr)
    try:
        os.execvp("sudo", ["sudo", exe, *raw_argv])
    except OSError as exc:  # sudo missing/unavailable
        raise CommandError(f"could not elevate via sudo: {exc}") from exc


# -- commands --------------------------------------------------------------
def cmd_restrict(args: argparse.Namespace, runner: Runner) -> None:
    user = resolve_user(args.user)
    lift_at = resolve_lift_time(for_=args.for_, until=args.until)
    api.restrict(user, lift_at, runner)
    runner.info(
        f"{user}: sudo restricted until {lift_at.strftime('%Y-%m-%d %H:%M')} "
        f"({format_remaining(lift_at)} from now)"
    )


def cmd_extend(args: argparse.Namespace, runner: Runner) -> None:
    user = resolve_user(args.user)
    new_lift = resolve_lift_time(for_=args.for_, until=args.until)
    api.extend(user, new_lift, runner)
    runner.info(
        f"{user}: lift time extended to {new_lift.strftime('%Y-%m-%d %H:%M')} "
        f"({format_remaining(new_lift)} from now)"
    )


def cmd_restore(args: argparse.Namespace, runner: Runner) -> None:
    user = resolve_user(args.user)
    api.restore(user, runner)
    runner.info(f"{user}: sudo rights restored")


def cmd_status(args: argparse.Namespace, runner: Runner) -> None:
    records = api.status()
    if not records:
        runner.info("No active restrictions.")
        return
    for r in records:
        runner.info(
            f"{r.user}: restricted — lifts at "
            f"{r.lift_dt.strftime('%Y-%m-%d %H:%M')} "
            f"({format_remaining(r.lift_dt, include_seconds=True)} left)"
        )


def cmd_check(args: argparse.Namespace, runner: Runner) -> None:
    user = resolve_user(args.user)
    findings = api.check(user)
    width = max(len(f.vector) for f in findings)
    runner.info(f"Root-access audit for {user}:")
    for f in findings:
        runner.info(f"  {f.vector.ljust(width)}  {f.status.upper():7}  {f.detail}")


# -- parser ----------------------------------------------------------------
def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="nosudo",
        description="Time-boxed, reboot/crash-safe revocation of a user's sudo rights.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="print intended actions without changing the system",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    def add_time_args(p: argparse.ArgumentParser) -> None:
        group = p.add_mutually_exclusive_group(required=True)
        group.add_argument("--for", dest="for_", metavar="DURATION",
                           help="relative duration, e.g. 90m, 2h, 1h30m, 3d")
        group.add_argument("--until", metavar="TIME",
                           help="absolute time, e.g. 18:00 or 2026-06-12T18:00")

    p_restrict = sub.add_parser("restrict", help="revoke a user's sudo for a bounded time")
    p_restrict.add_argument("user", nargs="?", help="target user (default: invoking user)")
    add_time_args(p_restrict)
    p_restrict.set_defaults(func=cmd_restrict)

    p_extend = sub.add_parser("extend", help="lengthen an active restriction (root-only)")
    p_extend.add_argument("user", nargs="?", help="target user (default: invoking user)")
    add_time_args(p_extend)
    p_extend.set_defaults(func=cmd_extend)

    p_restore = sub.add_parser("restore", help="restore sudo now (idempotent)")
    p_restore.add_argument("user", nargs="?", help="target user (default: invoking user)")
    p_restore.set_defaults(func=cmd_restore)

    p_status = sub.add_parser("status", help="show active restrictions and lift times")
    p_status.set_defaults(func=cmd_status)

    p_check = sub.add_parser("check", help="audit alternative paths to root")
    p_check.add_argument("user", nargs="?", help="target user (default: invoking user)")
    p_check.set_defaults(func=cmd_check)

    return parser


def main(argv: list[str] | None = None) -> int:
    raw_argv = list(sys.argv[1:] if argv is None else argv)
    parser = build_parser()
    args = parser.parse_args(argv)
    runner = Runner(dry_run=getattr(args, "dry_run", False))

    # Self-elevate for privileged commands (prompts for a password). Skipped
    # under --dry-run and when already root.
    if args.command in ROOT_COMMANDS and not runner.dry_run and os.geteuid() != 0:
        try:
            reexec_with_sudo(raw_argv)
        except CommandError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 1

    try:
        args.func(args, runner)
    except (CommandError, TimeParseError, SudoersError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
