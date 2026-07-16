from __future__ import annotations

import asyncio
import json
import secrets
import socket
import threading
import time
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from urllib.request import urlopen
from uuid import UUID

import pytest
import uvicorn
from alembic import command
from alembic.config import Config
from playwright.sync_api import Browser, Page, Playwright, sync_playwright
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from flight_hunter.api.app import create_app
from flight_hunter.application.agent_execution import (
    AgentExecutionPolicy,
    AgentExecutionService,
)
from flight_hunter.config import AppSettings
from flight_hunter.domain.money import Money
from flight_hunter.domain.offers import FlightOffer, Freshness, SearchIntent
from flight_hunter.domain.policy import ExecutionContext
from flight_hunter.ops.worker import run_once
from flight_hunter.persistence.agent_repositories import AgentRunRepository
from flight_hunter.persistence.database import create_database_engine
from tests.support.agent_gateway import (
    DeterministicAgentGateway,
    seed_agent_airports,
)


@dataclass(frozen=True, slots=True)
class LocalServer:
    url: str
    bootstrap_token: str
    app_secret_key: str


@dataclass(frozen=True, slots=True)
class AgentLocalServer(LocalServer):
    database_url: str
    settings: AppSettings
    gateway: DeterministicAgentGateway

    def run_until_terminal(
        self,
        *,
        household_id: str,
        run_id: str,
        limit: int = 12,
    ) -> str:
        return _run_async_in_thread(
            lambda: _run_agent_until_terminal(
                database_url=self.database_url,
                settings=self.settings,
                gateway=self.gateway,
                household_id=household_id,
                run_id=run_id,
                limit=limit,
            )
        )


class FakeBookingProvider:
    def search(
        self,
        intent: SearchIntent,
        *,
        request_fingerprint: str,
        context: ExecutionContext,
    ) -> tuple[FlightOffer, ...]:
        return (
            FlightOffer(
                provider_id="aviasales_search",
                provider_offer_id="e2e-offer-1",
                origin=intent.origin,
                destination=intent.destination,
                departure_date=intent.departure_date,
                return_date=intent.return_date,
                total_price=Money(123_400, intent.currency),
                passengers=intent.passengers,
                observed_at=datetime.now(UTC),
                freshness=Freshness.LIVE,
                requires_live_confirmation=False,
                baggage_summary="baggage:1",
                seller_name="E2E Gate",
                booking_action_ref=json.dumps(
                    {
                        "provider_id": "aviasales_search",
                        "proposal_id": "p1",
                        "results_url": "e2e-results.example",
                        "search_id": "s1",
                    },
                    separators=(",", ":"),
                    sort_keys=True,
                ),
            ),
        )

    def resolve_purchase_url(
        self,
        *,
        search_id: str,
        proposal_id: str,
        results_url: str,
        request_fingerprint: str,
        context: ExecutionContext,
    ) -> str | None:
        return "https://gate.example/e2e-buy"


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item: pytest.Item):
    outcome = yield
    report = outcome.get_result()
    setattr(item, f"rep_{report.when}", report)


@pytest.fixture(scope="session")
def playwright_runtime() -> Iterator[Playwright]:
    with sync_playwright() as runtime:
        yield runtime


@pytest.fixture(scope="session")
def browser(playwright_runtime: Playwright) -> Iterator[Browser]:
    browser_instance = playwright_runtime.chromium.launch(headless=True)
    yield browser_instance
    browser_instance.close()


@pytest.fixture
def local_server(tmp_path: Path) -> Iterator[LocalServer]:
    with _running_server(tmp_path / "offline.db", booking_enabled=False) as server:
        yield server


@pytest.fixture
def booking_server(tmp_path: Path) -> Iterator[LocalServer]:
    with _running_server(tmp_path / "booking.db", booking_enabled=True) as server:
        yield server


@pytest.fixture
def agent_server(tmp_path: Path) -> Iterator[AgentLocalServer]:
    with _running_server(
        tmp_path / "agent.db",
        booking_enabled=False,
        agent_enabled=True,
    ) as server:
        assert isinstance(server, AgentLocalServer)
        yield server


@pytest.fixture
def page(
    browser: Browser, local_server: LocalServer, request: pytest.FixtureRequest
) -> Iterator[Page]:
    context = browser.new_context(viewport={"width": 1440, "height": 1000})
    page_instance = context.new_page()
    yield page_instance
    report = getattr(request.node, "rep_call", None)
    if report is not None and report.failed:
        output_dir = Path(".pytest-tmp/browser-failures")
        output_dir.mkdir(parents=True, exist_ok=True)
        page_instance.screenshot(path=output_dir / f"{request.node.name}.png", full_page=True)
    context.close()


@pytest.fixture
def agent_page(
    browser: Browser,
    agent_server: AgentLocalServer,
    request: pytest.FixtureRequest,
) -> Iterator[Page]:
    context = browser.new_context(viewport={"width": 1440, "height": 1000})
    page_instance = context.new_page()
    yield page_instance
    report = getattr(request.node, "rep_call", None)
    if report is not None and report.failed:
        output_dir = Path(".pytest-tmp/browser-failures")
        output_dir.mkdir(parents=True, exist_ok=True)
        page_instance.screenshot(path=output_dir / f"{request.node.name}.png", full_page=True)
    context.close()


@contextmanager
def _running_server(
    database_path: Path,
    *,
    booking_enabled: bool,
    agent_enabled: bool = False,
) -> Iterator[LocalServer]:
    database_url = f"sqlite+aiosqlite:///{database_path.resolve().as_posix()}"
    migration_config = Config(str(Path("alembic.ini").resolve()))
    migration_config.set_main_option("sqlalchemy.url", database_url)
    with ThreadPoolExecutor(max_workers=1) as executor:
        executor.submit(command.upgrade, migration_config, "head").result()

    bootstrap_token = secrets.token_urlsafe(48)
    app_secret_key = secrets.token_urlsafe(48)
    settings = AppSettings(
        database_url=database_url,
        aviasales_search_enabled=booking_enabled or agent_enabled,
        aviasales_search_signature=(
            "123e4567-e89b-12d3-a456-426614174000" if booking_enabled or agent_enabled else None
        ),
        aviasales_search_marker=(
            "mobile_app.aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
            if booking_enabled or agent_enabled
            else None
        ),
        aviasales_search_internal_rpm=20,
        telegram_enabled=False,
        telegram_webhook_secret=None,
        app_secret_key=app_secret_key,
        auth_bootstrap_token=bootstrap_token,
        auth_allow_legacy_headers=False,
        agent_poll_interval_seconds=0,
    )
    providers = {"aviasales_search": FakeBookingProvider()} if booking_enabled else {}
    agent_gateway = DeterministicAgentGateway() if agent_enabled else None
    if agent_enabled:
        _run_async_in_thread(lambda: _seed_agent_database(database_url))
    app = create_app(
        settings=settings,
        provider_instances=providers,  # type: ignore[arg-type]
        agent_provider_gateway=agent_gateway,
    )
    host = "127.0.0.1"
    port = _free_loopback_port()
    server = uvicorn.Server(
        uvicorn.Config(app, host=host, port=port, log_level="warning", access_log=False)
    )
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    url = f"http://{host}:{port}"
    _wait_until_ready(url)
    try:
        if agent_gateway is None:
            yield LocalServer(
                url=url,
                bootstrap_token=bootstrap_token,
                app_secret_key=app_secret_key,
            )
        else:
            yield AgentLocalServer(
                url=url,
                bootstrap_token=bootstrap_token,
                app_secret_key=app_secret_key,
                database_url=database_url,
                settings=settings,
                gateway=agent_gateway,
            )
    finally:
        server.should_exit = True
        thread.join(timeout=10)
        if thread.is_alive():
            raise RuntimeError("e2e uvicorn server did not stop")


async def _seed_agent_database(database_url: str) -> None:
    engine = create_database_engine(database_url)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    await seed_agent_airports(sessions)
    await engine.dispose()


def _run_async_in_thread(factory):
    with ThreadPoolExecutor(max_workers=1) as executor:
        return executor.submit(lambda: asyncio.run(factory())).result()


async def _run_agent_until_terminal(
    *,
    database_url: str,
    settings: AppSettings,
    gateway: DeterministicAgentGateway,
    household_id: str,
    run_id: str,
    limit: int,
) -> str:
    for index in range(limit):
        engine = create_database_engine(database_url)
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        async with sessions() as session:
            run = await AgentRunRepository(session).get_run(
                UUID(household_id),
                UUID(run_id),
            )
            assert run is not None
            if run.status in {"completed", "partial", "failed", "cancelled"}:
                await engine.dispose()
                return run.status
        await engine.dispose()
        await run_once(
            database_url=database_url,
            settings=settings,
            worker_id=f"agent-e2e-worker-{index}",
            worker_roles=("agent",),
            agent_executor_factory=_agent_executor_factory(gateway),
        )
    raise AssertionError("agent E2E run did not become terminal")


def _agent_executor_factory(gateway: DeterministicAgentGateway):
    def factory(
        session: AsyncSession,
        settings: AppSettings,
        worker_id: str,
    ) -> AgentExecutionService:
        return AgentExecutionService(
            session=session,
            gateway=gateway,
            worker_id=worker_id,
            policy=AgentExecutionPolicy(
                provider_rpm=settings.aviasales_search_internal_rpm,
                operation_lease_seconds=settings.agent_operation_lease_seconds,
                circuit_failure_threshold=settings.agent_provider_circuit_failure_threshold,
                circuit_cooldown_seconds=settings.agent_provider_circuit_cooldown_seconds,
                circuit_probe_lease_seconds=min(30, settings.agent_operation_lease_seconds),
                poll_interval_seconds=0,
            ),
            durability_checkpoint=session.commit,
        )

    return factory


def _free_loopback_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _wait_until_ready(url: str) -> None:
    deadline = time.monotonic() + 10
    last_error: OSError | None = None
    while time.monotonic() < deadline:
        try:
            with urlopen(f"{url}/healthz", timeout=1) as response:
                if response.status == 200:
                    return
        except OSError as exc:
            last_error = exc
            time.sleep(0.05)
    raise RuntimeError("e2e server failed to start") from last_error
