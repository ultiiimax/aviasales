from __future__ import annotations

from fastapi.testclient import TestClient

from flight_hunter.api.app import create_app


def test_admin_provider_health_returns_provider_status_without_secrets(monkeypatch) -> None:
    monkeypatch.setenv("AVIASALES_SEARCH_ENABLED", "true")
    monkeypatch.setenv("AVIASALES_SEARCH_SIGNATURE", "secret-signature")
    monkeypatch.setenv("AVIASALES_SEARCH_MARKER", "secret-marker")
    client = TestClient(create_app())

    response = client.get("/api/v1/admin/providers/health")

    assert response.status_code == 200
    body = response.json()
    assert body["checked_at"]
    providers = {provider["provider_id"]: provider for provider in body["providers"]}
    assert providers["aviasales_search"]["credentials_present"] is True
    assert providers["aviasales_search"]["secret_present"] is True
    assert "secret-signature" not in str(body)
    assert "secret-marker" not in str(body)
