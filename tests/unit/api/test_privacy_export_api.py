from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from flight_hunter.api.app import create_app
from flight_hunter.domain.manual_confirmation import (
    ManualConfirmationStatus,
    ManualPriceConfirmation,
)
from flight_hunter.domain.money import Money
from flight_hunter.domain.offers import Freshness
from flight_hunter.domain.search_results import (
    BrowserObservedOffer,
    Confidence,
    DealCandidate,
    ResultKind,
)
from flight_hunter.persistence.models import mapper_registry
from flight_hunter.persistence.repositories import (
    AuditEventRepository,
    BrowserObservedOfferRepository,
    DealCandidateRepository,
    HouseholdWatchRepository,
    ManualPriceConfirmationRepository,
    NewAuditEvent,
    NewDealCandidate,
    NewWatch,
)

HOUSEHOLD_A = UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
HOUSEHOLD_B = UUID("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb")
USER_A = UUID("aaaaaaaa-0000-0000-0000-000000000001")
USER_A_OTHER = UUID("aaaaaaaa-0000-0000-0000-000000000002")
USER_B = UUID("bbbbbbbb-0000-0000-0000-000000000001")
WATCH_ACTIVE = UUID("11111111-1111-1111-1111-111111111111")
WATCH_DELETED = UUID("22222222-2222-2222-2222-222222222222")
WATCH_OTHER = UUID("33333333-3333-3333-3333-333333333333")
NOW = datetime(2026, 6, 29, 15, 0, tzinfo=UTC)


@pytest.mark.anyio
async def test_privacy_export_requires_household_context() -> None:
    client = TestClient(create_app(watch_session_factory=await _session_factory()))

    response = client.post("/api/v1/privacy/export")

    assert response.status_code == 401
    assert response.json() == {
        "code": "auth_context_missing",
        "message": "household context is required",
    }


@pytest.mark.anyio
async def test_privacy_export_is_scoped_and_omits_internal_fields() -> None:
    session_factory = await _session_factory()
    await _seed_privacy_data(session_factory)
    client = TestClient(create_app(watch_session_factory=session_factory))

    response = client.post("/api/v1/privacy/export", headers=_headers(HOUSEHOLD_A, USER_A))

    assert response.status_code == 200
    body = response.json()
    assert body["format_version"] == 1
    assert body["household_id"] == str(HOUSEHOLD_A)
    assert body["user_id"] == str(USER_A)
    assert body["collection_limits"] == {
        "watches": 500,
        "audit_events": 500,
        "manual_price_confirmations": 500,
        "browser_observed_offers": 500,
        "deal_candidates": 500,
    }
    assert body["truncated"] == {
        "watches": False,
        "audit_events": False,
        "manual_price_confirmations": False,
        "browser_observed_offers": False,
        "deal_candidates": False,
    }
    assert body["omitted_fields"] == [
        "provider_secrets",
        "raw_payloads",
        "raw_ref",
        "idempotency_keys",
        "session_tokens",
        "telegram_payload_json",
        "worker_queue_payloads",
    ]

    exported_watch_ids = {watch["id"] for watch in body["watches"]}
    assert exported_watch_ids == {str(WATCH_ACTIVE), str(WATCH_DELETED)}
    deleted_watch = next(watch for watch in body["watches"] if watch["id"] == str(WATCH_DELETED))
    assert deleted_watch["deleted_at"] == "2026-06-29T15:05:00+00:00"
    assert deleted_watch["deleted_by_user_id"] == str(USER_A)

    assert [event["action"] for event in body["audit_events"]] == ["watch.deleted"]
    assert [confirmation["target_id"] for confirmation in body["manual_price_confirmations"]] == [
        "target-a"
    ]
    assert [offer["provider_offer_id"] for offer in body["browser_observed_offers"]] == ["offer-a"]
    assert [candidate["title"] for candidate in body["deal_candidates"]] == ["Owner deal"]

    response_text = response.text
    assert "raw-secret-ref" not in response_text
    assert "Other user deal" not in response_text
    assert str(HOUSEHOLD_B) not in response_text
    assert '"session_token":' not in response_text
    assert '"idempotency_key":' not in response_text

    async with session_factory() as session:
        audit_events = await AuditEventRepository(session).list_recent(HOUSEHOLD_A, limit=1)

    assert audit_events[0].action == "privacy.exported"
    assert audit_events[0].actor_user_id == USER_A
    assert audit_events[0].entity_id == HOUSEHOLD_A


async def _seed_privacy_data(session_factory: async_sessionmaker) -> None:
    async with session_factory() as session:
        watches = HouseholdWatchRepository(session)
        await watches.add_watch(_watch(WATCH_ACTIVE, HOUSEHOLD_A, USER_A))
        await watches.add_watch(
            _watch(
                WATCH_DELETED,
                HOUSEHOLD_A,
                USER_A,
                origin="LED",
                destination="IST",
                created_at=NOW + timedelta(minutes=1),
            )
        )
        await watches.add_watch(_watch(WATCH_OTHER, HOUSEHOLD_B, USER_B))
        await watches.delete_watch(
            household_id=HOUSEHOLD_A,
            watch_id=WATCH_DELETED,
            expected_version=1,
            deleted_at=NOW + timedelta(minutes=5),
            deleted_by_user_id=USER_A,
        )

        audit = AuditEventRepository(session)
        await audit.add_event(
            NewAuditEvent(
                id=UUID("44444444-4444-4444-4444-444444444441"),
                household_id=HOUSEHOLD_A,
                actor_user_id=USER_A,
                action="watch.deleted",
                entity_type="watch",
                entity_id=WATCH_DELETED,
                summary="watch deleted",
                created_at=NOW + timedelta(minutes=5),
            )
        )
        await audit.add_event(
            NewAuditEvent(
                id=UUID("44444444-4444-4444-4444-444444444442"),
                household_id=HOUSEHOLD_B,
                actor_user_id=USER_B,
                action="watch.created",
                entity_type="watch",
                entity_id=WATCH_OTHER,
                summary="other household watch created",
                created_at=NOW + timedelta(minutes=6),
            )
        )

        confirmations = ManualPriceConfirmationRepository(session)
        await confirmations.add_confirmation(
            _confirmation(USER_A, "target-a", ManualConfirmationStatus.CONFIRMED)
        )
        await confirmations.add_confirmation(
            _confirmation(
                USER_A_OTHER,
                "target-other-user",
                ManualConfirmationStatus.PRICE_CHANGED,
            )
        )

        observed = BrowserObservedOfferRepository(session)
        await observed.add_offer(
            household_id=HOUSEHOLD_A,
            user_id=USER_A,
            search_id="search-a",
            offer=_browser_offer("offer-a", "https://tutu.example/flights/a"),
            expires_at=NOW + timedelta(days=1),
        )
        await observed.add_offer(
            household_id=HOUSEHOLD_A,
            user_id=USER_A_OTHER,
            search_id="search-other-user",
            offer=_browser_offer("offer-other", "https://tutu.example/flights/other"),
            expires_at=NOW + timedelta(days=1),
        )

        deals = DealCandidateRepository(session)
        await deals.add_candidate(
            _new_deal(
                id_value=UUID("55555555-5555-5555-5555-555555555551"),
                user_id=USER_A,
                title="Owner deal",
                raw_ref="raw-secret-ref",
            )
        )
        await deals.add_candidate(
            _new_deal(
                id_value=UUID("55555555-5555-5555-5555-555555555552"),
                user_id=USER_A_OTHER,
                title="Other user deal",
                raw_ref="other-raw-secret-ref",
            )
        )
        await session.commit()


def _watch(
    watch_id: UUID,
    household_id: UUID,
    user_id: UUID,
    *,
    origin: str = "MOW",
    destination: str = "AYT",
    created_at: datetime = NOW,
) -> NewWatch:
    return NewWatch(
        id=watch_id,
        household_id=household_id,
        owner_user_id=user_id,
        origin=origin,
        destination=destination,
        departure_date="2026-09-10",
        return_date=None,
        created_at=created_at,
    )


def _confirmation(
    user_id: UUID,
    target_id: str,
    status: ManualConfirmationStatus,
) -> ManualPriceConfirmation:
    return ManualPriceConfirmation(
        id=UUID(int=abs(hash((str(user_id), target_id))) % (2**128)),
        household_id=HOUSEHOLD_A,
        user_id=user_id,
        target_kind=ResultKind.BROWSER_OBSERVATION,
        target_id=target_id,
        source_id="tutu",
        status=status,
        confirmed_price=Money(1_234_500, "RUB") if status == "confirmed" else None,
        note="checked manually",
        confirmed_at=NOW + timedelta(minutes=7),
    )


def _browser_offer(provider_offer_id: str, url: str) -> BrowserObservedOffer:
    return BrowserObservedOffer(
        observation_id=UUID(int=abs(hash(provider_offer_id)) % (2**128)),
        source_id="tutu",
        source_name="Tutu",
        provider_offer_id=provider_offer_id,
        origin="MOW",
        destination="AYT",
        departure_date="2026-09-10",
        return_date=None,
        total_price=Money(1_234_500, "RUB"),
        passengers=1,
        observed_at=NOW + timedelta(minutes=8),
        final_url=url,
        display_url="tutu.example",
        freshness=Freshness.BROWSER_OBSERVED,
        confidence=Confidence.HIGH,
        parser_version="test",
        parser_warnings=(),
        requires_external_confirmation=True,
    )


def _new_deal(
    *,
    id_value: UUID,
    user_id: UUID,
    title: str,
    raw_ref: str,
) -> NewDealCandidate:
    expires_at = NOW + timedelta(days=2)
    return NewDealCandidate(
        id=id_value,
        household_id=HOUSEHOLD_A,
        user_id=user_id,
        search_id="search-a",
        candidate=DealCandidate(
            source_id="deal_discovery",
            url=f"https://example.com/deals/{id_value}",
            title=title,
            summary_ru="Manual verification required.",
            extracted_price=Money(1_234_500, "RUB"),
            extracted_origin="MOW",
            extracted_destination="AYT",
            extracted_date_window="2026-09-10",
            confidence=Confidence.MEDIUM,
            discovered_at=NOW + timedelta(minutes=9),
            expires_at=expires_at,
            requires_manual_verification=True,
        ),
        expires_at=expires_at,
        raw_ref=raw_ref,
    )


def _headers(household_id: UUID, user_id: UUID) -> dict[str, str]:
    return {
        "X-Flight-Hunter-Household-Id": str(household_id),
        "X-Flight-Hunter-User-Id": str(user_id),
    }


async def _session_factory() -> async_sessionmaker:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(mapper_registry.metadata.create_all)
    return async_sessionmaker(engine, expire_on_commit=False)
