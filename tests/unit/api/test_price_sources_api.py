from __future__ import annotations

from fastapi.testclient import TestClient

from flight_hunter.api.app import create_app


def test_price_sources_endpoint_lists_clickout_sources_without_booking() -> None:
    client = TestClient(create_app())

    response = client.get("/api/v1/price-sources")

    assert response.status_code == 200
    body = response.json()
    assert body["strategy"] == "external_clickout"
    sources = {source["id"]: source for source in body["sources"]}
    assert sources["aviasales_search"]["price_kind"] == "live"
    assert sources["aviasales_search"]["source_type"] == "api"
    assert sources["yandex_travel"]["source_type"] == "partner_link"
    assert sources["aeroflot"]["source_type"] == "carrier_site"
    assert all(source["in_app_booking"] is False for source in body["sources"])
    assert all(source["supports_rub"] is True for source in body["sources"])
