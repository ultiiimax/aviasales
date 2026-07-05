from __future__ import annotations

from flight_hunter.application.price_sources import (
    PriceKind,
    PriceSourceCatalog,
    PriceSourceType,
)


def test_catalog_marks_no_source_as_in_app_booking() -> None:
    catalog = PriceSourceCatalog.default()

    assert catalog.sources
    assert all(not source.in_app_booking for source in catalog.sources)
    assert all(source.purchase_flow == "external_clickout" for source in catalog.sources)


def test_catalog_separates_live_mobile_api_from_external_rub_searches() -> None:
    catalog = PriceSourceCatalog.default()
    by_id = {source.id: source for source in catalog.sources}

    assert by_id["aviasales_search"].price_kind == PriceKind.LIVE
    assert by_id["aviasales_search"].source_type == PriceSourceType.API
    assert by_id["aviasales_search"].supports_rub
    assert not by_id["aviasales_search"].requires_manual_confirmation
    assert by_id["yandex_travel"].source_type == PriceSourceType.PARTNER_LINK
    assert by_id["yandex_travel"].price_kind == PriceKind.USER_CONFIRMED_LIVE
    assert by_id["tutu"].source_type == PriceSourceType.PARTNER_LINK


def test_catalog_includes_official_carrier_clickouts_for_rub_purchase() -> None:
    catalog = PriceSourceCatalog.default()
    carrier_sources = [
        source for source in catalog.sources if source.source_type == PriceSourceType.CARRIER_SITE
    ]

    assert {source.id for source in carrier_sources} >= {
        "aeroflot",
        "pobeda",
        "s7",
        "ural_airlines",
        "nordwind",
        "red_wings",
        "smartavia",
        "azimuth",
        "utair",
        "rossiya",
        "turkish_airlines",
        "air_serbia",
        "pegasus",
        "uzbekistan_airways",
        "emirates",
        "qatar_airways",
        "etihad",
        "flydubai",
    }
    assert all(source.supports_rub for source in carrier_sources)
    assert all(source.requires_manual_confirmation for source in carrier_sources)
