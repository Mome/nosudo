"""Side-effect execution with a uniform ``--dry-run`` gate.

Every mutation in nosudo (running a command, writing a managed file) goes
through a ``Runner`` so that ``--dry-run`` can print intended actions instead of
performing them, and so logging is consistent.
"""

from __future__ import annotations

import os
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path


class Runner:
    def __init__(self, dry_run: bool = False) -> None:
        self.dry_run = dry_run

    # -- logging -----------------------------------------------------------
    def info(self, msg: str) -> None:
        print(msg)

    def warn(self, msg: str) -> None:
        print(f"warning: {msg}", file=sys.stderr)

    # -- command execution -------------------------------------------------
    def run(
        self,
        args: list[str],
        *,
        check: bool = True,
        always: bool = False,
        capture: bool = False,
    ) -> subprocess.CompletedProcess | None:
        """Run a command.

        ``always=True`` runs even under ``--dry-run`` (use for read-only probes
        such as audits/status). Mutating commands are skipped and printed when
        ``--dry-run`` is set.
        """
        if self.dry_run and not always:
            self.info(f"[dry-run] would run: {' '.join(args)}")
            return None
        return subprocess.run(
            args,
            check=check,
            text=True,
            capture_output=capture,
        )

    # -- file writes -------------------------------------------------------
    def write_file(
        self,
        path: Path,
        content: str,
        *,
        mode: int,
        validate: Callable[[Path], None] | None = None,
    ) -> None:
        """Atomically write ``content`` to ``path`` with ``mode``.

        Writes to a temp file in the same directory, optionally validates it,
        sets the mode, then ``os.replace``s it into position. Under ``--dry-run``
        nothing is written; the path, mode and content are printed instead.
        """
        if self.dry_run:
            self.info(f"[dry-run] would write {path} (mode {mode:#o}):")
            self.info("\n".join(f"    {line}" for line in content.splitlines()))
            return
        tmp = path.with_name(f".{path.name}.tmp")
        tmp.write_text(content)
        os.chmod(tmp, mode)
        try:
            if validate is not None:
                validate(tmp)
            os.replace(tmp, path)
        except BaseException:
            tmp.unlink(missing_ok=True)
            raise

    def remove_file(self, path: Path) -> None:
        if self.dry_run:
            self.info(f"[dry-run] would remove {path}")
            return
        path.unlink(missing_ok=True)
