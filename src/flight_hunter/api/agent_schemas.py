from __future__ import annotations

from datetime import date as Date
from datetime import datetime
from typing import Literal, Self, cast
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StrictInt, ValidationError, model_validator

from flight_hunter.agent.presets import AgentPresetId
from flight_hunter.application.agent_lifecycle import PlanView, RunResultsView, RunView
from flight_hunter.application.agent_scope import CoverageMode
from flight_hunter.domain.agent_search import DateMode, RouteStrategy, TripShape


class AgentLegSelection(BaseModel):
    model_config = ConfigDict(extra="forbid")

    origin: str = Field(min_length=1, max_length=200)
    destination: str = Field(min_length=1, max_length=200)
    date: Date | None = None


class AgentPlanSelections(BaseModel):
    model_config = ConfigDict(extra="forbid")

    origin: str | None = Field(default=None, min_length=1, max_length=200)
    destination: str | None = Field(default=None, min_length=1, max_length=200)
    legs: list[AgentLegSelection] | None = Field(default=None, min_length=1, max_length=8)
    date_mode: DateMode | None = None
    departure_date: Date | None = None
    date_start: Date | None = None
    date_end: Date | None = None
    flex_days: StrictInt | None = Field(default=None, ge=1, le=30)
    return_date: Date | None = None
    trip_shape: TripShape | None = None
    adults: StrictInt | None = Field(default=None, ge=1, le=9)
    children: StrictInt | None = Field(default=None, ge=0, le=9)
    infants: StrictInt | None = Field(default=None, ge=0, le=9)
    nearby_radius_km: StrictInt | None = Field(default=None, ge=0, le=500)
    currency: str | None = Field(default=None, pattern=r"^[A-Z]{3}$")
    requested_strategies: list[RouteStrategy] | None = Field(default=None, max_length=5)

    def to_parser_mapping(self) -> dict[str, object]:
        return cast(
            dict[str, object],
            self.model_dump(mode="json", exclude_none=True),
        )


class CreateAgentPlanRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: str = Field(default="", max_length=2_000)
    selections: AgentPlanSelections = Field(default_factory=AgentPlanSelections)
    coverage: CoverageMode = CoverageMode.QUICK
    preset_id: AgentPresetId | None = None


class EditAgentPlanRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_revision_id: UUID
    expected_revision: int = Field(ge=1)
    text: str | None = Field(default=None, max_length=2_000)
    selections: AgentPlanSelections = Field(default_factory=AgentPlanSelections)
    coverage: CoverageMode | None = None
    preset_id: AgentPresetId | None = None


class CloneAgentPlanRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_revision_id: UUID
    expected_revision: int = Field(ge=1)
    selections: AgentPlanSelections = Field(default_factory=AgentPlanSelections)
    coverage: CoverageMode | None = None


class ExecuteAgentPlanRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    revision_id: UUID | None = None
    expected_revision: int | None = Field(default=None, ge=1)
    content_hash: str | None = None
    hidden_city_warning_version: str | None = None


class ClarificationActionResponse(BaseModel):
    action_id: str
    label_ru: str
    selections: dict[str, str]
    date_mode: str | None = None


class ClarificationResponse(BaseModel):
    field: str
    code: str
    message_ru: str
    actions: list[ClarificationActionResponse]
    details: dict[str, int | str]


class AgentPlanEstimateResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    calendar_searches: int
    exact_searches: int
    logical_operations: int
    http_attempts: int
    deadline_seconds: int


class AgentPlanPassengerSummaryResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    adults: int
    children: int
    infants: int
    total: int
    currency: str


class AgentPlanScopeLegSummaryResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    origin_kind: str | None
    origin_value: str | None
    origin_airports: list[str]
    destination_kind: str | None
    destination_value: str | None
    destination_airports: list[str]
    anywhere: bool
    frozen: bool
    reciprocal_anywhere_return: bool
    nearby_radius_km: int
    date_mode: str
    date_start: Date | None
    date_end: Date | None
    flex_days: int


class AgentPlanProviderSummaryResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    source_id: str
    capability_version: str
    cost_model_version: str
    requests_per_minute: int | None


class AgentHiddenCityWarningResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    code: str
    message_ru: str
    message_en: str


class AgentPlanSummaryResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    trip_shape: str
    date_mode: str
    preset_id: str | None
    analysis_modes: list[str]
    passengers: AgentPlanPassengerSummaryResponse
    scope: list[AgentPlanScopeLegSummaryResponse]
    provider: AgentPlanProviderSummaryResponse
    hidden_city_enabled: bool
    hidden_city_warning_version: str | None
    hidden_city_warnings: list[AgentHiddenCityWarningResponse]
    baggage_preference: str
    wants_watch: bool


class AgentPlanResponse(BaseModel):
    plan_id: UUID
    revision_id: UUID
    revision: int
    state: str
    content_hash: str
    coverage: str
    executable: bool
    enabled_strategies: list[str]
    estimate: AgentPlanEstimateResponse | None
    summary: AgentPlanSummaryResponse
    clarifications: list[ClarificationResponse]
    created_at: datetime
    expires_at: datetime

    @classmethod
    def from_view(cls, view: PlanView) -> AgentPlanResponse:
        return cls.model_validate(
            {
                "plan_id": view.plan_id,
                "revision_id": view.revision_id,
                "revision": view.revision,
                "state": view.state,
                "content_hash": view.content_hash,
                "coverage": view.coverage,
                "executable": view.executable,
                "enabled_strategies": list(view.enabled_strategies),
                "estimate": view.estimate,
                "summary": view.summary,
                "clarifications": list(view.clarifications),
                "created_at": view.created_at,
                "expires_at": view.expires_at,
            }
        )


class AgentStageCountsResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    total: int
    pending: int
    running: int
    completed: int
    partial: int
    failed: int
    skipped: int
    cancelled: int


class AgentOperationCountsResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    total: int
    attempted: int
    pending: int
    leased: int
    retry_wait: int
    succeeded: int
    failed: int
    skipped: int


class AgentCoverageFrozenInputResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    origins: list[str]
    destinations: list[str]
    date_start: Date
    date_end: Date
    return_date: Date | None
    catalog_checksums: list[str]
    taxonomy_versions: list[str]


class AgentCoveragePairResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    origin: str
    destination: str
    departure_date: Date
    return_date: Date | None
    status: Literal["planned", "attempted", "succeeded", "failed", "skipped"]
    reason: str | None


class AgentCoverageDiscoveryPhaseResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    status: Literal["pending", "complete", "partial", "failed"]
    terminal_reason: str | None
    source_ids: list[str]
    max_destination_seeds: int
    exact_verification_limit: int


class AgentCoverageReportResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    coverage: Literal["quick", "full"]
    completion: Literal["pending", "complete", "full", "partial", "failed"]
    frozen_input: AgentCoverageFrozenInputResponse
    planned: int
    attempted: int
    succeeded: int
    failed: int
    skipped: int
    pairs: list[AgentCoveragePairResponse]
    reason_counts: dict[str, int]
    discovery_phase: AgentCoverageDiscoveryPhaseResponse | None


class AgentRunResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    run_id: UUID
    plan_id: UUID
    revision_id: UUID
    status: str
    created_at: datetime
    deadline_at: datetime
    started_at: datetime | None
    cancel_requested_at: datetime | None
    finished_at: datetime | None
    error_code: str | None
    public_message: str | None
    stage_counts: AgentStageCountsResponse
    operation_counts: AgentOperationCountsResponse
    logical_operation_budget: int
    logical_operations_consumed: int
    http_attempt_budget: int
    http_attempts_consumed: int
    cancellation_requested: bool
    coverage_report: AgentCoverageReportResponse | None
    coverage_error_code: Literal["agent_coverage_projection_invalid"] | None

    @classmethod
    def from_view(cls, view: RunView) -> AgentRunResponse:
        return cls.model_validate(view)


class AgentRunListResponse(BaseModel):
    runs: list[AgentRunResponse]


class AgentMoneyResponse(BaseModel):
    minor_units: int
    currency: str


class AgentCandidateReferenceResponse(BaseModel):
    kind: Literal["confirmed_offer", "composed_route"]
    id: UUID


class AgentBalancedWeightsResponse(BaseModel):
    price: int
    duration: int
    risk: int


class AgentRankedCandidateResponse(BaseModel):
    reference: AgentCandidateReferenceResponse
    rank: int
    reasons: list[str]


class AgentRankingViewResponse(BaseModel):
    name: Literal[
        "cheapest",
        "fastest",
        "low_risk",
        "balanced",
        "split_self_transfer",
        "risky",
    ]
    candidates: list[AgentRankedCandidateResponse]
    weights: AgentBalancedWeightsResponse | None = None


class AgentRankingSnapshotResponse(BaseModel):
    confirmed_evidence_ids: list[UUID]
    composed_candidate_ids: list[UUID]
    comparison_currency: str | None
    views: list[AgentRankingViewResponse]
    fingerprint: str


class AgentSegmentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    airline_code: str
    airline_name: str | None
    flight_number: str | None
    origin: str
    destination: str
    depart_at: str
    arrive_at: str
    depart_at_utc: datetime | None
    arrive_at_utc: datetime | None


class AgentPassengerMixResponse(BaseModel):
    adults: int
    children: int
    infants: int
    total: int


class AgentOrderedLegResponse(BaseModel):
    ordinal: int
    origin: str
    destination: str
    departure_date: Date
    component_evidence_ids: list[UUID]


class AgentTicketBoundaryResponse(BaseModel):
    ticket_index: int
    leg_ordinals: list[int]
    confirmed_evidence_id: UUID
    segment_ids: list[str]
    protection_status: Literal[
        "explicitly_protected",
        "self_transfer",
        "unknown",
    ]


class AgentConnectionAssumptionResponse(BaseModel):
    leg_ordinal: int
    inbound_component_id: UUID
    outbound_component_id: UUID
    arrival_airport: str
    departure_airport: str
    layover_seconds: int
    required_minimum_seconds: int
    airport_change: bool
    provenance: str | None
    transfer_cost: AgentMoneyResponse | None


class AgentUnknownCostResponse(BaseModel):
    kind: Literal["ground_transfer", "currency_conversion"]
    leg_ordinal: int
    description: str


class AgentRankingPlacementResponse(BaseModel):
    view: Literal[
        "cheapest",
        "fastest",
        "low_risk",
        "balanced",
        "split_self_transfer",
        "risky",
    ]
    rank: int
    reasons: list[str]


class AgentBookingActionResponse(BaseModel):
    available: bool
    token: str | None


class AgentBookingResolveRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    token: str = Field(min_length=1, max_length=4096)


class AgentBookingResolveResponse(BaseModel):
    status: Literal["resolved", "unavailable"]
    url: str | None = None


class AgentCandidateFactResponse(BaseModel):
    reference: AgentCandidateReferenceResponse
    passengers: int
    passenger_mix: AgentPassengerMixResponse
    trip_shape: Literal["one_way", "round_trip", "open_jaw", "multi_city"]
    price_basis: Literal[
        "total_for_passengers",
        "provider_single_adult_ticket",
    ]
    total_amount: AgentMoneyResponse | None
    sources: list[str]
    observed_at: datetime
    segments: list[AgentSegmentResponse]
    ticket_boundaries: list[AgentTicketBoundaryResponse]
    ordered_legs: list[AgentOrderedLegResponse]
    connection_assumptions: list[AgentConnectionAssumptionResponse]
    price_comparison_status: Literal[
        "fully_priced",
        "mandatory_cost_unknown",
        "non_comparable",
    ]
    unknown_costs: list[AgentUnknownCostResponse]
    protection_status: Literal[
        "explicitly_protected",
        "self_transfer",
        "unknown",
    ]
    baggage_summaries: list[str | None]
    unknowns: list[str]
    rankings: list[AgentRankingPlacementResponse]
    booking_action: AgentBookingActionResponse


class AgentHiddenCityCandidateResponse(BaseModel):
    evidence_id: UUID
    desired_airport: str
    ticketed_destination: str
    actionability: Literal["eligible", "research_only_not_actionable"]
    total_amount: AgentMoneyResponse
    passengers: int
    source_id: str
    freshness: Literal["live"]
    observed_at: datetime
    flown_segments: list[AgentSegmentResponse]
    skipped_segments: list[AgentSegmentResponse]
    warning_version: Literal["hidden-city-v1"]
    warnings: list[str]
    booking_action_available: Literal[False]
    watch_available: Literal[False]


class AgentBuyTimingThresholdsResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    minimum_observations: int
    minimum_history_span_days: int
    minimum_distinct_dates: int
    minimum_bucket_observations: int
    minimum_bucket_weeks: int
    minimum_recommendation_difference_percent: str
    buy_now_percentile: str


class AgentBuyTimingAnalysisResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal["insufficient_data", "historically_low", "no_buy_signal"]
    watch_action_available: bool
    sample_count: int
    distinct_dates: int
    distinct_weeks: int
    history_span_days: int
    current_percentile: str | None
    twentieth_percentile_minor_units: int | None
    median_minor_units: str | None
    timezone: str
    days_to_departure_band: Literal["0-6", "7-13", "14-29", "30-59", "60+"]
    recommended_weekday: int | None
    weekday_savings_percent: str | None
    recommended_four_hour_bucket: int | None
    four_hour_savings_percent: str | None
    calculation_version: Literal["buy-timing-v1"]
    thresholds: AgentBuyTimingThresholdsResponse


class AgentAnomalyThresholdsResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    minimum_observations: int
    minimum_distinct_dates: int
    maximum_median_ratio: str
    maximum_robust_mad_z: str


class AgentAnomalyAnalysisResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal["insufficient_data", "suspected_anomaly", "not_anomalous"]
    sample_count: int
    distinct_dates: int
    median_minor_units: str | None
    ratio_to_median: str | None
    mad_minor_units: str | None
    robust_mad_z: str | None
    observed_range_minor_units: int | None
    detector_version: Literal["suspected-anomaly-v1"]
    thresholds: AgentAnomalyThresholdsResponse


class AgentCurrencyAnalysisResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal["comparable", "not_comparable", "fx_provider_unavailable"]
    reason_code: str
    reference_evidence_id: UUID
    reference_amount: AgentMoneyResponse
    candidate_evidence_id: UUID | None
    candidate_amount: AgentMoneyResponse | None
    comparison_currency: str
    savings_minor_units: int | None
    savings_percent: str | None
    calculation_version: Literal["currency-comparison-v1"]


class AgentFareAnalysisWatchActionResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    available: bool
    origin: str = Field(pattern=r"^[A-Z]{3}$")
    destination: str = Field(pattern=r"^[A-Z]{3}$")
    departure_date: Date
    return_date: Date | None
    passengers: int = Field(ge=1)
    currency: str = Field(pattern=r"^[A-Z]{3}$")


class AgentFareAnalysisResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: Literal["fare-analysis-snapshot-v1"]
    source: Literal["confirmed_exact_history"]
    aggregation_mode: Literal["market_minimum"]
    scope_status: Literal["supported", "unsupported_trip_structure"]
    scope_reason: Literal["full_itinerary_history_unavailable"] | None = None
    trip_shape: Literal["one_way", "round_trip", "open_jaw", "multi_city"]
    requested_modes: list[Literal["buy_timing", "error_fare", "currency_compare"]]
    source_evidence_truncated: bool
    primary_evidence_id: UUID | None = None
    history_series_hash: str | None = Field(
        default=None,
        pattern=r"^sha256:[0-9a-f]{64}$",
    )
    history_observation_count: int | None = Field(default=None, ge=0)
    history_evidence_fingerprint: str | None = Field(
        default=None,
        pattern=r"^sha256:[0-9a-f]{64}$",
    )
    provider_id: str | None = None
    freshness: Literal["live"] | None = None
    passengers: int | None = Field(default=None, ge=1)
    passenger_basis: Literal["total_for_passengers"] | None = None
    primary_amount: AgentMoneyResponse | None = None
    origin: str | None = Field(default=None, pattern=r"^[A-Z]{3}$")
    destination: str | None = Field(default=None, pattern=r"^[A-Z]{3}$")
    departure_date: Date | None = None
    return_date: Date | None = None
    observed_at: datetime | None = None
    watch_action: AgentFareAnalysisWatchActionResponse | None = None
    buy_timing: AgentBuyTimingAnalysisResponse | None = None
    anomaly: AgentAnomalyAnalysisResponse | None = None
    currency_comparison: AgentCurrencyAnalysisResponse | None = None

    @model_validator(mode="after")
    def validate_scope_contract(self) -> Self:
        mode_fields = {
            "buy_timing": self.buy_timing,
            "error_fare": self.anomaly,
            "currency_compare": self.currency_comparison,
        }
        if len(self.requested_modes) != len(set(self.requested_modes)):
            raise ValueError("requested analysis modes must be unique")
        if self.scope_status == "unsupported_trip_structure":
            if self.scope_reason != "full_itinerary_history_unavailable" or any(
                value is not None
                for value in (
                    self.primary_evidence_id,
                    self.history_series_hash,
                    self.history_observation_count,
                    self.history_evidence_fingerprint,
                    self.provider_id,
                    self.freshness,
                    self.passengers,
                    self.passenger_basis,
                    self.primary_amount,
                    self.origin,
                    self.destination,
                    self.departure_date,
                    self.return_date,
                    self.observed_at,
                    self.watch_action,
                    *mode_fields.values(),
                )
            ):
                raise ValueError("unsupported analysis scope cannot expose partial-trip results")
            return self

        required = (
            self.primary_evidence_id,
            self.history_series_hash,
            self.history_observation_count,
            self.history_evidence_fingerprint,
            self.provider_id,
            self.freshness,
            self.passengers,
            self.passenger_basis,
            self.primary_amount,
            self.origin,
            self.destination,
            self.departure_date,
            self.observed_at,
        )
        if (
            self.scope_reason is not None
            or self.trip_shape not in {"one_way", "round_trip"}
            or any(value is None for value in required)
        ):
            raise ValueError("supported analysis scope requires complete evidence facts")
        for mode, value in mode_fields.items():
            if (mode in self.requested_modes) != (value is not None):
                raise ValueError("analysis result fields must match requested modes")
        if ("buy_timing" in self.requested_modes) != (self.watch_action is not None):
            raise ValueError("watch action must match buy timing analysis")
        if self.watch_action is not None and (
            self.buy_timing is None
            or self.watch_action.available != self.buy_timing.watch_action_available
            or self.watch_action.origin != self.origin
            or self.watch_action.destination != self.destination
            or self.watch_action.departure_date != self.departure_date
            or self.watch_action.return_date != self.return_date
            or self.watch_action.passengers != self.passengers
            or self.primary_amount is None
            or self.watch_action.currency != self.primary_amount.currency
        ):
            raise ValueError("watch action must be bound to the analyzed fare")
        return self


class AgentRunResultsResponse(BaseModel):
    run_id: UUID
    state: Literal["not_ready", "ready", "unavailable"]
    evidence_available: bool
    ranking: AgentRankingSnapshotResponse | None = None
    candidates: list[AgentCandidateFactResponse] | None = None
    analysis: AgentFareAnalysisResponse | None = None
    hidden_city_candidates: list[AgentHiddenCityCandidateResponse] | None = None
    error_code: Literal["agent_results_unavailable"] | None = None

    @classmethod
    def from_view(cls, view: RunResultsView) -> AgentRunResultsResponse:
        try:
            analysis = (
                None
                if view.analysis is None
                else AgentFareAnalysisResponse.model_validate(view.analysis)
            )
        except ValidationError:
            return cls(
                run_id=view.run_id,
                state="unavailable",
                evidence_available=view.evidence_available,
                error_code="agent_results_unavailable",
            )
        report = view.report
        return cls(
            run_id=view.run_id,
            state=view.state,
            evidence_available=view.evidence_available,
            ranking=(
                None
                if report is None
                else AgentRankingSnapshotResponse(
                    confirmed_evidence_ids=list(report.ranking.confirmed_evidence_ids),
                    composed_candidate_ids=list(report.ranking.composed_candidate_ids),
                    comparison_currency=report.ranking.comparison_currency,
                    views=[
                        AgentRankingViewResponse(
                            name=ranking_view.name.value,
                            candidates=[
                                AgentRankedCandidateResponse(
                                    reference=AgentCandidateReferenceResponse(
                                        kind=candidate.reference.kind.value,
                                        id=candidate.reference.id,
                                    ),
                                    rank=candidate.rank,
                                    reasons=list(candidate.reasons),
                                )
                                for candidate in ranking_view.candidates
                            ],
                            weights=(
                                None
                                if ranking_view.weights is None
                                else AgentBalancedWeightsResponse(
                                    price=ranking_view.weights.price,
                                    duration=ranking_view.weights.duration,
                                    risk=ranking_view.weights.risk,
                                )
                            ),
                        )
                        for ranking_view in report.ranking.views
                    ],
                    fingerprint=report.ranking.fingerprint,
                )
            ),
            candidates=(
                None
                if report is None
                else [
                    AgentCandidateFactResponse(
                        reference=AgentCandidateReferenceResponse(
                            kind=candidate.reference.kind.value,
                            id=candidate.reference.id,
                        ),
                        passengers=candidate.passengers,
                        passenger_mix=AgentPassengerMixResponse(
                            adults=candidate.passenger_mix.adults,
                            children=candidate.passenger_mix.children,
                            infants=candidate.passenger_mix.infants,
                            total=candidate.passenger_mix.total,
                        ),
                        trip_shape=candidate.trip_shape.value,
                        price_basis=candidate.price_basis.value,
                        total_amount=(
                            None
                            if candidate.total_amount is None
                            else AgentMoneyResponse(
                                minor_units=candidate.total_amount.minor_units,
                                currency=candidate.total_amount.currency,
                            )
                        ),
                        sources=list(candidate.sources),
                        observed_at=candidate.observed_at,
                        segments=[
                            AgentSegmentResponse.model_validate(segment)
                            for segment in candidate.segments
                        ],
                        ticket_boundaries=[
                            AgentTicketBoundaryResponse(
                                ticket_index=boundary.ticket_index,
                                leg_ordinals=list(boundary.leg_ordinals),
                                confirmed_evidence_id=boundary.confirmed_evidence_id,
                                segment_ids=list(boundary.segment_ids),
                                protection_status=boundary.protection_status.value,
                            )
                            for boundary in candidate.ticket_boundaries
                        ],
                        ordered_legs=[
                            AgentOrderedLegResponse(
                                ordinal=leg.ordinal,
                                origin=leg.origin,
                                destination=leg.destination,
                                departure_date=leg.departure_date,
                                component_evidence_ids=list(leg.component_evidence_ids),
                            )
                            for leg in candidate.ordered_legs
                        ],
                        connection_assumptions=[
                            AgentConnectionAssumptionResponse(
                                leg_ordinal=assumption.leg_ordinal,
                                inbound_component_id=assumption.inbound_component_id,
                                outbound_component_id=assumption.outbound_component_id,
                                arrival_airport=assumption.arrival_airport,
                                departure_airport=assumption.departure_airport,
                                layover_seconds=int(assumption.layover.total_seconds()),
                                required_minimum_seconds=int(
                                    assumption.required_minimum.total_seconds()
                                ),
                                airport_change=assumption.airport_change,
                                provenance=assumption.provenance,
                                transfer_cost=(
                                    None
                                    if assumption.transfer_cost is None
                                    else AgentMoneyResponse(
                                        minor_units=assumption.transfer_cost.minor_units,
                                        currency=assumption.transfer_cost.currency,
                                    )
                                ),
                            )
                            for assumption in candidate.connection_assumptions
                        ],
                        price_comparison_status=(candidate.price_comparison_status.value),
                        unknown_costs=[
                            AgentUnknownCostResponse(
                                kind=cost.kind.value,
                                leg_ordinal=cost.leg_ordinal,
                                description=cost.description,
                            )
                            for cost in candidate.unknown_costs
                        ],
                        protection_status=candidate.protection_status.value,
                        baggage_summaries=list(candidate.baggage_summaries),
                        unknowns=list(candidate.unknowns),
                        rankings=[
                            AgentRankingPlacementResponse(
                                view=placement.view.value,
                                rank=placement.rank,
                                reasons=list(placement.reasons),
                            )
                            for placement in candidate.rankings
                        ],
                        booking_action=AgentBookingActionResponse(
                            available=candidate.booking_action.available,
                            token=candidate.booking_action.token,
                        ),
                    )
                    for candidate in report.candidates
                ]
            ),
            analysis=analysis,
            hidden_city_candidates=(
                None
                if not view.hidden_city_candidates
                else [
                    AgentHiddenCityCandidateResponse(
                        evidence_id=candidate.source_evidence.id,
                        desired_airport=candidate.desired_airport,
                        ticketed_destination=candidate.ticketed_destination,
                        actionability=candidate.actionability.value,
                        total_amount=AgentMoneyResponse(
                            minor_units=candidate.source_evidence.total_amount.minor_units,
                            currency=candidate.source_evidence.total_amount.currency,
                        ),
                        passengers=candidate.source_evidence.passengers,
                        source_id=candidate.source_evidence.provider_id,
                        freshness="live",
                        observed_at=candidate.source_evidence.observed_at,
                        flown_segments=[
                            AgentSegmentResponse.model_validate(segment)
                            for segment in candidate.flown_segments
                        ],
                        skipped_segments=[
                            AgentSegmentResponse.model_validate(segment)
                            for segment in candidate.skipped_segments
                        ],
                        warning_version="hidden-city-v1",
                        warnings=[warning.code for warning in candidate.warnings],
                        booking_action_available=False,
                        watch_available=False,
                    )
                    for candidate in view.hidden_city_candidates
                ]
            ),
            error_code=view.error_code,
        )
