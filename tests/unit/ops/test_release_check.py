from __future__ import annotations

import io
import json
from collections.abc import Mapping
from subprocess import CompletedProcess

from flight_hunter.ops.release_check import (
    ReleaseStageResult,
    default_stages,
    run_release_check,
)


class RecordingRunner:
    def __init__(self, results: list[CompletedProcess[str]]) -> None:
        self._results = list(results)
        self.calls: list[tuple[tuple[str, ...], Mapping[str, str] | None]] = []

    def __call__(
        self,
        command: tuple[str, ...],
        *,
        env: Mapping[str, str] | None = None,
    ) -> CompletedProcess[str]:
        self.calls.append((command, env))
        return self._results.pop(0)


def test_default_release_stages_are_deterministic() -> None:
    assert default_stages() == (
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


def test_skipped_stage_has_versioned_json_reason() -> None:
    result = ReleaseStageResult.skipped("browser", "browser_runtime_not_requested")

    assert result.to_json_dict() == {
        "schema_version": 1,
        "stage": "browser",
        "status": "skipped",
        "code": "skipped",
        "skipped_reason": "browser_runtime_not_requested",
    }


def test_release_check_relays_command_output_to_stderr_and_jsonl_to_stdout() -> None:
    runner = RecordingRunner(
        [CompletedProcess(("uv",), 0, stdout="pytest output\n", stderr="pytest warning\n")]
    )
    stdout = io.StringIO()
    stderr = io.StringIO()

    results = run_release_check(
        stages=("health",),
        runner=runner,
        stdout=stdout,
        stderr=stderr,
        environ={},
    )

    assert results[0].status == "passed"
    assert runner.calls[0][0] == (
        "uv",
        "run",
        "pytest",
        "tests/unit/api/test_api_app.py",
        "-q",
        "-k",
        "health",
    )
    assert stderr.getvalue() == "pytest output\npytest warning\n"
    assert json.loads(stdout.getvalue()) == results[0].to_json_dict()


def test_browser_stage_is_skipped_unless_requested() -> None:
    runner = RecordingRunner([])
    stdout = io.StringIO()

    results = run_release_check(
        stages=("browser",),
        runner=runner,
        stdout=stdout,
        stderr=io.StringIO(),
        environ={},
    )

    assert results == (ReleaseStageResult.skipped("browser", "browser_runtime_not_requested"),)
    assert runner.calls == []


def test_compose_stage_uses_process_only_safe_environment() -> None:
    runner = RecordingRunner(
        [CompletedProcess(("docker", "compose", "config", "--quiet"), 0, stdout="", stderr="")]
    )

    results = run_release_check(
        stages=("compose",),
        runner=runner,
        stdout=io.StringIO(),
        stderr=io.StringIO(),
        environ={"APP_SECRET_KEY": "unsafe-inherited", "PATH": "test-path"},
    )

    assert results[0].status == "passed"
    command, environment = runner.calls[0]
    assert command == ("docker", "compose", "config", "--quiet")
    assert environment is not None
    assert environment["PATH"] == "test-path"
    assert environment["APP_SECRET_KEY"] != "unsafe-inherited"
    assert len(environment["APP_SECRET_KEY"]) >= 40
    assert environment["AUTH_ALLOW_LEGACY_HEADERS"] == "false"
    assert environment["AVIASALES_SEARCH_ENABLED"] == "false"
    assert environment["AVIASALES_SEARCH_SIGNATURE"] == ""
    assert environment["AVIASALES_SEARCH_MARKER"] == ""
