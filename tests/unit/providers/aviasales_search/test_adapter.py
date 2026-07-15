from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import pytest

from flight_hunter.domain.offers import Freshness, SearchIntent
from flight_hunter.domain.policy import ExecutionContext
from flight_hunter.providers.aviasales_search.adapter import AviasalesSearchAdapter
from flight_hunter.providers.aviasales_search.client import (
    AviasalesSearchClient,
    AviasalesSearchSchemaError,
    AviasalesSearchTransport,
)

FIXTURE = Path("tests/fixtures/provider/aviasales_search/raw_chunk_mow_led.json")


class _FakeResponse:
    def __init__(self, *, status_code: int = 200, payload: Any = None) -> None:
        self.status_code = status_code
        self._payload = payload
        self.content = b"x" if payload is not None else b""
        self.headers: Mapping[str, str] = {}

    def json(self) -> Any:
        return self._payload

    @property
    def text(self) -> str:
        return json.dumps(self._payload) if self._payload is not None else ""


class _FakeTransport:
    def __init__(
        self, *, posts: list[_FakeResponse], gets: list[_FakeResponse] | None = None
    ) -> None:
        self._posts = list(posts)
        self._gets = list(gets or [])
        self.post_calls = 0
        self.get_calls = 0

    def post(
        self, url: str, *, json: Any, headers: Mapping[str, str], timeout: float
    ) -> _FakeResponse:
        self.post_calls += 1
        return self._posts.pop(0) if self._posts else _FakeResponse(status_code=500)

    def get(
        self, url: str, *, params: Mapping[str, Any], headers: Mapping[str, str], timeout: float
    ) -> _FakeResponse:
        self.get_calls += 1
        return self._gets.pop(0) if self._gets else _FakeResponse(status_code=404)


def _transport_with_fixture_results() -> _FakeTransport:
    chunk = json.loads(FIXTURE.read_text(encoding="utf-8"))
    return _FakeTransport(
        posts=[
            _FakeResponse(
                payload={
                    "search_id": "sid-1",
                    "results_url": "results-fixture.aviasales.ru",
                    "blet_url": None,
                }
            ),
            _FakeResponse(payload=[chunk]),
        ]
    )


def _client(transport: AviasalesSearchTransport) -> AviasalesSearchClient:
    return AviasalesSearchClient(
        signature="sig",
        marker="mobile_app.token",
        transport=transport,
        timeout=5.0,
        max_retries=0,
        sleep_fn=lambda _s: None,
    )


def _intent() -> SearchIntent:
    return SearchIntent(
        origin="MOW",
        destination="LED",
        departure_date="2026-09-15",
        return_date=None,
        passengers=1,
        currency="RUB",
    )


def _adapter(
    transport: AviasalesSearchTransport, *, enabled: bool, credentials: bool
) -> AviasalesSearchAdapter:
    return AviasalesSearchAdapter(
        client=_client(transport),
        enabled=enabled,
        credentials_present=credentials,
        poll_rounds=2,
        poll_delay=0.0,
    )


def test_search_returns_live_offers_from_fixture_when_enabled() -> None:
    transport = _transport_with_fixture_results()
    adapter = _adapter(transport, enabled=True, credentials=True)

    offers = adapter.search(
        _intent(),
        request_fingerprint="sha256:abc",
        context=ExecutionContext.WEB_USER_ACTION,
    )

    assert len(offers) == 5
    assert all(o.provider_id == "aviasales_search" for o in offers)
    assert all(o.freshness == Freshness.LIVE for o in offers)
    assert all(o.destination == "LED" for o in offers)
    assert offers[0].total_price.minor_units <= offers[-1].total_price.minor_units
    assert transport.post_calls == 2


def test_search_wraps_chunk_parse_failure_as_schema_error() -> None:
    transport = _FakeTransport(
        posts=[
            _FakeResponse(
                payload={
                    "search_id": "sid-1",
                    "results_url": "results-fixture.aviasales.ru",
                }
            ),
            _FakeResponse(payload=[{"tickets": "not-a-list"}]),
        ]
    )
    adapter = _adapter(transport, enabled=True, credentials=True)

    with pytest.raises(AviasalesSearchSchemaError, match="aviasales_search_schema_error"):
        adapter.search(
            _intent(),
            request_fingerprint="sha256:abc",
            context=ExecutionContext.WEB_USER_ACTION,
        )


def test_search_returns_empty_and_skips_calls_when_disabled() -> None:
    transport = _transport_with_fixture_results()
    adapter = _adapter(transport, enabled=False, credentials=True)

    offers = adapter.search(
        _intent(),
        request_fingerprint="sha256:abc",
        context=ExecutionContext.WEB_USER_ACTION,
    )

    assert offers == ()
    assert transport.post_calls == 0


def test_search_returns_empty_when_credentials_missing() -> None:
    transport = _transport_with_fixture_results()
    adapter = _adapter(transport, enabled=True, credentials=False)

    offers = adapter.search(
        _intent(),
        request_fingerprint="sha256:abc",
        context=ExecutionContext.WEB_USER_ACTION,
    )

    assert offers == ()
    assert transport.post_calls == 0


def test_search_allows_scheduler_context_for_background_watch_scans() -> None:
    transport = _transport_with_fixture_results()
    adapter = _adapter(transport, enabled=True, credentials=True)

    offers = adapter.search(
        _intent(),
        request_fingerprint="sha256:abc",
        context=ExecutionContext.SCHEDULER,
    )

    assert len(offers) == 5
    assert transport.post_calls == 2


def test_resolve_purchase_url_returns_link_on_click() -> None:
    transport = _FakeTransport(
        posts=[
            _FakeResponse(
                payload={
                    "search_id": "sid-1",
                    "results_url": "results-fixture.aviasales.ru",
                    "blet_url": None,
                }
            )
        ],
        gets=[_FakeResponse(payload={"url": "https://gate.example/booking/x"})],
    )
    adapter = _adapter(transport, enabled=True, credentials=True)

    url = adapter.resolve_purchase_url(
        search_id="sid-1",
        proposal_id="120:0",
        results_url="results-fixture.aviasales.ru",
        request_fingerprint="sha256:abc",
    )

    assert url == "https://gate.example/booking/x"
    assert transport.get_calls == 1
