# nosudo — Project Instructions

## Python tooling: use `uv`

Use [`uv`](https://docs.astral.sh/uv/) for all Python tooling in this project — do **not** use
bare `pip`, `python -m venv`, `pipx`, or `python` directly.

- Run code/tools: `uv run <cmd>` (e.g. `uv run nosudo ...`, `uv run pytest`).
- Manage deps: `uv add <pkg>` / `uv remove <pkg>`; sync env with `uv sync`.
- Lockfile `uv.lock` is committed.
- Project metadata lives in `pyproject.toml` (managed by uv).
