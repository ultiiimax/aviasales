from __future__ import annotations

from dataclasses import replace
from datetime import date

import pytest

from flight_hunter.application.agent_scope import (
    AnywhereDiscoveryRule,
    CoverageMode,
    GeographyChoice,
    GeographyClarification,
    ScopeResolver,
)
from flight_hunter.domain.agent_search import LocationScope, LocationScopeKind
from flight_hunter.geo.airports import (
    Airport,
    AirportCatalogSnapshot,
    AirportType,
    freeze_airport_catalog,
)


class MutableAirportCatalog:
    def __init__(self, airports: tuple[Airport, ...]) -> None:
        self.airports = airports

    async def catalog_snapshot(self) -> AirportCatalogSnapshot:
        return freeze_airport_catalog(self.airports)


def _airport(
    code: str,
    municipality: str,
    country: str,
    *,
    airport_type: AirportType = AirportType.LARGE_AIRPORT,
    scheduled_service: bool = True,
    active: bool = True,
    keywords: tuple[str, ...] = (),
) -> Airport:
    return Airport(
        iata_code=code,
        name=f"{municipality} {code} Airport",
        municipality=municipality,
        country_code=country,
        latitude=48.0 + len(code) / 100,
        longitude=2.0 + len(municipality) / 100,
        airport_type=airport_type,
        active=active,
        keywords=keywords,
        scheduled_service=scheduled_service,
        commercial_provenance="ourairports.scheduled_service",
    )


def _french_catalog() -> tuple[Airport, ...]:
    return (
        _airport("ORY", "Paris", "FR"),
        _airport("CDG", "Paris", "FR"),
        _airport("NCE", "Nice", "FR"),
        _airport("LYS", "Lyon", "FR"),
        _airport("SML", "Smallville", "FR", airport_type=AirportType.SMALL_AIRPORT),
        _airport("NOS", "Idle", "FR", scheduled_service=False),
        _airport("CLS", "Closed", "FR", active=False),
        _airport("BRU", "Brussels", "BE"),
    )


@pytest.mark.anyio
async def test_country_scope_freezes_all_searchable_airports_and_catalog_checksum() -> None:
    repository = MutableAirportCatalog(_french_catalog())
    original_checksum = (await repository.catalog_snapshot()).checksum
    resolver = ScopeResolver(repository=repository)

    resolved = await resolver.resolve_finite(
        LocationScope(LocationScopeKind.COUNTRY, "FR"),
        coverage=CoverageMode.FULL,
    )

    assert resolved.airport_codes == ("CDG", "LYS", "NCE", "ORY")
    assert resolved.catalog_checksum == original_checksum
    assert resolved.commercial_provenance == "ourairports.scheduled_service"


@pytest.mark.anyio
async def test_quick_scope_requires_an_explicit_limit_and_orders_deterministically() -> None:
    resolver = ScopeResolver(repository=MutableAirportCatalog(tuple(reversed(_french_catalog()))))

    with pytest.raises(ValueError, match="quick_limit"):
        await resolver.resolve_finite(
            LocationScope(LocationScopeKind.COUNTRY, "FR"),
            coverage=CoverageMode.QUICK,
        )

    quick = await resolver.resolve_finite(
        LocationScope(LocationScopeKind.COUNTRY, "FR"),
        coverage=CoverageMode.QUICK,
        quick_limit=2,
    )

    assert quick.airport_codes == ("CDG", "LYS")


@pytest.mark.anyio
async def test_frozen_scope_keeps_old_checksum_after_later_catalog_import() -> None:
    repository = MutableAirportCatalog(_french_catalog())
    resolver = ScopeResolver(repository=repository)
    frozen = await resolver.resolve_finite(
        LocationScope(LocationScopeKind.COUNTRY, "FR"),
        coverage=CoverageMode.FULL,
    )

    repository.airports += (_airport("BVA", "Beauvais", "FR"),)
    later = await resolver.resolve_finite(
        LocationScope(LocationScopeKind.COUNTRY, "FR"),
        coverage=CoverageMode.FULL,
    )

    assert frozen.airport_codes == ("CDG", "LYS", "NCE", "ORY")
    assert frozen.catalog_checksum != later.catalog_checksum
    assert later.airport_codes == ("BVA", "CDG", "LYS", "NCE", "ORY")


def test_country_names_resolve_only_through_versioned_country_taxonomy() -> None:
    resolver = ScopeResolver(repository=MutableAirportCatalog(_french_catalog()))

    french = resolver.resolve_country_text("France")
    russian = resolver.resolve_country_text("Франция")
    congo = resolver.resolve_country_text("Congo")
    unknown = resolver.resolve_country_text("Атлантида")

    assert isinstance(french, GeographyChoice)
    assert isinstance(russian, GeographyChoice)
    assert french.scope == LocationScope(LocationScopeKind.COUNTRY, "FR")
    assert russian.scope == french.scope
    assert french.taxonomy_version.startswith("countries-v1-")
    assert isinstance(congo, GeographyClarification)
    assert congo.reason == "ambiguous_geography"
    assert tuple(choice.scope.value for choice in congo.choices) == ("CD", "CG")
    assert isinstance(unknown, GeographyClarification)
    assert unknown.reason == "unknown_geography"
    assert unknown.choices == ()


@pytest.mark.anyio
async def test_city_text_groups_catalog_matches_and_asks_when_name_is_ambiguous() -> None:
    catalog = (
        *_french_catalog(),
        _airport("PAR", "Springfield", "US", keywords=("springfield",)),
        _airport("SPI", "Springfield", "US", keywords=("springfield",)),
        _airport("ZSF", "Springfield", "CA", keywords=("springfield",)),
    )
    resolver = ScopeResolver(repository=MutableAirportCatalog(catalog))

    paris = await resolver.resolve_city_text("Paris")
    springfield = await resolver.resolve_city_text("Springfield")

    assert isinstance(paris, GeographyChoice)
    assert paris.scope == LocationScope(LocationScopeKind.CITY, "CDG")
    assert paris.airport_codes == ("CDG", "ORY")
    assert isinstance(springfield, GeographyClarification)
    assert springfield.reason == "ambiguous_geography"
    assert tuple(choice.scope.value for choice in springfield.choices) == ("ZSF", "PAR")
    assert tuple(choice.airport_codes for choice in springfield.choices) == (
        ("ZSF",),
        ("PAR", "SPI"),
    )


@pytest.mark.anyio
async def test_city_anchor_expands_same_country_and_normalized_municipality() -> None:
    resolver = ScopeResolver(repository=MutableAirportCatalog(_french_catalog()))

    resolved = await resolver.resolve_finite(
        LocationScope(LocationScopeKind.CITY, "CDG"),
        coverage=CoverageMode.FULL,
    )

    assert resolved.airport_codes == ("CDG", "ORY")


@pytest.mark.anyio
async def test_region_alias_resolves_from_versioned_json_taxonomy() -> None:
    resolver = ScopeResolver(repository=MutableAirportCatalog(_french_catalog()))

    resolved = await resolver.resolve_finite(
        LocationScope(LocationScopeKind.REGION, "западная европа"),
        coverage=CoverageMode.FULL,
    )

    assert resolved.airport_codes == ("BRU", "CDG", "LYS", "NCE", "ORY")
    assert resolved.taxonomy_version.startswith("regions-v1-")


@pytest.mark.anyio
async def test_nearby_expansion_is_separate_from_city_membership() -> None:
    cdg = replace(_airport("CDG", "Paris", "FR"), latitude=49.0097, longitude=2.5479)
    ory = replace(_airport("ORY", "Paris", "FR"), latitude=48.7262, longitude=2.3652)
    bva = replace(_airport("BVA", "Beauvais", "FR"), latitude=49.4544, longitude=2.1128)
    resolver = ScopeResolver(repository=MutableAirportCatalog((cdg, ory, bva)))

    city_only = await resolver.resolve_finite(
        LocationScope(LocationScopeKind.CITY, "CDG"),
        coverage=CoverageMode.FULL,
    )
    with_nearby = await resolver.resolve_finite(
        LocationScope(LocationScopeKind.CITY, "CDG"),
        coverage=CoverageMode.FULL,
        nearby_radius_km=150,
    )

    assert city_only.airport_codes == ("CDG", "ORY")
    assert with_nearby.airport_codes == ("BVA", "CDG", "ORY")


@pytest.mark.anyio
async def test_anywhere_rule_freezes_origins_without_inventing_destinations() -> None:
    resolver = ScopeResolver(repository=MutableAirportCatalog(_french_catalog()))
    origins = await resolver.resolve_finite(
        LocationScope(LocationScopeKind.CITY, "CDG"),
        coverage=CoverageMode.FULL,
    )

    rule = resolver.build_anywhere_rule(
        frozen_origins=origins,
        date_start=date(2026, 9, 1),
        date_end=date(2026, 11, 29),
        allowed_country_codes=("FR", "BE"),
        excluded_country_codes=("DE",),
        max_destination_seeds=12,
        exact_verification_limit=5,
    )

    assert rule == AnywhereDiscoveryRule(
        origin_airports=("CDG", "ORY"),
        date_start=date(2026, 9, 1),
        date_end=date(2026, 11, 29),
        allowed_country_codes=("BE", "FR"),
        excluded_country_codes=("DE",),
        discovery_source_ids=("aviasales_calendar", "aviasales_hot_offers"),
        max_destination_seeds=12,
        exact_verification_limit=5,
        catalog_checksum=origins.catalog_checksum,
        taxonomy_version=resolver.taxonomy_version,
    )
    assert not hasattr(rule, "destination_airports")
