from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from uuid import UUID

from flight_hunter.application.live_observations import (
    BrowserSourceCatalog,
    GrantIssueCode,
    GrantSource,
    LiveObservationCreateCode,
    LiveObservationService,
    search_intent_fingerprint,
)
from flight_hunter.domain.observation import ObservationStatus
from flight_hunter.domain.offers import Freshness, SearchIntent
from flight_hunter.domain.places import PlaceKind
from flight_hunter.domain.policy import ExecutionContext

NOW = datetime(2026, 6, 23, 12, 0, tzinfo=UTC)
USER_ID = UUID("11111111-1111-1111-1111-111111111111")
OTHER_USER_ID = UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")


def intent() -> SearchIntent:
    return SearchIntent(
        origin="WAW",
        destination="BCN",
        departure_date="2026-10-12",
        return_date="2026-10-19",
        passengers=2,
        currency="RUB",
    )


def service(*, enabled: bool = True) -> LiveObservationService:
    return LiveObservationService(
        catalog=BrowserSourceCatalog.demo(enabled=enabled, clock=lambda: NOW),
        clock=lambda: NOW,
        grant_ttl=timedelta(minutes=5),
    )


def test_search_intent_fingerprint_includes_resolved_place_snapshot() -> None:
    legacy = intent()
    resolved = replace(
        legacy,
        origin_kind=PlaceKind.AIRPORT,
        origin_airport_codes=("WAW",),
        destination_airport_codes=("BCN",),
        directory_version="directory-v2",
        origin_membership_version="origin-v2",
        destination_membership_version="destination-v2",
    )

    assert search_intent_fingerprint(legacy) != search_intent_fingerprint(resolved)


def test_issue_grant_requires_enabled_source_with_active_permission() -> None:
    disabled_service = service(enabled=False)

    decision = disabled_service.issue_grant(
        user_id=USER_ID,
        source_id="demo_browser",
        search_intent=intent(),
        source=GrantSource.WEB_CLICK,
    )

    assert not decision.allowed
    assert decision.code == GrantIssueCode.SOURCE_DISABLED


def test_live_observation_consumes_one_time_grant_and_fake_worker_marks_live_observed() -> None:
    live_service = service()
    grant = live_service.issue_grant(
        user_id=USER_ID,
        source_id="demo_browser",
        search_intent=intent(),
        source=GrantSource.WEB_CLICK,
    )

    created = live_service.create_observation(
        user_id=USER_ID,
        source_id="demo_browser",
        search_intent=intent(),
        grant_token=grant.grant_token,
        idempotency_key="idem-1",
        context=ExecutionContext.WEB_USER_ACTION,
    )

    assert created.accepted
    assert created.code == LiveObservationCreateCode.QUEUED
    assert created.initial_status == ObservationStatus.QUEUED
    observation = live_service.get_observation(
        user_id=USER_ID,
        observation_id=created.observation_id,
    )
    assert observation is not None
    assert observation.status == ObservationStatus.SUCCEEDED
    assert observation.offers[0].freshness == Freshness.LIVE_OBSERVED
    assert observation.offers[0].requires_live_confirmation is True

    replay = live_service.create_observation(
        user_id=USER_ID,
        source_id="demo_browser",
        search_intent=intent(),
        grant_token=grant.grant_token,
        idempotency_key="idem-2",
        context=ExecutionContext.WEB_USER_ACTION,
    )
    assert not replay.accepted
    assert replay.code == LiveObservationCreateCode.USER_ACTION_GRANT_CONSUMED


def test_live_observation_creation_is_idempotent_for_same_user_and_key() -> None:
    live_service = service()
    grant = live_service.issue_grant(
        user_id=USER_ID,
        source_id="demo_browser",
        search_intent=intent(),
        source=GrantSource.WEB_CLICK,
    )

    first = live_service.create_observation(
        user_id=USER_ID,
        source_id="demo_browser",
        search_intent=intent(),
        grant_token=grant.grant_token,
        idempotency_key="idem-1",
        context=ExecutionContext.WEB_USER_ACTION,
    )
    second = live_service.create_observation(
        user_id=USER_ID,
        source_id="demo_browser",
        search_intent=intent(),
        grant_token=grant.grant_token,
        idempotency_key="idem-1",
        context=ExecutionContext.WEB_USER_ACTION,
    )

    assert first.observation_id == second.observation_id
    assert second.code == LiveObservationCreateCode.QUEUED


def test_worker_context_cannot_create_live_observation_or_consume_grant() -> None:
    live_service = service()
    grant = live_service.issue_grant(
        user_id=USER_ID,
        source_id="demo_browser",
        search_intent=intent(),
        source=GrantSource.WEB_CLICK,
    )

    denied = live_service.create_observation(
        user_id=USER_ID,
        source_id="demo_browser",
        search_intent=intent(),
        grant_token=grant.grant_token,
        idempotency_key="idem-worker",
        context=ExecutionContext.WORKER,
    )
    allowed_after_denial = live_service.create_observation(
        user_id=USER_ID,
        source_id="demo_browser",
        search_intent=intent(),
        grant_token=grant.grant_token,
        idempotency_key="idem-user",
        context=ExecutionContext.WEB_USER_ACTION,
    )

    assert denied.code == LiveObservationCreateCode.BACKGROUND_NOT_ALLOWED
    assert allowed_after_denial.accepted


def test_observation_lookup_is_user_scoped() -> None:
    live_service = service()
    grant = live_service.issue_grant(
        user_id=USER_ID,
        source_id="demo_browser",
        search_intent=intent(),
        source=GrantSource.WEB_CLICK,
    )
    created = live_service.create_observation(
        user_id=USER_ID,
        source_id="demo_browser",
        search_intent=intent(),
        grant_token=grant.grant_token,
        idempotency_key="idem-1",
        context=ExecutionContext.WEB_USER_ACTION,
    )

    assert (
        live_service.get_observation(
            user_id=OTHER_USER_ID,
            observation_id=created.observation_id,
        )
        is None
    )
