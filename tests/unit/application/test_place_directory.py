from __future__ import annotations

import json
from dataclasses import replace
from importlib.resources import files
from pathlib import Path

import pytest

from flight_hunter.application.place_directory import (
    PlaceDirectory,
    PlaceKindRequiredError,
    PlaceUnavailableError,
    PlaceUnknownError,
)
from flight_hunter.domain.places import PlaceKind, PlaceRef
from flight_hunter.geo.airports import freeze_airport_catalog
from flight_hunter.geo.demo_repository import DemoAirportRepository


def directory_from_demo() -> PlaceDirectory:
    return PlaceDirectory.from_snapshot(freeze_airport_catalog(DemoAirportRepository().all()))


def write_groups(
    tmp_path: Path,
    *,
    code: str,
    members: list[str],
    coverage: str = "complete",
    duplicate: bool = False,
) -> Path:
    group = {
        "code": code,
        "country_code": "RU",
        "allowed_member_countries": ["RU"],
        "names": {"ru": "Москва", "en": "Moscow"},
        "aliases": ["москва", "moscow"],
        "airport_codes": members,
        "coverage": coverage,
        "membership_version": "test-membership-v1",
        "observed_at": "2026-07-17",
        "provenance": "test_city_group",
    }
    path = tmp_path / "city-groups.json"
    path.write_text(
        json.dumps(
            {
                "version": "test-city-groups-v1",
                "groups": [group, dict(group)] if duplicate else [group],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return path


def test_place_ref_is_strict_and_normalizes_iata_code() -> None:
    assert PlaceRef(PlaceKind.CITY, " mow ") == PlaceRef(PlaceKind.CITY, "MOW")

    with pytest.raises(ValueError, match="place code must be a three-letter IATA code"):
        PlaceRef(PlaceKind.AIRPORT, "DM")
    with pytest.raises(TypeError, match="kind must be a PlaceKind"):
        PlaceRef("airport", "DME")  # type: ignore[arg-type]


def test_moscow_city_and_domodedovo_airport_are_distinct() -> None:
    directory = directory_from_demo()

    city = directory.lookup(PlaceRef(PlaceKind.CITY, "MOW"), locale="ru")
    airport = directory.lookup(PlaceRef(PlaceKind.AIRPORT, "DME"), locale="ru")

    assert city.display_name.text == "Москва"
    assert city.airport_codes == ("DME", "SVO", "VKO", "ZIA")
    assert city.membership_version == "mow-2026-07-17"
    assert city.membership_observed_at == "2026-07-17"
    assert airport.display_name.text == "Домодедово"
    assert airport.airport_codes == ("DME",)
    assert city.country_code == airport.country_code == "RU"
    assert city.country_name is not None
    assert city.country_name.text == "Россия"
    assert city.directory_version == airport.directory_version == directory.directory_version


def test_paris_group_and_all_required_airport_overlays_are_bundled() -> None:
    directory = directory_from_demo()

    paris = directory.lookup(PlaceRef(PlaceKind.CITY, "PAR"), locale="ru")
    assert paris.display_name.text == "Париж"
    assert paris.airport_codes == ("BVA", "CDG", "ORY")
    assert paris.country_code == "FR"

    required_overlays = (
        "DME",
        "SVO",
        "VKO",
        "ZIA",
        "BVA",
        "CDG",
        "ORY",
        "LED",
        "WAW",
        "WMI",
        "BCN",
        "PVG",
        "SHA",
    )
    for code in required_overlays:
        option = directory.lookup(PlaceRef(PlaceKind.AIRPORT, code), locale="ru")
        assert option.display_name.resolved_locale == "ru"
        assert option.display_name.provenance == "bundled_place_label"


def test_legacy_resolution_does_not_treat_dme_as_city() -> None:
    directory = directory_from_demo()

    assert directory.resolve_legacy("DME", locale="ru").ref.kind is PlaceKind.AIRPORT
    assert directory.resolve_legacy("MOW", locale="ru").ref.kind is PlaceKind.CITY


def test_incomplete_city_group_is_not_executable(tmp_path: Path) -> None:
    groups = write_groups(tmp_path, code="MOW", members=["DME", "XXX"])
    directory = PlaceDirectory.from_snapshot(
        freeze_airport_catalog(DemoAirportRepository().all()),
        city_groups_path=groups,
    )

    with pytest.raises(PlaceUnavailableError, match="city_group_member_missing") as error:
        directory.lookup(PlaceRef(PlaceKind.CITY, "MOW"), locale="ru")
    assert error.value.code == "place_unavailable"


def test_city_group_declared_incomplete_is_not_executable(tmp_path: Path) -> None:
    groups = write_groups(
        tmp_path,
        code="MOW",
        members=["DME", "SVO", "VKO", "ZIA"],
        coverage="partial",
    )
    directory = PlaceDirectory.from_snapshot(
        freeze_airport_catalog(DemoAirportRepository().all()),
        city_groups_path=groups,
    )

    with pytest.raises(PlaceUnavailableError, match="city_group_coverage_incomplete"):
        directory.lookup(PlaceRef(PlaceKind.CITY, "MOW"), locale="en")


def test_non_searchable_airport_and_its_city_group_are_unavailable() -> None:
    airports = tuple(
        replace(airport, scheduled_service=False) if airport.iata_code == "DME" else airport
        for airport in DemoAirportRepository().all()
    )
    directory = PlaceDirectory.from_snapshot(freeze_airport_catalog(airports))

    with pytest.raises(PlaceUnavailableError, match="airport_not_searchable"):
        directory.lookup(PlaceRef(PlaceKind.AIRPORT, "DME"), locale="ru")
    with pytest.raises(PlaceUnavailableError, match="city_group_member_unsearchable"):
        directory.lookup(PlaceRef(PlaceKind.CITY, "MOW"), locale="ru")


def test_duplicate_typed_city_key_is_rejected_but_same_code_across_kinds_is_valid(
    tmp_path: Path,
) -> None:
    snapshot = freeze_airport_catalog(DemoAirportRepository().all())
    duplicate_groups = write_groups(
        tmp_path,
        code="MOW",
        members=["DME", "SVO", "VKO", "ZIA"],
        duplicate=True,
    )
    with pytest.raises(ValueError, match="duplicate_typed_place_key:city:MOW"):
        PlaceDirectory.from_snapshot(snapshot, city_groups_path=duplicate_groups)

    same_code_group = write_groups(tmp_path, code="DME", members=["DME"])
    directory = PlaceDirectory.from_snapshot(snapshot, city_groups_path=same_code_group)
    assert directory.lookup(PlaceRef(PlaceKind.CITY, "DME"), locale="ru").ref.kind is PlaceKind.CITY
    assert (
        directory.lookup(PlaceRef(PlaceKind.AIRPORT, "DME"), locale="ru").ref.kind
        is PlaceKind.AIRPORT
    )
    with pytest.raises(PlaceKindRequiredError) as error:
        directory.resolve_legacy("DME", locale="ru")
    assert error.value.code == "place_kind_required"


def test_suggest_is_unicode_casefolded_deterministic_and_omits_unavailable() -> None:
    directory = directory_from_demo()

    first = directory.suggest("МОСКВА", locale="ru")  # noqa: RUF001
    second = directory.suggest("москва", locale="ru")

    assert first == second
    assert first[0].ref == PlaceRef(PlaceKind.CITY, "MOW")
    assert {item.ref.code for item in first} >= {"MOW", "DME", "SVO", "VKO", "ZIA"}
    assert directory.suggest("", locale="ru") == ()


def test_exact_city_refs_use_names_aliases_and_codes_without_prefix_matches(
    tmp_path: Path,
) -> None:
    snapshot = freeze_airport_catalog(DemoAirportRepository().all())
    groups_payload = json.loads(
        files("flight_hunter.geo").joinpath("city_groups.v1.json").read_text(encoding="utf-8")
    )
    groups_payload["groups"][0]["aliases"].extend(["capital", "shared hub"])
    groups_payload["groups"][1]["aliases"].extend(["capital region", "shared hub"])
    groups = tmp_path / "exact-city-groups.json"
    groups.write_text(
        json.dumps(groups_payload, ensure_ascii=False),
        encoding="utf-8",
    )
    directory = PlaceDirectory.from_snapshot(snapshot, city_groups_path=groups)

    assert directory.exact_city_refs("Москва") == (PlaceRef(PlaceKind.CITY, "MOW"),)
    assert directory.exact_city_refs("MOW") == (PlaceRef(PlaceKind.CITY, "MOW"),)
    assert directory.exact_city_refs("CAPITAL") == (PlaceRef(PlaceKind.CITY, "MOW"),)
    assert directory.exact_city_refs("cap") == ()
    assert directory.exact_city_refs("shared hub") == (
        PlaceRef(PlaceKind.CITY, "MOW"),
        PlaceRef(PlaceKind.CITY, "PAR"),
    )


def test_labels_report_field_level_locale_provenance_and_fallback() -> None:
    directory = directory_from_demo()

    russian = directory.lookup(PlaceRef(PlaceKind.AIRPORT, "LED"), locale="ru")
    german = directory.lookup(PlaceRef(PlaceKind.AIRPORT, "LED"), locale="de")

    assert russian.display_name.text == "Пулково"
    assert russian.display_name.resolved_locale == "ru"
    assert russian.display_name.provenance == "bundled_place_label"
    assert russian.display_name.fallback_reason is None
    assert german.display_name.text == "Pulkovo Airport"
    assert german.display_name.resolved_locale == "source"
    assert german.display_name.provenance == "airport_catalog"
    assert german.display_name.fallback_reason == "source_locale"
    assert german.country_name is not None
    assert german.country_name.resolved_locale == "en"
    assert german.country_name.fallback_reason == "source_locale"


def test_directory_checksum_covers_catalog_groups_labels_and_countries(
    tmp_path: Path,
) -> None:
    snapshot = freeze_airport_catalog(DemoAirportRepository().all())
    baseline = PlaceDirectory.from_snapshot(snapshot)
    groups_payload = json.loads(
        files("flight_hunter.geo").joinpath("city_groups.v1.json").read_text(encoding="utf-8")
    )
    groups_payload["groups"][0]["aliases"].append("московский авиаузел")
    groups = tmp_path / "groups.json"
    groups.write_text(
        json.dumps(groups_payload, ensure_ascii=False),
        encoding="utf-8",
    )

    changed = PlaceDirectory.from_snapshot(snapshot, city_groups_path=groups)

    assert changed.directory_version != baseline.directory_version
    assert len(changed.directory_version) == 64


def test_unknown_place_has_stable_typed_error() -> None:
    directory = directory_from_demo()

    with pytest.raises(PlaceUnknownError) as error:
        directory.lookup(PlaceRef(PlaceKind.AIRPORT, "XXX"), locale="ru")

    assert error.value.code == "place_unknown"
