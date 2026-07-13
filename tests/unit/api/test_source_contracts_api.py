from __future__ import annotations

from fastapi.testclient import TestClient

from flight_hunter.api.app import create_app


def test_source_contracts_endpoint_exposes_readiness_without_secret_values(monkeypatch) -> None:
    monkeypatch.setenv("AVIASALES_SEARCH_ENABLED", "true")
    monkeypatch.setenv("AVIASALES_SEARCH_SIGNATURE", "secret-signature")
    monkeypatch.setenv("AVIASALES_SEARCH_MARKER", "secret-marker")
    client = TestClient(create_app())

    response = client.get("/api/v1/source-contracts")

    assert response.status_code == 200
    body = response.json()
    assert body["summary"]["total"] >= 6
    assert body["summary"]["implemented"] >= 2
    sources = {source["source_id"]: source for source in body["sources"]}
    assert sources["fake"]["stage"] == "implemented"
    assert sources["aviasales_search"]["stage"] == "implemented"
    assert sources["aviasales_search"]["credentials_present"] is True
    assert sources["aviasales_search"]["merge_scope"] == "mergeable"
    assert sources["aviasales_search"]["background_requests_allowed"] is True
    assert "https://tickets-api.aviasales.ru" in sources["aviasales_search"]["egress_policy"]
    assert "secret-signature" not in str(body)
    assert "secret-marker" not in str(body)
