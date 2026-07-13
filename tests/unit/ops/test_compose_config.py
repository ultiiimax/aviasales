from __future__ import annotations

import re
import tomllib
from pathlib import Path

from flight_hunter import __version__


def test_deal_discovery_compose_profile_uses_pinned_internal_services() -> None:
    compose = Path("compose.yaml").read_text(encoding="utf-8")

    assert "searxng/searxng:2026.6.29-0e990f78a" in compose
    assert "unclecode/crawl4ai:0.8.9" in compose
    assert "searxng/searxng:latest" not in compose
    assert '"8080:8080"' not in compose
    assert '"11235:11235"' not in compose
    assert "http://searxng:8080" in compose
    assert "http://crawl4ai:11235" in compose
    assert 'CRAWL4AI_MODE: "${CRAWL4AI_MODE:-server}"' in compose
    assert "CRAWL4AI_API_TOKEN" in compose
    assert "CRAWL4AI_TIMEOUT_SECONDS" in compose
    assert "healthcheck:" in compose
    assert "crawl4ai_cache" in compose


def test_local_v1_package_compose_and_image_contracts() -> None:
    project = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))
    compose = Path("compose.yaml").read_text(encoding="utf-8")
    dockerfile = Path("Dockerfile").read_text(encoding="utf-8")
    api = _service_block(compose, "api", "worker")
    worker = _service_block(compose, "worker", "searxng")

    assert project["project"]["version"] == "1.0.0"
    assert __version__ == "1.0.0"
    assert '      - "127.0.0.1:8000:8000"' in api
    assert "profiles:" not in worker
    assert re.search(
        r"depends_on:\s+api:\s+condition: service_healthy",
        worker,
    )
    assert re.search(r"healthcheck:.*?interval: 10s", api, flags=re.DOTALL)
    assert re.search(r"healthcheck:.*?interval: 30s", worker, flags=re.DOTALL)
    assert re.search(
        r"flight-hunter-worker-healthcheck\s+- --role\s+- flight_hunter_worker",
        worker,
    )
    assert "${APP_SECRET_KEY:?" in api
    assert 'AUTH_ALLOW_LEGACY_HEADERS: "false"' in api
    assert "uv sync --frozen --no-dev" in dockerfile
    assert "--group scraping" not in dockerfile
    assert "chown -R flight-hunter:flight-hunter /app /data" in dockerfile
    assert re.search(r"^USER (?!root)\S+", dockerfile, flags=re.MULTILINE)


def test_ci_covers_linux_windows_browser_and_image_without_live_credentials() -> None:
    workflow = Path(".github/workflows/ci.yml").read_text(encoding="utf-8")

    for job in ("quality-linux", "quality-windows", "browser", "image"):
        assert f"  {job}:" in workflow
    assert "Документы/Flight Hunter" in workflow
    assert "uv sync --frozen --group dev" in workflow
    assert "uv run flight-hunter-release-check" in workflow
    assert "playwright install --with-deps chromium" in workflow
    assert "pytest tests/e2e -q -m browser_e2e --strict-markers" in workflow
    assert "uv run flight-hunter-init-local" in workflow
    assert "docker compose build api worker" in workflow
    assert "AVIASALES_SEARCH_SIGNATURE:" not in workflow
    assert "AVIASALES_SEARCH_MARKER:" not in workflow


def _service_block(compose: str, name: str, next_name: str) -> str:
    start = compose.index(f"  {name}:\n")
    end = compose.index(f"  {next_name}:\n", start)
    return compose[start:end]
