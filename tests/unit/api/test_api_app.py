from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from flight_hunter.api.app import create_app
from flight_hunter.deals.url_policy import DealUrlPolicyError
from flight_hunter.domain.money import Money
from flight_hunter.domain.observation import ObservationStatus
from flight_hunter.domain.offers import Freshness
from flight_hunter.domain.search_results import BrowserObservedOffer, Confidence, DealCandidate
from flight_hunter.persistence.models import mapper_registry
from flight_hunter.persistence.repositories import (
    BrowserObservationJobRepository,
    BrowserObservedOfferRepository,
    SourceHealthEventRepository,
)

HOUSEHOLD_ID = UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
USER_ID = UUID("11111111-1111-1111-1111-111111111111")
NOW = datetime(2026, 6, 29, 16, 30, tzinfo=UTC)
TUTU_SOURCE_FIXTURE = Path("tests/fixtures/browser/tutu/search_result_source_specific.html")


def test_health_endpoint_reports_ready_without_external_credentials() -> None:
    client = TestClient(create_app())

    response = client.get("/healthz")

    assert response.status_code == 200
    assert response.json() == {
        "app": "Flight Hunter",
        "status": "ok",
        "external_credentials_required": False,
    }


def test_providers_endpoint_exposes_disabled_reasons_without_secrets() -> None:
    client = TestClient(create_app())

    response = client.get("/api/v1/providers")

    assert response.status_code == 200
    providers = {item["provider_id"]: item for item in response.json()["providers"]}
    assert providers["fake"]["enabled"] is True
    assert providers["aviasales_search"]["merge_scope"] == "mergeable"
    assert providers["aviasales_search"]["background_requests_allowed"] is True
    assert "credentials_missing" in providers["aviasales_search"]["blocked_reasons"]
    assert "token" not in str(response.json()).lower()


def test_search_endpoint_returns_demo_cached_result_and_provider_denials() -> None:
    client = TestClient(create_app())

    response = client.post(
        "/api/v1/searches",
        json={
            "origin": "WAW",
            "destination": "BCN",
            "departure_date": "2026-10-12",
            "return_date": "2026-10-19",
            "passengers": 2,
            "currency": "PLN",
        },
    )

    assert response.status_code == 201
    body = response.json()
    assert body["priced_offers"] == body["offers"]
    assert body["browser_observed_offers"] == []
    assert body["deal_candidates"] == []
    assert body["freshness_summary"]["needs_external_confirmation"] is True
    assert body["freshness_summary"]["best_price_source"] == "fake"
    assert "external_links_are_not_prices" in body["warnings"]
    assert {link["source_id"] for link in body["external_links"]} >= {
        "aviasales_clickout",
        "tutu",
        "yandex_travel",
    }
    assert body["external_links"][0]["price_known"] is False
    assert body["offers"][0]["provider_id"] == "fake"
    assert body["offers"][0]["freshness"] == "cached"
    assert body["offers"][0]["requires_live_confirmation"] is True
    assert body["offers"][0]["price_basis"] == "total_for_passengers"
    assert body["offers"][0]["total_price"]["minor_units"] == 159800
    assert body["offers"][0]["ranking_reasons"] == [
        "cached_price",
        "requires_live_confirmation",
        "baggage_unknown",
    ]
    assert body["offers"][0]["risk"] == {
        "level": "medium",
        "flags": [
            "cached_price",
            "requires_live_confirmation",
            "baggage_unknown",
        ],
        "explanations": [
            "Price came from cached data and must be checked before purchase.",
            "Provider requires a live confirmation before purchase.",
            "Baggage and fare-rule data are not available for this offer.",
        ],
    }
    assert "aviasales_search" in body["denied_providers"]


def test_search_endpoint_logs_safe_structured_started_event(caplog) -> None:
    caplog.set_level(logging.INFO, logger="flight_hunter.observability")
    client = TestClient(create_app())
    headers = {
        "X-Flight-Hunter-Household-Id": str(HOUSEHOLD_ID),
        "X-Flight-Hunter-User-Id": str(USER_ID),
    }

    response = client.post(
        "/api/v1/searches",
        headers=headers,
        json={
            "origin": "MOW",
            "destination": "IST",
            "departure_date": "2026-09-10",
            "return_date": "2026-09-20",
            "passengers": 1,
            "currency": "RUB",
        },
    )

    assert response.status_code == 201
    payload = _logged_event(caplog, "search_started")
    assert payload["search_id"] == response.json()["search_id"]
    assert payload["household_id"] == str(HOUSEHOLD_ID)
    assert payload["priced_offer_count"] >= 1
    assert isinstance(payload["duration_ms"], int)
    log_text = "\n".join(record.getMessage() for record in caplog.records)
    assert "MOW" not in log_text
    assert "IST" not in log_text
    assert "authorization" not in log_text.lower()


def test_deal_discovery_endpoint_is_disabled_without_crawler_settings() -> None:
    client = TestClient(create_app())

    response = client.post(
        "/api/v1/deals/discover",
        json={
            "search_intent": {
                "origin": "MOW",
                "destination": "IST",
                "departure_date": "2026-09-10",
                "return_date": "2026-09-20",
                "passengers": 1,
                "currency": "RUB",
            }
        },
    )

    assert response.status_code == 503
    assert response.json()["code"] == "deal_discovery_disabled"


def test_deal_discovery_endpoint_returns_manual_candidates_from_injected_service() -> None:
    client = TestClient(create_app(deal_discovery_service=FakeDealDiscoveryService()))

    response = client.post(
        "/api/v1/deals/discover",
        json={
            "search_intent": {
                "origin": "MOW",
                "destination": "IST",
                "departure_date": "2026-09-10",
                "return_date": "2026-09-20",
                "passengers": 1,
                "currency": "RUB",
            },
            "limit": 3,
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["warnings"] == ["deal_candidates_require_manual_verification"]
    assert body["candidates"][0]["kind"] == "deal_candidate"
    assert body["candidates"][0]["requires_manual_verification"] is True
    assert body["candidates"][0]["expires_at"] is not None
    assert datetime.fromisoformat(body["candidates"][0]["expires_at"]) > datetime.fromisoformat(
        body["candidates"][0]["discovered_at"]
    )


def test_deal_discovery_job_endpoint_requires_auth_context() -> None:
    client = TestClient(create_app(deal_discovery_service=FakeDealDiscoveryService()))

    response = client.post(
        "/api/v1/deals/discovery-jobs",
        headers={"Idempotency-Key": "deal-job-idem-1"},
        json={
            "search_id": "sha256:search",
            "search_intent": {
                "origin": "MOW",
                "destination": "IST",
                "departure_date": "2026-09-10",
                "return_date": "2026-09-20",
                "passengers": 1,
                "currency": "RUB",
            },
        },
    )

    assert response.status_code == 401
    assert response.json()["code"] == "auth_context_missing"


def test_deal_discovery_job_endpoint_is_disabled_without_crawler_settings() -> None:
    client = TestClient(create_app())

    response = client.post(
        "/api/v1/deals/discovery-jobs",
        headers={
            "X-Flight-Hunter-Household-Id": str(HOUSEHOLD_ID),
            "X-Flight-Hunter-User-Id": str(USER_ID),
            "Idempotency-Key": "deal-job-idem-1",
        },
        json={
            "search_id": "sha256:search",
            "search_intent": {
                "origin": "MOW",
                "destination": "IST",
                "departure_date": "2026-09-10",
                "return_date": "2026-09-20",
                "passengers": 1,
                "currency": "RUB",
            },
        },
    )

    assert response.status_code == 503
    assert response.json()["code"] == "deal_discovery_disabled"


@pytest.mark.anyio
async def test_deal_discovery_job_api_enqueues_idempotently_and_scopes_status() -> None:
    session_factory = await _session_factory()
    client = TestClient(
        create_app(
            watch_session_factory=session_factory,
            deal_discovery_service=FakeDealDiscoveryService(),
        )
    )
    headers = {
        "X-Flight-Hunter-Household-Id": str(HOUSEHOLD_ID),
        "X-Flight-Hunter-User-Id": str(USER_ID),
        "Idempotency-Key": "deal-job-idem-1",
    }
    body = {
        "search_id": "sha256:search",
        "search_intent": {
            "origin": "MOW",
            "destination": "IST",
            "departure_date": "2026-09-10",
            "return_date": "2026-09-20",
            "passengers": 1,
            "currency": "RUB",
        },
        "limit": 3,
    }

    created = client.post("/api/v1/deals/discovery-jobs", headers=headers, json=body)
    replay = client.post("/api/v1/deals/discovery-jobs", headers=headers, json=body)
    job_id = created.json()["job_id"]
    status = client.get(f"/api/v1/deals/discovery-jobs/{job_id}", headers=headers)
    other_user = client.get(
        f"/api/v1/deals/discovery-jobs/{job_id}",
        headers={**headers, "X-Flight-Hunter-User-Id": str(UUID(int=2))},
    )

    assert created.status_code == 202
    assert replay.status_code == 202
    assert replay.json()["job_id"] == job_id
    assert replay.json()["idempotent_replay"] is True
    assert status.status_code == 200
    assert status.json()["status"] == "queued"
    assert status.json()["search_id"] == "sha256:search"
    assert status.json()["candidates"] == []
    assert other_user.status_code == 404
    assert other_user.json()["code"] == "deal_discovery_job_not_found"


@pytest.mark.anyio
async def test_deal_discovery_endpoint_records_source_health_on_success() -> None:
    session_factory = await _session_factory()
    client = TestClient(
        create_app(
            deal_discovery_service=FakeDealDiscoveryService(),
            watch_session_factory=session_factory,
        )
    )

    response = client.post(
        "/api/v1/deals/discover",
        json={
            "search_intent": {
                "origin": "MOW",
                "destination": "IST",
                "departure_date": "2026-09-10",
                "return_date": "2026-09-20",
                "passengers": 1,
                "currency": "RUB",
            }
        },
    )

    assert response.status_code == 200
    events = await _source_health_events(session_factory, "deal_discovery")
    assert len(events) == 1
    assert events[0].status == "ok"
    assert "candidates=1" in events[0].message


@pytest.mark.anyio
async def test_deal_discovery_endpoint_returns_typed_error_and_health_on_url_rejection() -> None:
    session_factory = await _session_factory()
    client = TestClient(
        create_app(
            deal_discovery_service=FailingDealDiscoveryService(),
            watch_session_factory=session_factory,
        )
    )

    response = client.post(
        "/api/v1/deals/discover",
        json={
            "search_intent": {
                "origin": "MOW",
                "destination": "IST",
                "departure_date": "2026-09-10",
                "return_date": "2026-09-20",
                "passengers": 1,
                "currency": "RUB",
            }
        },
    )

    assert response.status_code == 502
    assert response.json()["code"] == "deal_discovery_url_rejected"
    events = await _source_health_events(session_factory, "deal_discovery")
    assert len(events) == 1
    assert events[0].status == "failed"
    assert "deal_url_blocked_ip" in events[0].message


@pytest.mark.anyio
async def test_search_endpoint_returns_user_scoped_browser_observed_offers() -> None:
    session_factory = await _session_factory()
    client = TestClient(create_app(watch_session_factory=session_factory))
    request = {
        "origin": "MOW",
        "destination": "IST",
        "departure_date": "2026-09-10",
        "return_date": "2026-09-20",
        "passengers": 1,
        "currency": "RUB",
    }
    headers = {
        "X-Flight-Hunter-Household-Id": str(HOUSEHOLD_ID),
        "X-Flight-Hunter-User-Id": str(USER_ID),
    }
    first = client.post("/api/v1/searches", headers=headers, json=request)
    search_id = first.json()["search_id"]

    async with session_factory() as session:
        repository = BrowserObservedOfferRepository(session)
        await repository.add_offer(
            household_id=HOUSEHOLD_ID,
            user_id=USER_ID,
            search_id=search_id,
            offer=_browser_offer(),
            expires_at=datetime(2030, 1, 1, tzinfo=UTC),
        )
        await session.commit()

    response = client.post("/api/v1/searches", headers=headers, json=request)
    other_user_response = client.post(
        "/api/v1/searches",
        headers={**headers, "X-Flight-Hunter-User-Id": str(UUID(int=2))},
        json=request,
    )

    assert response.status_code == 201
    observed = response.json()["browser_observed_offers"]
    assert len(observed) == 1
    assert observed[0]["source_id"] == "tutu"
    assert observed[0]["freshness"] == "browser_observed"
    assert observed[0]["confidence"] == "medium"
    assert observed[0]["observed_at"] == NOW.isoformat()
    freshest_observation_at = datetime.fromisoformat(
        response.json()["freshness_summary"]["freshest_observation_at"]
    )
    assert freshest_observation_at >= NOW
    assert other_user_response.json()["browser_observed_offers"] == []


@pytest.mark.anyio
async def test_deal_discovery_persists_user_scoped_candidates_for_search() -> None:
    session_factory = await _session_factory()
    client = TestClient(
        create_app(
            watch_session_factory=session_factory,
            deal_discovery_service=FakeDealDiscoveryService(),
        )
    )
    request = {
        "origin": "MOW",
        "destination": "IST",
        "departure_date": "2026-09-10",
        "return_date": "2026-09-20",
        "passengers": 1,
        "currency": "RUB",
    }
    headers = {
        "X-Flight-Hunter-Household-Id": str(HOUSEHOLD_ID),
        "X-Flight-Hunter-User-Id": str(USER_ID),
    }
    search_id = client.post("/api/v1/searches", headers=headers, json=request).json()["search_id"]

    discovery = client.post(
        "/api/v1/deals/discover",
        headers=headers,
        json={"search_id": search_id, "search_intent": request, "limit": 3},
    )
    response = client.post("/api/v1/searches", headers=headers, json=request)
    other_user_response = client.post(
        "/api/v1/searches",
        headers={**headers, "X-Flight-Hunter-User-Id": str(UUID(int=2))},
        json=request,
    )

    assert discovery.status_code == 200
    assert response.status_code == 201
    body = response.json()
    assert len(body["deal_candidates"]) == 1
    assert body["deal_candidates"][0]["kind"] == "deal_candidate"
    assert body["deal_candidates"][0]["extracted_price"]["minor_units"] == 1_842_000
    assert body["deal_candidates"][0]["expires_at"] is not None
    assert "deal_candidates_require_manual_verification" in body["warnings"]
    assert body["offers"] == body["priced_offers"]
    assert all(offer["provider_id"] != "deal_discovery" for offer in body["priced_offers"])
    assert other_user_response.json()["deal_candidates"] == []


@pytest.mark.anyio
async def test_manual_price_confirmation_api_records_user_scoped_history() -> None:
    session_factory = await _session_factory()
    client = TestClient(create_app(watch_session_factory=session_factory))
    headers = {
        "X-Flight-Hunter-Household-Id": str(HOUSEHOLD_ID),
        "X-Flight-Hunter-User-Id": str(USER_ID),
    }
    other_user_headers = {**headers, "X-Flight-Hunter-User-Id": str(UUID(int=2))}

    created = client.post(
        "/api/v1/manual-price-confirmations",
        headers=headers,
        json={
            "target_kind": "browser_observation",
            "target_id": "obs-1",
            "source_id": "tutu",
            "status": "confirmed",
            "amount_minor": 1_842_000,
            "currency": "RUB",
            "note": "checked after opening provider page",
        },
    )
    other_user = client.post(
        "/api/v1/manual-price-confirmations",
        headers=other_user_headers,
        json={
            "target_kind": "browser_observation",
            "target_id": "obs-1",
            "source_id": "tutu",
            "status": "sold_out",
        },
    )
    listing = client.get("/api/v1/manual-price-confirmations", headers=headers)
    filtered = client.get(
        "/api/v1/manual-price-confirmations",
        headers=headers,
        params={"target_kind": "browser_observation", "target_id": "obs-1"},
    )
    other_user_listing = client.get(
        "/api/v1/manual-price-confirmations",
        headers=other_user_headers,
    )

    assert created.status_code == 201
    assert other_user.status_code == 201
    body = created.json()
    assert body["household_id"] == str(HOUSEHOLD_ID)
    assert body["user_id"] == str(USER_ID)
    assert body["target_kind"] == "browser_observation"
    assert body["status"] == "confirmed"
    assert body["confirmed_price"]["minor_units"] == 1_842_000
    assert body["confirmed_price"]["currency"] == "RUB"
    assert listing.status_code == 200
    assert [item["status"] for item in listing.json()["confirmations"]] == ["confirmed"]
    assert filtered.json()["confirmations"][0]["target_id"] == "obs-1"
    assert other_user_listing.json()["confirmations"][0]["status"] == "sold_out"


def test_manual_price_confirmation_api_requires_auth_context() -> None:
    client = TestClient(create_app())

    response = client.post(
        "/api/v1/manual-price-confirmations",
        json={
            "target_kind": "browser_observation",
            "target_id": "obs-1",
            "source_id": "tutu",
            "status": "confirmed",
        },
    )

    assert response.status_code == 401
    assert response.json()["code"] == "auth_context_missing"


def test_manual_price_confirmation_api_rejects_partial_price() -> None:
    client = TestClient(create_app())
    headers = {
        "X-Flight-Hunter-Household-Id": str(HOUSEHOLD_ID),
        "X-Flight-Hunter-User-Id": str(USER_ID),
    }

    response = client.post(
        "/api/v1/manual-price-confirmations",
        headers=headers,
        json={
            "target_kind": "browser_observation",
            "target_id": "obs-1",
            "source_id": "tutu",
            "status": "price_changed",
            "amount_minor": 1_900_000,
        },
    )

    assert response.status_code == 422


def test_search_endpoint_accepts_explicit_passenger_mix() -> None:
    client = TestClient(create_app())

    response = client.post(
        "/api/v1/searches",
        json={
            "origin": "WAW",
            "destination": "BCN",
            "departure_date": "2026-10-12",
            "return_date": "2026-10-19",
            "passengers": 3,
            "adults": 2,
            "children": 1,
            "infants": 0,
            "trip_type": "round_trip",
            "currency": "PLN",
        },
    )

    assert response.status_code == 201
    body = response.json()
    assert body["offers"][0]["passengers"] == 3
    assert body["offers"][0]["total_price"]["minor_units"] == 239700


def test_browser_source_parser_endpoint_parses_sanitized_fixture_without_echoing_html(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SCRAPLING_ENABLED", "false")
    client = TestClient(create_app())

    response = client.post(
        "/api/v1/browser-sources/tutu/test-parser",
        headers=_auth_headers(),
        json={
            "search_intent": _mow_ist_request(),
            "html": TUTU_SOURCE_FIXTURE.read_text(encoding="utf-8"),
            "title": "sanitized fixture",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["source_id"] == "tutu"
    assert body["confidence"] == "medium"
    assert body["html_hash"].startswith("sha256:")
    assert body["visible_text_hash"].startswith("sha256:")
    assert body["warnings"] == ["parser_stage:tutu"]
    assert body["offers"][0]["provider_offer_id"] == "tutu-realistic-1"
    assert body["offers"][0]["total_price"]["minor_units"] == 1_842_000
    assert "tutu-flight-card" not in response.text
    assert "<html" not in response.text.lower()


def test_browser_source_parser_endpoint_requires_auth_context() -> None:
    client = TestClient(create_app())

    response = client.post(
        "/api/v1/browser-sources/tutu/test-parser",
        json={"search_intent": _mow_ist_request(), "html": "<html>18 420 RUB</html>"},
    )

    assert response.status_code == 401
    assert response.json()["code"] == "auth_context_missing"


def test_browser_source_parser_endpoint_rejects_unsafe_url_and_non_observable_source() -> None:
    client = TestClient(create_app())
    payload = {
        "search_intent": _mow_ist_request(),
        "html": "<html>18 420 RUB</html>",
    }

    unsafe_url = client.post(
        "/api/v1/browser-sources/tutu/test-parser",
        headers=_auth_headers(),
        json={**payload, "final_url": "https://user:pass@www.tutu.ru/avia/"},
    )
    non_observable = client.post(
        "/api/v1/browser-sources/aviasales_clickout/test-parser",
        headers=_auth_headers(),
        json=payload,
    )

    assert unsafe_url.status_code == 422
    assert unsafe_url.json()["code"] == "invalid_final_url"
    assert non_observable.status_code == 403
    assert non_observable.json()["code"] == "source_not_observable"


@pytest.mark.anyio
async def test_personal_observation_api_queues_user_scoped_job(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("PERSONAL_OBSERVER_ENABLED", "true")
    monkeypatch.setenv("PERSONAL_OBSERVER_ALLOWED_HOSTS", "www.tutu.ru,tutu.ru,avia.tutu.ru")
    session_factory = await _session_factory()
    client = TestClient(create_app(watch_session_factory=session_factory))
    request = {
        "origin": "MOW",
        "destination": "IST",
        "departure_date": "2026-09-10",
        "return_date": "2026-09-20",
        "passengers": 1,
        "currency": "RUB",
    }
    headers = {
        "X-Flight-Hunter-Household-Id": str(HOUSEHOLD_ID),
        "X-Flight-Hunter-User-Id": str(USER_ID),
    }
    search_id = client.post("/api/v1/searches", headers=headers, json=request).json()["search_id"]
    grant = client.post(
        "/api/v1/personal-observations/grants",
        headers={"X-Flight-Hunter-User-Id": str(USER_ID)},
        json={"source_id": "tutu", "search_intent": request},
    )
    assert grant.status_code == 201

    created = client.post(
        "/api/v1/personal-observations",
        headers={**headers, "Idempotency-Key": "personal-idem-1"},
        json={
            "source_id": "tutu",
            "search_id": search_id,
            "search_intent": request,
            "grant_token": grant.json()["grant_token"],
        },
    )
    replay = client.post(
        "/api/v1/personal-observations",
        headers={**headers, "Idempotency-Key": "personal-idem-1"},
        json={
            "source_id": "tutu",
            "search_id": search_id,
            "search_intent": request,
            "grant_token": grant.json()["grant_token"],
        },
    )
    body = created.json()
    status = client.get(f"/api/v1/personal-observations/{body['job_id']}", headers=headers)
    other_household = client.get(
        f"/api/v1/personal-observations/{body['job_id']}",
        headers={**headers, "X-Flight-Hunter-Household-Id": str(UUID(int=9))},
    )

    assert created.status_code == 202
    assert body["status"] == "queued"
    assert body["idempotent_replay"] is False
    assert replay.status_code == 202
    assert replay.json()["job_id"] == body["job_id"]
    assert replay.json()["idempotent_replay"] is True
    assert status.status_code == 200
    assert status.json()["status"] == "queued"
    assert status.json()["attempts"] == 0
    assert status.json()["waiting_since"] is None
    assert status.json()["next_retry_at"] is None
    assert status.json()["operator_instruction"] is None
    assert status.json()["browser_observed_offers"] == []
    assert other_household.status_code == 404


@pytest.mark.anyio
async def test_personal_observation_api_controls_waiting_checkpoint(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("PERSONAL_OBSERVER_ENABLED", "true")
    monkeypatch.setenv("PERSONAL_OBSERVER_ALLOWED_HOSTS", "www.tutu.ru,tutu.ru,avia.tutu.ru")
    session_factory = await _session_factory()
    client = TestClient(create_app(watch_session_factory=session_factory))
    request = _mow_ist_request()
    headers = _auth_headers()
    search_id = client.post("/api/v1/searches", headers=headers, json=request).json()["search_id"]

    resume_job_id = _queue_personal_observation_job(client, headers, search_id, request, "resume")
    abort_job_id = _queue_personal_observation_job(client, headers, search_id, request, "abort")
    async with session_factory() as session:
        repository = BrowserObservationJobRepository(session)
        for job_id in (resume_job_id, abort_job_id):
            await repository.mark_running(job_id=UUID(job_id), started_at=NOW)
            await repository.mark_runtime_status(
                job_id=UUID(job_id),
                status=ObservationStatus.WAITING_FOR_USER,
                observed_at=NOW,
            )
        await session.commit()

    resumed = client.post(f"/api/v1/personal-observations/{resume_job_id}/resume", headers=headers)
    aborted = client.post(f"/api/v1/personal-observations/{abort_job_id}/abort", headers=headers)
    other_household = client.post(
        f"/api/v1/personal-observations/{abort_job_id}/resume",
        headers={**headers, "X-Flight-Hunter-Household-Id": str(UUID(int=9))},
    )
    resume_after_abort = client.post(
        f"/api/v1/personal-observations/{abort_job_id}/resume",
        headers=headers,
    )

    assert resumed.status_code == 200
    assert resumed.json()["status"] == "waiting_for_user"
    assert resumed.json()["operator_resume_requested_at"] is not None
    assert resumed.json()["operator_abort_requested_at"] is None
    assert "Resume requested" in resumed.json()["operator_instruction"]
    assert aborted.status_code == 200
    assert aborted.json()["operator_abort_requested_at"] is not None
    assert aborted.json()["operator_resume_requested_at"] is None
    assert "Abort requested" in aborted.json()["operator_instruction"]
    assert other_household.status_code == 404
    assert resume_after_abort.status_code == 409
    assert resume_after_abort.json()["code"] == "operator_checkpoint_not_active"


@pytest.mark.anyio
async def test_personal_observation_confirm_and_mark_stale_append_manual_ledger(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("PERSONAL_OBSERVER_ENABLED", "true")
    monkeypatch.setenv("PERSONAL_OBSERVER_ALLOWED_HOSTS", "www.tutu.ru,tutu.ru,avia.tutu.ru")
    session_factory = await _session_factory()
    client = TestClient(create_app(watch_session_factory=session_factory))
    request = _mow_ist_request()
    headers = _auth_headers()
    search_id = client.post("/api/v1/searches", headers=headers, json=request).json()["search_id"]
    grant = client.post(
        "/api/v1/personal-observations/grants",
        headers={"X-Flight-Hunter-User-Id": str(USER_ID)},
        json={"source_id": "tutu", "search_intent": request},
    )
    created = client.post(
        "/api/v1/personal-observations",
        headers={**headers, "Idempotency-Key": "personal-confirm-idem"},
        json={
            "source_id": "tutu",
            "search_id": search_id,
            "search_intent": request,
            "grant_token": grant.json()["grant_token"],
        },
    )
    job_id = created.json()["job_id"]

    confirmed = client.post(
        f"/api/v1/personal-observations/{job_id}/confirm",
        headers=headers,
        json={
            "status": "confirmed",
            "amount_minor": 1_842_000,
            "currency": "RUB",
            "note": "matched after opening provider",
        },
    )
    stale = client.post(
        f"/api/v1/personal-observations/{job_id}/mark-stale",
        headers=headers,
        json={"status": "sold_out", "note": "no seats after manual check"},
    )
    other_household = client.post(
        f"/api/v1/personal-observations/{job_id}/confirm",
        headers={**headers, "X-Flight-Hunter-Household-Id": str(UUID(int=9))},
        json={"status": "confirmed"},
    )
    listing = client.get(
        "/api/v1/manual-price-confirmations",
        headers=headers,
        params={"target_kind": "browser_observation", "target_id": job_id},
    )

    assert confirmed.status_code == 201
    assert confirmed.json()["target_kind"] == "browser_observation"
    assert confirmed.json()["target_id"] == job_id
    assert confirmed.json()["source_id"] == "tutu"
    assert confirmed.json()["confirmed_price"]["minor_units"] == 1_842_000
    assert stale.status_code == 201
    assert stale.json()["status"] == "sold_out"
    assert stale.json()["confirmed_price"] is None
    assert other_household.status_code == 404
    assert [item["status"] for item in listing.json()["confirmations"]] == [
        "sold_out",
        "confirmed",
    ]


def test_search_endpoint_respects_configured_clickout_source_allowlist(monkeypatch) -> None:
    monkeypatch.setenv("RU_AGGREGATORS_ENABLED", "tutu")
    monkeypatch.setenv("CARRIER_LINKS_ENABLED", "")
    client = TestClient(create_app())

    response = client.post(
        "/api/v1/searches",
        json={
            "origin": "WAW",
            "destination": "BCN",
            "departure_date": "2026-10-12",
            "return_date": "2026-10-19",
            "passengers": 2,
            "currency": "PLN",
        },
    )

    assert response.status_code == 201
    body = response.json()
    assert [link["source_id"] for link in body["external_links"]] == ["tutu"]


def test_search_endpoint_rejects_passenger_mix_total_mismatch() -> None:
    client = TestClient(create_app())

    response = client.post(
        "/api/v1/searches",
        json={
            "origin": "WAW",
            "destination": "BCN",
            "departure_date": "2026-10-12",
            "return_date": "2026-10-19",
            "passengers": 3,
            "adults": 1,
            "children": 0,
            "infants": 0,
            "trip_type": "round_trip",
            "currency": "PLN",
        },
    )

    assert response.status_code == 422


def test_providers_endpoint_can_show_aviasales_search_enabled_without_leaking_secrets(
    monkeypatch,
) -> None:
    monkeypatch.setenv("AVIASALES_SEARCH_ENABLED", "true")
    monkeypatch.setenv("AVIASALES_SEARCH_SIGNATURE", "secret-signature")
    monkeypatch.setenv("AVIASALES_SEARCH_MARKER", "secret-marker")
    client = TestClient(create_app())

    response = client.get("/api/v1/providers")

    assert response.status_code == 200
    providers = {item["provider_id"]: item for item in response.json()["providers"]}
    assert providers["aviasales_search"]["enabled"] is True
    assert providers["aviasales_search"]["credentials_present"] is True
    assert "secret-signature" not in str(response.json())
    assert "secret-marker" not in str(response.json())


async def _session_factory():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(mapper_registry.metadata.create_all)
    return async_sessionmaker(engine, expire_on_commit=False)


async def _source_health_events(session_factory, source_id: str):
    async with session_factory() as session:
        return await SourceHealthEventRepository(session).list_recent(source_id=source_id)


def _auth_headers() -> dict[str, str]:
    return {
        "X-Flight-Hunter-Household-Id": str(HOUSEHOLD_ID),
        "X-Flight-Hunter-User-Id": str(USER_ID),
    }


def _mow_ist_request() -> dict[str, object]:
    return {
        "origin": "MOW",
        "destination": "IST",
        "departure_date": "2026-09-10",
        "return_date": "2026-09-20",
        "passengers": 1,
        "currency": "RUB",
    }


def _queue_personal_observation_job(
    client: TestClient,
    headers: dict[str, str],
    search_id: str,
    request: dict[str, object],
    idempotency_suffix: str,
) -> str:
    grant = client.post(
        "/api/v1/personal-observations/grants",
        headers={"X-Flight-Hunter-User-Id": str(USER_ID)},
        json={"source_id": "tutu", "search_intent": request},
    )
    created = client.post(
        "/api/v1/personal-observations",
        headers={**headers, "Idempotency-Key": f"personal-control-{idempotency_suffix}"},
        json={
            "source_id": "tutu",
            "search_id": search_id,
            "search_intent": request,
            "grant_token": grant.json()["grant_token"],
        },
    )
    assert created.status_code == 202
    return str(created.json()["job_id"])


def _logged_event(caplog, event: str) -> dict[str, object]:
    for record in caplog.records:
        if record.name != "flight_hunter.observability":
            continue
        payload = json.loads(record.getMessage())
        if payload.get("event") == event:
            return payload
    raise AssertionError(f"missing structured log event {event}")


class FakeDealDiscoveryService:
    async def discover(self, intent, *, limit: int = 5):
        return (
            DealCandidate(
                source_id="deal_discovery",
                url="https://example.com/deal",
                title="Распродажа MOW IST",
                summary_ru="Возможная акция, требуется ручная проверка.",
                extracted_price=Money(1_842_000, "RUB"),
                extracted_origin=intent.origin,
                extracted_destination=intent.destination,
                extracted_date_window="2026-09-10",
                confidence=Confidence.MEDIUM,
                discovered_at=NOW,
                requires_manual_verification=True,
            ),
        )


class FailingDealDiscoveryService:
    async def discover(self, intent, *, limit: int = 5):
        raise DealUrlPolicyError("deal_url_blocked_ip")


def _browser_offer() -> BrowserObservedOffer:
    return BrowserObservedOffer(
        observation_id=UUID("33333333-3333-3333-3333-333333333333"),
        source_id="tutu",
        source_name="Туту",
        provider_offer_id="tutu-card-1",
        origin="MOW",
        destination="IST",
        departure_date="2026-09-10",
        return_date="2026-09-20",
        total_price=Money(1_842_000, "RUB"),
        passengers=1,
        observed_at=NOW,
        final_url="https://www.tutu.ru/",
        display_url="www.tutu.ru",
        freshness=Freshness.BROWSER_OBSERVED,
        confidence=Confidence.MEDIUM,
        parser_version="fixture-parser",
        parser_warnings=("baggage_unknown",),
        seller_name="Туту",
    )
