from __future__ import annotations

import subprocess
from collections.abc import Callable
from typing import Protocol


class CommandResult(Protocol):
    returncode: int


CommandRunner = Callable[..., CommandResult]

_COMMANDS: tuple[tuple[str, ...], ...] = (
    ("uv", "sync", "--group", "dev", "--group", "scraping"),
    ("uv", "run", "playwright", "install", "chromium"),
)


def browser_bootstrap(*, run: CommandRunner | None = None) -> int:
    command_runner = run or _run_command
    for command in _COMMANDS:
        completed = command_runner(command, check=False)
        if completed.returncode != 0:
            return completed.returncode
    return 0


def _run_command(command: tuple[str, ...], *, check: bool) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(command, check=check, shell=False)


def main() -> int:
    return browser_bootstrap()


if __name__ == "__main__":
    raise SystemExit(main())
