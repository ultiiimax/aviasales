from __future__ import annotations

import asyncio
import inspect
import json
import threading
import traceback
from collections.abc import Mapping
from dataclasses import asdict, replace
from datetime import UTC, date, datetime
from typing import Any
from uuid import UUID

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

NOW = datetime(2026, 7, 14, 21, 0, tzinfo=UTC)
EVIDENCE_NAMESPACE = UUID("11111111-1111-4111-8111-111111111111")
OTHER_EVIDENCE_NAMESPACE = UUID("22222222-2222-4222-8222-222222222222")
RESULTS_HOST = "results-fixture.aviasales.ru"


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
        adults=1,
        children=0,
        infants=0,
        trip_class="Y",
        currency="RUB",
        market="RU",
    )


def _continuation(
    *,
    evidence_namespace: UUID = EVIDENCE_NAMESPACE,
    origin: str = "SVO",
    destination: str = "LED",
    departure_date: date = date(2026, 9, 15),
    return_date: date | None = None,
    currency: str = "RUB",
    passengers: int = 1,
) -> ExactSearchContinuation:
    return ExactSearchContinuation(
        search_id="opaque-search-state",
        results_url=RESULTS_HOST,
        last_update_timestamp=0,
        request_id="opaque-request-state",
        evidence_namespace=evidence_namespace,
        expected_origin=origin,
        expected_destination=destination,
        expected_departure_date=departure_date,
        expected_return_date=return_date,
        expected_currency=currency,
        passengers=passengers,
    )


def _one_way_chunk(
    *,
    origin: str = "SVO",
    destination: str = "LED",
    departure_date: str = "2026-09-15",
    currency: str | None = "RUB",
    price: int = 4_321,
) -> dict[str, object]:
    price_payload: dict[str, object] = {"value": price}
    if currency is not None:
        price_payload["currency_code"] = currency
    return {
        "last_update_timestamp": 14,
        "agents": {"1": {"gate_name": "Fixture Gate"}},
        "airlines": {"FH": {"name": {"ru": {"default": "Fixture Air"}}}},
        "flight_legs": [
            {
                "origin": origin,
                "destination": destination,
                "local_departure_date_time": f"{departure_date} 10:00",
                "local_arrival_date_time": f"{departure_date} 11:30",
                "operating_carrier_designator": {"carrier": "FH", "number": "101"},
            }
        ],
        "tickets": [
            {
                "signature": "private-ticket-signature",
                "segments": [{"flights": [0]}],
                "proposals": [
                    {
                        "id": "1:0",
                        "agent_id": 1,
                        "price": price_payload,
                    }
                ],
            }
        ],
    }


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
                    "results_url": RESULTS_HOST,
                    "blet_url": "opaque-blet-state",
                }
            )
        ]
    )
    main_thread_id = threading.get_ident()

    continuation = asyncio.run(
        _gateway(transport).start_exact(
            _start_params(),
            evidence_namespace=EVIDENCE_NAMESPACE,
            request_fingerprint="sha256:start",
            context=ExecutionContext.WORKER,
        )
    )

    assert continuation.last_update_timestamp == 0
    assert continuation.evidence_namespace == EVIDENCE_NAMESPACE
    assert continuation.expected_origin == "SVO"
    assert continuation.expected_destination == "LED"
    assert continuation.expected_departure_date == date(2026, 9, 15)
    assert continuation.expected_return_date is None
    assert continuation.expected_currency == "RUB"
    assert continuation.passengers == 1
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
                evidence_namespace=EVIDENCE_NAMESPACE,
                request_fingerprint="sha256:city",
                context=ExecutionContext.WORKER,
            )
        )

    assert transport.post_calls == []


def test_gateway_admits_city_only_when_capability_is_supported() -> None:
    transport = _FakeTransport(
        posts=[_FakeResponse(payload={"search_id": "opaque", "results_url": RESULTS_HOST})]
    )
    params = _start_params(
        origin=ProviderLocation(kind=LocationScopeKind.CITY, code="MOW"),
        destination=ProviderLocation(kind=LocationScopeKind.CITY, code="LED"),
    )

    asyncio.run(
        _gateway(transport, city_state=CapabilityState.SUPPORTED).start_exact(
            params,
            evidence_namespace=EVIDENCE_NAMESPACE,
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
                evidence_namespace=EVIDENCE_NAMESPACE,
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
                request_fingerprint="sha256:poll-denied",
            )
        )
    with pytest.raises(AviasalesSearchPolicyDenied, match="provider_disabled"):
        asyncio.run(
            gateway.calendar(
                calendar_params,
                evidence_namespace=EVIDENCE_NAMESPACE,
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


def test_poll_interface_cannot_override_continuation_passenger_count() -> None:
    assert "passengers" not in inspect.signature(AviasalesSearchGateway.poll_exact_once).parameters


def test_start_exact_rejects_non_uuid_evidence_namespace_before_transport() -> None:
    transport = _FakeTransport()

    with pytest.raises(TypeError) as raised:
        asyncio.run(
            _gateway(transport).start_exact(
                _start_params(),
                evidence_namespace="private-namespace",  # type: ignore[arg-type]
                request_fingerprint="sha256:invalid-namespace",
            )
        )

    assert "private-namespace" not in str(raised.value)
    assert transport.post_calls == []


def test_start_exact_does_not_hide_a_second_transport_attempt() -> None:
    transport = _FakeTransport(
        posts=[
            _FakeResponse(status_code=500, payload={}),
            _FakeResponse(payload={"search_id": "unused", "results_url": RESULTS_HOST}),
        ]
    )

    with pytest.raises(AviasalesSearchError):
        asyncio.run(
            _gateway(transport).start_exact(
                _start_params(),
                evidence_namespace=EVIDENCE_NAMESPACE,
                request_fingerprint="sha256:no-hidden-retry",
                context=ExecutionContext.WORKER,
            )
        )

    assert len(transport.post_calls) == 1


def test_poll_exact_once_returns_only_confirmed_sanitized_evidence() -> None:
    chunk = _one_way_chunk()
    transport = _FakeTransport(posts=[_FakeResponse(payload=[chunk])])

    outcome = asyncio.run(
        _gateway(transport).poll_exact_once(
            _continuation(),
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
    assert first.passengers == 1
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
        RESULTS_HOST,
        "opaque-request-state",
        first.provider_offer_id,
    ):
        if private_value == first.provider_offer_id:
            continue
        assert private_value not in public_text
    assert "booking" not in public_text.lower()


def test_ticket_bearing_poll_does_not_claim_unproven_search_completion() -> None:
    chunk = _one_way_chunk()
    transport = _FakeTransport(posts=[_FakeResponse(payload=[chunk])])

    outcome = asyncio.run(
        _gateway(transport).poll_exact_once(
            _continuation(),
            request_fingerprint="sha256:not-complete",
        )
    )

    assert outcome.evidence
    assert outcome.complete is False


@pytest.mark.parametrize(
    "ticket_overrides",
    [
        {"origin": "DME"},
        {"destination": "CDG"},
        {"departure_date": "2026-09-16"},
        {"currency": "USD"},
    ],
)
def test_poll_rejects_ticket_that_does_not_match_bound_continuation(
    ticket_overrides: dict[str, Any],
) -> None:
    transport = _FakeTransport(posts=[_FakeResponse(payload=[_one_way_chunk(**ticket_overrides)])])

    with pytest.raises(AviasalesSearchSchemaError):
        asyncio.run(
            _gateway(transport).poll_exact_once(
                _continuation(),
                request_fingerprint="sha256:bound-ticket",
            )
        )

    assert len(transport.post_calls) == 1


@pytest.mark.parametrize(
    "chunk",
    [
        _one_way_chunk(currency=None),
        _one_way_chunk(currency="РУБ"),
        _one_way_chunk(price=-1),
    ],
)
def test_poll_converts_corrupt_proposal_money_to_stable_schema_error(
    chunk: dict[str, object],
) -> None:
    transport = _FakeTransport(posts=[_FakeResponse(payload=[chunk])])

    with pytest.raises(AviasalesSearchSchemaError) as raised:
        asyncio.run(
            _gateway(transport).poll_exact_once(
                _continuation(),
                request_fingerprint="sha256:corrupt-money",
            )
        )

    assert str(raised.value) == AviasalesSearchSchemaError.code
    assert raised.value.__cause__ is None
    assert len(transport.post_calls) == 1


@pytest.mark.parametrize(
    ("field_name", "private_value"),
    [
        ("results_url", "private-invalid-host.example.test"),
        ("passengers", "private-passenger-count"),
    ],
)
def test_poll_revalidates_corrupt_private_continuation_before_transport(
    field_name: str,
    private_value: str,
) -> None:
    transport = _FakeTransport()
    continuation = _continuation()
    object.__setattr__(continuation, field_name, private_value)

    with pytest.raises((TypeError, ValueError, AviasalesSearchSchemaError)) as raised:
        asyncio.run(
            _gateway(transport).poll_exact_once(
                continuation,
                request_fingerprint="sha256:corrupt-continuation",
            )
        )

    rendered = "".join(
        traceback.format_exception(type(raised.value), raised.value, raised.value.__traceback__)
    )
    assert private_value not in str(raised.value)
    assert private_value not in repr(raised.value)
    assert private_value not in rendered
    assert transport.post_calls == []


def test_exact_evidence_uuid_is_idempotent_within_operation_namespace() -> None:
    def poll(namespace: UUID) -> Any:
        transport = _FakeTransport(posts=[_FakeResponse(payload=[_one_way_chunk()])])
        return asyncio.run(
            _gateway(transport).poll_exact_once(
                _continuation(evidence_namespace=namespace),
                request_fingerprint=f"sha256:{namespace}",
            )
        ).evidence[0]

    first = poll(EVIDENCE_NAMESPACE)
    repeated = poll(EVIDENCE_NAMESPACE)
    other_operation = poll(OTHER_EVIDENCE_NAMESPACE)

    assert first.id == repeated.id
    assert first.id != other_operation.id
    assert first.provider_offer_id == other_operation.provider_offer_id
    assert first.segment_ids == other_operation.segment_ids


def test_private_continuation_repr_redacts_all_upstream_state() -> None:
    continuation = _continuation()

    rendered = repr(continuation)

    assert rendered == "ExactSearchContinuation(<private>)"
    assert "opaque-search-state" not in rendered
    assert RESULTS_HOST not in rendered
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
            evidence_namespace=EVIDENCE_NAMESPACE,
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
            ).calendar(
                params,
                evidence_namespace=EVIDENCE_NAMESPACE,
                request_fingerprint="sha256:calendar-repeat",
            )
        )[0].id
    )


def test_calendar_evidence_uuid_is_scoped_to_operation_namespace() -> None:
    params = CalendarSearchParams(
        origin=_airport("SVO"),
        destination=_airport("LED"),
        depart_from=date(2026, 9, 14),
        depart_to=date(2026, 9, 16),
        one_way=True,
        currency="RUB",
    )

    def observe(namespace: UUID) -> Any:
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
                                "currency": "RUB",
                            }
                        ]
                    }
                )
            ]
        )
        return asyncio.run(
            _gateway(transport).calendar(
                params,
                evidence_namespace=namespace,
                request_fingerprint=f"sha256:calendar:{namespace}",
            )
        )[0]

    first = observe(EVIDENCE_NAMESPACE)
    repeated = observe(EVIDENCE_NAMESPACE)
    other_operation = observe(OTHER_EVIDENCE_NAMESPACE)

    assert first.id == repeated.id
    assert first.id != other_operation.id


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
                evidence_namespace=EVIDENCE_NAMESPACE,
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


def test_calendar_rejects_response_currency_different_from_request() -> None:
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
                            "currency": "USD",
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

    with pytest.raises(AviasalesSearchSchemaError):
        asyncio.run(
            _gateway(transport).calendar(
                params,
                evidence_namespace=EVIDENCE_NAMESPACE,
                request_fingerprint="sha256:calendar-currency",
            )
        )

    assert len(transport.get_calls) == 1


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
        _gateway(transport).calendar(
            params,
            evidence_namespace=EVIDENCE_NAMESPACE,
            request_fingerprint="sha256:calendar-filter",
        )
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
                evidence_namespace=EVIDENCE_NAMESPACE,
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
