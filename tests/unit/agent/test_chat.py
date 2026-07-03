from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

import pytest

from flight_hunter.agent.chat import AgentChatService, AgentTurnRequest
from flight_hunter.application.airport_service import AirportService
from flight_hunter.application.date_matrix import DateMatrixPlanner
from flight_hunter.application.provider_registry import ProviderRegistry
from flight_hunter.application.search_service import DemoSearchService
from flight_hunter.geo.demo_repository import DemoAirportRepository
from flight_hunter.persistence.repositories import WatchRecord

HOUSEHOLD_ID = UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
USER_ID = UUID("aaaaaaaa-0000-0000-0000-000000000001")
NOW = datetime(2026, 6, 24, 12, 0, tzinfo=UTC)


@pytest.mark.anyio
async def test_agent_chat_shows_airport_choices_for_ambiguous_city_names() -> None:
    service = _service()

    response = await service.handle_turn(
        AgentTurnRequest(
            message="из Варшавы в Барселону на неделю в октябре",
            household_id=HOUSEHOLD_ID,
            user_id=USER_ID,
        )
    )

    assert response.extracted["origin_query"] == "Warsaw"
    assert response.extracted["destination_query"] == "Barcelona"
    assert [option.iata_code for option in response.airport_options["origin"]] == ["WAW", "WMI"]
    assert [option.iata_code for option in response.airport_options["destination"]] == ["BCN"]
    assert response.missing_slots == ("origin", "departure_date")
    assert all(action.kind != "search_cached_offers" for action in response.actions)
    assert "выбери аэропорт" in response.reply_ru.lower()


@pytest.mark.anyio
async def test_agent_chat_understands_spb_to_shanghai_month_without_guessing_date() -> None:
    service = _service()

    response = await service.handle_turn(
        AgentTurnRequest(
            message="Хочу из спб улететь в Шанхай в октябре",
            household_id=HOUSEHOLD_ID,
            user_id=USER_ID,
        )
    )

    assert response.extracted["origin_query"] == "Saint Petersburg"
    assert response.extracted["destination_query"] == "Shanghai"
    assert response.extracted["origin"] == "LED"
    assert response.extracted["destination"] is None
    assert response.extracted["departure_date"] is None
    assert response.extracted["date_hint"] == "октябрь"
    assert response.missing_slots == ("destination", "departure_date")
    assert [option.iata_code for option in response.airport_options["origin"]] == ["LED"]
    assert [option.iata_code for option in response.airport_options["destination"]] == [
        "PVG",
        "SHA",
    ]
    assert [action.kind for action in response.actions] == [
        "clarify_airport_choice",
        "clarify_travel_dates",
    ]
    assert all(action.kind != "search_cached_offers" for action in response.actions)
    assert "Шанхай" in response.reply_ru
    assert "октябр" in response.reply_ru.lower()


@pytest.mark.anyio
async def test_agent_chat_runs_safe_actions_and_creates_watch_only_on_explicit_request() -> None:
    watch_creator = RecordingWatchCreator()
    service = _service(watch_creator=watch_creator)

    response = await service.handle_turn(
        AgentTurnRequest(
            message="WAW BCN 2026-10-12 2026-10-19 следи",
            household_id=HOUSEHOLD_ID,
            user_id=USER_ID,
        )
    )

    action_kinds = [action.kind for action in response.actions]
    assert action_kinds == [
        "search_cached_offers",
        "build_date_matrix",
        "find_nearby_airports",
        "create_watch",
        "offer_live_check",
    ]
    assert watch_creator.created == [("WAW", "BCN", "2026-10-12", "2026-10-19")]
    assert response.audit_events
    assert all("следи" not in event.summary.lower() for event in response.audit_events)


@pytest.mark.anyio
async def test_agent_chat_does_not_create_watch_without_explicit_monitoring_words() -> None:
    watch_creator = RecordingWatchCreator()
    service = _service(watch_creator=watch_creator)

    response = await service.handle_turn(
        AgentTurnRequest(
            message="WAW BCN 2026-10-12 2026-10-19",
            household_id=HOUSEHOLD_ID,
            user_id=USER_ID,
        )
    )

    action_kinds = [action.kind for action in response.actions]
    assert "create_watch" not in action_kinds
    assert "propose_watch" in action_kinds
    assert watch_creator.created == []


class RecordingWatchCreator:
    def __init__(self) -> None:
        self.created: list[tuple[str, str, str, str | None]] = []

    async def create_watch(
        self,
        *,
        household_id: UUID,
        user_id: UUID,
        origin: str,
        destination: str,
        departure_date: str,
        return_date: str | None,
    ) -> WatchRecord:
        self.created.append((origin, destination, departure_date, return_date))
        return WatchRecord(
            id=UUID("cccccccc-cccc-cccc-cccc-cccccccccccc"),
            household_id=household_id,
            owner_user_id=user_id,
            origin=origin,
            destination=destination,
            departure_date=departure_date,
            return_date=return_date,
            passengers=1,
            currency="RUB",
            enabled=True,
            paused_until=None,
            next_eligible_at=NOW,
            scan_interval_seconds=21_600,
            allowed_provider_ids=(),
            last_scanned_at=None,
            last_scan_status=None,
            last_scan_error_code=None,
            created_at=NOW,
            updated_at=NOW,
            version=1,
            archived_at=None,
            archived_by_user_id=None,
            deleted_at=None,
            deleted_by_user_id=None,
        )


def _service(watch_creator: RecordingWatchCreator | None = None) -> AgentChatService:
    registry = ProviderRegistry.default(clock=lambda: NOW)
    return AgentChatService(
        airport_service=AirportService(repository=DemoAirportRepository()),
        date_matrix_planner=DateMatrixPlanner(),
        search_service=DemoSearchService(registry=registry, clock=lambda: NOW),
        watch_creator=watch_creator,
        clock=lambda: NOW,
    )
