from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from flight_hunter.agent.presets import AgentPresetId
from flight_hunter.application.agent_lifecycle import PlanView, RunResultsView, RunView
from flight_hunter.application.agent_scope import CoverageMode


class CreateAgentPlanRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: str = ""
    selections: dict[str, object] = Field(default_factory=dict)
    coverage: CoverageMode = CoverageMode.QUICK
    preset_id: AgentPresetId | None = None


class EditAgentPlanRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_revision_id: UUID
    expected_revision: int = Field(ge=1)
    text: str | None = None
    selections: dict[str, object] = Field(default_factory=dict)
    coverage: CoverageMode | None = None
    preset_id: AgentPresetId | None = None


class CloneAgentPlanRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_revision_id: UUID
    expected_revision: int = Field(ge=1)
    selections: dict[str, object] = Field(default_factory=dict)
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
    error_message: str | None

    @classmethod
    def from_view(cls, view: RunView) -> AgentRunResponse:
        return cls.model_validate(view)


class AgentRunListResponse(BaseModel):
    runs: list[AgentRunResponse]


class AgentRunResultsResponse(BaseModel):
    run_id: UUID
    state: str
    evidence_available: bool
    items: list[object]

    @classmethod
    def from_view(cls, view: RunResultsView) -> AgentRunResultsResponse:
        return cls(
            run_id=view.run_id,
            state=view.state,
            evidence_available=view.evidence_available,
            items=list(view.items),
        )
