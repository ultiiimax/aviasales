from __future__ import annotations

from pathlib import Path


def test_makefile_exposes_required_operational_targets() -> None:
    makefile = Path("Makefile").read_text(encoding="utf-8")
    targets = {
        line.split(":", 1)[0]
        for line in makefile.splitlines()
        if line and not line.startswith(("\t", ".", "#")) and ":" in line
    }

    assert {
        "bootstrap",
        "dev",
        "test",
        "test-unit",
        "test-integration",
        "test-e2e",
        "lint",
        "typecheck",
        "migrate",
        "seed-demo",
        "provider-contracts",
        "security",
        "source-smoke",
        "browser-smoke",
        "parse-fixture",
        "redact-url",
        "sanitize-html",
        "worker-healthcheck",
        "compose-up",
        "compose-down",
        "compose-deals-config",
        "compose-deals-up",
        "compose-worker-up",
        "backup",
        "backup-verify",
        "restore",
    }.issubset(targets)
