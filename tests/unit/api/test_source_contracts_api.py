from __future__ import annotations

from fastapi.testclient import TestClient

from flight_hunter.api.app import create_app


def test_source_contracts_endpoint_exposes_readiness_without_secret_values(monkeypatch) -> None:
    monkeypatch.setenv("TRAVELPAYOUTS_API_TOKEN", "secret-value")
    monkeypatch.setenv("AVIASALES_DATA_ENABLED", "true")
    client = TestClient(create_app())

    response = client.get("/api/v1/source-contracts")

    assert response.status_code == 200
    body = response.json()
    assert body["summary"]["total"] >= 6
    assert body["summary"]["implemented"] >= 2
    sources = {source["source_id"]: source for source in body["sources"]}
    assert sources["fake"]["stage"] == "implemented"
    assert sources["aviasales_data"]["stage"] == "implemented"
    assert sources["aviasales_data"]["credentials_present"] is True
    assert "https://api.travelpayouts.com" in sources["aviasales_data"]["egress_policy"]
    assert sources["aviasales_search"]["stage"] == "policy_skeleton"
    assert sources["aviasales_search"]["merge_scope"] == "provider_isolated"
    assert sources["aviasales_search"]["background_requests_allowed"] is False
    assert "not_configured_until_access_approved" in sources["aviasales_search"]["egress_policy"]
    assert "secret-value" not in str(body)
