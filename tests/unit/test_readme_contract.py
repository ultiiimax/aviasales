from __future__ import annotations

import re
import tomllib
from pathlib import Path


def test_readme_is_the_local_v1_operator_entrypoint() -> None:
    readme = Path("README.md").read_text(encoding="utf-8")
    project = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))

    assert project["project"]["version"] == "1.0.0"
    assert "# Flight Hunter 1.0.0" in readme
    assert "http://127.0.0.1:8000" in readme
    assert "AUTH_ALLOW_LEGACY_HEADERS=false" in readme
    assert "локаль" in readme.lower()
    assert "Docker Desktop" in readme
    for command in (
        "uv run flight-hunter-init-local",
        "uv run alembic upgrade head",
        "uv run uvicorn flight_hunter.api.app:app --host 127.0.0.1 --port 8000",
        "docker compose up --build",
        "uv run flight-hunter-browser-bootstrap",
        "uv run flight-hunter-release-check --include-browser",
        "uv run flight-hunter-backup",
        "uv run flight-hunter-backup-verify",
        "uv run flight-hunter-restore",
        "uv run flight-hunter-source-smoke --source aviasales_search --exact-search",
    ):
        assert command in readme

    assert "466 passed" not in readme
    assert "856890a7-59b2-4043-9bc7-e478bb4e6405" not in readme


def test_readme_only_invokes_declared_project_scripts_and_make_targets() -> None:
    readme = Path("README.md").read_text(encoding="utf-8")
    project = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))
    scripts = set(project["project"]["scripts"])
    makefile = Path("Makefile").read_text(encoding="utf-8")
    targets = {
        line.split(":", 1)[0]
        for line in makefile.splitlines()
        if line and not line.startswith(("\t", ".", "#")) and ":" in line
    }

    documented_scripts = set(re.findall(r"uv run (flight-hunter-[a-z0-9-]+)", readme))
    documented_targets = set(re.findall(r"(?m)^make ([a-z0-9-]+)(?:\s|$)", readme))

    assert documented_scripts <= scripts
    assert documented_targets <= targets
