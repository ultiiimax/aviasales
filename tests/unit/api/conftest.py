from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass, replace
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from flight_hunter.api.app import create_app
from flight_hunter.config import AppSettings
from flight_hunter.geo.airports import Airport, AirportImportBatch, AirportType
from flight_hunter.persistence.models import mapper_registry
from flight_hunter.persistence.repositories import AirportReferenceRepository

AGENT_BOOTSTRAP_TOKEN = "agent-bootstrap-secret"


class CountingAgentProviderGateway:
    def __init__(self) -> None:
        self.calls = 0

    async def search(self, *_args: object, **_kwargs: object) -> None:
        self.calls += 1
        raise AssertionError("plan lifecycle must not call a provider")


@dataclass(frozen=True, slots=True)
class AgentApiHarness:
    client: TestClient
    session_factory: async_sessionmaker[AsyncSession]
    session_token: str
    household_id: str
    user_id: str
    provider: CountingAgentProviderGateway

    @property
    def auth_headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.session_token}"}

    def create_second_session(self) -> dict[str, str]:
        invitation = self.client.post(
            "/api/v1/auth/bootstrap-invitation",
            headers={"X-Flight-Hunter-Bootstrap-Token": AGENT_BOOTSTRAP_TOKEN},
            json={"household_name": "Other household"},
        )
        assert invitation.status_code == 201
        accepted = self.client.post(
            "/api/v1/auth/accept-invitation",
            json={
                "invitation_code": invitation.json()["invitation_code"],
                "display_name": "Other owner",
            },
        )
        assert accepted.status_code == 201
        return accepted.json()


@pytest.fixture(autouse=True)
def enable_legacy_headers_for_non_auth_api_unit_tests(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("AUTH_ALLOW_LEGACY_HEADERS", "true")


@pytest.fixture
async def agent_api_harness() -> AsyncIterator[AgentApiHarness]:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(mapper_registry.metadata.create_all)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with session_factory() as session:
        airport_repository = AirportReferenceRepository(session)
        airports = (_airport("LED", "RU", "Saint Petersburg"), _airport("CDG", "FR", "Paris"))
        await airport_repository.import_airports(
            AirportImportBatch(
                source_path="task5-fixture.csv",
                rows_seen=len(airports),
                rows_imported=len(airports),
                airports=airports,
                observed_iata_codes=tuple(airport.iata_code for airport in airports),
            ),
            imported_at=datetime(2026, 7, 14, 8, 0, tzinfo=UTC),
            source="task5-fixture",
        )
        await session.commit()

    provider = CountingAgentProviderGateway()
    settings = replace(
        AppSettings.from_env(),
        auth_allow_legacy_headers=False,
        auth_bootstrap_token=AGENT_BOOTSTRAP_TOKEN,
    )
    client = TestClient(
        create_app(
            watch_session_factory=session_factory,
            settings=settings,
            agent_provider_gateway=provider,
        )
    )
    invitation = client.post(
        "/api/v1/auth/bootstrap-invitation",
        headers={"X-Flight-Hunter-Bootstrap-Token": AGENT_BOOTSTRAP_TOKEN},
        json={"household_name": "Agent household"},
    )
    assert invitation.status_code == 201
    accepted = client.post(
        "/api/v1/auth/accept-invitation",
        json={
            "invitation_code": invitation.json()["invitation_code"],
            "display_name": "Agent owner",
        },
    )
    assert accepted.status_code == 201
    session_body = accepted.json()
    yield AgentApiHarness(
        client=client,
        session_factory=session_factory,
        session_token=session_body["session_token"],
        household_id=session_body["household_id"],
        user_id=session_body["user_id"],
        provider=provider,
    )
    client.close()
    await engine.dispose()


def _airport(code: str, country: str, municipality: str) -> Airport:
    return Airport(
        iata_code=code,
        name=f"{municipality} {code} Airport",
        municipality=municipality,
        country_code=country,
        latitude=48.0,
        longitude=2.0,
        airport_type=AirportType.LARGE_AIRPORT,
        active=True,
        scheduled_service=True,
        commercial_provenance="task5.fixture",
    )
