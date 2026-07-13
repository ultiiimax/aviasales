from __future__ import annotations

import argparse
import json
import os
import secrets
import subprocess
import sys
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Protocol, TextIO


class CommandResult(Protocol):
    returncode: int
    stdout: str
    stderr: str


CommandRunner = Callable[..., CommandResult]

STAGE_COMMANDS: dict[str, tuple[str, ...]] = {
    "tests": (
        "uv",
        "run",
        "pytest",
        "--disable-warnings",
        "-q",
        "-m",
        "not browser_e2e",
        "--strict-markers",
    ),
    "format": ("uv", "run", "ruff", "format", "--check", "."),
    "lint": ("uv", "run", "ruff", "check", "."),
    "types": ("uv", "run", "mypy"),
    "migrations": (
        "uv",
        "run",
        "pytest",
        "tests/unit/persistence/test_alembic_upgrade.py",
        "-q",
    ),
    "upgrade_migrations": (
        "uv",
        "run",
        "pytest",
        "tests/integration/test_upgrade_from_pre_v1.py",
        "-q",
    ),
    "security": ("uv", "run", "flight-hunter-security-scan"),
    "compose": ("docker", "compose", "config"),
    "health": (
        "uv",
        "run",
        "pytest",
        "tests/unit/api/test_api_app.py",
        "-q",
        "-k",
        "health",
    ),
}

_BROWSER_COMMANDS: tuple[tuple[str, ...], ...] = (
    ("uv", "run", "flight-hunter-browser-smoke"),
    (
        "uv",
        "run",
        "pytest",
        "tests/e2e",
        "-q",
        "-m",
        "browser_e2e",
        "--strict-markers",
    ),
)
_DOCKER_BUILD_COMMANDS: tuple[tuple[str, ...], ...] = (
    ("docker", "info", "--format", "{{.ServerVersion}}"),
    ("docker", "compose", "build", "api", "worker"),
)


@dataclass(frozen=True, slots=True)
class ReleaseStageResult:
    schema_version: int
    stage: str
    status: str
    code: str
    skipped_reason: str | None

    @classmethod
    def passed(cls, stage: str) -> ReleaseStageResult:
        return cls(
            schema_version=1,
            stage=stage,
            status="passed",
            code="ok",
            skipped_reason=None,
        )

    @classmethod
    def failed(cls, stage: str, code: str) -> ReleaseStageResult:
        return cls(
            schema_version=1,
            stage=stage,
            status="failed",
            code=code,
            skipped_reason=None,
        )

    @classmethod
    def skipped(cls, stage: str, reason: str) -> ReleaseStageResult:
        return cls(
            schema_version=1,
            stage=stage,
            status="skipped",
            code="skipped",
            skipped_reason=reason,
        )

    def to_json_dict(self) -> dict[str, int | str | None]:
        return {
            "schema_version": self.schema_version,
            "stage": self.stage,
            "status": self.status,
            "code": self.code,
            "skipped_reason": self.skipped_reason,
        }


def default_stages() -> tuple[str, ...]:
    return (
        "tests",
        "format",
        "lint",
        "types",
        "migrations",
        "upgrade_migrations",
        "security",
        "compose",
        "health",
        "browser",
    )


def run_release_check(
    *,
    stages: Sequence[str],
    include_browser: bool = False,
    include_docker_build: bool = False,
    runner: CommandRunner | None = None,
    stdout: TextIO | None = None,
    stderr: TextIO | None = None,
    environ: Mapping[str, str] | None = None,
) -> tuple[ReleaseStageResult, ...]:
    command_runner = runner or _run_command
    output = stdout or sys.stdout
    errors = stderr or sys.stderr
    process_environment = environ if environ is not None else os.environ
    results: list[ReleaseStageResult] = []
    for stage in stages:
        if stage == "browser" and not include_browser:
            result = ReleaseStageResult.skipped(
                "browser",
                "browser_runtime_not_requested",
            )
        elif stage == "docker_build" and not include_docker_build:
            result = ReleaseStageResult.skipped(
                "docker_build",
                "docker_build_not_requested",
            )
        else:
            result = _run_stage(
                stage,
                runner=command_runner,
                stderr=errors,
                environ=process_environment,
            )
        results.append(result)
        output.write(json.dumps(result.to_json_dict(), ensure_ascii=False) + "\n")
        output.flush()
    return tuple(results)


def _run_stage(
    stage: str,
    *,
    runner: CommandRunner,
    stderr: TextIO,
    environ: Mapping[str, str],
) -> ReleaseStageResult:
    if stage == "browser":
        commands = _BROWSER_COMMANDS
    elif stage == "docker_build":
        commands = _DOCKER_BUILD_COMMANDS
    else:
        command = STAGE_COMMANDS.get(stage)
        if command is None:
            return ReleaseStageResult.failed(stage, "unknown_stage")
        commands = (command,)

    command_environment = _compose_environment(environ) if stage == "compose" else None
    for index, command in enumerate(commands):
        try:
            completed = runner(command, env=command_environment)
        except OSError:
            code = "docker_unavailable" if stage == "docker_build" else "command_unavailable"
            return ReleaseStageResult.failed(stage, code)
        _relay_command_output(completed, stderr)
        if completed.returncode != 0:
            if stage == "docker_build" and index == 0:
                return ReleaseStageResult.failed(stage, "docker_unavailable")
            return ReleaseStageResult.failed(stage, f"{stage}_failed")
    return ReleaseStageResult.passed(stage)


def _compose_environment(environ: Mapping[str, str]) -> dict[str, str]:
    environment = dict(environ)
    environment.update(
        {
            "APP_SECRET_KEY": secrets.token_urlsafe(48),
            "AUTH_BOOTSTRAP_TOKEN": "",
            "AUTH_ALLOW_LEGACY_HEADERS": "false",
            "AVIASALES_SEARCH_ENABLED": "false",
            "AVIASALES_SEARCH_SIGNATURE": "",
            "AVIASALES_SEARCH_MARKER": "",
            "TELEGRAM_ENABLED": "false",
            "TELEGRAM_BOT_TOKEN": "",
        }
    )
    return environment


def _relay_command_output(completed: CommandResult, stderr: TextIO) -> None:
    if completed.stdout:
        stderr.write(completed.stdout)
    if completed.stderr:
        stderr.write(completed.stderr)
    stderr.flush()


def _run_command(
    command: tuple[str, ...],
    *,
    env: Mapping[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        check=False,
        shell=False,
        capture_output=True,
        text=True,
        env=dict(env) if env is not None else None,
    )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="flight-hunter-release-check",
        description="Run deterministic local v1 release stages and emit JSONL results.",
    )
    parser.add_argument(
        "--stage",
        action="append",
        choices=(*default_stages(), "docker_build"),
        dest="stages",
    )
    parser.add_argument("--include-browser", action="store_true")
    parser.add_argument("--include-docker-build", action="store_true")
    return parser


def main() -> int:
    args = _parser().parse_args()
    stages = tuple(args.stages) if args.stages else default_stages()
    if args.include_docker_build and "docker_build" not in stages:
        stages = (*stages, "docker_build")
    results = run_release_check(
        stages=stages,
        include_browser=args.include_browser,
        include_docker_build=args.include_docker_build,
    )
    return 1 if any(result.status == "failed" for result in results) else 0


if __name__ == "__main__":
    raise SystemExit(main())
