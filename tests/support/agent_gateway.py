from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from uuid import UUID, uuid5

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from flight_hunter.domain.agent_evidence import (
    ConfirmedOfferEvidence,
    DiscoverySignal,
    ProtectionStatus,
)
from flight_hunter.domain.money import Money
from flight_hunter.domain.offers import FlightSegmentSummary
from flight_hunter.geo.airports import Airport, AirportImportBatch, AirportType
from flight_hunter.persistence.repositories import AirportReferenceRepository
from flight_hunter.providers.aviasales_search.client import SearchStartParams
from flight_hunter.providers.aviasales_search.gateway import (
    AnywhereDiscoveryParams,
    CalendarSearchParams,
    ExactPollOutcome,
    ExactSearchContinuation,
)


@dataclass(slots=True)
class DeterministicAgentGateway:
    start_calls: list[SearchStartParams] = field(default_factory=list)
    poll_calls: list[ExactSearchContinuation] = field(default_factory=list)
    calendar_calls: list[CalendarSearchParams] = field(default_factory=list)
    anywhere_calls: list[AnywhereDiscoveryParams] = field(default_factory=list)
    booking_calls: int = 0

    @property
    def calls(self) -> int:
        return (
            len(self.start_calls)
            + len(self.poll_calls)
            + len(self.calendar_calls)
            + len(self.anywhere_calls)
        )

    async def search(self, *_args: object, **_kwargs: object) -> None:
        raise AssertionError("plan lifecycle must not call provider search")

    async def resolve_booking_action(
        self,
        descriptor: Mapping[str, object],
        *,
        request_fingerprint: str,
    ) -> str | None:
        assert descriptor.get("provider_id") == "aviasales_search"
        assert request_fingerprint
        self.booking_calls += 1
        return "https://fixture.example.test/buy"

    async def start_exact(
        self,
        params: SearchStartParams,
        *,
        evidence_namespace: UUID,
        request_fingerprint: str,
        **_kwargs: object,
    ) -> ExactSearchContinuation:
        assert request_fingerprint
        self.start_calls.append(params)
        return ExactSearchContinuation(
            search_id=f"fixture-search-{len(self.start_calls)}",
            results_url="results.aviasales.ru",
            last_update_timestamp=0,
            request_id=f"fixture-request-{len(self.start_calls)}",
            evidence_namespace=evidence_namespace,
            expected_origin=params.origin.code,
            expected_destination=params.destination.code,
            expected_departure_date=date.fromisoformat(params.departure_date),
            expected_return_date=(
                date.fromisoformat(params.return_date) if params.return_date is not None else None
            ),
            expected_currency=params.currency,
            passengers=params.passengers,
        )

    async def poll_exact_once(
        self,
        continuation: ExactSearchContinuation,
        *,
        request_fingerprint: str,
        **_kwargs: object,
    ) -> ExactPollOutcome:
        assert request_fingerprint
        self.poll_calls.append(continuation)
        return ExactPollOutcome(
            evidence=(self._evidence(continuation),),
            next_cursor=continuation.last_update_timestamp + 1,
            complete=True,
        )

    async def calendar(
        self,
        params: CalendarSearchParams,
        *,
        evidence_namespace: UUID,
        request_fingerprint: str,
        **_kwargs: object,
    ) -> tuple[DiscoverySignal, ...]:
        assert evidence_namespace
        assert request_fingerprint
        self.calendar_calls.append(params)
        return ()

    async def discover_anywhere(
        self,
        params: AnywhereDiscoveryParams,
        *,
        evidence_namespace: UUID,
        request_fingerprint: str,
        **_kwargs: object,
    ) -> tuple[DiscoverySignal, ...]:
        assert evidence_namespace
        assert request_fingerprint
        self.anywhere_calls.append(params)
        return ()

    def _evidence(self, continuation: ExactSearchContinuation) -> ConfirmedOfferEvidence:
        departure = continuation.expected_departure_date
        depart_at = datetime(departure.year, departure.month, departure.day, 10, tzinfo=UTC)
        arrive_at = datetime(departure.year, departure.month, departure.day, 13, tzinfo=UTC)
        segment = FlightSegmentSummary(
            airline_code="FX",
            airline_name="Fixture Air",
            flight_number="FX100",
            origin=continuation.expected_origin,
            destination=continuation.expected_destination,
            depart_at=f"{departure.isoformat()} 10:00",
            arrive_at=f"{departure.isoformat()} 13:00",
            depart_at_utc=depart_at,
            arrive_at_utc=arrive_at,
        )
        provider_offer_id = (
            "aviasales_search:"
            + uuid5(
                continuation.evidence_namespace,
                f"{continuation.expected_origin}|{continuation.expected_destination}|"
                f"{departure.isoformat()}",
            ).hex
        )
        return ConfirmedOfferEvidence(
            id=uuid5(
                continuation.evidence_namespace,
                f"exact|{provider_offer_id}|{continuation.passengers}",
            ),
            provider_id="aviasales_search",
            provider_offer_id=provider_offer_id,
            origin=continuation.expected_origin,
            destination=continuation.expected_destination,
            departure_date=departure,
            return_date=continuation.expected_return_date,
            total_amount=Money(20_000, continuation.expected_currency),
            passengers=continuation.passengers,
            observed_at=datetime.now(UTC),
            segment_ids=(uuid5(continuation.evidence_namespace, "fixture-segment-0").hex,),
            segments=(segment,),
            protection_status=ProtectionStatus.UNKNOWN,
            seller_name="Fixture seller",
            baggage_summary=None,
        )


async def seed_agent_airports(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    airports = (
        _airport("LED", "RU", "Saint Petersburg", 59.8, 30.3),
        _airport("CDG", "FR", "Paris", 49.0, 2.5),
        _airport("ORY", "FR", "Paris", 48.7, 2.4),
        _airport("LYS", "FR", "Lyon", 45.7, 5.1),
        _airport("MRS", "FR", "Marseille", 43.4, 5.2),
    )
    async with session_factory() as session:
        await AirportReferenceRepository(session).import_airports(
            AirportImportBatch(
                source_path="task14-agent-fixture.csv",
                rows_seen=len(airports),
                rows_imported=len(airports),
                airports=airports,
                observed_iata_codes=tuple(airport.iata_code for airport in airports),
            ),
            imported_at=datetime.now(UTC),
            source="task14-agent-fixture",
        )
        await session.commit()


def _airport(
    code: str,
    country: str,
    municipality: str,
    latitude: float,
    longitude: float,
) -> Airport:
    return Airport(
        iata_code=code,
        name=f"{municipality} {code} Airport",
        municipality=municipality,
        country_code=country,
        latitude=latitude,
        longitude=longitude,
        airport_type=AirportType.LARGE_AIRPORT,
        active=True,
        scheduled_service=True,
        commercial_provenance="task14.fixture",
    )
