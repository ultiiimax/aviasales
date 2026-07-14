from __future__ import annotations

import json
import re
import unicodedata
from collections import defaultdict
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date
from enum import StrEnum
from hashlib import sha256
from importlib.resources import files
from typing import Literal, Protocol, cast

from flight_hunter.domain.agent_search import LocationScope, LocationScopeKind
from flight_hunter.geo.airports import Airport, AirportCatalogSnapshot, distance_km

_COUNTRY_CODE_RE = re.compile(r"^[A-Z]{2}$")
_DISCOVERY_SOURCE_IDS = ("aviasales_calendar", "aviasales_hot_offers")
_ASSIGNED_ISO_COUNTRY_COUNT = 250
_REJECTED_NON_ISO_COUNTRY_CODES = frozenset({"AC", "CP", "DG", "EA", "IC", "TA", "XK"})


class CoverageMode(StrEnum):
    QUICK = "quick"
    FULL = "full"


ClarificationReason = Literal[
    "unknown_geography",
    "ambiguous_geography",
    "no_searchable_airports",
]


class AirportCatalogRepository(Protocol):
    async def catalog_snapshot(self) -> AirportCatalogSnapshot: ...


@dataclass(frozen=True, slots=True)
class GeographyChoice:
    label: str
    scope: LocationScope
    airport_codes: tuple[str, ...]
    taxonomy_version: str


@dataclass(frozen=True, slots=True)
class GeographyClarification:
    query: str
    kind: LocationScopeKind
    reason: ClarificationReason
    choices: tuple[GeographyChoice, ...]
    taxonomy_version: str


@dataclass(frozen=True, slots=True)
class FrozenAirportScope:
    requested_scope: LocationScope
    airport_codes: tuple[str, ...]
    catalog_checksum: str
    taxonomy_version: str
    commercial_provenance: str
    coverage: CoverageMode
    nearby_radius_km: int


@dataclass(frozen=True, slots=True)
class AnywhereDiscoveryRule:
    origin_airports: tuple[str, ...]
    date_start: date
    date_end: date
    allowed_country_codes: tuple[str, ...]
    excluded_country_codes: tuple[str, ...]
    discovery_source_ids: tuple[str, ...]
    max_destination_seeds: int
    exact_verification_limit: int
    catalog_checksum: str
    taxonomy_version: str


@dataclass(frozen=True, slots=True)
class _Country:
    code: str
    english_name: str
    russian_name: str
    aliases: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class _CountryTaxonomy:
    version: str
    countries: Mapping[str, _Country]
    text_index: Mapping[str, tuple[str, ...]]


@dataclass(frozen=True, slots=True)
class _Region:
    region_id: str
    country_codes: tuple[str, ...]
    aliases: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class _RegionTaxonomy:
    version: str
    regions: Mapping[str, _Region]
    text_index: Mapping[str, tuple[str, ...]]


class ScopeResolver:
    def __init__(self, *, repository: AirportCatalogRepository) -> None:
        self._repository = repository
        self._countries = _load_country_taxonomy()
        self._regions = _load_region_taxonomy(self._countries)

    @property
    def taxonomy_version(self) -> str:
        return self._regions.version

    def resolve_country_text(
        self,
        text: str,
    ) -> GeographyChoice | GeographyClarification:
        normalized = _normalize_geography_text(text)
        country_codes = self._countries.text_index.get(normalized, ())
        choices = tuple(self._country_choice(code) for code in country_codes)
        if len(choices) == 1:
            return choices[0]
        return GeographyClarification(
            query=text,
            kind=LocationScopeKind.COUNTRY,
            reason="ambiguous_geography" if choices else "unknown_geography",
            choices=choices,
            taxonomy_version=self._countries.version,
        )

    def resolve_region_text(
        self,
        text: str,
    ) -> GeographyChoice | GeographyClarification:
        normalized = _normalize_geography_text(text)
        region_ids = self._regions.text_index.get(normalized, ())
        choices = tuple(self._region_choice(region_id, ()) for region_id in region_ids)
        if len(choices) == 1:
            return choices[0]
        return GeographyClarification(
            query=text,
            kind=LocationScopeKind.REGION,
            reason="ambiguous_geography" if choices else "unknown_geography",
            choices=choices,
            taxonomy_version=self._regions.version,
        )

    async def resolve_city_text(
        self,
        text: str,
    ) -> GeographyChoice | GeographyClarification:
        normalized = _normalize_geography_text(text)
        snapshot = await self._repository.catalog_snapshot()
        matching = tuple(
            airport
            for airport in snapshot.airports
            if airport.is_searchable and _airport_matches_city_text(airport, normalized)
        )
        groups: dict[tuple[str, str], list[Airport]] = defaultdict(list)
        for airport in matching:
            key = (airport.country_code, _normalize_geography_text(airport.municipality))
            groups[key].append(airport)
        choices = tuple(
            _city_choice(group, taxonomy_version=self._countries.version)
            for _, group in sorted(groups.items())
        )
        if len(choices) == 1:
            return choices[0]
        return GeographyClarification(
            query=text,
            kind=LocationScopeKind.CITY,
            reason="ambiguous_geography" if choices else "unknown_geography",
            choices=choices,
            taxonomy_version=self._countries.version,
        )

    async def resolve_finite(
        self,
        scope: LocationScope,
        *,
        coverage: CoverageMode,
        quick_limit: int | None = None,
        nearby_radius_km: int = 0,
    ) -> FrozenAirportScope | GeographyClarification:
        if not isinstance(scope, LocationScope):
            raise TypeError("scope must be a LocationScope")
        if scope.kind is LocationScopeKind.ANYWHERE:
            raise ValueError("anywhere requires a discovery rule")
        normalized_coverage = _validate_coverage(coverage, quick_limit)
        _validate_nearby_radius(nearby_radius_km)
        if scope.kind is LocationScopeKind.COUNTRY:
            assert scope.value is not None
            if scope.value not in self._countries.countries:
                return GeographyClarification(
                    query=scope.value,
                    kind=LocationScopeKind.COUNTRY,
                    reason="unknown_geography",
                    choices=(),
                    taxonomy_version=self._countries.version,
                )

        snapshot = await self._repository.catalog_snapshot()
        searchable = tuple(airport for airport in snapshot.airports if airport.is_searchable)
        selected = self._select_base_airports(scope, searchable)
        if isinstance(selected, GeographyClarification):
            return selected
        if not selected:
            return GeographyClarification(
                query=scope.value or "",
                kind=scope.kind,
                reason="no_searchable_airports",
                choices=(),
                taxonomy_version=self._taxonomy_version_for(scope.kind),
            )

        expanded = _expand_nearby(selected, searchable, nearby_radius_km)
        ordered = tuple(sorted(expanded, key=lambda airport: airport.iata_code))
        if normalized_coverage is CoverageMode.QUICK:
            assert quick_limit is not None
            ordered = ordered[:quick_limit]
        provenances = tuple(
            sorted(
                {
                    airport.commercial_provenance
                    for airport in ordered
                    if airport.commercial_provenance is not None
                }
            )
        )
        commercial_provenance = (
            provenances[0] if len(provenances) == 1 else f"mixed:{'+'.join(provenances)}"
        )
        return FrozenAirportScope(
            requested_scope=scope,
            airport_codes=tuple(airport.iata_code for airport in ordered),
            catalog_checksum=snapshot.checksum,
            taxonomy_version=self._taxonomy_version_for(scope.kind),
            commercial_provenance=commercial_provenance,
            coverage=normalized_coverage,
            nearby_radius_km=nearby_radius_km,
        )

    def build_anywhere_rule(
        self,
        *,
        frozen_origins: FrozenAirportScope,
        date_start: date,
        date_end: date,
        allowed_country_codes: tuple[str, ...] = (),
        excluded_country_codes: tuple[str, ...] = (),
        max_destination_seeds: int,
        exact_verification_limit: int,
    ) -> AnywhereDiscoveryRule:
        if not isinstance(frozen_origins, FrozenAirportScope):
            raise TypeError("frozen_origins must be a FrozenAirportScope")
        if type(date_start) is not date or type(date_end) is not date:
            raise TypeError("anywhere date bounds must be dates")
        if date_end < date_start:
            raise ValueError("date_end cannot be before date_start")
        allowed = self._normalized_country_codes(allowed_country_codes)
        excluded = self._normalized_country_codes(excluded_country_codes)
        if set(allowed) & set(excluded):
            raise ValueError("allowed and excluded country codes cannot overlap")
        if type(max_destination_seeds) is not int or max_destination_seeds < 1:
            raise ValueError("max_destination_seeds must be a positive integer")
        if type(exact_verification_limit) is not int or exact_verification_limit < 1:
            raise ValueError("exact_verification_limit must be a positive integer")
        if exact_verification_limit > max_destination_seeds:
            raise ValueError("exact_verification_limit cannot exceed max_destination_seeds")
        return AnywhereDiscoveryRule(
            origin_airports=frozen_origins.airport_codes,
            date_start=date_start,
            date_end=date_end,
            allowed_country_codes=allowed,
            excluded_country_codes=excluded,
            discovery_source_ids=_DISCOVERY_SOURCE_IDS,
            max_destination_seeds=max_destination_seeds,
            exact_verification_limit=exact_verification_limit,
            catalog_checksum=frozen_origins.catalog_checksum,
            taxonomy_version=self.taxonomy_version,
        )

    def _select_base_airports(
        self,
        scope: LocationScope,
        searchable: tuple[Airport, ...],
    ) -> tuple[Airport, ...] | GeographyClarification:
        assert scope.value is not None
        if scope.kind is LocationScopeKind.AIRPORT:
            return tuple(airport for airport in searchable if airport.iata_code == scope.value)
        if scope.kind is LocationScopeKind.CITY:
            anchor = next(
                (airport for airport in searchable if airport.iata_code == scope.value),
                None,
            )
            if anchor is None:
                return ()
            municipality = _normalize_geography_text(anchor.municipality)
            return tuple(
                airport
                for airport in searchable
                if airport.country_code == anchor.country_code
                and _normalize_geography_text(airport.municipality) == municipality
            )
        if scope.kind is LocationScopeKind.COUNTRY:
            return tuple(airport for airport in searchable if airport.country_code == scope.value)
        region_ids = self._regions.text_index.get(_normalize_geography_text(scope.value), ())
        if len(region_ids) != 1:
            choices = tuple(self._region_choice(region_id, searchable) for region_id in region_ids)
            return GeographyClarification(
                query=scope.value,
                kind=LocationScopeKind.REGION,
                reason="ambiguous_geography" if choices else "unknown_geography",
                choices=choices,
                taxonomy_version=self._regions.version,
            )
        country_codes = set(self._regions.regions[region_ids[0]].country_codes)
        return tuple(airport for airport in searchable if airport.country_code in country_codes)

    def _country_choice(self, code: str) -> GeographyChoice:
        country = self._countries.countries[code]
        return GeographyChoice(
            label=f"{country.english_name} / {country.russian_name} ({code})",
            scope=LocationScope(LocationScopeKind.COUNTRY, code),
            airport_codes=(),
            taxonomy_version=self._countries.version,
        )

    def _region_choice(
        self,
        region_id: str,
        searchable: tuple[Airport, ...],
    ) -> GeographyChoice:
        region = self._regions.regions[region_id]
        country_codes = set(region.country_codes)
        airport_codes = tuple(
            sorted(
                airport.iata_code for airport in searchable if airport.country_code in country_codes
            )
        )
        return GeographyChoice(
            label=region.aliases[0] if region.aliases else region_id,
            scope=LocationScope(LocationScopeKind.REGION, region_id),
            airport_codes=airport_codes,
            taxonomy_version=self._regions.version,
        )

    def _normalized_country_codes(self, values: tuple[str, ...]) -> tuple[str, ...]:
        if isinstance(values, str):
            raise TypeError("country codes must be a collection")
        normalized = tuple(sorted({value.strip().upper() for value in values}))
        unknown = tuple(
            code
            for code in normalized
            if not _COUNTRY_CODE_RE.fullmatch(code) or code not in self._countries.countries
        )
        if unknown:
            raise ValueError(f"unknown ISO country codes: {', '.join(unknown)}")
        return normalized

    def _taxonomy_version_for(self, kind: LocationScopeKind) -> str:
        if kind is LocationScopeKind.REGION:
            return self._regions.version
        return self._countries.version


def _validate_coverage(coverage: CoverageMode, quick_limit: int | None) -> CoverageMode:
    normalized = CoverageMode(coverage)
    if normalized is CoverageMode.QUICK:
        if type(quick_limit) is not int or quick_limit < 1:
            raise ValueError("quick_limit must be a positive integer for quick coverage")
    elif quick_limit is not None:
        raise ValueError("quick_limit must be omitted for full coverage")
    return normalized


def _validate_nearby_radius(nearby_radius_km: int) -> None:
    if type(nearby_radius_km) is not int or nearby_radius_km < 0:
        raise ValueError("nearby_radius_km must be a non-negative integer")


def _expand_nearby(
    selected: tuple[Airport, ...],
    searchable: tuple[Airport, ...],
    radius_km: int,
) -> tuple[Airport, ...]:
    if radius_km == 0:
        return selected
    selected_codes = {airport.iata_code for airport in selected}
    expanded = list(selected)
    for candidate in searchable:
        if candidate.iata_code in selected_codes:
            continue
        if any(distance_km(origin, candidate) <= radius_km for origin in selected):
            expanded.append(candidate)
            selected_codes.add(candidate.iata_code)
    return tuple(expanded)


def _airport_matches_city_text(airport: Airport, normalized_query: str) -> bool:
    if not normalized_query:
        return False
    values = (airport.municipality, airport.name, *airport.keywords)
    return any(normalized_query in _normalize_geography_text(value) for value in values if value)


def _city_choice(
    airports: list[Airport],
    *,
    taxonomy_version: str,
) -> GeographyChoice:
    ordered = tuple(sorted(airports, key=lambda airport: airport.iata_code))
    anchor = ordered[0]
    codes = tuple(airport.iata_code for airport in ordered)
    return GeographyChoice(
        label=f"{anchor.municipality}, {anchor.country_code} ({', '.join(codes)})",
        scope=LocationScope(LocationScopeKind.CITY, anchor.iata_code),
        airport_codes=codes,
        taxonomy_version=taxonomy_version,
    )


def _normalize_geography_text(value: str) -> str:
    if not isinstance(value, str):
        raise TypeError("geography text must be a string")
    normalized = unicodedata.normalize("NFKC", value).casefold()
    normalized = re.sub(r"[_\-\N{EN DASH}\N{EM DASH}]+", " ", normalized)
    normalized = re.sub(r"[^\w\s]+", " ", normalized, flags=re.UNICODE)
    return " ".join(normalized.split())


def _load_country_taxonomy() -> _CountryTaxonomy:
    payload = _resource_mapping("countries.v1.json")
    version = _required_string(payload, "version")
    countries_payload = _required_mapping(payload, "countries")
    source = _required_mapping(payload, "source")
    _validate_import_checksum(countries_payload, source)
    countries: dict[str, _Country] = {}
    index: dict[str, set[str]] = defaultdict(set)
    for code, raw_country in sorted(countries_payload.items()):
        if not _COUNTRY_CODE_RE.fullmatch(code):
            raise ValueError(f"invalid country taxonomy code: {code}")
        country_payload = _as_mapping(raw_country, f"countries.{code}")
        english_name = _required_string(country_payload, "en")
        russian_name = _required_string(country_payload, "ru")
        aliases = _string_tuple(country_payload.get("aliases"), f"countries.{code}.aliases")
        country = _Country(
            code=code,
            english_name=english_name,
            russian_name=russian_name,
            aliases=aliases,
        )
        countries[code] = country
        for value in (code, english_name, russian_name, *aliases):
            index[_normalize_geography_text(value)].add(code)
    expected_count = source.get("entry_count")
    if type(expected_count) is not int or expected_count != len(countries):
        raise ValueError("country taxonomy entry count does not match source metadata")
    code_selection = _required_mapping(source, "code_selection")
    excluded_non_iso_codes = set(
        _string_tuple(
            code_selection.get("excluded_non_iso_codes"),
            "source.code_selection.excluded_non_iso_codes",
        )
    )
    if (
        len(countries) != _ASSIGNED_ISO_COUNTRY_COUNT
        or "CQ" not in countries
        or not _REJECTED_NON_ISO_COUNTRY_CODES.isdisjoint(countries)
        or excluded_non_iso_codes != _REJECTED_NON_ISO_COUNTRY_CODES
    ):
        raise ValueError("country taxonomy does not contain the assigned ISO code set")
    return _CountryTaxonomy(
        version=version,
        countries=countries,
        text_index={key: tuple(sorted(value)) for key, value in index.items()},
    )


def _load_region_taxonomy(countries: _CountryTaxonomy) -> _RegionTaxonomy:
    payload = _resource_mapping("regions.v1.json")
    version = _required_string(payload, "version")
    regions_payload = _required_mapping(payload, "regions")
    source = _required_mapping(payload, "source")
    _validate_import_checksum(regions_payload, source)
    regions: dict[str, _Region] = {}
    index: dict[str, set[str]] = defaultdict(set)
    for region_id, raw_region in sorted(regions_payload.items()):
        region_payload = _as_mapping(raw_region, f"regions.{region_id}")
        country_codes = _string_tuple(
            region_payload.get("country_codes"),
            f"regions.{region_id}.country_codes",
        )
        if any(code not in countries.countries for code in country_codes):
            raise ValueError(f"region {region_id} contains an unknown ISO country code")
        aliases = _string_tuple(region_payload.get("aliases"), f"regions.{region_id}.aliases")
        region = _Region(
            region_id=region_id,
            country_codes=tuple(sorted(set(country_codes))),
            aliases=aliases,
        )
        regions[region_id] = region
        for value in (region_id, *aliases):
            index[_normalize_geography_text(value)].add(region_id)
    expected_count = source.get("entry_count")
    if type(expected_count) is not int or expected_count != len(regions):
        raise ValueError("region taxonomy entry count does not match source metadata")
    return _RegionTaxonomy(
        version=version,
        regions=regions,
        text_index={key: tuple(sorted(value)) for key, value in index.items()},
    )


def _resource_mapping(name: str) -> Mapping[str, object]:
    raw: object = json.loads(files("flight_hunter.geo").joinpath(name).read_text(encoding="utf-8"))
    return _as_mapping(raw, name)


def _as_mapping(value: object, field: str) -> Mapping[str, object]:
    if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
        raise ValueError(f"{field} must be a JSON object")
    return cast(dict[str, object], value)


def _required_mapping(value: Mapping[str, object], field: str) -> Mapping[str, object]:
    if field not in value:
        raise ValueError(f"{field} is required")
    return _as_mapping(value[field], field)


def _required_string(value: Mapping[str, object], field: str) -> str:
    result = value.get(field)
    if not isinstance(result, str) or not result:
        raise ValueError(f"{field} must be a non-empty string")
    return result


def _string_tuple(value: object, field: str) -> tuple[str, ...]:
    if not isinstance(value, list) or not all(isinstance(item, str) and item for item in value):
        raise ValueError(f"{field} must be a list of non-empty strings")
    return tuple(cast(list[str], value))


def _validate_import_checksum(
    values: Mapping[str, object],
    source: Mapping[str, object],
) -> None:
    expected = _required_string(source, "import_checksum_sha256")
    canonical = json.dumps(
        values,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    actual = sha256(canonical).hexdigest()
    if actual != expected:
        raise ValueError("taxonomy import checksum mismatch")
