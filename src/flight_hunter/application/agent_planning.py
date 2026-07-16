from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from enum import StrEnum

from flight_hunter.application.agent_capabilities import ProviderCapabilityRegistry
from flight_hunter.application.agent_intent import (
    ClarificationAction,
    IntentClarification,
    ParsedIntent,
    return_before_outbound_window_end_clarification,
)
from flight_hunter.application.agent_scope import (
    AnywhereDiscoveryRule,
    CoverageMode,
    FrozenAirportScope,
    GeographyClarification,
    ScopeResolver,
    finite_route_pairs,
)
from flight_hunter.config import AppSettings
from flight_hunter.domain.agent_search import (
    MAX_ANYWHERE_DISCOVERY_MONTHS,
    CapabilityState,
    DateConstraint,
    DateMode,
    LocationScopeKind,
    PlanBudget,
    ProviderCapabilitySnapshot,
    ProviderHttpCostModel,
    RouteStrategy,
    TravelIntent,
    TripShape,
    inclusive_month_count,
)


class PlanBudgetExceededReason(StrEnum):
    ABSOLUTE_LOGICAL_LIMIT = "absolute_logical_limit"
    QUICK_LOGICAL_LIMIT = "quick_logical_limit"
    QUICK_CALENDAR_LIMIT = "quick_calendar_limit"
    QUICK_EXACT_LIMIT = "quick_exact_limit"


_QUICK_BUDGET_REASONS = frozenset(
    {
        PlanBudgetExceededReason.QUICK_LOGICAL_LIMIT,
        PlanBudgetExceededReason.QUICK_CALENDAR_LIMIT,
        PlanBudgetExceededReason.QUICK_EXACT_LIMIT,
    }
)


class PlanBudgetExceededError(ValueError):
    code = "budget_too_large"

    def __init__(
        self,
        reason: PlanBudgetExceededReason,
        *,
        actual: int,
        limit: int,
    ) -> None:
        self.reason = PlanBudgetExceededReason(reason)
        self.actual = actual
        self.limit = limit
        super().__init__(f"{self.reason.value} exceeded: {actual} > {limit}")


class PlanRevisionStatus(StrEnum):
    DRAFT = "draft"
    AWAITING_APPROVAL = "awaiting_approval"


@dataclass(frozen=True, slots=True)
class SearchSurface:
    coverage: CoverageMode
    calendar_searches: int
    exact_searches: int

    def __post_init__(self) -> None:
        object.__setattr__(self, "coverage", CoverageMode(self.coverage))
        for field_name in ("calendar_searches", "exact_searches"):
            value = getattr(self, field_name)
            if type(value) is not int or value < 0:
                raise ValueError(f"{field_name} must be a non-negative integer")
        if self.calendar_searches + self.exact_searches == 0:
            raise ValueError("search surface must contain at least one operation")


@dataclass(frozen=True, slots=True)
class PlanEstimate:
    coverage: CoverageMode
    calendar_searches: int
    exact_searches: int
    logical_operations: int
    http_attempts: int
    deadline_seconds: int
    requested_logical_limit: int
    requires_budget_revision: bool
    cost_model_version: str

    @property
    def budget(self) -> PlanBudget:
        return PlanBudget(
            logical_operations=self.logical_operations,
            http_attempts=self.http_attempts,
            deadline_seconds=self.deadline_seconds,
        )


@dataclass(frozen=True, slots=True)
class FrozenPlanLeg:
    origin_scope: FrozenAirportScope | None
    destination_scope: FrozenAirportScope | None
    anywhere_rule: AnywhereDiscoveryRule | None
    date_constraint: DateConstraint
    reciprocal_anywhere_return: bool = False

    def __post_init__(self) -> None:
        if type(self.reciprocal_anywhere_return) is not bool:
            raise TypeError("reciprocal_anywhere_return must be a boolean")
        if self.reciprocal_anywhere_return:
            if (
                self.origin_scope is not None
                or not isinstance(self.destination_scope, FrozenAirportScope)
                or self.anywhere_rule is not None
            ):
                raise ValueError("reciprocal anywhere return leg must contain only destination")
        elif not isinstance(self.origin_scope, FrozenAirportScope):
            raise TypeError("origin_scope must be FrozenAirportScope")
        elif (self.destination_scope is None) == (self.anywhere_rule is None):
            raise ValueError("exactly one destination scope representation is required")
        if self.destination_scope is not None and not isinstance(
            self.destination_scope,
            FrozenAirportScope,
        ):
            raise TypeError("destination_scope must be FrozenAirportScope")
        if self.anywhere_rule is not None and not isinstance(
            self.anywhere_rule,
            AnywhereDiscoveryRule,
        ):
            raise TypeError("anywhere_rule must be AnywhereDiscoveryRule")
        if not isinstance(self.date_constraint, DateConstraint):
            raise TypeError("date_constraint must be DateConstraint")


@dataclass(frozen=True, slots=True)
class FrozenCompositionRule:
    version: str
    max_hubs_per_leg: int
    source: str = "confirmed_connection_airports"

    def __post_init__(self) -> None:
        if self.version != "confirmed-hubs-v1":
            raise ValueError("unsupported composition rule version")
        if type(self.max_hubs_per_leg) is not int or self.max_hubs_per_leg <= 0:
            raise ValueError("max_hubs_per_leg must be a positive integer")
        if self.source != "confirmed_connection_airports":
            raise ValueError("unsupported composition hub source")


@dataclass(frozen=True, slots=True)
class ProposedPlanRevision:
    status: PlanRevisionStatus
    parsed_intent: ParsedIntent
    travel_intent: TravelIntent | None
    coverage: CoverageMode
    capability_snapshot: ProviderCapabilitySnapshot | None
    estimate: PlanEstimate | None
    frozen_legs: tuple[FrozenPlanLeg, ...]
    clarifications: tuple[IntentClarification, ...]
    created_at: datetime
    expires_at: datetime
    composition_rule: FrozenCompositionRule | None = None
    builder_version: str = "agent-plan-builder-v4"


class PlanEstimator:
    def __init__(
        self,
        *,
        settings: AppSettings | None = None,
        cost_model: ProviderHttpCostModel | None = None,
    ) -> None:
        self._settings = settings or AppSettings.from_env()
        self.cost_model = cost_model or ProviderCapabilityRegistry().snapshot().cost_model

    def estimate_http_attempts(
        self,
        *,
        exact_searches: int,
        calendar_searches: int,
        cost_model: ProviderHttpCostModel | None = None,
    ) -> int:
        for field_name, value in (
            ("exact_searches", exact_searches),
            ("calendar_searches", calendar_searches),
        ):
            if type(value) is not int or value < 0:
                raise ValueError(f"{field_name} must be a non-negative integer")
        model = cost_model or self.cost_model
        return (
            exact_searches * model.worst_case_exact_http_attempts
            + calendar_searches * model.start_attempts
        )

    def estimate(
        self,
        surface: SearchSurface,
        cost_model: ProviderHttpCostModel,
    ) -> PlanEstimate:
        if not isinstance(surface, SearchSurface):
            raise TypeError("surface must be SearchSurface")
        if not isinstance(cost_model, ProviderHttpCostModel):
            raise TypeError("cost_model must be ProviderHttpCostModel")
        logical_operations = surface.calendar_searches + surface.exact_searches
        if logical_operations > self._settings.agent_absolute_logical_limit:
            raise PlanBudgetExceededError(
                PlanBudgetExceededReason.ABSOLUTE_LOGICAL_LIMIT,
                actual=logical_operations,
                limit=self._settings.agent_absolute_logical_limit,
            )

        if surface.coverage is CoverageMode.QUICK:
            if logical_operations > self._settings.agent_quick_logical_limit:
                raise PlanBudgetExceededError(
                    PlanBudgetExceededReason.QUICK_LOGICAL_LIMIT,
                    actual=logical_operations,
                    limit=self._settings.agent_quick_logical_limit,
                )
            if surface.calendar_searches > self._settings.agent_quick_calendar_limit:
                raise PlanBudgetExceededError(
                    PlanBudgetExceededReason.QUICK_CALENDAR_LIMIT,
                    actual=surface.calendar_searches,
                    limit=self._settings.agent_quick_calendar_limit,
                )
            if surface.exact_searches > self._settings.agent_quick_exact_limit:
                raise PlanBudgetExceededError(
                    PlanBudgetExceededReason.QUICK_EXACT_LIMIT,
                    actual=surface.exact_searches,
                    limit=self._settings.agent_quick_exact_limit,
                )
            requested_limit = self._settings.agent_quick_logical_limit
            deadline_seconds = self._settings.agent_quick_deadline_seconds
            requires_revision = False
        else:
            requires_revision = logical_operations > self._settings.agent_full_logical_limit
            requested_limit = (
                logical_operations if requires_revision else self._settings.agent_full_logical_limit
            )
            deadline_seconds = self._settings.agent_full_deadline_seconds

        return PlanEstimate(
            coverage=surface.coverage,
            calendar_searches=surface.calendar_searches,
            exact_searches=surface.exact_searches,
            logical_operations=logical_operations,
            http_attempts=self.estimate_http_attempts(
                exact_searches=surface.exact_searches,
                calendar_searches=surface.calendar_searches,
                cost_model=cost_model,
            ),
            deadline_seconds=deadline_seconds,
            requested_logical_limit=requested_limit,
            requires_budget_revision=requires_revision,
            cost_model_version=cost_model.version,
        )


class AgentPlanBuilder:
    def __init__(
        self,
        *,
        clock: Callable[[], datetime] | None = None,
        settings: AppSettings | None = None,
        capabilities: ProviderCapabilityRegistry | None = None,
        estimator: PlanEstimator | None = None,
        scope_resolver: ScopeResolver | None = None,
    ) -> None:
        self._clock = clock or (lambda: datetime.now(UTC))
        self._settings = settings or AppSettings.from_env()
        self._capabilities = capabilities or ProviderCapabilityRegistry(
            requests_per_minute=self._settings.aviasales_search_internal_rpm
        )
        self._estimator = estimator or PlanEstimator(settings=self._settings)
        self._scope_resolver = scope_resolver

    async def build(
        self,
        parsed: ParsedIntent,
        coverage: CoverageMode | str,
    ) -> ProposedPlanRevision:
        if not isinstance(parsed, ParsedIntent):
            raise TypeError("parsed must be ParsedIntent")
        normalized_coverage = CoverageMode(coverage)
        created_at = self._clock()
        if created_at.tzinfo is None or created_at.utcoffset() is None:
            raise ValueError("plan-builder clock must return a timezone-aware datetime")
        expires_at = created_at + timedelta(seconds=self._settings.agent_plan_ttl_seconds)
        snapshot = self._capabilities.snapshot()

        if parsed.clarifications:
            return _draft_revision(
                parsed=parsed,
                coverage=normalized_coverage,
                snapshot=snapshot,
                clarifications=parsed.clarifications,
                created_at=created_at,
                expires_at=expires_at,
            )

        travel_intent = parsed.to_travel_intent(today=created_at.date())
        if travel_intent is None:
            return _draft_revision(
                parsed=parsed,
                coverage=normalized_coverage,
                snapshot=snapshot,
                clarifications=(_incomplete_intent_clarification(),),
                created_at=created_at,
                expires_at=expires_at,
            )

        chronology_clarification = _round_trip_chronology_clarification(travel_intent)
        if chronology_clarification is not None:
            return _draft_revision(
                parsed=parsed,
                travel_intent=travel_intent,
                coverage=normalized_coverage,
                snapshot=snapshot,
                clarifications=(chronology_clarification,),
                created_at=created_at,
                expires_at=expires_at,
            )

        if self._scope_resolver is None:
            return _draft_revision(
                parsed=parsed,
                travel_intent=travel_intent,
                coverage=normalized_coverage,
                snapshot=snapshot,
                clarifications=(_geography_catalog_clarification(),),
                created_at=created_at,
                expires_at=expires_at,
            )

        frozen_legs, geography_clarifications = await self._freeze_legs(
            travel_intent,
            normalized_coverage,
            nearby_radius_km=_nearby_radius_km(parsed),
        )
        if geography_clarifications:
            return _draft_revision(
                parsed=parsed,
                travel_intent=travel_intent,
                coverage=normalized_coverage,
                snapshot=snapshot,
                clarifications=geography_clarifications,
                created_at=created_at,
                expires_at=expires_at,
            )

        composition_rule = _composition_rule(travel_intent, normalized_coverage)
        if composition_rule is not None and any(
            leg.anywhere_rule is not None for leg in frozen_legs
        ):
            return _draft_revision(
                parsed=parsed,
                travel_intent=travel_intent,
                coverage=normalized_coverage,
                snapshot=snapshot,
                frozen_legs=frozen_legs,
                composition_rule=composition_rule,
                clarifications=(_split_anywhere_unsupported_clarification(),),
                created_at=created_at,
                expires_at=expires_at,
            )
        surface = _surface_for_frozen_legs(
            frozen_legs,
            normalized_coverage,
            trip_shape=travel_intent.trip_shape,
            capability_snapshot=snapshot,
        )
        if composition_rule is not None:
            surface = _surface_with_composition_budget(
                surface,
                frozen_legs,
                composition_rule,
            )
        try:
            estimate = self._estimator.estimate(surface, snapshot.cost_model)
        except PlanBudgetExceededError as error:
            if (
                normalized_coverage is not CoverageMode.QUICK
                or error.reason not in _QUICK_BUDGET_REASONS
            ):
                raise
            return _draft_revision(
                parsed=parsed,
                travel_intent=travel_intent,
                coverage=normalized_coverage,
                snapshot=snapshot,
                frozen_legs=frozen_legs,
                composition_rule=composition_rule,
                clarifications=(
                    _quick_budget_clarification(
                        surface,
                        logical_limit=self._settings.agent_quick_logical_limit,
                    ),
                ),
                created_at=created_at,
                expires_at=expires_at,
            )
        if estimate.requires_budget_revision:
            return _draft_revision(
                parsed=parsed,
                travel_intent=travel_intent,
                coverage=normalized_coverage,
                snapshot=snapshot,
                estimate=estimate,
                frozen_legs=frozen_legs,
                composition_rule=composition_rule,
                clarifications=(
                    _budget_revision_clarification(
                        estimate,
                        logical_limit=self._settings.agent_full_logical_limit,
                    ),
                ),
                created_at=created_at,
                expires_at=expires_at,
            )
        return ProposedPlanRevision(
            status=PlanRevisionStatus.AWAITING_APPROVAL,
            parsed_intent=parsed,
            travel_intent=travel_intent,
            coverage=normalized_coverage,
            capability_snapshot=snapshot,
            estimate=estimate,
            frozen_legs=frozen_legs,
            clarifications=(),
            created_at=created_at,
            expires_at=expires_at,
            composition_rule=composition_rule,
        )

    async def _freeze_legs(
        self,
        intent: TravelIntent,
        coverage: CoverageMode,
        *,
        nearby_radius_km: int,
    ) -> tuple[tuple[FrozenPlanLeg, ...], tuple[IntentClarification, ...]]:
        assert self._scope_resolver is not None
        frozen_legs: list[FrozenPlanLeg] = []
        clarifications: list[IntentClarification] = []
        quick_limit = (
            self._settings.agent_quick_exact_limit if coverage is CoverageMode.QUICK else None
        )
        for index, leg in enumerate(intent.legs):
            if (
                intent.trip_shape is TripShape.ROUND_TRIP
                and index == 1
                and len(frozen_legs) == 1
                and leg.origin.kind is LocationScopeKind.ANYWHERE
                and intent.legs[0].destination.kind is LocationScopeKind.ANYWHERE
                and leg.destination == intent.legs[0].origin
                and frozen_legs[0].anywhere_rule is not None
            ):
                return_destination = frozen_legs[0].origin_scope
                assert return_destination is not None
                frozen_legs.append(
                    FrozenPlanLeg(
                        origin_scope=None,
                        destination_scope=return_destination,
                        anywhere_rule=None,
                        date_constraint=leg.date_constraint,
                        reciprocal_anywhere_return=True,
                    )
                )
                continue
            if leg.origin.kind is LocationScopeKind.ANYWHERE:
                clarifications.append(_anywhere_origin_clarification(index))
                continue
            frozen_origin = await self._scope_resolver.resolve_finite(
                leg.origin,
                coverage=coverage,
                quick_limit=quick_limit,
                nearby_radius_km=nearby_radius_km,
            )
            if isinstance(frozen_origin, GeographyClarification):
                clarifications.append(_scope_clarification(index, "origin", frozen_origin))
                continue

            if leg.destination.kind is LocationScopeKind.ANYWHERE:
                date_start, date_end = _date_bounds(leg.date_constraint)
                month_count = inclusive_month_count(date_start, date_end)
                if month_count > MAX_ANYWHERE_DISCOVERY_MONTHS:
                    clarifications.append(
                        _anywhere_date_range_too_large_clarification(
                            index,
                            actual_months=month_count,
                        )
                    )
                    continue
                if coverage is CoverageMode.QUICK:
                    max_destination_seeds = self._settings.agent_quick_calendar_limit
                    exact_verification_limit = min(
                        self._settings.agent_quick_exact_limit,
                        max_destination_seeds,
                    )
                else:
                    max_destination_seeds = max(
                        1,
                        self._settings.agent_full_logical_limit * 2 // 3,
                    )
                    exact_verification_limit = max(
                        1,
                        self._settings.agent_full_logical_limit - max_destination_seeds,
                    )
                anywhere_rule = self._scope_resolver.build_anywhere_rule(
                    frozen_origins=frozen_origin,
                    date_start=date_start,
                    date_end=date_end,
                    max_destination_seeds=max_destination_seeds,
                    exact_verification_limit=exact_verification_limit,
                )
                frozen_legs.append(
                    FrozenPlanLeg(
                        origin_scope=frozen_origin,
                        destination_scope=None,
                        anywhere_rule=anywhere_rule,
                        date_constraint=leg.date_constraint,
                    )
                )
                continue

            frozen_destination = await self._scope_resolver.resolve_finite(
                leg.destination,
                coverage=coverage,
                quick_limit=quick_limit,
                nearby_radius_km=nearby_radius_km,
            )
            if isinstance(frozen_destination, GeographyClarification):
                clarifications.append(
                    _scope_clarification(index, "destination", frozen_destination)
                )
                continue
            if frozen_origin.catalog_checksum != frozen_destination.catalog_checksum:
                clarifications.append(_catalog_changed_clarification(index))
                continue
            if not any(
                origin != destination
                for origin in frozen_origin.airport_codes
                for destination in frozen_destination.airport_codes
            ):
                clarifications.append(_same_origin_destination_clarification(index))
                continue
            frozen_legs.append(
                FrozenPlanLeg(
                    origin_scope=frozen_origin,
                    destination_scope=frozen_destination,
                    anywhere_rule=None,
                    date_constraint=leg.date_constraint,
                )
            )
        if clarifications:
            return (), tuple(clarifications)
        return tuple(frozen_legs), ()


def _surface_for_frozen_legs(
    frozen_legs: tuple[FrozenPlanLeg, ...],
    coverage: CoverageMode,
    *,
    trip_shape: TripShape,
    capability_snapshot: ProviderCapabilitySnapshot,
) -> SearchSurface:
    native_round_trip = _native_round_trip_outbound(frozen_legs, trip_shape, capability_snapshot)
    if native_round_trip is not None:
        assert native_round_trip.origin_scope is not None
        assert native_round_trip.destination_scope is not None
        route_pairs = len(
            finite_route_pairs(
                native_round_trip.origin_scope.airport_codes,
                native_round_trip.destination_scope.airport_codes,
            )
        )
        if native_round_trip.date_constraint.mode is DateMode.EXACT:
            return SearchSurface(
                coverage=coverage,
                calendar_searches=0,
                exact_searches=route_pairs,
            )
        operations = route_pairs * _date_count(native_round_trip.date_constraint)
        return SearchSurface(
            coverage=coverage,
            calendar_searches=operations,
            exact_searches=operations,
        )

    calendar_searches = 0
    exact_searches = 0
    for frozen_leg in frozen_legs:
        if frozen_leg.reciprocal_anywhere_return:
            continue
        assert frozen_leg.origin_scope is not None
        origin_count = len(frozen_leg.origin_scope.airport_codes)
        date_count = _date_count(frozen_leg.date_constraint)
        if frozen_leg.anywhere_rule is not None:
            discovery_query_work = origin_count * len(frozen_leg.anywhere_rule.discovery_source_ids)
            calendar_searches += max(
                frozen_leg.anywhere_rule.max_destination_seeds,
                discovery_query_work,
            )
            exact_searches += frozen_leg.anywhere_rule.exact_verification_limit
            continue
        assert frozen_leg.destination_scope is not None
        route_pairs = len(
            finite_route_pairs(
                frozen_leg.origin_scope.airport_codes,
                frozen_leg.destination_scope.airport_codes,
            )
        )
        if frozen_leg.date_constraint.mode is DateMode.EXACT:
            exact_searches += route_pairs
        else:
            operations = route_pairs * date_count
            calendar_searches += operations
            exact_searches += operations
    return SearchSurface(
        coverage=coverage,
        calendar_searches=calendar_searches,
        exact_searches=exact_searches,
    )


def _composition_rule(
    intent: TravelIntent,
    coverage: CoverageMode,
) -> FrozenCompositionRule | None:
    if not {
        RouteStrategy.SPLIT_TICKET,
        RouteStrategy.SELF_TRANSFER,
    }.intersection(intent.requested_strategies):
        return None
    return FrozenCompositionRule(
        version="confirmed-hubs-v1",
        max_hubs_per_leg=2 if coverage is CoverageMode.QUICK else 4,
    )


def _surface_with_composition_budget(
    surface: SearchSurface,
    frozen_legs: tuple[FrozenPlanLeg, ...],
    rule: FrozenCompositionRule,
) -> SearchSurface:
    split_exact_searches = 0
    for frozen_leg in frozen_legs:
        if frozen_leg.reciprocal_anywhere_return:
            continue
        if frozen_leg.anywhere_rule is not None:
            raise ValueError("split anywhere must be rejected before estimation")
        assert frozen_leg.origin_scope is not None
        assert frozen_leg.destination_scope is not None
        route_pair_count = len(
            finite_route_pairs(
                frozen_leg.origin_scope.airport_codes,
                frozen_leg.destination_scope.airport_codes,
            )
        )
        split_exact_searches += (
            route_pair_count * _date_count(frozen_leg.date_constraint) * rule.max_hubs_per_leg * 2
        )
    return SearchSurface(
        coverage=surface.coverage,
        calendar_searches=surface.calendar_searches,
        exact_searches=surface.exact_searches + split_exact_searches,
    )


def _native_round_trip_outbound(
    frozen_legs: tuple[FrozenPlanLeg, ...],
    trip_shape: TripShape,
    capability_snapshot: ProviderCapabilitySnapshot,
) -> FrozenPlanLeg | None:
    if (
        trip_shape is not TripShape.ROUND_TRIP
        or capability_snapshot.round_trip is not CapabilityState.SUPPORTED
        or len(frozen_legs) != 2
    ):
        return None
    outbound, inbound = frozen_legs
    if (
        outbound.origin_scope is None
        or outbound.destination_scope is None
        or inbound.origin_scope is None
        or inbound.destination_scope is None
        or outbound.reciprocal_anywhere_return
        or inbound.reciprocal_anywhere_return
        or inbound.date_constraint.mode is not DateMode.EXACT
        or set(outbound.origin_scope.airport_codes) != set(inbound.destination_scope.airport_codes)
        or set(outbound.destination_scope.airport_codes) != set(inbound.origin_scope.airport_codes)
    ):
        return None
    return outbound


def _date_count(constraint: DateConstraint) -> int:
    start_date, end_date = _date_bounds(constraint)
    return (end_date - start_date).days + 1


def _date_bounds(constraint: DateConstraint) -> tuple[date, date]:
    if constraint.mode is DateMode.EXACT:
        return constraint.start_date, constraint.start_date
    if constraint.mode is DateMode.FLEXIBLE:
        delta = timedelta(days=constraint.flex_days)
        return constraint.start_date - delta, constraint.start_date + delta
    assert constraint.end_date is not None
    return constraint.start_date, constraint.end_date


def _round_trip_chronology_clarification(
    intent: TravelIntent,
) -> IntentClarification | None:
    if intent.trip_shape is not TripShape.ROUND_TRIP or len(intent.legs) != 2:
        return None
    outbound_end = _date_bounds(intent.legs[0].date_constraint)[1]
    return_constraint = intent.legs[1].date_constraint
    if return_constraint.mode is DateMode.EXACT and return_constraint.start_date < outbound_end:
        return return_before_outbound_window_end_clarification()
    return None


def _draft_revision(
    *,
    parsed: ParsedIntent,
    coverage: CoverageMode,
    snapshot: ProviderCapabilitySnapshot,
    clarifications: tuple[IntentClarification, ...],
    created_at: datetime,
    expires_at: datetime,
    travel_intent: TravelIntent | None = None,
    estimate: PlanEstimate | None = None,
    frozen_legs: tuple[FrozenPlanLeg, ...] = (),
    composition_rule: FrozenCompositionRule | None = None,
) -> ProposedPlanRevision:
    return ProposedPlanRevision(
        status=PlanRevisionStatus.DRAFT,
        parsed_intent=parsed,
        travel_intent=travel_intent,
        coverage=coverage,
        capability_snapshot=snapshot,
        estimate=estimate,
        frozen_legs=frozen_legs,
        clarifications=clarifications,
        created_at=created_at,
        expires_at=expires_at,
        composition_rule=composition_rule,
    )


def _scope_clarification(
    leg_index: int,
    role: str,
    geography: GeographyClarification,
) -> IntentClarification:
    return IntentClarification(
        field=f"legs.{leg_index}.{role}_scope",
        code=geography.reason,
        message_ru="Уточните географию маршрута.",
        geography=geography,
    )


def _anywhere_origin_clarification(leg_index: int) -> IntentClarification:
    return IntentClarification(
        field=f"legs.{leg_index}.origin_scope",
        code="unknown_geography",
        message_ru="Для поиска куда угодно нужен конечный пункт отправления.",
    )


def _anywhere_date_range_too_large_clarification(
    leg_index: int,
    *,
    actual_months: int,
) -> IntentClarification:
    return IntentClarification(
        field=f"legs.{leg_index}.date_constraint",
        code="anywhere_date_range_too_large",
        message_ru=(
            "Поиск куда угодно ограничен двенадцатью календарными месяцами. Сузьте диапазон дат."
        ),
        details={
            "actual_months": actual_months,
            "max_months": MAX_ANYWHERE_DISCOVERY_MONTHS,
        },
    )


def _catalog_changed_clarification(leg_index: int) -> IntentClarification:
    return IntentClarification(
        field=f"legs.{leg_index}.scope",
        code="catalog_changed_during_planning",
        message_ru="Каталог аэропортов изменился. Повторите построение плана.",
    )


def _split_anywhere_unsupported_clarification() -> IntentClarification:
    return IntentClarification(
        field="requested_strategies",
        code="split_anywhere_unsupported",
        message_ru=(
            "Сначала ограничьте направление: split/self-transfer требует "
            "замороженного конечного маршрута и бюджета узлов пересадки."
        ),
    )


def _geography_catalog_clarification() -> IntentClarification:
    return IntentClarification(
        field="geography_catalog",
        code="geography_catalog_required",
        message_ru="Для заморозки маршрута нужен локальный каталог аэропортов.",
    )


def _incomplete_intent_clarification() -> IntentClarification:
    return IntentClarification(
        field="intent",
        code="intent_incomplete",
        message_ru="План нельзя завершить, пока маршрут не заполнен.",
    )


def _same_origin_destination_clarification(leg_index: int) -> IntentClarification:
    return IntentClarification(
        field=f"legs.{leg_index}.route",
        code="same_origin_destination",
        message_ru="Аэропорт вылета и прилёта совпадают. Выберите разные точки маршрута.",
        details={"leg_index": leg_index},
    )


def _budget_revision_clarification(
    estimate: PlanEstimate,
    *,
    logical_limit: int,
) -> IntentClarification:
    return IntentClarification(
        field="budget",
        code="budget_revision_required",
        message_ru=("Полный поиск превышает локальный лимит. Сузьте географию или диапазон дат."),
        details={
            "logical_operations": estimate.logical_operations,
            "limit": logical_limit,
        },
    )


def _quick_budget_clarification(
    surface: SearchSurface,
    *,
    logical_limit: int,
) -> IntentClarification:
    logical_operations = surface.calendar_searches + surface.exact_searches
    return IntentClarification(
        field="budget",
        code="quick_budget_too_large",
        message_ru=(
            "Быстрый поиск не вмещает весь замороженный объём. "
            "Сузьте географию или даты либо выберите полный поиск."
        ),
        actions=(
            ClarificationAction(
                action_id="narrow_scope_or_dates",
                label_ru="Сузить географию или даты",
                selections={},
            ),
        ),
        details={
            "calendar_searches": surface.calendar_searches,
            "exact_searches": surface.exact_searches,
            "logical_operations": logical_operations,
            "limit": logical_limit,
        },
    )


def _nearby_radius_km(parsed: ParsedIntent) -> int:
    return parsed.nearby_radius_km
