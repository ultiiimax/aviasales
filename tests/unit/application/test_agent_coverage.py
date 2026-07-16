from __future__ import annotations

from dataclasses import replace
from datetime import UTC, date, datetime

import pytest

import flight_hunter.application.agent_operations as agent_operations
import flight_hunter.application.agent_scope as agent_scope
from flight_hunter.agent.presets import AgentPresetId
from flight_hunter.application.agent_intent import IntentParser
from flight_hunter.application.agent_planning import AgentPlanBuilder, PlanRevisionStatus
from flight_hunter.domain.agent_search import LocationScope, LocationScopeKind
from flight_hunter.geo.airports import (
    Airport,
    AirportCatalogSnapshot,
    AirportType,
    freeze_airport_catalog,
)

NOW = datetime(2026, 7, 16, 9, 0, tzinfo=UTC)


class StaticAirportCatalog:
    def __init__(self, airports: tuple[Airport, ...]) -> None:
        self._snapshot = freeze_airport_catalog(airports)

    async def catalog_snapshot(self) -> AirportCatalogSnapshot:
        return self._snapshot


def _airport(
    code: str,
    municipality: str,
    country: str,
    *,
    latitude: float,
    longitude: float,
    airport_type: AirportType = AirportType.LARGE_AIRPORT,
) -> Airport:
    return Airport(
        iata_code=code,
        name=f"{municipality} {code} Airport",
        municipality=municipality,
        country_code=country,
        latitude=latitude,
        longitude=longitude,
        airport_type=airport_type,
        active=True,
        scheduled_service=True,
        commercial_provenance="coverage.test_catalog",
    )


def _required_type(module: object, name: str) -> type[object]:
    value = getattr(module, name, None)
    assert isinstance(value, type), f"{name} coverage contract is not implemented"
    return value


def _required_callable(module: object, name: str) -> object:
    value = getattr(module, name, None)
    assert callable(value), f"{name} coverage contract is not implemented"
    return value


def test_quick_scope_key_uses_the_approved_stable_tuple() -> None:
    candidate_type = _required_type(agent_scope, "ScopeAirportCandidate")
    quick_scope_key = _required_callable(agent_scope, "quick_scope_key")
    airport = _airport(
        "CDG",
        "Paris",
        "FR",
        latitude=49.0097,
        longitude=2.5479,
    )
    candidate = candidate_type(
        airport=airport,
        discovery_evidence_count=3,
        commercial_relevance=7,
        nearby_distance_km=42,
        ground_transfer_cost_minor=None,
        ground_transfer_currency=None,
    )

    assert quick_scope_key(candidate) == (-3, -7, 42, "CDG")
    unknown_distance = replace(candidate, nearby_distance_km=None)
    assert quick_scope_key(unknown_distance) == (-3, -7, 0, "CDG")


@pytest.mark.anyio
async def test_led_to_fr_quick_freezes_deterministic_airports_and_exact_date() -> None:
    airports = (
        _airport("NCE", "Nice", "FR", latitude=43.6653, longitude=7.2150),
        _airport("LED", "Saint Petersburg", "RU", latitude=59.8003, longitude=30.2625),
        _airport("ORY", "Paris", "FR", latitude=48.7262, longitude=2.3652),
        _airport("LYS", "Lyon", "FR", latitude=45.7256, longitude=5.0811),
        _airport("CDG", "Paris", "FR", latitude=49.0097, longitude=2.5479),
    )
    resolver = agent_scope.ScopeResolver(repository=StaticAirportCatalog(airports))
    parsed = IntentParser().parse(
        "LED → France",
        preset=None,
        selections={"departure_date": "2026-09-10"},
    )

    revision = await AgentPlanBuilder(clock=lambda: NOW, scope_resolver=resolver).build(
        parsed,
        agent_scope.CoverageMode.QUICK,
    )

    assert revision.status is PlanRevisionStatus.AWAITING_APPROVAL
    assert revision.estimate is not None
    assert (revision.estimate.calendar_searches, revision.estimate.exact_searches) == (0, 4)
    (leg,) = revision.frozen_legs
    assert leg.origin_scope.airport_codes == ("LED",)
    assert leg.destination_scope is not None
    assert leg.destination_scope.airport_codes == ("CDG", "LYS", "NCE", "ORY")
    assert leg.date_constraint.start_date == date(2026, 9, 10)


@pytest.mark.anyio
async def test_overlapping_finite_scopes_exclude_same_airport_pairs_from_the_estimate() -> None:
    airports = (
        _airport("CDG", "Paris", "FR", latitude=49.0097, longitude=2.5479),
        _airport("ORY", "Paris", "FR", latitude=48.7262, longitude=2.3652),
        _airport("LYS", "Lyon", "FR", latitude=45.7256, longitude=5.0811),
        _airport("NCE", "Nice", "FR", latitude=43.6653, longitude=7.2150),
    )
    resolver = agent_scope.ScopeResolver(repository=StaticAirportCatalog(airports))
    parsed = IntentParser().parse(
        "city:CDG → France",
        preset=None,
        selections={"departure_date": "2026-09-10"},
    )

    revision = await AgentPlanBuilder(clock=lambda: NOW, scope_resolver=resolver).build(
        parsed,
        agent_scope.CoverageMode.FULL,
    )

    assert revision.status is PlanRevisionStatus.AWAITING_APPROVAL
    assert revision.estimate is not None
    assert revision.estimate.exact_searches == 6


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("preset", "text", "selections", "expected_radius"),
    (
        (
            AgentPresetId.NEARBY_AIRPORTS,
            "",
            {"origin": "LED", "destination": "CDG", "departure_date": "2026-09-10"},
            150,
        ),
        (
            None,
            "Проверь аэропорты рядом",
            {"origin": "LED", "destination": "CDG", "departure_date": "2026-09-10"},
            150,
        ),
        (
            None,
            "LED → CDG",
            {
                "origin": "LED",
                "destination": "CDG",
                "departure_date": "2026-09-10",
                "nearby_radius_km": 80,
            },
            80,
        ),
    ),
)
async def test_nearby_defaults_to_150_and_explicit_radius_is_frozen(
    preset: AgentPresetId | None,
    text: str,
    selections: dict[str, object],
    expected_radius: int,
) -> None:
    led = _airport("LED", "Saint Petersburg", "RU", latitude=59.8003, longitude=30.2625)
    cdg = _airport("CDG", "Paris", "FR", latitude=49.0097, longitude=2.5479)
    bva = _airport("BVA", "Beauvais", "FR", latitude=49.4544, longitude=2.1128)
    resolver = agent_scope.ScopeResolver(repository=StaticAirportCatalog((bva, cdg, led)))
    parsed = IntentParser().parse(text, preset=preset, selections=selections)

    revision = await AgentPlanBuilder(clock=lambda: NOW, scope_resolver=resolver).build(
        parsed,
        agent_scope.CoverageMode.FULL,
    )

    assert parsed.nearby_radius_km == expected_radius
    assert revision.status is PlanRevisionStatus.AWAITING_APPROVAL
    (leg,) = revision.frozen_legs
    assert leg.origin_scope.nearby_radius_km == expected_radius
    assert leg.destination_scope is not None
    assert leg.destination_scope.nearby_radius_km == expected_radius
    assert leg.destination_scope.airport_codes == ("BVA", "CDG")


@pytest.mark.anyio
async def test_nearby_scope_records_distance_and_keeps_unknown_ground_cost_uncertain() -> None:
    cdg = _airport("CDG", "Paris", "FR", latitude=49.0097, longitude=2.5479)
    ory = _airport("ORY", "Paris", "FR", latitude=48.7262, longitude=2.3652)
    bva = _airport("BVA", "Beauvais", "FR", latitude=49.4544, longitude=2.1128)
    resolver = agent_scope.ScopeResolver(repository=StaticAirportCatalog((bva, ory, cdg)))

    frozen = await resolver.resolve_finite(
        LocationScope(LocationScopeKind.CITY, "CDG"),
        coverage=agent_scope.CoverageMode.FULL,
        nearby_radius_km=150,
    )

    assert not isinstance(frozen, agent_scope.GeographyClarification)
    candidates = {item.airport.iata_code: item for item in frozen.airport_candidates}
    assert tuple(candidates) == ("BVA", "CDG", "ORY")
    assert 0 < candidates["BVA"].nearby_distance_km <= 150
    assert candidates["BVA"].ground_transfer_cost_minor is None
    assert candidates["BVA"].ground_transfer_currency is None
    assert candidates["BVA"].ground_cost_uncertain is True
    assert not hasattr(candidates["BVA"], "estimated_savings_minor")


def test_coverage_report_lists_every_pair_and_never_hides_a_failure() -> None:
    frozen_type = _required_type(agent_operations, "FrozenCoverageInput")
    pair_type = _required_type(agent_operations, "CoveragePair")
    outcome_type = _required_type(agent_operations, "CoveragePairOutcome")
    build_report = _required_callable(agent_operations, "build_coverage_report")
    first = pair_type("LED", "CDG", date(2026, 9, 10), None)
    second = pair_type("LED", "ORY", date(2026, 9, 10), None)
    third = pair_type("LED", "NCE", date(2026, 9, 10), None)
    frozen = frozen_type(
        coverage="full",
        origins=("LED",),
        destinations=("CDG", "NCE", "ORY"),
        date_start=date(2026, 9, 10),
        date_end=date(2026, 9, 10),
        catalog_checksums=("catalog-v1",),
        taxonomy_versions=("countries-v1",),
    )

    report = build_report(
        frozen_input=frozen,
        planned_pairs=(first, second, third),
        outcomes={
            first: outcome_type(status="succeeded"),
            second: outcome_type(status="failed", reason="provider_schema"),
        },
    )

    assert report.coverage == "full"
    assert report.completion == "partial"
    assert (report.planned, report.attempted, report.succeeded, report.failed, report.skipped) == (
        3,
        2,
        1,
        1,
        0,
    )
    assert tuple((item.pair, item.status, item.reason) for item in report.pairs) == (
        (first, "succeeded", None),
        (second, "failed", "provider_schema"),
        (third, "planned", "agent_pair_not_attempted"),
    )
    assert report.reason_counts == {
        "agent_pair_not_attempted": 1,
        "provider_schema": 1,
    }


def test_full_coverage_requires_every_frozen_pair_to_succeed() -> None:
    frozen_type = _required_type(agent_operations, "FrozenCoverageInput")
    pair_type = _required_type(agent_operations, "CoveragePair")
    outcome_type = _required_type(agent_operations, "CoveragePairOutcome")
    build_report = _required_callable(agent_operations, "build_coverage_report")
    pair = pair_type("LED", "CDG", date(2026, 9, 10), None)
    frozen = frozen_type(
        coverage="full",
        origins=("LED",),
        destinations=("CDG",),
        date_start=date(2026, 9, 10),
        date_end=date(2026, 9, 10),
        catalog_checksums=("catalog-v1",),
        taxonomy_versions=("countries-v1",),
    )

    complete = build_report(
        frozen_input=frozen,
        planned_pairs=(pair,),
        outcomes={pair: outcome_type(status="succeeded")},
    )
    skipped = build_report(
        frozen_input=frozen,
        planned_pairs=(pair,),
        outcomes={pair: outcome_type(status="skipped", reason="agent_http_budget_exhausted")},
    )

    assert complete.completion == "full"
    assert skipped.completion == "partial"
    assert skipped.skipped == 1


def test_full_coverage_cannot_omit_a_frozen_pair_from_the_planned_input() -> None:
    frozen_type = _required_type(agent_operations, "FrozenCoverageInput")
    pair_type = _required_type(agent_operations, "CoveragePair")
    outcome_type = _required_type(agent_operations, "CoveragePairOutcome")
    build_report = _required_callable(agent_operations, "build_coverage_report")
    cdg = pair_type("LED", "CDG", date(2026, 9, 10), date(2026, 9, 20))
    ory = pair_type("LED", "ORY", date(2026, 9, 10), date(2026, 9, 20))
    frozen = frozen_type(
        coverage="full",
        origins=("LED",),
        destinations=("CDG", "ORY"),
        date_start=date(2026, 9, 10),
        date_end=date(2026, 9, 10),
        return_date=date(2026, 9, 20),
        catalog_checksums=("catalog-v1",),
        taxonomy_versions=("countries-v1",),
    )

    report = build_report(
        frozen_input=frozen,
        planned_pairs=(cdg,),
        outcomes={cdg: outcome_type(status="succeeded")},
    )

    assert report.completion == "partial"
    assert report.planned == 2
    assert tuple((item.pair, item.status, item.reason) for item in report.pairs) == (
        (cdg, "succeeded", None),
        (ory, "planned", "agent_pair_not_planned"),
    )
    assert report.reason_counts == {"agent_pair_not_planned": 1}


def test_coverage_surface_excludes_same_airport_pairs() -> None:
    frozen_type = _required_type(agent_operations, "FrozenCoverageInput")
    pair_type = _required_type(agent_operations, "CoveragePair")
    outcome_type = _required_type(agent_operations, "CoveragePairOutcome")
    build_report = _required_callable(agent_operations, "build_coverage_report")
    cdg_to_ory = pair_type("CDG", "ORY", date(2026, 9, 10), None)
    ory_to_cdg = pair_type("ORY", "CDG", date(2026, 9, 10), None)
    frozen = frozen_type(
        coverage="full",
        origins=("CDG", "ORY"),
        destinations=("CDG", "ORY"),
        date_start=date(2026, 9, 10),
        date_end=date(2026, 9, 10),
        catalog_checksums=("catalog-v1",),
        taxonomy_versions=("countries-v1",),
    )

    report = build_report(
        frozen_input=frozen,
        planned_pairs=(cdg_to_ory, ory_to_cdg),
        outcomes={
            cdg_to_ory: outcome_type(status="succeeded"),
            ory_to_cdg: outcome_type(status="succeeded"),
        },
    )

    assert report.planned == 2
    assert tuple((item.pair.origin, item.pair.destination) for item in report.pairs) == (
        ("CDG", "ORY"),
        ("ORY", "CDG"),
    )
    assert report.completion == "full"


def test_anywhere_coverage_uses_only_source_signal_bound_pairs_across_a_range() -> None:
    frozen_type = _required_type(agent_operations, "FrozenCoverageInput")
    pair_type = _required_type(agent_operations, "CoveragePair")
    outcome_type = _required_type(agent_operations, "CoveragePairOutcome")
    build_report = _required_callable(agent_operations, "build_coverage_report")
    cdg = pair_type("LED", "CDG", date(2026, 9, 10), None)
    ory = pair_type("LED", "ORY", date(2026, 9, 12), None)
    frozen = frozen_type(
        coverage="quick",
        origins=("LED",),
        destinations=("CDG", "ORY"),
        date_start=date(2026, 9, 10),
        date_end=date(2026, 9, 12),
        catalog_checksums=("catalog-v1",),
        taxonomy_versions=("countries-v1",),
        explicit_pairs=(cdg, ory),
    )

    report = build_report(
        frozen_input=frozen,
        planned_pairs=(cdg, ory),
        outcomes={
            cdg: outcome_type(status="succeeded"),
            ory: outcome_type(status="succeeded"),
        },
    )

    assert report.planned == 2
    assert tuple(item.pair for item in report.pairs) == (cdg, ory)
    assert report.completion == "complete"


def test_coverage_report_rejects_unapproved_pairs_and_unstable_reasons() -> None:
    frozen_type = _required_type(agent_operations, "FrozenCoverageInput")
    pair_type = _required_type(agent_operations, "CoveragePair")
    outcome_type = _required_type(agent_operations, "CoveragePairOutcome")
    build_report = _required_callable(agent_operations, "build_coverage_report")
    approved = pair_type("LED", "CDG", date(2026, 9, 10), None)
    unapproved = pair_type("LED", "ORY", date(2026, 9, 10), None)
    frozen = frozen_type(
        coverage="quick",
        origins=("LED",),
        destinations=("CDG",),
        date_start=date(2026, 9, 10),
        date_end=date(2026, 9, 10),
        catalog_checksums=("catalog-v1",),
        taxonomy_versions=("countries-v1",),
    )

    with pytest.raises(ValueError, match="unapproved coverage pair"):
        build_report(
            frozen_input=frozen,
            planned_pairs=(approved,),
            outcomes={unapproved: outcome_type(status="succeeded")},
        )
    with pytest.raises(ValueError, match="reason"):
        outcome_type(status="failed", reason="raw provider body: secret")
