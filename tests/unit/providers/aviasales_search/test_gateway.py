from __future__ import annotations

import asyncio
import json
import threading
import traceback
from collections.abc import Mapping
from dataclasses import asdict, replace
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import pytest

from flight_hunter.application.agent_capabilities import ProviderCapabilityRegistry
from flight_hunter.domain.agent_evidence import (
    ConfirmationState,
    DiscoverySource,
    ProtectionStatus,
)
from flight_hunter.domain.agent_search import CapabilityState, LocationScopeKind
from flight_hunter.domain.money import Money
from flight_hunter.domain.policy import ExecutionContext, ProviderPolicy
from flight_hunter.providers.aviasales_search.client import (
    AviasalesSearchClient,
    AviasalesSearchError,
    AviasalesSearchSchemaError,
    AviasalesSearchTransport,
    SearchStartParams,
)
from flight_hunter.providers.aviasales_search.gateway import (
    AviasalesSearchCapabilityError,
    AviasalesSearchGateway,
    AviasalesSearchPolicyDenied,
    CalendarSearchParams,
    ExactSearchContinuation,
)
from flight_hunter.providers.aviasales_search.schemas import ProviderLocation

FIXTURE = Path("tests/fixtures/provider/aviasales_search/raw_chunk_mow_led.json")
NOW = datetime(2026, 7, 14, 21, 0, tzinfo=UTC)


class _FakeResponse:
    def __init__(
        self,
        *,
        status_code: int = 200,
        payload: Any = None,
        headers: Mapping[str, str] | None = None,
    ) -> None:
        self.status_code = status_code
        self._payload = payload
        self.content = b"x" if payload is not None else b""
        self.headers = headers or {}

    def json(self) -> Any:
        return self._payload

    @property
    def text(self) -> str:
        return json.dumps(self._payload) if self._payload is not None else ""


class _FakeTransport:
    def __init__(
        self,
        *,
        posts: list[_FakeResponse] | None = None,
        gets: list[_FakeResponse] | None = None,
    ) -> None:
        self._posts = list(posts or [])
        self._gets = list(gets or [])
        self.post_calls: list[dict[str, Any]] = []
        self.get_calls: list[dict[str, Any]] = []
        self.thread_ids: list[int] = []

    def post(
        self,
        url: str,
        *,
        json: Any,
        headers: Mapping[str, str],
        timeout: float,
    ) -> _FakeResponse:
        self.thread_ids.append(threading.get_ident())
        self.post_calls.append(
            {"url": url, "json": json, "headers": dict(headers), "timeout": timeout}
        )
        return self._posts.pop(0) if self._posts else _FakeResponse(status_code=500)

    def get(
        self,
        url: str,
        *,
        params: Mapping[str, Any],
        headers: Mapping[str, str],
        timeout: float,
    ) -> _FakeResponse:
        self.thread_ids.append(threading.get_ident())
        self.get_calls.append(
            {"url": url, "params": dict(params), "headers": dict(headers), "timeout": timeout}
        )
        return self._gets.pop(0) if self._gets else _FakeResponse(status_code=500)


def _policy(*, enabled: bool = True) -> ProviderPolicy:
    return ProviderPolicy.aviasales_search_live(
        terms_verified_at=NOW,
        credentials_present=True,
        enabled=enabled,
    )


def _client(
    transport: AviasalesSearchTransport,
    *,
    max_retries: int = 0,
) -> AviasalesSearchClient:
    return AviasalesSearchClient(
        signature="fixture-signature",
        marker="fixture-marker",
        transport=transport,
        timeout=5.0,
        max_retries=max_retries,
        sleep_fn=lambda _seconds: None,
    )


def _gateway(
    transport: AviasalesSearchTransport,
    *,
    enabled: bool = True,
    city_state: CapabilityState = CapabilityState.UNKNOWN,
    max_retries: int = 0,
) -> AviasalesSearchGateway:
    capabilities = replace(
        ProviderCapabilityRegistry().snapshot(),
        city_location_semantics=city_state,
    )
    return AviasalesSearchGateway(
        client=_client(transport, max_retries=max_retries),
        policy=_policy(enabled=enabled),
        capability_snapshot=capabilities,
        clock=lambda: NOW,
    )


def _airport(code: str) -> ProviderLocation:
    return ProviderLocation(kind=LocationScopeKind.AIRPORT, code=code)


def _start_params(*, origin: Any | None = None, destination: Any | None = None) -> Any:
    return SearchStartParams(
        origin=origin or _airport("svo"),
        destination=destination or _airport("led"),
        departure_date="2026-09-15",
        return_date=None,
        adults=2,
        children=0,
        infants=0,
        trip_class="Y",
        currency="RUB",
        market="RU",
    )


def _continuation() -> ExactSearchContinuation:
    return ExactSearchContinuation(
        search_id="opaque-search-state",
        results_url="opaque-results-host",
        last_update_timestamp=0,
        request_id="opaque-request-state",
    )


def test_provider_location_normalizes_iata_and_rejects_unsupported_kinds() -> None:
    airport = ProviderLocation(kind="airport", code="svo")

    assert airport.kind is LocationScopeKind.AIRPORT
    assert airport.code == "SVO"
    with pytest.raises(ValueError, match="airport or city"):
        ProviderLocation(kind=LocationScopeKind.COUNTRY, code="FRA")
    with pytest.raises(ValueError, match="IATA"):
        ProviderLocation(kind=LocationScopeKind.AIRPORT, code="PARIS")


def test_start_exact_uses_one_background_thread_call_and_airport_flags() -> None:
    transport = _FakeTransport(
        posts=[
            _FakeResponse(
                payload={
                    "search_id": "opaque-search-state",
                    "results_url": "opaque-results-host",
                    "blet_url": "opaque-blet-state",
                }
            )
        ]
    )
    main_thread_id = threading.get_ident()

    continuation = asyncio.run(
        _gateway(transport).start_exact(
            _start_params(),
            request_fingerprint="sha256:start",
            context=ExecutionContext.WORKER,
        )
    )

    assert continuation.last_update_timestamp == 0
    assert len(transport.post_calls) == 1
    directions = transport.post_calls[0]["json"]["search_params"]["directions"]
    assert directions[0]["is_origin_airport"] is True
    assert directions[0]["is_destination_airport"] is True
    assert transport.thread_ids == [transport.thread_ids[0]]
    assert transport.thread_ids[0] != main_thread_id


def test_gateway_rejects_unknown_city_semantics_before_policy_or_transport() -> None:
    transport = _FakeTransport()
    params = _start_params(origin=ProviderLocation(kind=LocationScopeKind.CITY, code="MOW"))

    with pytest.raises(AviasalesSearchCapabilityError, match="city_location_semantics"):
        asyncio.run(
            _gateway(transport).start_exact(
                params,
                request_fingerprint="sha256:city",
                context=ExecutionContext.WORKER,
            )
        )

    assert transport.post_calls == []


def test_gateway_admits_city_only_when_capability_is_supported() -> None:
    transport = _FakeTransport(
        posts=[_FakeResponse(payload={"search_id": "opaque", "results_url": "opaque-host"})]
    )
    params = _start_params(
        origin=ProviderLocation(kind=LocationScopeKind.CITY, code="MOW"),
        destination=ProviderLocation(kind=LocationScopeKind.CITY, code="LED"),
    )

    asyncio.run(
        _gateway(transport, city_state=CapabilityState.SUPPORTED).start_exact(
            params,
            request_fingerprint="sha256:city-supported",
            context=ExecutionContext.WORKER,
        )
    )

    direction = transport.post_calls[0]["json"]["search_params"]["directions"][0]
    assert direction["is_origin_airport"] is False
    assert direction["is_destination_airport"] is False


def test_gateway_policy_denial_performs_no_transport_call() -> None:
    transport = _FakeTransport()

    with pytest.raises(AviasalesSearchPolicyDenied, match="provider_disabled"):
        asyncio.run(
            _gateway(transport, enabled=False).start_exact(
                _start_params(),
                request_fingerprint="sha256:denied",
                context=ExecutionContext.WORKER,
            )
        )

    assert transport.post_calls == []


def test_poll_and_calendar_each_authorize_before_transport() -> None:
    transport = _FakeTransport()
    gateway = _gateway(transport, enabled=False)
    calendar_params = CalendarSearchParams(
        origin=_airport("SVO"),
        destination=_airport("LED"),
        depart_from=date(2026, 9, 14),
        depart_to=date(2026, 9, 16),
        one_way=True,
        currency="RUB",
    )

    with pytest.raises(AviasalesSearchPolicyDenied, match="provider_disabled"):
        asyncio.run(
            gateway.poll_exact_once(
                _continuation(),
                passengers=1,
                request_fingerprint="sha256:poll-denied",
            )
        )
    with pytest.raises(AviasalesSearchPolicyDenied, match="provider_disabled"):
        asyncio.run(
            gateway.calendar(
                calendar_params,
                request_fingerprint="sha256:calendar-denied",
            )
        )

    assert transport.post_calls == []
    assert transport.get_calls == []


def test_gateway_requires_a_zero_retry_orchestrator_client() -> None:
    transport = _FakeTransport()

    with pytest.raises(ValueError, match="max_retries=0"):
        _gateway(transport, max_retries=1)

    assert AviasalesSearchGateway


def test_start_exact_does_not_hide_a_second_transport_attempt() -> None:
    transport = _FakeTransport(
        posts=[
            _FakeResponse(status_code=500, payload={}),
            _FakeResponse(payload={"search_id": "unused", "results_url": "unused"}),
        ]
    )

    with pytest.raises(AviasalesSearchError):
        asyncio.run(
            _gateway(transport).start_exact(
                _start_params(),
                request_fingerprint="sha256:no-hidden-retry",
                context=ExecutionContext.WORKER,
            )
        )

    assert len(transport.post_calls) == 1


def test_poll_exact_once_returns_only_confirmed_sanitized_evidence() -> None:
    chunk = json.loads(FIXTURE.read_text(encoding="utf-8"))
    transport = _FakeTransport(posts=[_FakeResponse(payload=[chunk])])

    outcome = asyncio.run(
        _gateway(transport).poll_exact_once(
            _continuation(),
            passengers=2,
            request_fingerprint="sha256:poll",
            context=ExecutionContext.WORKER,
        )
    )

    assert len(transport.post_calls) == 1
    assert outcome.evidence
    assert outcome.next_cursor >= 0
    assert outcome.complete is False
    assert set(outcome.__dataclass_fields__) == {"evidence", "next_cursor", "complete"}
    first = outcome.evidence[0]
    assert first.provider_id == "aviasales_search"
    assert first.provider_offer_id.startswith("aviasales_search:")
    assert first.provider_offer_id.removeprefix("aviasales_search:").isalnum()
    assert len(first.provider_offer_id.removeprefix("aviasales_search:")) == 64
    assert first.total_amount.currency == "RUB"
    assert first.passengers == 2
    assert first.observed_at == NOW
    assert first.seller_name
    assert first.segments
    assert len(first.segment_ids) == len(first.segments)
    assert len(set(first.segment_ids)) == len(first.segment_ids)
    assert first.protection_status is ProtectionStatus.UNKNOWN
    assert first.confirmation_state is ConfirmationState.CONFIRMED
    public_text = repr(asdict(outcome))
    for private_value in (
        "opaque-search-state",
        "opaque-results-host",
        "opaque-request-state",
        first.provider_offer_id,
    ):
        if private_value == first.provider_offer_id:
            continue
        assert private_value not in public_text
    assert "booking" not in public_text.lower()


def test_ticket_bearing_poll_does_not_claim_unproven_search_completion() -> None:
    chunk = json.loads(FIXTURE.read_text(encoding="utf-8"))
    transport = _FakeTransport(posts=[_FakeResponse(payload=[chunk])])

    outcome = asyncio.run(
        _gateway(transport).poll_exact_once(
            _continuation(),
            passengers=1,
            request_fingerprint="sha256:not-complete",
        )
    )

    assert outcome.evidence
    assert outcome.complete is False


def test_private_continuation_repr_redacts_all_upstream_state() -> None:
    continuation = _continuation()

    rendered = repr(continuation)

    assert rendered == "ExactSearchContinuation(<private>)"
    assert "opaque-search-state" not in rendered
    assert "opaque-results-host" not in rendered
    assert "opaque-request-state" not in rendered


def test_calendar_returns_discovery_signals_in_one_transport_call() -> None:
    transport = _FakeTransport(
        gets=[
            _FakeResponse(
                payload={
                    "prices": [
                        {
                            "origin": "SVO",
                            "destination": "LED",
                            "depart_date": "2026-09-15",
                            "value": 4321,
                            "currency": "rub",
                        }
                    ]
                }
            )
        ]
    )
    params = CalendarSearchParams(
        origin=_airport("svo"),
        destination=_airport("led"),
        depart_from=date(2026, 9, 14),
        depart_to=date(2026, 9, 16),
        one_way=True,
        currency="rub",
        adults=1,
        children=0,
        infants=0,
    )

    signals = asyncio.run(
        _gateway(transport).calendar(
            params,
            request_fingerprint="sha256:calendar",
            context=ExecutionContext.WORKER,
        )
    )

    assert len(transport.get_calls) == 1
    call = transport.get_calls[0]
    assert call["params"]["origin_type"] == "airport"
    assert call["params"]["destination_type"] == "airport"
    assert call["params"]["locale"] == "ru_RU"
    assert len(signals) == 1
    signal = signals[0]
    assert signal.provider_id == "aviasales_search"
    assert signal.source_kind is DiscoverySource.CALENDAR
    assert signal.confirmation_state is ConfirmationState.INDICATIVE
    assert signal.observed_amount == Money(432_100, "RUB")
    assert signal.passengers == 1
    assert signal.observed_at == NOW
    assert (
        signal.id
        == asyncio.run(
            _gateway(
                _FakeTransport(
                    gets=[
                        _FakeResponse(
                            payload={
                                "prices": [
                                    {
                                        "origin": "SVO",
                                        "destination": "LED",
                                        "depart_date": "2026-09-15",
                                        "value": 4321,
                                        "currency": "rub",
                                    }
                                ]
                            }
                        )
                    ]
                )
            ).calendar(params, request_fingerprint="sha256:calendar-repeat")
        )[0].id
    )


def test_calendar_rejects_unsupported_passenger_mix_before_transport() -> None:
    transport = _FakeTransport()
    params = CalendarSearchParams(
        origin=_airport("SVO"),
        destination=_airport("LED"),
        depart_from=date(2026, 9, 14),
        depart_to=date(2026, 9, 16),
        one_way=True,
        currency="RUB",
        adults=2,
        children=0,
        infants=0,
    )

    with pytest.raises(AviasalesSearchCapabilityError, match="passenger_mix"):
        asyncio.run(
            _gateway(transport).calendar(
                params,
                request_fingerprint="sha256:calendar-passengers",
            )
        )

    assert transport.get_calls == []


def test_calendar_params_reject_non_string_currency_before_transport() -> None:
    with pytest.raises(TypeError, match="currency"):
        CalendarSearchParams(
            origin=_airport("SVO"),
            destination=_airport("LED"),
            depart_from=date(2026, 9, 14),
            depart_to=date(2026, 9, 16),
            one_way=True,
            currency=123,  # type: ignore[arg-type]
        )


def test_calendar_discards_wrong_route_and_out_of_range_provider_rows() -> None:
    transport = _FakeTransport(
        gets=[
            _FakeResponse(
                payload={
                    "prices": [
                        {
                            "origin": "SVO",
                            "destination": "CDG",
                            "depart_date": "2026-09-15",
                            "value": 100,
                            "currency": "rub",
                        },
                        {
                            "origin": "SVO",
                            "destination": "LED",
                            "depart_date": "2026-10-15",
                            "value": 200,
                            "currency": "rub",
                        },
                        {
                            "origin": "SVO",
                            "destination": "LED",
                            "depart_date": "2026-09-15",
                            "value": 300,
                            "currency": "rub",
                        },
                    ]
                }
            )
        ]
    )
    params = CalendarSearchParams(
        origin=_airport("SVO"),
        destination=_airport("LED"),
        depart_from=date(2026, 9, 14),
        depart_to=date(2026, 9, 16),
        one_way=True,
        currency="RUB",
    )

    signals = asyncio.run(
        _gateway(transport).calendar(params, request_fingerprint="sha256:calendar-filter")
    )

    assert len(signals) == 1
    assert signals[0].origin == "SVO"
    assert signals[0].destination == "LED"
    assert signals[0].departure_date == date(2026, 9, 15)
    assert signals[0].observed_amount == Money(30_000, "RUB")


def test_calendar_schema_error_suppresses_provider_value_from_traceback() -> None:
    private_invalid_value = "private-provider-date"
    transport = _FakeTransport(
        gets=[
            _FakeResponse(
                payload={
                    "prices": [
                        {
                            "origin": "SVO",
                            "destination": "LED",
                            "depart_date": private_invalid_value,
                            "value": 300,
                            "currency": "rub",
                        }
                    ]
                }
            )
        ]
    )
    params = CalendarSearchParams(
        origin=_airport("SVO"),
        destination=_airport("LED"),
        depart_from=date(2026, 9, 14),
        depart_to=date(2026, 9, 16),
        one_way=True,
        currency="RUB",
    )

    with pytest.raises(AviasalesSearchSchemaError) as raised:
        asyncio.run(
            _gateway(transport).calendar(
                params,
                request_fingerprint="sha256:calendar-invalid",
            )
        )

    rendered = "".join(
        traceback.format_exception(
            type(raised.value),
            raised.value,
            raised.value.__traceback__,
        )
    )
    assert private_invalid_value not in rendered
