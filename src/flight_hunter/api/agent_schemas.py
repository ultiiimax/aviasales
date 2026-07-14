from __future__ import annotations

from datetime import date as Date
from datetime import datetime
from typing import Literal, cast
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StrictInt

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

    @classmethod
    def from_view(cls, view: RunView) -> AgentRunResponse:
        return cls.model_validate(view)


class AgentRunListResponse(BaseModel):
    runs: list[AgentRunResponse]


class AgentRunResultsResponse(BaseModel):
    run_id: UUID
    state: Literal["not_ready"]
    evidence_available: bool

    @classmethod
    def from_view(cls, view: RunResultsView) -> AgentRunResultsResponse:
        return cls(
            run_id=view.run_id,
            state=view.state,
            evidence_available=view.evidence_available,
        )
