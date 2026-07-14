# ruff: noqa: B008

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Request
from fastapi.exception_handlers import request_validation_exception_handler
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from flight_hunter.api.agent_schemas import (
    AgentPlanResponse,
    AgentRunListResponse,
    AgentRunResponse,
    AgentRunResultsResponse,
    CloneAgentPlanRequest,
    CreateAgentPlanRequest,
    EditAgentPlanRequest,
    ExecuteAgentPlanRequest,
)
from flight_hunter.application.agent_intent import IntentParser
from flight_hunter.application.agent_lifecycle import (
    AgentLifecycleError,
    AgentLifecycleService,
    CancelAgentRun,
    CloneAgentPlan,
    CreateAgentPlan,
    EditAgentPlan,
    ExecuteAgentPlan,
)
from flight_hunter.application.agent_planning import AgentPlanBuilder
from flight_hunter.application.agent_scope import ScopeResolver
from flight_hunter.config import AppSettings
from flight_hunter.domain.auth import AuthSession, token_hash
from flight_hunter.persistence.repositories import AirportReferenceRepository, IdentityRepository

ERROR_STATUS = {
    "auth_context_missing": 401,
    "idempotency_key_required": 400,
    "agent_plan_incomplete": 409,
    "agent_plan_stale": 409,
    "agent_plan_consumed": 409,
    "agent_plan_expired": 410,
    "agent_plan_budget_too_large": 422,
    "agent_plan_approval_required": 403,
    "agent_hidden_city_ack_required": 403,
    "agent_run_already_active": 409,
    "agent_plan_invalid_input": 422,
    "agent_plan_not_found": 404,
    "agent_run_not_found": 404,
    "agent_sqlite_nested_transaction_unsupported": 409,
    "agent_run_idempotency_conflict": 409,
    "agent_run_transition_conflict": 409,
    "agent_run_cancelled": 409,
    "agent_plan_duplicate_revision": 409,
    "agent_plan_conflict": 409,
}

_BEARER = HTTPBearer(auto_error=False)


class AgentRouteError(RuntimeError):
    def __init__(self, code: str) -> None:
        self.code = code
        self.status_code = _status_for_error(code)
        super().__init__(code)


async def agent_route_error_handler(
    _request: Request,
    error: Exception,
) -> JSONResponse:
    if not isinstance(error, AgentRouteError):
        raise error
    return JSONResponse(
        status_code=error.status_code,
        content={"code": error.code, "message": _error_message(error.code)},
    )


async def agent_validation_error_handler(
    request: Request,
    error: Exception,
) -> JSONResponse:
    if not isinstance(error, RequestValidationError):
        raise error
    if request.url.path == "/api/v1/agent/search-plans" or request.url.path.startswith(
        "/api/v1/agent/search-plans/"
    ):
        return JSONResponse(
            status_code=422,
            content={
                "code": "agent_plan_invalid_input",
                "message": _error_message("agent_plan_invalid_input"),
            },
        )
    return await request_validation_exception_handler(request, error)


def create_agent_router(
    *,
    session_factory: async_sessionmaker[AsyncSession],
    provider_gateway: object | None = None,
    clock: Callable[[], datetime] | None = None,
    settings: AppSettings | None = None,
) -> APIRouter:
    router = APIRouter(prefix="/api/v1/agent/search-plans", tags=["agent-plans"])
    lifecycle_clock = clock or (lambda: datetime.now(UTC))
    lifecycle_settings = settings or AppSettings.from_env()

    async def require_bearer_session(
        credentials: HTTPAuthorizationCredentials | None = Depends(_BEARER),
    ) -> AuthSession:
        if credentials is None or credentials.scheme.lower() != "bearer":
            raise AgentRouteError("auth_context_missing")
        async with session_factory() as session:
            auth_session = await IdentityRepository(session).session_by_token_hash(
                token_hash=token_hash(credentials.credentials),
                now=datetime.now(UTC),
            )
        if auth_session is None:
            raise AgentRouteError("auth_context_missing")
        return auth_session

    def service(session: AsyncSession) -> AgentLifecycleService:
        resolver = ScopeResolver(repository=AirportReferenceRepository(session))
        return AgentLifecycleService(
            session=session,
            parser=IntentParser(),
            builder=AgentPlanBuilder(
                clock=lifecycle_clock,
                settings=lifecycle_settings,
                scope_resolver=resolver,
            ),
            clock=lifecycle_clock,
            provider_gateway=provider_gateway,
        )

    @router.post("", response_model=AgentPlanResponse, status_code=201)
    async def create_plan(
        body: CreateAgentPlanRequest,
        auth: AuthSession = Depends(require_bearer_session),
    ) -> AgentPlanResponse:
        async with session_factory() as session:
            try:
                view = await service(session).create_plan(
                    CreateAgentPlan(
                        household_id=auth.household_id,
                        user_id=auth.user_id,
                        text=body.text,
                        selections=body.selections.to_parser_mapping(),
                        coverage=body.coverage,
                        preset_id=body.preset_id,
                    )
                )
            except AgentLifecycleError as error:
                raise _route_lifecycle_error(error) from error
        return AgentPlanResponse.from_view(view)

    @router.get("/{plan_id}", response_model=AgentPlanResponse)
    async def get_plan(
        plan_id: UUID,
        auth: AuthSession = Depends(require_bearer_session),
    ) -> AgentPlanResponse:
        async with session_factory() as session:
            try:
                view = await service(session).get_plan(auth.household_id, plan_id)
            except AgentLifecycleError as error:
                raise _route_lifecycle_error(error) from error
        return AgentPlanResponse.from_view(view)

    @router.patch("/{plan_id}", response_model=AgentPlanResponse)
    async def edit_plan(
        plan_id: UUID,
        body: EditAgentPlanRequest,
        auth: AuthSession = Depends(require_bearer_session),
    ) -> AgentPlanResponse:
        async with session_factory() as session:
            try:
                view = await service(session).edit_plan(
                    EditAgentPlan(
                        household_id=auth.household_id,
                        user_id=auth.user_id,
                        plan_id=plan_id,
                        source_revision_id=body.source_revision_id,
                        expected_revision=body.expected_revision,
                        text=body.text,
                        selections=body.selections.to_parser_mapping(),
                        coverage=body.coverage,
                        preset_id=body.preset_id,
                    )
                )
            except AgentLifecycleError as error:
                raise _route_lifecycle_error(error) from error
        return AgentPlanResponse.from_view(view)

    @router.post("/{plan_id}/revisions", response_model=AgentPlanResponse, status_code=201)
    async def clone_revision(
        plan_id: UUID,
        body: CloneAgentPlanRequest,
        auth: AuthSession = Depends(require_bearer_session),
        idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    ) -> AgentPlanResponse:
        key = _required_idempotency_key(idempotency_key)
        async with session_factory() as session:
            try:
                view = await service(session).clone_revision(
                    CloneAgentPlan(
                        household_id=auth.household_id,
                        user_id=auth.user_id,
                        plan_id=plan_id,
                        source_revision_id=body.source_revision_id,
                        expected_revision=body.expected_revision,
                        idempotency_key=key,
                        selections=body.selections.to_parser_mapping(),
                        coverage=body.coverage,
                    )
                )
            except AgentLifecycleError as error:
                raise _route_lifecycle_error(error) from error
        return AgentPlanResponse.from_view(view)

    @router.post("/{plan_id}/execute", response_model=AgentRunResponse, status_code=202)
    async def execute_plan(
        plan_id: UUID,
        body: ExecuteAgentPlanRequest,
        auth: AuthSession = Depends(require_bearer_session),
        idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    ) -> AgentRunResponse:
        key = _required_idempotency_key(idempotency_key)
        async with session_factory() as session:
            try:
                view = await service(session).execute_plan(
                    ExecuteAgentPlan(
                        household_id=auth.household_id,
                        user_id=auth.user_id,
                        approved_by_session_id=auth.id,
                        plan_id=plan_id,
                        revision_id=body.revision_id,
                        expected_revision=body.expected_revision,
                        content_hash=body.content_hash,
                        idempotency_key=key,
                        hidden_city_warning_version=body.hidden_city_warning_version,
                    )
                )
            except AgentLifecycleError as error:
                raise _route_lifecycle_error(error) from error
        return AgentRunResponse.from_view(view)

    @router.get("/{plan_id}/runs", response_model=AgentRunListResponse)
    async def list_runs(
        plan_id: UUID,
        auth: AuthSession = Depends(require_bearer_session),
    ) -> AgentRunListResponse:
        async with session_factory() as session:
            try:
                views = await service(session).list_runs(auth.household_id, plan_id)
            except AgentLifecycleError as error:
                raise _route_lifecycle_error(error) from error
        return AgentRunListResponse(runs=[AgentRunResponse.from_view(view) for view in views])

    @router.get("/{plan_id}/runs/latest", response_model=AgentRunResponse)
    async def latest_run(
        plan_id: UUID,
        auth: AuthSession = Depends(require_bearer_session),
    ) -> AgentRunResponse:
        async with session_factory() as session:
            try:
                view = await service(session).get_latest_run(auth.household_id, plan_id)
            except AgentLifecycleError as error:
                raise _route_lifecycle_error(error) from error
        return AgentRunResponse.from_view(view)

    @router.get("/{plan_id}/runs/{run_id}", response_model=AgentRunResponse)
    async def get_run(
        plan_id: UUID,
        run_id: UUID,
        auth: AuthSession = Depends(require_bearer_session),
    ) -> AgentRunResponse:
        async with session_factory() as session:
            try:
                view = await service(session).get_run(auth.household_id, plan_id, run_id)
            except AgentLifecycleError as error:
                raise _route_lifecycle_error(error) from error
        return AgentRunResponse.from_view(view)

    @router.post("/{plan_id}/runs/{run_id}/cancel", response_model=AgentRunResponse)
    async def cancel_run(
        plan_id: UUID,
        run_id: UUID,
        auth: AuthSession = Depends(require_bearer_session),
    ) -> AgentRunResponse:
        async with session_factory() as session:
            try:
                view = await service(session).cancel_run(
                    CancelAgentRun(
                        household_id=auth.household_id,
                        user_id=auth.user_id,
                        plan_id=plan_id,
                        run_id=run_id,
                    )
                )
            except AgentLifecycleError as error:
                raise _route_lifecycle_error(error) from error
        return AgentRunResponse.from_view(view)

    @router.get("/{plan_id}/runs/{run_id}/results", response_model=AgentRunResultsResponse)
    async def get_run_results(
        plan_id: UUID,
        run_id: UUID,
        auth: AuthSession = Depends(require_bearer_session),
    ) -> AgentRunResultsResponse:
        async with session_factory() as session:
            try:
                view = await service(session).get_run_results(
                    auth.household_id,
                    plan_id,
                    run_id,
                )
            except AgentLifecycleError as error:
                raise _route_lifecycle_error(error) from error
        return AgentRunResultsResponse.from_view(view)

    return router


def _required_idempotency_key(value: str | None) -> str:
    if value is None or not value.strip():
        raise AgentRouteError("idempotency_key_required")
    return value.strip()


def _status_for_error(code: str) -> int:
    return ERROR_STATUS[code]


def _route_lifecycle_error(error: AgentLifecycleError) -> AgentRouteError:
    if error.code not in ERROR_STATUS:
        raise error
    return AgentRouteError(error.code)


def _error_message(code: str) -> str:
    messages = {
        "auth_context_missing": "bearer session is required",
        "idempotency_key_required": "Idempotency-Key header is required",
        "agent_plan_not_found": "agent plan or run was not found",
        "agent_run_not_found": "agent run was not found",
        "agent_plan_invalid_input": "agent plan input is invalid",
    }
    return messages.get(code, "agent lifecycle transition was rejected")
