from __future__ import annotations

import subprocess
import time
from pathlib import Path

import pytest

import flight_hunter.agent.codex_cli as codex_cli
from flight_hunter.agent.codex_cli import CodexCliAgentAdapter, CodexIntentDraftValidator


def test_codex_intent_validator_accepts_only_search_intent_fields() -> None:
    result = CodexIntentDraftValidator().validate_json(
        """
        {
          "origin_query": "Warsaw",
          "destination_query": "Barcelona",
          "departure_date": "2026-10-12",
          "return_date": "2026-10-19",
          "trip_shape": "round_trip",
          "date_mode": "exact",
          "adults": 2,
          "children": 0,
          "infants": 0,
          "currency": "RUB",
          "nearby_radius_km": 150,
          "requested_strategies": ["split_ticket"],
          "baggage_preference": "checked",
          "wants_watch": true
        }
        """
    )

    assert result.code == "valid"
    assert result.draft is not None
    assert result.draft.origin_query == "Warsaw"
    assert result.draft.requested_strategies == ("split_ticket",)
    assert result.draft.baggage_preference == "checked"
    assert result.draft.wants_watch is True


def test_codex_intent_validator_rejects_prices_and_provider_facts() -> None:
    result = CodexIntentDraftValidator().validate_json(
        """
        {
          "origin_query": "Warsaw",
          "destination_query": "Barcelona",
          "departure_date": "2026-10-12",
          "amount_minor": 123400,
          "provider_offer_id": "made-up"
        }
        """
    )

    assert result.code == "forbidden_field"
    assert result.draft is None


def test_codex_cli_adapter_builds_sandboxed_ephemeral_command() -> None:
    adapter = CodexCliAgentAdapter(
        enabled=True,
        service_tier="fast",
        timeout_seconds=5,
        model_name="gpt-5.2-codex",
    )

    command = adapter.build_command(schema_path="C:/tmp/schema.json")

    assert command[:2] == ("codex", "exec")
    assert "--ephemeral" in command
    assert "--ignore-user-config" in command
    assert "--ignore-rules" in command
    assert "--skip-git-repo-check" in command
    assert "--sandbox" in command
    assert "read-only" in command
    assert "-c" in command
    assert 'service_tier="fast"' in command
    assert command[command.index("--model") + 1] == "gpt-5.2-codex"
    assert "--output-schema" in command


def test_codex_validator_rejects_oversized_or_wrong_typed_output() -> None:
    validator = CodexIntentDraftValidator(max_output_bytes=80)

    oversized = validator.validate_json('{"origin_query":"' + "x" * 100 + '"}')
    wrong_type = CodexIntentDraftValidator().validate_json('{"adults":"two"}')

    assert oversized.code == "output_too_large"
    assert wrong_type.code == "invalid_shape"


def test_codex_timeout_terminates_process_tree_and_returns_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class TimeoutProcess:
        pid = 4312
        returncode: int | None = None
        terminated = False

        def __enter__(self) -> TimeoutProcess:
            return self

        def __exit__(self, *args: object) -> None:
            del args

        def kill(self) -> None:
            self.terminated = True
            self.returncode = -9

        def poll(self) -> int | None:
            return self.returncode

        def communicate(
            self,
            input: bytes | None = None,
            timeout: int | float | None = None,
        ) -> tuple[bytes, bytes]:
            del input, timeout
            if not self.terminated:
                raise subprocess.TimeoutExpired(cmd="codex", timeout=1)
            return b"", b""

    process = TimeoutProcess()
    terminated: list[int] = []

    def terminate_process_tree(candidate: TimeoutProcess) -> None:
        terminated.append(candidate.pid)
        candidate.terminated = True
        candidate.returncode = -1

    monkeypatch.setattr(codex_cli.shutil, "which", lambda _: "C:/fake/codex.CMD")
    monkeypatch.setattr(codex_cli.subprocess, "Popen", lambda *args, **kwargs: process)
    monkeypatch.setattr(
        codex_cli,
        "_terminate_process_tree",
        terminate_process_tree,
        raising=False,
    )

    result = CodexCliAgentAdapter(enabled=True, timeout_seconds=1).extract_intent(
        "из Санкт-Петербурга к морю в сентябре"
    )

    assert result is None
    assert terminated == [4312]


def test_codex_temp_cleanup_retries_a_transient_windows_lock(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    directory = tmp_path / "intent"
    directory.mkdir()
    (directory / "intent.output.json").write_text("{}", encoding="utf-8")
    real_rmtree = codex_cli.shutil.rmtree
    attempts = 0

    def locked_then_remove(path: object) -> None:
        nonlocal attempts
        attempts += 1
        if attempts < 3:
            raise PermissionError("transient child-process handle")
        real_rmtree(path)

    monkeypatch.setattr(codex_cli.shutil, "rmtree", locked_then_remove)
    monkeypatch.setattr(time, "sleep", lambda _: None)

    assert hasattr(codex_cli, "_cleanup_intent_directory")
    codex_cli._cleanup_intent_directory(directory)

    assert attempts == 3
    assert not directory.exists()
