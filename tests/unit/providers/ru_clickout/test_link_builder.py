from __future__ import annotations

from urllib.parse import urlparse

from flight_hunter.domain.offers import SearchIntent
from flight_hunter.providers.ru_clickout.link_builder import RuClickoutLinkBuilder
from flight_hunter.providers.ru_clickout.source_specs import default_ru_aggregator_specs


def test_ru_clickout_builds_conservative_external_links_for_default_sources() -> None:
    intent = SearchIntent(
        origin="MOW",
        destination="IST",
        departure_date="2026-09-10",
        return_date="2026-09-20",
        passengers=2,
        adults=2,
        children=0,
        infants=0,
        currency="RUB",
    )
    builder = RuClickoutLinkBuilder(default_ru_aggregator_specs())

    links = builder.build_all(intent)

    ids = {link.source_id for link in links}
    assert {
        "aviasales_clickout",
        "yandex_travel",
        "tutu",
        "onetwotrip",
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
    }.issubset(ids)
    assert all(link.price_known is False for link in links)
    assert all(link.requires_external_confirmation is True for link in links)
    assert all(link.origin == "MOW" and link.destination == "IST" for link in links)
    assert all(link.currency == "RUB" for link in links)


def test_ru_clickout_urls_stay_inside_declared_allowed_hosts() -> None:
    intent = SearchIntent(
        origin="WAW",
        destination="BCN",
        departure_date="2026-10-12",
        return_date=None,
        passengers=1,
        currency="RUB",
    )
    specs = default_ru_aggregator_specs()
    builder = RuClickoutLinkBuilder(specs)

    links = builder.build_all(intent)
    specs_by_id = {spec.source_id: spec for spec in specs}

    for link in links:
        host = urlparse(link.url).netloc.lower()
        assert host in specs_by_id[link.source_id].allowed_hosts


def test_ru_clickout_does_not_fake_precise_deeplink_for_unknown_templates() -> None:
    intent = SearchIntent(
        origin="WAW",
        destination="BCN",
        departure_date="2026-10-12",
        return_date="2026-10-19",
        passengers=3,
        adults=2,
        children=1,
        infants=0,
        currency="RUB",
    )
    builder = RuClickoutLinkBuilder(default_ru_aggregator_specs())

    links = {link.source_id: link for link in builder.build_all(intent)}

    tutu = links["tutu"]
    assert tutu.url == "https://www.tutu.ru/"
    assert "заполните маршрут" in (tutu.notes_ru or "").lower()
    assert "children_not_prefilled" in tutu.warnings


def test_ru_clickout_can_filter_enabled_sources() -> None:
    intent = SearchIntent(
        origin="WAW",
        destination="BCN",
        departure_date="2026-10-12",
        return_date=None,
        passengers=1,
        currency="RUB",
    )
    builder = RuClickoutLinkBuilder(default_ru_aggregator_specs())

    links = builder.build_all(intent, enabled_source_ids=("tutu", "s7"))

    assert [link.source_id for link in links] == ["tutu", "s7"]
