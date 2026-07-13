# ruff: noqa: RUF001

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum

from flight_hunter.application.agent_capabilities import ProviderCapabilityRegistry
from flight_hunter.application.agent_intent import (
    ClarificationAction,
    IntentClarification,
    ParsedIntent,
)
from flight_hunter.application.agent_scope import CoverageMode
from flight_hunter.config import AppSettings
from flight_hunter.domain.agent_search import (
    DateMode,
    PlanBudget,
    ProviderCapabilitySnapshot,
    ProviderHttpCostModel,
    TravelIntent,
)


class PlanBudgetExceededError(ValueError):
    code = "budget_too_large"


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
class ProposedPlanRevision:
    status: PlanRevisionStatus
    parsed_intent: ParsedIntent
    travel_intent: TravelIntent | None
    coverage: CoverageMode
    capability_snapshot: ProviderCapabilitySnapshot | None
    estimate: PlanEstimate | None
    clarifications: tuple[IntentClarification, ...]
    created_at: datetime
    expires_at: datetime
    builder_version: str = "agent-plan-builder-v1"


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
                "absolute_logical_limit exceeded: "
                f"{logical_operations} > {self._settings.agent_absolute_logical_limit}"
            )

        if surface.coverage is CoverageMode.QUICK:
            if logical_operations > self._settings.agent_quick_logical_limit:
                raise PlanBudgetExceededError(
                    "quick_logical_limit exceeded: "
                    f"{logical_operations} > {self._settings.agent_quick_logical_limit}"
                )
            if surface.calendar_searches > self._settings.agent_quick_calendar_limit:
                raise PlanBudgetExceededError(
                    "quick_calendar_limit exceeded: "
                    f"{surface.calendar_searches} > "
                    f"{self._settings.agent_quick_calendar_limit}"
                )
            if surface.exact_searches > self._settings.agent_quick_exact_limit:
                raise PlanBudgetExceededError(
                    "quick_exact_limit exceeded: "
                    f"{surface.exact_searches} > {self._settings.agent_quick_exact_limit}"
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
    ) -> None:
        self._clock = clock or (lambda: datetime.now(UTC))
        self._settings = settings or AppSettings.from_env()
        self._capabilities = capabilities or ProviderCapabilityRegistry()
        self._estimator = estimator or PlanEstimator(settings=self._settings)

    def build(
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
            return ProposedPlanRevision(
                status=PlanRevisionStatus.DRAFT,
                parsed_intent=parsed,
                travel_intent=None,
                coverage=normalized_coverage,
                capability_snapshot=snapshot,
                estimate=None,
                clarifications=parsed.clarifications,
                created_at=created_at,
                expires_at=expires_at,
            )

        travel_intent = parsed.to_travel_intent(today=created_at.date())
        if travel_intent is None:
            return ProposedPlanRevision(
                status=PlanRevisionStatus.DRAFT,
                parsed_intent=parsed,
                travel_intent=None,
                coverage=normalized_coverage,
                capability_snapshot=snapshot,
                estimate=None,
                clarifications=(_incomplete_intent_clarification(),),
                created_at=created_at,
                expires_at=expires_at,
            )

        surface = _surface_for(
            travel_intent,
            normalized_coverage,
            quick_calendar_limit=self._settings.agent_quick_calendar_limit,
            quick_exact_limit=self._settings.agent_quick_exact_limit,
        )
        estimate = self._estimator.estimate(surface, snapshot.cost_model)
        if estimate.requires_budget_revision:
            return ProposedPlanRevision(
                status=PlanRevisionStatus.DRAFT,
                parsed_intent=parsed,
                travel_intent=travel_intent,
                coverage=normalized_coverage,
                capability_snapshot=snapshot,
                estimate=estimate,
                clarifications=(_budget_revision_clarification(estimate),),
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
            clarifications=(),
            created_at=created_at,
            expires_at=expires_at,
        )


def _surface_for(
    intent: TravelIntent,
    coverage: CoverageMode,
    *,
    quick_calendar_limit: int,
    quick_exact_limit: int,
) -> SearchSurface:
    calendar_searches = 0
    exact_searches = len(intent.legs)
    for leg in intent.legs:
        constraint = leg.date_constraint
        if constraint.mode is DateMode.FLEXIBLE:
            calendar_searches += constraint.flex_days * 2 + 1
        elif constraint.mode in {DateMode.RANGE, DateMode.ROLLING_90_DAYS}:
            assert constraint.end_date is not None
            calendar_searches += (constraint.end_date - constraint.start_date).days + 1
    if calendar_searches:
        exact_searches = min(calendar_searches, quick_exact_limit)
    if coverage is CoverageMode.QUICK:
        calendar_searches = min(calendar_searches, quick_calendar_limit)
        exact_searches = min(exact_searches, quick_exact_limit)
    return SearchSurface(
        coverage=coverage,
        calendar_searches=calendar_searches,
        exact_searches=exact_searches,
    )


def _incomplete_intent_clarification() -> IntentClarification:
    return IntentClarification(
        field="intent",
        code="intent_incomplete",
        message_ru="План нельзя завершить, пока маршрут не заполнен.",
    )


def _budget_revision_clarification(estimate: PlanEstimate) -> IntentClarification:
    return IntentClarification(
        field="budget",
        code="budget_revision_required",
        message_ru="Полный поиск требует отдельной ревизии с увеличенным бюджетом.",
        actions=(
            ClarificationAction(
                action_id="approve_larger_budget_revision",
                label_ru="Создать новую ревизию бюджета",
                selections={"logical_limit": str(estimate.requested_logical_limit)},
            ),
        ),
    )
