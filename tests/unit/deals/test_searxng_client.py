from __future__ import annotations

from datetime import UTC, datetime

import httpx2
import pytest

from flight_hunter.deals.searxng_client import SearxngClient, SearxngClientError

NOW = datetime(2026, 6, 29, 20, 0, tzinfo=UTC)


def test_searxng_client_requests_json_search_without_secrets() -> None:
    captured_request: httpx2.Request | None = None

    def handler(request: httpx2.Request) -> httpx2.Response:
        nonlocal captured_request
        captured_request = request
        return httpx2.Response(
            200,
            json={
                "results": [
                    {
                        "title": "Распродажа MOW IST",
                        "url": "https://example.com/deal",
                        "content": "Билеты от 18 420 RUB.",
                        "engine": "rss",
                    }
                ]
            },
        )

    client = SearxngClient(
        base_url="http://127.0.0.1:8080",
        http_client=httpx2.Client(
            transport=httpx2.MockTransport(handler),
            base_url="http://127.0.0.1:8080",
        ),
        clock=lambda: NOW,
    )

    response = client.search("авиабилеты MOW IST акция")

    assert captured_request is not None
    assert captured_request.url.path == "/search"
    assert captured_request.url.params["format"] == "json"
    assert "token" not in str(captured_request.url).lower()
    assert response.received_at == NOW
    assert len(response.results) == 1
    assert response.results[0].url == "https://example.com/deal"


def test_searxng_client_rejects_unsafe_result_url() -> None:
    def handler(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(
            200,
            json={
                "results": [
                    {
                        "title": "internal metadata",
                        "url": "http://169.254.169.254/latest/meta-data",
                        "content": "not a public deal page",
                    }
                ]
            },
        )

    client = SearxngClient(
        base_url="http://127.0.0.1:8080",
        http_client=httpx2.Client(
            transport=httpx2.MockTransport(handler),
            base_url="http://127.0.0.1:8080",
        ),
        clock=lambda: NOW,
    )

    with pytest.raises(SearxngClientError, match="searxng_invalid_url"):
        client.search("unsafe")


def test_searxng_client_raises_typed_error_on_rate_limit() -> None:
    def handler(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(429, json={"error": "rate limited"})

    client = SearxngClient(
        base_url="http://127.0.0.1:8080",
        http_client=httpx2.Client(
            transport=httpx2.MockTransport(handler),
            base_url="http://127.0.0.1:8080",
        ),
        clock=lambda: NOW,
    )

    with pytest.raises(SearxngClientError, match="searxng_rate_limited"):
        client.search("rate limited")


def test_searxng_client_wraps_transport_errors() -> None:
    def handler(request: httpx2.Request) -> httpx2.Response:
        raise httpx2.ConnectError("connection refused", request=request)

    client = SearxngClient(
        base_url="http://127.0.0.1:8080",
        http_client=httpx2.Client(
            transport=httpx2.MockTransport(handler),
            base_url="http://127.0.0.1:8080",
        ),
        clock=lambda: NOW,
    )

    with pytest.raises(SearxngClientError, match="searxng_unavailable"):
        client.search("transport failure")


def test_searxng_client_wraps_invalid_json_without_echoing_payload() -> None:
    client = SearxngClient(
        base_url="http://127.0.0.1:8080",
        http_client=httpx2.Client(
            transport=httpx2.MockTransport(
                lambda request: httpx2.Response(200, text="not-json token=secret")
            ),
            base_url="http://127.0.0.1:8080",
        ),
        clock=lambda: NOW,
    )

    with pytest.raises(SearxngClientError, match=r"^searxng_invalid_json$") as exc_info:
        client.search("bad json")

    assert "secret" not in str(exc_info.value)
