from __future__ import annotations

import json
import re
import unicodedata
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from hashlib import sha256
from importlib.resources import files
from pathlib import Path
from types import MappingProxyType
from typing import ClassVar, cast

from flight_hunter.domain.places import PlaceKind, PlaceLabel, PlaceOption, PlaceRef
from flight_hunter.geo.airports import Airport, AirportCatalogSnapshot

_IATA_RE = re.compile(r"[A-Z]{3}")
_COUNTRY_RE = re.compile(r"[A-Z]{2}")
_AIRPORT_MEMBERSHIP_VERSION = "airport-self-v1"
_AIRPORT_MEMBERSHIP_OBSERVED_AT = "catalog-snapshot"


class PlaceDirectoryError(LookupError):
    code: ClassVar[str]

    def __init__(self, reason: str, *, ref: PlaceRef | None = None, code: str | None = None):
        self.reason = reason
        self.ref = ref
        self.place_code = ref.code if ref is not None else code
        identity = (
            f"{ref.kind.value}:{ref.code}"
            if ref is not None
            else (code if code is not None else "unknown")
        )
        super().__init__(f"{self.code}:{reason}:{identity}")


class PlaceUnknownError(PlaceDirectoryError):
    code = "place_unknown"


class PlaceKindRequiredError(PlaceDirectoryError):
    code = "place_kind_required"


class PlaceUnavailableError(PlaceDirectoryError):
    code = "place_unavailable"


@dataclass(frozen=True, slots=True)
class _CityGroup:
    ref: PlaceRef
    country_code: str
    allowed_member_countries: tuple[str, ...]
    names: tuple[tuple[str, str], ...]
    aliases: tuple[str, ...]
    airport_codes: tuple[str, ...]
    coverage: str
    membership_version: str
    observed_at: str
    provenance: str


@dataclass(frozen=True, slots=True)
class _LabelOverlay:
    ref: PlaceRef
    names: tuple[tuple[str, str], ...]
    city_names: tuple[tuple[str, str], ...]
    aliases: tuple[str, ...]
    provenance: str


@dataclass(frozen=True, slots=True)
class _CountryFacts:
    names: tuple[tuple[str, str], ...]
    aliases: tuple[str, ...]


class PlaceDirectory:
    def __init__(
        self,
        *,
        snapshot: AirportCatalogSnapshot,
        groups: tuple[_CityGroup, ...],
        overlays: tuple[_LabelOverlay, ...],
        countries: tuple[tuple[str, _CountryFacts], ...],
        directory_version: str,
    ) -> None:
        airports_by_code: dict[str, Airport] = {}
        for airport in snapshot.airports:
            if not isinstance(airport, Airport):
                raise TypeError("airport catalog must contain Airport values")
            if airport.iata_code in airports_by_code:
                raise ValueError(f"duplicate_typed_place_key:airport:{airport.iata_code}")
            airports_by_code[airport.iata_code] = airport

        groups_by_code: dict[str, _CityGroup] = {}
        for group in groups:
            if group.ref.code in groups_by_code:
                raise ValueError(f"duplicate_typed_place_key:city:{group.ref.code}")
            groups_by_code[group.ref.code] = group

        overlays_by_ref: dict[PlaceRef, _LabelOverlay] = {}
        for overlay in overlays:
            if overlay.ref in overlays_by_ref:
                raise ValueError(
                    f"duplicate_typed_place_key:{overlay.ref.kind.value}:{overlay.ref.code}"
                )
            overlays_by_ref[overlay.ref] = overlay

        member_groups: dict[str, list[_CityGroup]] = {}
        for group in groups:
            for airport_code in group.airport_codes:
                member_groups.setdefault(airport_code, []).append(group)

        self._snapshot = snapshot
        self._airports_by_code: Mapping[str, Airport] = MappingProxyType(airports_by_code)
        self._groups_by_code: Mapping[str, _CityGroup] = MappingProxyType(groups_by_code)
        self._overlays_by_ref: Mapping[PlaceRef, _LabelOverlay] = MappingProxyType(overlays_by_ref)
        self._countries: Mapping[str, _CountryFacts] = MappingProxyType(dict(countries))
        self._member_groups: Mapping[str, tuple[_CityGroup, ...]] = MappingProxyType(
            {
                code: tuple(sorted(values, key=lambda value: value.ref.code))
                for code, values in member_groups.items()
            }
        )
        self._directory_version = directory_version

    @property
    def directory_version(self) -> str:
        return self._directory_version

    @classmethod
    def from_snapshot(
        cls,
        snapshot: AirportCatalogSnapshot,
        *,
        city_groups_path: str | Path | None = None,
        place_labels_path: str | Path | None = None,
        countries_path: str | Path | None = None,
    ) -> PlaceDirectory:
        if not isinstance(snapshot, AirportCatalogSnapshot):
            raise TypeError("snapshot must be an AirportCatalogSnapshot")
        groups_payload = _load_payload(city_groups_path, "city_groups.v1.json")
        labels_payload = _load_payload(place_labels_path, "place_labels.v1.json")
        countries_payload = _load_payload(countries_path, "countries.v1.json")
        groups = _parse_city_groups(groups_payload)
        overlays = _parse_label_overlays(labels_payload)
        countries = _parse_countries(countries_payload)
        checksum_payload = {
            "schema": "place-directory-v1",
            "airport_catalog_checksum": snapshot.checksum,
            "city_groups": groups_payload,
            "place_labels": labels_payload,
            "countries": countries_payload,
        }
        directory_version = sha256(
            json.dumps(
                checksum_payload,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
        return cls(
            snapshot=snapshot,
            groups=groups,
            overlays=overlays,
            countries=countries,
            directory_version=directory_version,
        )

    def lookup(self, ref: PlaceRef, locale: str = "ru") -> PlaceOption:
        if not isinstance(ref, PlaceRef):
            raise TypeError("ref must be a PlaceRef")
        language = _language(locale)
        if ref.kind is PlaceKind.AIRPORT:
            airport = self._airports_by_code.get(ref.code)
            if airport is None:
                raise PlaceUnknownError("typed_ref_not_found", ref=ref)
            if not airport.is_searchable:
                raise PlaceUnavailableError("airport_not_searchable", ref=ref)
            return self._airport_option(airport, language)

        group = self._groups_by_code.get(ref.code)
        if group is None:
            raise PlaceUnknownError("typed_ref_not_found", ref=ref)
        self._validate_executable_group(group)
        return self._city_option(group, language)

    def resolve_legacy(self, code: str, locale: str = "ru") -> PlaceOption:
        normalized_code = _iata_code(code, "legacy place code")
        airport_exists = normalized_code in self._airports_by_code
        city_exists = normalized_code in self._groups_by_code
        if airport_exists and city_exists:
            raise PlaceKindRequiredError("ambiguous_bare_place_code", code=normalized_code)
        if airport_exists:
            return self.lookup(PlaceRef(PlaceKind.AIRPORT, normalized_code), locale)
        if city_exists:
            return self.lookup(PlaceRef(PlaceKind.CITY, normalized_code), locale)
        raise PlaceUnknownError("bare_code_not_found", code=normalized_code)

    def suggest(
        self,
        query: str,
        locale: str = "ru",
        limit: int = 20,
    ) -> tuple[PlaceOption, ...]:
        if not isinstance(query, str):
            raise TypeError("query must be a string")
        if type(limit) is not int:
            raise TypeError("limit must be an integer")
        if limit <= 0:
            raise ValueError("limit must be positive")
        normalized_query = _search_text(query)
        if not normalized_query:
            return ()
        language = _language(locale)
        ranked: list[tuple[int, int, str, str, PlaceOption]] = []
        refs = tuple(
            [PlaceRef(PlaceKind.CITY, code) for code in self._groups_by_code]
            + [PlaceRef(PlaceKind.AIRPORT, code) for code in self._airports_by_code]
        )
        for ref in refs:
            try:
                option = self.lookup(ref, language)
            except PlaceUnavailableError:
                continue
            terms = self._search_terms(ref, option)
            rank = _match_rank(normalized_query, ref.code, terms)
            if rank is None:
                continue
            ranked.append(
                (
                    rank,
                    0 if ref.kind is PlaceKind.CITY else 1,
                    _search_text(option.display_name.text),
                    ref.code,
                    option,
                )
            )
        ranked.sort(key=lambda item: item[:4])
        return tuple(item[4] for item in ranked[:limit])

    def _airport_option(self, airport: Airport, language: str) -> PlaceOption:
        ref = PlaceRef(PlaceKind.AIRPORT, airport.iata_code)
        overlay = self._overlays_by_ref.get(ref)
        display_name = _airport_label(
            localized=overlay.names if overlay is not None else (),
            language=language,
            source_text=airport.name,
            localized_provenance=(
                overlay.provenance if overlay is not None else "bundled_place_label"
            ),
        )
        city_name = _airport_label(
            localized=overlay.city_names if overlay is not None else (),
            language=language,
            source_text=airport.municipality,
            localized_provenance=(
                overlay.provenance if overlay is not None else "bundled_place_label"
            ),
        )
        return PlaceOption(
            ref=ref,
            display_name=display_name,
            city_name=city_name,
            country_code=airport.country_code,
            country_name=self._country_label(airport.country_code, language),
            airport_codes=(airport.iata_code,),
            directory_version=self._directory_version,
            membership_version=_AIRPORT_MEMBERSHIP_VERSION,
            membership_observed_at=_AIRPORT_MEMBERSHIP_OBSERVED_AT,
        )

    def _city_option(self, group: _CityGroup, language: str) -> PlaceOption:
        display_name = _bundled_label(
            group.names,
            language=language,
            provenance=group.provenance,
            code=group.ref.code,
        )
        return PlaceOption(
            ref=group.ref,
            display_name=display_name,
            city_name=None,
            country_code=group.country_code,
            country_name=self._country_label(group.country_code, language),
            airport_codes=group.airport_codes,
            directory_version=self._directory_version,
            membership_version=group.membership_version,
            membership_observed_at=group.observed_at,
        )

    def _country_label(self, country_code: str, language: str) -> PlaceLabel:
        facts = self._countries.get(country_code)
        if facts is None:
            return PlaceLabel(
                text=country_code,
                resolved_locale="none",
                provenance="country_code",
                fallback_reason="country_code_only",
            )
        return _bundled_label(
            facts.names,
            language=language,
            provenance="bundled_country_label",
            code=country_code,
        )

    def _validate_executable_group(self, group: _CityGroup) -> None:
        if group.coverage != "complete":
            raise PlaceUnavailableError("city_group_coverage_incomplete", ref=group.ref)
        missing = tuple(code for code in group.airport_codes if code not in self._airports_by_code)
        if missing:
            raise PlaceUnavailableError("city_group_member_missing", ref=group.ref)
        unsearchable = tuple(
            code for code in group.airport_codes if not self._airports_by_code[code].is_searchable
        )
        if unsearchable:
            raise PlaceUnavailableError("city_group_member_unsearchable", ref=group.ref)
        invalid_country = tuple(
            code
            for code in group.airport_codes
            if self._airports_by_code[code].country_code not in group.allowed_member_countries
        )
        if invalid_country:
            raise PlaceUnavailableError("city_group_member_country_not_allowed", ref=group.ref)

    def _search_terms(self, ref: PlaceRef, option: PlaceOption) -> tuple[str, ...]:
        terms: list[str] = [ref.code, option.display_name.text]
        if option.city_name is not None:
            terms.append(option.city_name.text)
        if option.country_name is not None:
            terms.append(option.country_name.text)
        if ref.kind is PlaceKind.CITY:
            group = self._groups_by_code[ref.code]
            terms.extend(value for _, value in group.names)
            terms.extend(group.aliases)
        else:
            airport = self._airports_by_code[ref.code]
            terms.extend((airport.name, airport.municipality, *airport.keywords))
            overlay = self._overlays_by_ref.get(ref)
            if overlay is not None:
                terms.extend(value for _, value in overlay.names)
                terms.extend(value for _, value in overlay.city_names)
                terms.extend(overlay.aliases)
            for group in self._member_groups.get(ref.code, ()):
                terms.extend(value for _, value in group.names)
                terms.extend(group.aliases)
        return tuple(dict.fromkeys(_search_text(term) for term in terms if term))


def _load_payload(path: str | Path | None, resource_name: str) -> Mapping[str, object]:
    if path is None:
        text = files("flight_hunter.geo").joinpath(resource_name).read_text(encoding="utf-8")
    else:
        text = Path(path).read_text(encoding="utf-8")
    try:
        decoded = cast(
            object,
            json.loads(text, object_pairs_hook=_reject_duplicate_json_keys),
        )
    except json.JSONDecodeError as error:
        raise ValueError(f"invalid_place_facts_json:{resource_name}") from error
    return _mapping(decoded, resource_name)


def _reject_duplicate_json_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate_json_key:{key}")
        result[key] = value
    return result


def _parse_city_groups(payload: Mapping[str, object]) -> tuple[_CityGroup, ...]:
    _required_string(payload, "version", "city_groups")
    rows = _sequence(payload.get("groups"), "city_groups.groups")
    groups: list[_CityGroup] = []
    seen: set[PlaceRef] = set()
    for index, value in enumerate(rows):
        context = f"city_groups.groups[{index}]"
        row = _mapping(value, context)
        ref = PlaceRef(PlaceKind.CITY, _required_string(row, "code", context))
        if ref in seen:
            raise ValueError(f"duplicate_typed_place_key:city:{ref.code}")
        seen.add(ref)
        country_code = _country_code(
            _required_string(row, "country_code", context),
            f"{context}.country_code",
        )
        allowed_member_countries = tuple(
            _country_code(item, f"{context}.allowed_member_countries")
            for item in _string_sequence(
                row.get("allowed_member_countries"),
                f"{context}.allowed_member_countries",
            )
        )
        if not allowed_member_countries:
            raise ValueError(f"{context}.allowed_member_countries cannot be empty")
        if len(set(allowed_member_countries)) != len(allowed_member_countries):
            raise ValueError(f"{context}.allowed_member_countries cannot contain duplicates")
        airport_codes = tuple(
            _iata_code(item, f"{context}.airport_codes")
            for item in _string_sequence(row.get("airport_codes"), f"{context}.airport_codes")
        )
        if not airport_codes:
            raise ValueError(f"{context}.airport_codes cannot be empty")
        if len(set(airport_codes)) != len(airport_codes):
            raise ValueError(f"{context}.airport_codes cannot contain duplicates")
        groups.append(
            _CityGroup(
                ref=ref,
                country_code=country_code,
                allowed_member_countries=allowed_member_countries,
                names=_localized_names(row.get("names"), f"{context}.names"),
                aliases=_string_sequence(row.get("aliases", []), f"{context}.aliases"),
                airport_codes=airport_codes,
                coverage=_required_string(row, "coverage", context),
                membership_version=_required_string(row, "membership_version", context),
                observed_at=_required_string(row, "observed_at", context),
                provenance=_required_string(row, "provenance", context),
            )
        )
    return tuple(groups)


def _parse_label_overlays(payload: Mapping[str, object]) -> tuple[_LabelOverlay, ...]:
    _required_string(payload, "version", "place_labels")
    rows = _sequence(payload.get("labels"), "place_labels.labels")
    overlays: list[_LabelOverlay] = []
    seen: set[PlaceRef] = set()
    for index, value in enumerate(rows):
        context = f"place_labels.labels[{index}]"
        row = _mapping(value, context)
        kind_value = _required_string(row, "kind", context)
        try:
            kind = PlaceKind(kind_value)
        except ValueError as error:
            raise ValueError(f"{context}.kind must be city or airport") from error
        ref = PlaceRef(kind, _required_string(row, "code", context))
        if ref in seen:
            raise ValueError(f"duplicate_typed_place_key:{ref.kind.value}:{ref.code}")
        seen.add(ref)
        overlays.append(
            _LabelOverlay(
                ref=ref,
                names=_localized_names(row.get("names"), f"{context}.names"),
                city_names=_localized_names(
                    row.get("city_names", {}),
                    f"{context}.city_names",
                    allow_empty=True,
                ),
                aliases=_string_sequence(row.get("aliases", []), f"{context}.aliases"),
                provenance=_required_string(row, "provenance", context),
            )
        )
    return tuple(overlays)


def _parse_countries(
    payload: Mapping[str, object],
) -> tuple[tuple[str, _CountryFacts], ...]:
    _required_string(payload, "version", "countries")
    rows = _mapping(payload.get("countries"), "countries.countries")
    countries: list[tuple[str, _CountryFacts]] = []
    for raw_code, value in sorted(rows.items()):
        code = _country_code(raw_code, "countries.countries key")
        context = f"countries.countries.{code}"
        row = _mapping(value, context)
        names = tuple(
            (locale, _nonempty_string(label, f"{context}.{locale}"))
            for locale, label in sorted(row.items())
            if locale != "aliases"
        )
        if not names:
            raise ValueError(f"{context} must contain localized names")
        countries.append(
            (
                code,
                _CountryFacts(
                    names=names,
                    aliases=_string_sequence(row.get("aliases", []), f"{context}.aliases"),
                ),
            )
        )
    return tuple(countries)


def _airport_label(
    *,
    localized: tuple[tuple[str, str], ...],
    language: str,
    source_text: str,
    localized_provenance: str,
) -> PlaceLabel:
    localized_mapping = dict(localized)
    if language in localized_mapping:
        return PlaceLabel(
            text=localized_mapping[language],
            resolved_locale=language,
            provenance=localized_provenance,
        )
    return PlaceLabel(
        text=source_text,
        resolved_locale="source",
        provenance="airport_catalog",
        fallback_reason="source_locale",
    )


def _bundled_label(
    localized: tuple[tuple[str, str], ...],
    *,
    language: str,
    provenance: str,
    code: str,
) -> PlaceLabel:
    localized_mapping = dict(localized)
    if language in localized_mapping:
        return PlaceLabel(
            text=localized_mapping[language],
            resolved_locale=language,
            provenance=provenance,
        )
    if "en" in localized_mapping:
        return PlaceLabel(
            text=localized_mapping["en"],
            resolved_locale="en",
            provenance=provenance,
            fallback_reason="source_locale",
        )
    if localized:
        resolved_locale, text = localized[0]
        return PlaceLabel(
            text=text,
            resolved_locale=resolved_locale,
            provenance=provenance,
            fallback_reason="source_locale",
        )
    return PlaceLabel(
        text=code,
        resolved_locale="none",
        provenance=provenance,
        fallback_reason="code_only",
    )


def _match_rank(query: str, code: str, terms: tuple[str, ...]) -> int | None:
    normalized_code = _search_text(code)
    if query == normalized_code:
        return 0
    if query in terms:
        return 1
    if any(term.startswith(query) for term in terms):
        return 2
    if any(query in term for term in terms):
        return 3
    return None


def _search_text(value: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", value).casefold().split())


def _language(locale: str) -> str:
    if not isinstance(locale, str):
        raise TypeError("locale must be a string")
    normalized = locale.strip().replace("_", "-").casefold()
    if not normalized:
        raise ValueError("locale cannot be empty")
    return normalized.split("-", maxsplit=1)[0]


def _mapping(value: object, context: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping) or any(not isinstance(key, str) for key in value):
        raise ValueError(f"{context} must be an object")
    return cast(Mapping[str, object], value)


def _sequence(value: object, context: str) -> Sequence[object]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        raise ValueError(f"{context} must be an array")
    return cast(Sequence[object], value)


def _required_string(row: Mapping[str, object], field: str, context: str) -> str:
    if field not in row:
        raise ValueError(f"{context}.{field} is required")
    return _nonempty_string(row[field], f"{context}.{field}")


def _nonempty_string(value: object, context: str) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{context} must be a string")
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{context} cannot be empty")
    return normalized


def _string_sequence(value: object, context: str) -> tuple[str, ...]:
    return tuple(_nonempty_string(item, context) for item in _sequence(value, context))


def _localized_names(
    value: object,
    context: str,
    *,
    allow_empty: bool = False,
) -> tuple[tuple[str, str], ...]:
    mapping = _mapping(value, context)
    result = tuple(
        (
            _nonempty_string(locale, f"{context} locale").casefold(),
            _nonempty_string(label, f"{context}.{locale}"),
        )
        for locale, label in sorted(mapping.items())
    )
    if not result and not allow_empty:
        raise ValueError(f"{context} cannot be empty")
    if len({locale for locale, _ in result}) != len(result):
        raise ValueError(f"{context} cannot contain duplicate locales")
    return result


def _iata_code(value: object, context: str) -> str:
    normalized = _nonempty_string(value, context).upper()
    if not _IATA_RE.fullmatch(normalized):
        raise ValueError(f"{context} must be a three-letter IATA code")
    return normalized


def _country_code(value: object, context: str) -> str:
    normalized = _nonempty_string(value, context).upper()
    if not _COUNTRY_RE.fullmatch(normalized):
        raise ValueError(f"{context} must be an ISO 3166 alpha-2 code")
    return normalized
