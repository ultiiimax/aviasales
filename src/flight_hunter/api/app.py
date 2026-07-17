from __future__ import annotations

import hmac
import json
from collections.abc import Callable
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from time import perf_counter
from typing import Literal
from urllib.parse import urlparse
from uuid import UUID, uuid4

from fastapi import FastAPI, Header, HTTPException, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from flight_hunter import __version__
from flight_hunter.agent.chat import (
    AgentAction,
    AgentAuditEvent,
    AgentChatService,
    AgentIntentAdapter,
    AgentRuntimeInfo,
    AgentTurnRequest,
    AgentTurnResponse,
    AirportOption,
)
from flight_hunter.agent.presets import AgentPreset, apply_preset_edits, list_presets
from flight_hunter.api.agent_routes import (
    AgentRouteError,
    agent_lifecycle_route_error,
    agent_route_error_handler,
    agent_validation_error_handler,
    create_agent_router,
)
from flight_hunter.api.agent_schemas import AgentPlanResponse as DurableAgentPlanResponse
from flight_hunter.api.web import (
    render_index_html,
    render_pwa_icon_svg,
    render_service_worker_js,
    render_web_manifest,
)
from flight_hunter.application.agent_intent import IntentParser
from flight_hunter.application.agent_lifecycle import (
    AgentLifecycleError,
    AgentLifecycleService,
    CreateAgentPlan,
)
from flight_hunter.application.agent_planning import AgentPlanBuilder
from flight_hunter.application.agent_scope import ScopeResolver
from flight_hunter.application.airport_service import (
    AirportAutocompleteMatch,
    AirportService,
    NearbyAirport,
)
from flight_hunter.application.booking_actions import (
    BookingActionTokenError,
    decode_booking_ref,
    sign_booking_action_token,
    verify_booking_action_token,
)
from flight_hunter.application.date_matrix import (
    DateMatrix,
    DateMatrixCell,
    DateMatrixDiscoveryContext,
    DateMatrixPlanner,
    DateMatrixRequest,
)
from flight_hunter.application.durable_live_observations import DurableLiveObservationService
from flight_hunter.application.live_observations import BrowserSourceCatalog, GrantSource
from flight_hunter.application.personal_observations import PersonalObservationService
from flight_hunter.application.place_directory import (
    PlaceDirectory,
    PlaceDirectoryError,
    PlaceUnavailableError,
    PlaceUnknownError,
)
from flight_hunter.application.price_sources import PriceSource, PriceSourceCatalog
from flight_hunter.application.provider_registry import ProviderRegistry, ProviderStatus
from flight_hunter.application.search_service import (
    DemoSearchService,
    SearchRequest,
    SearchResult,
    with_browser_observed_offers_and_deal_candidates,
)
from flight_hunter.application.source_contracts import SourceContractCatalog, SourceReadiness
from flight_hunter.application.source_health import (
    SourceHealthEventView,
    SourceHealthItem,
    SourceHealthService,
)
from flight_hunter.application.telegram_notifications import (
    TelegramLinkService,
    TelegramWatchCommandService,
)
from flight_hunter.application.watch_service import (
    CreateWatchCommand,
    UpdateWatchCommand,
    WatchLifecycleCommand,
    WatchService,
)
from flight_hunter.application.worker_health import (
    AgentOperationalHealthItem,
    WorkerControlService,
    WorkerControlState,
    WorkerHealthAlert,
    WorkerHealthItem,
    WorkerHealthService,
    WorkerQueueHealthItem,
    render_worker_health_prometheus,
)
from flight_hunter.browser.html_extractor import (
    BrowserOfferParserPipeline,
    DomSnapshot,
    PriceCandidate,
)
from flight_hunter.config import AppSettings, load_env_file
from flight_hunter.deals import DealDiscoveryService
from flight_hunter.deals.crawl4ai_client import Crawl4AiClientError, Crawl4AiMarkdownClient
from flight_hunter.deals.searxng_client import SearxngClient, SearxngClientError
from flight_hunter.deals.url_policy import DealUrlPolicy, DealUrlPolicyError
from flight_hunter.domain.agent_evidence import (
    ConfirmationState,
    DiscoverySignal,
    DiscoverySource,
)
from flight_hunter.domain.agent_search import DateMode
from flight_hunter.domain.auth import AuthSession, HouseholdRole, new_secret_token, token_hash
from flight_hunter.domain.manual_confirmation import (
    ManualConfirmationStatus,
    ManualPriceConfirmation,
)
from flight_hunter.domain.money import Money
from flight_hunter.domain.observation import BrowserSource, LiveObservation, ObservationStatus
from flight_hunter.domain.offers import (
    FlightOffer,
    FlightSegmentSummary,
    Freshness,
    PriceBasis,
    SearchIntent,
)
from flight_hunter.domain.places import PlaceKind, PlaceLabel, PlaceOption, PlaceRef
from flight_hunter.domain.policy import ExecutionContext
from flight_hunter.domain.ranking import offer_ranking_key
from flight_hunter.domain.search_results import (
    BrowserObservedOffer,
    Confidence,
    DealCandidate,
    ExternalSearchLink,
    FreshnessSummary,
    ResultKind,
)
from flight_hunter.geo.airports import freeze_airport_catalog
from flight_hunter.geo.demo_repository import DemoAirportRepository
from flight_hunter.itinerary_engine.risk import OfferRiskAssessment, assess_offer_risk
from flight_hunter.notifications.telegram import (
    TelegramWebhookDecisionCode,
    TelegramWebhookHandler,
)
from flight_hunter.ops.application_metrics import render_application_metrics
from flight_hunter.ops.structured_logging import log_event
from flight_hunter.persistence.agent_repositories import AgentOperationalHealthRepository
from flight_hunter.persistence.database import create_database_engine, current_alembic_head
from flight_hunter.persistence.repositories import (
    AgentAuditRepository,
    AirportReferenceRepository,
    AirportSearchMatch,
    AuditEventRecord,
    AuditEventRepository,
    BrowserObservationJobRecord,
    BrowserObservationJobRepository,
    BrowserObservedOfferRepository,
    DealCandidateRepository,
    DealDiscoveryJobRecord,
    DealDiscoveryJobRepository,
    HouseholdWatchRepository,
    IdentityRepository,
    LiveObservationRepository,
    ManualPriceConfirmationRepository,
    NewAgentAuditEvent,
    NewAuditEvent,
    NewDealCandidate,
    NewDealDiscoveryJob,
    NewSourceHealthEvent,
    PriceSnapshotRecord,
    PriceSnapshotRepository,
    SourceHealthEventRepository,
    TelegramLinkRepository,
    TelegramNotificationOutboxRepository,
    TelegramUpdateRepository,
    WatchMutationResult,
    WatchRecord,
    WorkerControlRepository,
    WorkerHeartbeatRepository,
    WorkerQueueHealthRepository,
)
from flight_hunter.providers.aviasales_search.adapter import AviasalesSearchAdapter
from flight_hunter.providers.aviasales_search.client import (
    AviasalesSearchAuthFailed,
    AviasalesSearchBlocked,
    AviasalesSearchClient,
    AviasalesSearchError,
    AviasalesSearchRateLimited,
    AviasalesSearchSchemaError,
    validate_calendar_price_rows,
)
from flight_hunter.providers.aviasales_search.mapper import map_calendar_price_to_discovery
from flight_hunter.providers.personal_observer import (
    PersonalObserverConfig,
    PersonalObserverRunner,
    PersonalObserverRunnerAdapter,
    crawl4ai_browser_markdown_provider_from_settings,
)
from flight_hunter.providers.ru_clickout import RuClickoutLinkBuilder, default_ru_aggregator_specs
from flight_hunter.providers.ru_clickout.source_specs import RuAggregatorSpec

_RESULT_KIND_PATTERN = "^(" + "|".join(kind.value for kind in ResultKind) + ")$"
_MANUAL_CONFIRMATION_STATUS_PATTERN = (
    "^(" + "|".join(status.value for status in ManualConfirmationStatus) + ")$"
)
_PRIVACY_EXPORT_LIMITS = {
    "watches": 500,
    "audit_events": 500,
    "manual_price_confirmations": 500,
    "browser_observed_offers": 500,
    "deal_candidates": 500,
}
_PRIVACY_EXPORT_OMITTED_FIELDS = (
    "provider_secrets",
    "raw_payloads",
    "raw_ref",
    "idempotency_keys",
    "session_tokens",
    "telegram_payload_json",
    "worker_queue_payloads",
)
_ACCOUNT_DEACTIVATION_RETAINED_RECORDS = (
    "audit_events",
    "price_history",
    "manual_confirmations",
    "browser_observations",
    "deal_candidates",
)


class HealthResponse(BaseModel):
    app: str
    status: str
    external_credentials_required: bool


class ReadyResponse(BaseModel):
    status: str
    database: str


class BootstrapInvitationRequestBody(BaseModel):
    household_name: str = Field(min_length=1, max_length=160)
    recipient_label: str | None = Field(default=None, max_length=160)
    ttl_hours: int = Field(default=168, ge=1, le=720)


class BootstrapInvitationResponse(BaseModel):
    invitation_id: str
    household_id: str
    invitation_code: str
    expires_at: str


class AcceptInvitationRequestBody(BaseModel):
    invitation_code: str = Field(min_length=16, max_length=200)
    display_name: str = Field(min_length=1, max_length=160)


class AuthSessionResponse(BaseModel):
    session_token: str
    household_id: str
    user_id: str
    role: str
    expires_at: str


class AuthMeResponse(BaseModel):
    household_id: str
    user_id: str
    role: str
    expires_at: str


class AccountDeactivationResponse(BaseModel):
    status: str
    household_id: str
    user_id: str
    sessions_revoked: int
    membership_disabled: bool
    telegram_account_revoked: bool
    owned_watches_deleted: int
    retained_records: list[str]


class ProviderStatusResponse(BaseModel):
    provider_id: str
    enabled: bool
    credentials_present: bool
    access_approved: bool
    data_kind: str
    merge_scope: str
    background_requests_allowed: bool
    user_action_required: bool
    blocked_reasons: list[str]
    notes: str


class ProvidersResponse(BaseModel):
    providers: list[ProviderStatusResponse]


class AdminProviderHealthItemResponse(BaseModel):
    provider_id: str
    enabled: bool
    credentials_present: bool
    secret_present: bool
    access_approved: bool
    data_kind: str
    background_requests_allowed: bool
    blocked_reasons: list[str]


class AdminProviderHealthResponse(BaseModel):
    checked_at: str
    providers: list[AdminProviderHealthItemResponse]


class AdminSourceHealthEventResponse(BaseModel):
    id: str
    event_type: str
    status: str
    message: str
    observed_at: str
    cooldown_until: str | None


class AdminSourceHealthItemResponse(BaseModel):
    source_id: str
    display_name: str
    contract_known: bool
    stage: str | None
    enabled: bool
    data_kind: str | None
    merge_scope: str | None
    background_requests_allowed: bool | None
    user_action_required: bool | None
    blocked_reasons: list[str]
    current_status: str
    latest_event: AdminSourceHealthEventResponse | None


class AdminSourceHealthResponse(BaseModel):
    checked_at: str
    sources_limit: int
    sources_offset: int
    event_limit: int
    sources: list[AdminSourceHealthItemResponse]


class AdminWorkerHealthItemResponse(BaseModel):
    worker_id: str
    role: str
    status: str
    effective_status: str
    current_phase: str
    current_job_kind: str | None
    current_job_id: str | None
    started_at: str
    last_seen_at: str
    stopping_at: str | None
    stopped_at: str | None
    last_summary: dict[str, object]


class AdminWorkerControlResponse(BaseModel):
    drain_requested: bool
    reason: str | None
    requested_at: str | None
    cleared_at: str | None
    updated_at: str | None


class AdminWorkerQueueHealthResponse(BaseModel):
    lane: str
    status_counts: dict[str, int]
    due_count: int
    delayed_count: int
    stale_count: int
    expired_count: int
    oldest_queued_age_seconds: int | None
    oldest_locked_age_seconds: int | None
    warning_level: str


class AdminWorkerHealthAlertResponse(BaseModel):
    severity: str
    code: str
    subject_kind: str
    subject_id: str
    message: str


class AdminAgentOperationalHealthResponse(BaseModel):
    operation_status_counts: dict[str, int]
    run_status_counts: dict[str, int]
    due_operation_count: int
    oldest_due_operation_age_seconds: int | None
    circuit_state_counts: dict[str, int]
    estimated_logical_operations: int
    actual_logical_operations: int
    estimated_http_attempts: int
    actual_http_attempts: int
    confirmed_candidates: int
    provider_denials: int
    terminal_run_count: int
    terminal_run_duration_seconds: float
    recovered_operations: int


class AdminWorkerHealthResponse(BaseModel):
    checked_at: str
    workers_limit: int
    workers_offset: int
    control: AdminWorkerControlResponse
    workers: list[AdminWorkerHealthItemResponse]
    queues: list[AdminWorkerQueueHealthResponse]
    alerts: list[AdminWorkerHealthAlertResponse]
    agent: AdminAgentOperationalHealthResponse


class AdminWorkerControlUpdateRequest(BaseModel):
    drain_requested: bool
    reason: str | None = Field(default=None, max_length=500)


class AdminAuditEventResponse(BaseModel):
    id: str
    actor_user_id: str | None
    action: str
    entity_type: str
    entity_id: str
    summary: str
    created_at: str


class AdminAuditEventsResponse(BaseModel):
    limit: int
    offset: int
    audit_events: list[AdminAuditEventResponse]


class PriceSourceResponse(BaseModel):
    id: str
    name: str
    source_type: str
    price_kind: str
    supports_rub: bool
    in_app_booking: bool
    purchase_flow: str
    requires_manual_confirmation: bool
    setup_required_ru: str
    notes_ru: str


class PriceSourcesResponse(BaseModel):
    strategy: str
    sources: list[PriceSourceResponse]


class SourceContractResponse(BaseModel):
    source_id: str
    display_name: str
    stage: str
    adapter_module: str | None
    contract_file: str
    terms_url: str
    required_env: list[str]
    operations: list[str]
    invariants: list[str]
    egress_policy: list[str]
    notes: str
    enabled: bool
    credentials_present: bool
    access_approved: bool
    data_kind: str
    merge_scope: str
    background_requests_allowed: bool
    user_action_required: bool
    blocked_reasons: list[str]


class SourceContractSummaryResponse(BaseModel):
    total: int
    implemented: int
    policy_skeleton: int
    contract_only: int


class SourceContractsResponse(BaseModel):
    summary: SourceContractSummaryResponse
    sources: list[SourceContractResponse]


class BrowserSourceResponse(BaseModel):
    source_id: str
    display_name: str
    enabled: bool
    permission_status: str
    user_action_required: bool
    background_allowed: bool
    supported_routes: list[str]
    current_health: str


class BrowserSourcesResponse(BaseModel):
    sources: list[BrowserSourceResponse]


class PlaceRefRequest(BaseModel):
    kind: PlaceKind
    code: str = Field(min_length=3, max_length=3)


class PlaceLookupRequestBody(BaseModel):
    locale: str = Field(default="ru", min_length=2, max_length=16)
    places: list[PlaceRefRequest] = Field(default_factory=list, max_length=64)

    @model_validator(mode="after")
    def validate_unique_refs(self) -> PlaceLookupRequestBody:
        refs = tuple(PlaceRef(place.kind, place.code) for place in self.places)
        if len(set(refs)) != len(refs):
            raise ValueError("places must contain unique typed refs")
        return self


class PlaceRefResponse(BaseModel):
    kind: PlaceKind
    code: str


class PlaceLabelResponse(BaseModel):
    text: str
    resolved_locale: str
    provenance: str
    fallback_reason: str | None


class PlaceOptionResponse(BaseModel):
    ref: PlaceRefResponse
    display_name: PlaceLabelResponse
    city_name: PlaceLabelResponse | None
    country_code: str | None
    country_name: PlaceLabelResponse | None
    airport_codes: list[str]
    directory_version: str
    membership_version: str
    membership_observed_at: str


class PlaceLookupErrorResponse(BaseModel):
    code: str
    reason: str


class PlaceLookupItemResponse(BaseModel):
    ref: PlaceRefResponse
    resolved: bool
    display_name: PlaceLabelResponse | None
    city_name: PlaceLabelResponse | None
    country_code: str | None
    country_name: PlaceLabelResponse | None
    airport_codes: list[str]
    directory_version: str | None
    membership_version: str | None
    membership_observed_at: str | None
    error: PlaceLookupErrorResponse | None


class PlaceEnvelopeResponse(BaseModel):
    catalog_status: Literal["ready", "unavailable"]
    enrichment_status: Literal["disabled", "ready", "partial", "unavailable"]
    directory_version: str | None
    items: list[PlaceLookupItemResponse]


class SearchRequestBody(BaseModel):
    origin: str = Field(min_length=3, max_length=3)
    destination: str = Field(min_length=3, max_length=3)
    origin_kind: PlaceKind | None = None
    destination_kind: PlaceKind | None = None
    departure_date: str
    return_date: str | None = None
    passengers: int = Field(ge=1)
    adults: int | None = Field(default=None, ge=1)
    children: int = Field(default=0, ge=0)
    infants: int = Field(default=0, ge=0)
    trip_type: str | None = Field(default=None, pattern="^(one_way|round_trip)$")
    currency: str = Field(min_length=3, max_length=3)
    provider_ids: list[str] | None = None

    @model_validator(mode="after")
    def validate_passenger_mix_and_trip_type(self) -> SearchRequestBody:
        adults = self.adults if self.adults is not None else self.passengers
        if adults + self.children + self.infants != self.passengers:
            raise ValueError("passengers must match adults + children + infants")
        if self.trip_type == "round_trip" and self.return_date is None:
            raise ValueError("round_trip requires return_date")
        if self.trip_type == "one_way" and self.return_date is not None:
            raise ValueError("one_way cannot include return_date")
        return self


class AgentModeResponse(BaseModel):
    enabled: bool
    provider: str
    mcp_enabled: bool
    mcp_server_configured: bool


class AgentPresetResponse(BaseModel):
    id: str
    title_ru: str
    description_ru: str
    required_slots: list[str]
    risk_level: str


class AgentPresetsResponse(BaseModel):
    mode: AgentModeResponse
    presets: list[AgentPresetResponse]


class AgentPlanRequestBody(BaseModel):
    preset_id: str
    slots: dict[str, object] = Field(default_factory=dict)


class AgentChatTurnRequestBody(BaseModel):
    message: str = Field(min_length=1, max_length=2000)
    selected_origin: str | None = Field(default=None, min_length=3, max_length=3)
    selected_destination: str | None = Field(default=None, min_length=3, max_length=3)
    departure_date: date | None = None
    return_date: date | None = None
    date_mode: DateMode | None = None
    passengers: int = Field(default=1, ge=1)
    adults: int | None = Field(default=None, ge=1)
    children: int = Field(default=0, ge=0)
    infants: int = Field(default=0, ge=0)
    currency: str = Field(default="RUB", min_length=3, max_length=3)


class AgentAirportOptionResponse(BaseModel):
    iata_code: str
    label: str
    name: str
    municipality: str
    country_code: str


class AgentActionResponse(BaseModel):
    kind: str
    title_ru: str
    parameters: dict[str, object]
    requires_user_action: bool
    policy_decision: str
    related_id: str | None


class AgentAuditEventResponse(BaseModel):
    event_type: str
    tool_name: str
    summary: str
    policy_decision: str
    related_id: str | None


class AgentRuntimeResponse(BaseModel):
    backend: str
    agentic_loop: str
    model: str | None
    fallback_backend: str | None
    live_calls_allowed: bool
    cloudflare_ready: bool


class AgentChatTurnResponse(BaseModel):
    reply_ru: str
    proposed_plan: DurableAgentPlanResponse
    extracted: dict[str, object]
    missing_slots: list[str]
    airport_options: dict[str, list[AgentAirportOptionResponse]]
    actions: list[AgentActionResponse]
    audit_events: list[AgentAuditEventResponse]
    runtime: AgentRuntimeResponse


class MoneyResponse(BaseModel):
    minor_units: int
    currency: str
    formatted: str


class FlightSegmentSummaryResponse(BaseModel):
    airline_code: str
    airline_name: str | None
    flight_number: str | None
    origin: str
    destination: str
    depart_at: str
    arrive_at: str


class OfferRiskResponse(BaseModel):
    level: str
    flags: list[str]
    explanations: list[str]


class OfferResponse(BaseModel):
    provider_id: str
    provider_offer_id: str
    origin: str
    destination: str
    departure_date: str
    return_date: str | None
    total_price: MoneyResponse
    passengers: int
    price_basis: str
    observed_at: str
    freshness: str
    requires_live_confirmation: bool
    baggage_summary: str | None
    seller_name: str | None
    segments: list[FlightSegmentSummaryResponse]
    booking_action_available: bool
    booking_action_token: str | None
    ranking_reasons: list[str]
    risk: OfferRiskResponse


class BookingResolveRequestBody(BaseModel):
    token: str = Field(min_length=1, max_length=4096)


class BookingResolveResponse(BaseModel):
    status: str
    url: str | None


class AviasalesSuggestItemResponse(BaseModel):
    code: str
    name: str
    place_type: str
    country_code: str | None


class AviasalesSuggestResponse(BaseModel):
    places: list[AviasalesSuggestItemResponse]


class AviasalesHotOfferResponse(BaseModel):
    origin: str
    destination: str
    departure_date: str | None
    return_date: str | None
    amount_minor: int | None
    currency: str | None


class AviasalesHotOffersResponse(BaseModel):
    offers: list[AviasalesHotOfferResponse]


class AviasalesCalendarPriceResponse(BaseModel):
    origin: str
    destination: str
    departure_date: str
    return_date: str | None
    amount_minor: int
    currency: str
    provider_id: Literal["aviasales_search"] = "aviasales_search"
    source_kind: DiscoverySource = DiscoverySource.CALENDAR
    observed_at: datetime
    evidence_kind: Literal["discovery_signal"] = "discovery_signal"
    confirmation_state: ConfirmationState = ConfirmationState.INDICATIVE
    requires_live_confirmation: Literal[True] = True
    passengers: Literal[1] = 1
    price_basis: PriceBasis = PriceBasis.PROVIDER_SINGLE_ADULT_TICKET


class AviasalesCalendarResponse(BaseModel):
    prices: list[AviasalesCalendarPriceResponse]


class AviasalesGraphqlBlockResponse(BaseModel):
    typename: str


class AviasalesGraphqlBlocksResponse(BaseModel):
    blocks: list[AviasalesGraphqlBlockResponse]


class ExternalSearchLinkResponse(BaseModel):
    kind: str
    source_id: str
    source_name: str
    url: str
    origin: str
    destination: str
    departure_date: str
    return_date: str | None
    passengers: int
    adults: int
    children: int
    infants: int
    currency: str
    source_type: str
    purchase_flow: str
    price_known: bool
    requires_external_confirmation: bool
    notes_ru: str | None
    warnings: list[str]


class BrowserObservedOfferResponse(BaseModel):
    kind: str
    observation_id: str
    source_id: str
    source_name: str
    provider_offer_id: str
    origin: str
    destination: str
    departure_date: str | None
    return_date: str | None
    total_price: MoneyResponse | None
    passengers: int
    observed_at: str
    final_url: str
    display_url: str
    freshness: str
    confidence: str
    parser_version: str
    parser_warnings: list[str]
    airline_name: str | None
    airline_iata: str | None
    flight_number: str | None
    departure_time_local: str | None
    arrival_time_local: str | None
    duration_minutes: int | None
    stops: int | None
    baggage_summary: str | None
    seller_name: str | None
    requires_external_confirmation: bool


class BrowserParserTestRequestBody(BaseModel):
    search_intent: SearchRequestBody
    html: str = Field(min_length=1, max_length=500_000)
    final_url: str | None = Field(default=None, max_length=2048)
    title: str | None = Field(default=None, max_length=200)


class BrowserParserPriceCandidateResponse(BaseModel):
    raw_text: str
    amount: MoneyResponse
    accepted: bool
    rejection_reason: str | None


class BrowserParserTestResponse(BaseModel):
    source_id: str
    final_url: str
    captured_at: str
    html_hash: str
    visible_text_hash: str
    confidence: str
    warnings: list[str]
    offers: list[BrowserObservedOfferResponse]
    raw_price_candidates: list[BrowserParserPriceCandidateResponse]


class DealCandidateResponse(BaseModel):
    kind: str
    source_id: str
    url: str
    title: str
    summary_ru: str
    extracted_price: MoneyResponse | None
    extracted_origin: str | None
    extracted_destination: str | None
    extracted_date_window: str | None
    confidence: str
    discovered_at: str
    expires_at: str | None
    requires_manual_verification: bool


class ManualPriceConfirmationRequestBody(BaseModel):
    target_kind: str = Field(pattern=_RESULT_KIND_PATTERN)
    target_id: str = Field(min_length=1, max_length=160)
    source_id: str = Field(min_length=1, max_length=80)
    status: str = Field(pattern=_MANUAL_CONFIRMATION_STATUS_PATTERN)
    amount_minor: int | None = Field(default=None, ge=0)
    currency: str | None = Field(default=None, min_length=3, max_length=3)
    note: str | None = Field(default=None, max_length=500)

    @model_validator(mode="after")
    def validate_price_pair(self) -> ManualPriceConfirmationRequestBody:
        amount_present = self.amount_minor is not None
        currency_present = self.currency is not None
        if amount_present != currency_present:
            raise ValueError("amount_minor and currency must be provided together")
        return self


class ManualPriceConfirmationResponse(BaseModel):
    id: str
    household_id: str
    user_id: str
    target_kind: str
    target_id: str
    source_id: str
    status: str
    confirmed_at: str
    confirmed_price: MoneyResponse | None
    note: str | None


class ManualPriceConfirmationsResponse(BaseModel):
    confirmations: list[ManualPriceConfirmationResponse]


class PrivacyWatchResponse(BaseModel):
    id: str
    household_id: str
    owner_user_id: str
    origin: str
    destination: str
    origin_kind: PlaceKind
    destination_kind: PlaceKind
    origin_airport_codes: list[str]
    destination_airport_codes: list[str]
    directory_version: str
    origin_membership_version: str | None
    destination_membership_version: str | None
    departure_date: str
    return_date: str | None
    passengers: int
    currency: str
    allowed_provider_ids: list[str]
    enabled: bool
    paused_until: str | None
    next_eligible_at: str | None
    scan_interval_seconds: int
    last_scanned_at: str | None
    last_scan_status: str | None
    last_scan_error_code: str | None
    created_at: str
    updated_at: str
    version: int
    archived_at: str | None
    archived_by_user_id: str | None
    deleted_at: str | None
    deleted_by_user_id: str | None


class PrivacyExportResponse(BaseModel):
    format_version: int
    exported_at: str
    household_id: str
    user_id: str
    collection_limits: dict[str, int]
    truncated: dict[str, bool]
    omitted_fields: list[str]
    watches: list[PrivacyWatchResponse]
    audit_events: list[AdminAuditEventResponse]
    manual_price_confirmations: list[ManualPriceConfirmationResponse]
    browser_observed_offers: list[BrowserObservedOfferResponse]
    deal_candidates: list[DealCandidateResponse]


class DealDiscoveryRequestBody(BaseModel):
    search_intent: SearchRequestBody
    limit: int = Field(default=5, ge=1, le=10)
    search_id: str | None = None


class DealDiscoveryResponse(BaseModel):
    candidates: list[DealCandidateResponse]
    warnings: list[str]


class DealDiscoveryJobRequestBody(BaseModel):
    search_id: str = Field(min_length=1, max_length=160)
    search_intent: SearchRequestBody
    limit: int = Field(default=5, ge=1, le=10)


class DealDiscoveryJobCreateResponse(BaseModel):
    job_id: str
    search_id: str
    status: str
    idempotent_replay: bool


class DealDiscoveryJobResponse(BaseModel):
    job_id: str
    search_id: str
    status: str
    attempts: int
    max_attempts: int
    created_at: str
    started_at: str | None
    completed_at: str | None
    next_retry_at: str | None
    deadline_at: str
    result_count: int
    error_code: str | None
    error_message: str | None
    candidates: list[DealCandidateResponse]


class FreshnessSummaryResponse(BaseModel):
    best_price_source: str | None
    freshest_observation_at: str | None
    needs_external_confirmation: bool


class ProviderDenialResponse(BaseModel):
    code: str
    message: str


class RequestedRouteResponse(BaseModel):
    origin: PlaceOptionResponse
    destination: PlaceOptionResponse


class SearchResponse(BaseModel):
    search_id: str
    requested_route: RequestedRouteResponse
    offers: list[OfferResponse]
    priced_offers: list[OfferResponse]
    provider_isolated_offers: list[OfferResponse]
    browser_observed_offers: list[BrowserObservedOfferResponse]
    external_links: list[ExternalSearchLinkResponse]
    deal_candidates: list[DealCandidateResponse]
    denied_providers: dict[str, ProviderDenialResponse]
    warnings: list[str]
    freshness_summary: FreshnessSummaryResponse


class LiveObservationGrantRequestBody(BaseModel):
    source_id: str
    search_intent: SearchRequestBody


class LiveObservationGrantResponse(BaseModel):
    source_id: str
    grant_token: str
    expires_at: str


class LiveObservationCreateRequestBody(BaseModel):
    source_id: str
    search_intent: SearchRequestBody
    grant_token: str


class LiveObservationCreateResponse(BaseModel):
    observation_id: str
    status: str


class LiveObservationResponse(BaseModel):
    observation_id: str
    source_id: str
    status: str
    result_scope: str
    observed_at: str | None
    offers: list[OfferResponse]
    error_code: str | None
    error_message: str | None


class PersonalObservationGrantRequestBody(BaseModel):
    source_id: str
    search_intent: SearchRequestBody


class PersonalObservationGrantResponse(BaseModel):
    source_id: str
    grant_token: str
    expires_at: str


class PersonalObservationCreateRequestBody(BaseModel):
    source_id: str
    search_id: str
    search_intent: SearchRequestBody
    grant_token: str


class PersonalObservationCreateResponse(BaseModel):
    job_id: str
    status: str
    idempotent_replay: bool


class PersonalObservationResponse(BaseModel):
    job_id: str
    source_id: str
    search_id: str
    status: str
    attempts: int
    created_at: str
    started_at: str | None
    waiting_since: str | None
    operator_resume_requested_at: str | None
    operator_abort_requested_at: str | None
    completed_at: str | None
    next_retry_at: str | None
    expires_at: str
    operator_instruction: str | None
    error_code: str | None
    error_message: str | None
    browser_observed_offers: list[BrowserObservedOfferResponse]


class PersonalObservationConfirmRequestBody(BaseModel):
    status: str = Field(
        default=ManualConfirmationStatus.CONFIRMED.value,
        pattern="^(confirmed|price_changed|sold_out|bought)$",
    )
    amount_minor: int | None = Field(default=None, ge=0)
    currency: str | None = Field(default=None, min_length=3, max_length=3)
    note: str | None = Field(default=None, max_length=500)

    @model_validator(mode="after")
    def validate_price_pair(self) -> PersonalObservationConfirmRequestBody:
        amount_present = self.amount_minor is not None
        currency_present = self.currency is not None
        if amount_present != currency_present:
            raise ValueError("amount_minor and currency must be provided together")
        return self


class PersonalObservationMarkStaleRequestBody(BaseModel):
    status: str = Field(
        default=ManualConfirmationStatus.PRICE_CHANGED.value,
        pattern="^(price_changed|sold_out|wrong_route)$",
    )
    note: str | None = Field(default=None, max_length=500)


class AirportAutocompleteItemResponse(BaseModel):
    iata_code: str
    name: str
    municipality: str
    country_code: str
    label: str


class AirportAutocompleteResponse(BaseModel):
    airports: list[AirportAutocompleteItemResponse]


class AirportImportStatusResponse(BaseModel):
    source: str
    imported_at: str | None
    rows_imported: int | None


class AirportSearchResponse(BaseModel):
    airports: list[AirportAutocompleteItemResponse]
    import_status: AirportImportStatusResponse


class NearbyAirportResponse(BaseModel):
    iata_code: str
    name: str
    municipality: str
    country_code: str
    distance_km: int
    transfer_note: str


class NearbyAirportsResponse(BaseModel):
    airports: list[NearbyAirportResponse]


class DateMatrixRequestBody(BaseModel):
    origin: str | None = Field(default=None, min_length=3, max_length=3)
    destination: str | None = Field(default=None, min_length=3, max_length=3)
    departure_date: date
    return_date: date | None = None
    flexibility_days: int = Field(ge=0, le=7)
    min_stay_days: int | None = Field(default=None, ge=0)
    max_stay_days: int | None = Field(default=None, ge=0)
    passengers: int = Field(default=1, ge=1)
    adults: int | None = Field(default=None, ge=1)
    children: int = Field(default=0, ge=0)
    infants: int = Field(default=0, ge=0)
    currency: str = Field(default="RUB", min_length=3, max_length=3)
    provider_ids: list[str] | None = None

    @model_validator(mode="after")
    def validate_passenger_total(self) -> DateMatrixRequestBody:
        adults = self.adults if self.adults is not None else self.passengers
        if adults + self.children + self.infants != self.passengers:
            raise ValueError("passengers must match adults + children + infants")
        return self


class DateMatrixCellResponse(BaseModel):
    departure_date: str
    return_date: str | None
    stay_days: int | None
    amount_minor: int | None = None
    currency: str | None = None
    provider_id: str | None = None
    source_kind: DiscoverySource | None = None
    freshness: str | None = None
    observed_at: str | None = None
    evidence_kind: Literal["discovery_signal"] | None = None
    confirmation_state: ConfirmationState | None = None
    requires_live_confirmation: bool | None = None
    passengers: int | None = None
    price_basis: PriceBasis | None = None


class DateMatrixResponse(BaseModel):
    cells: list[DateMatrixCellResponse]
    provider_calls_required: int
    priced: bool
    pricing_denials: list[str] = Field(default_factory=list)


class TelegramWebhookResponse(BaseModel):
    code: str
    status: str


class TelegramLinkCodeResponse(BaseModel):
    code: str
    expires_at: str


class WatchCreateRequestBody(BaseModel):
    origin: str = Field(min_length=3, max_length=3)
    destination: str = Field(min_length=3, max_length=3)
    origin_kind: PlaceKind | None = None
    destination_kind: PlaceKind | None = None
    departure_date: str
    return_date: str | None = None
    passengers: int = Field(default=1, ge=1)
    currency: str = Field(default="RUB", min_length=3, max_length=3)
    allowed_provider_ids: list[str] = Field(default_factory=list)


class WatchUpdateRequestBody(BaseModel):
    expected_version: int = Field(ge=1)
    origin: str | None = Field(default=None, min_length=3, max_length=3)
    destination: str | None = Field(default=None, min_length=3, max_length=3)
    origin_kind: PlaceKind | None = None
    destination_kind: PlaceKind | None = None
    departure_date: str | None = None
    return_date: str | None = None
    passengers: int | None = Field(default=None, ge=1)
    currency: str | None = Field(default=None, min_length=3, max_length=3)
    allowed_provider_ids: list[str] | None = None
    enabled: bool | None = None
    paused_until: datetime | None = None
    scan_interval_seconds: int | None = Field(default=None, ge=300)


class WatchPauseRequestBody(BaseModel):
    paused_until: datetime | None = None


class WatchVersionRequestBody(BaseModel):
    expected_version: int = Field(ge=1)


class WatchResponse(BaseModel):
    id: str
    household_id: str
    owner_user_id: str
    origin: str
    destination: str
    origin_kind: PlaceKind
    destination_kind: PlaceKind
    origin_airport_codes: list[str]
    destination_airport_codes: list[str]
    directory_version: str
    origin_membership_version: str | None
    destination_membership_version: str | None
    departure_date: str
    return_date: str | None
    passengers: int
    currency: str
    allowed_provider_ids: list[str]
    enabled: bool
    paused_until: str | None
    next_eligible_at: str | None
    scan_interval_seconds: int
    last_scanned_at: str | None
    last_scan_status: str | None
    last_scan_error_code: str | None
    created_at: str
    updated_at: str
    version: int
    archived_at: str | None
    deleted_at: str | None


class WatchLifecycleResponse(BaseModel):
    watch_id: str
    status: str
    version: int


class WatchesResponse(BaseModel):
    watches: list[WatchResponse]


class WatchPriceSnapshotResponse(BaseModel):
    provider_id: str
    itinerary_fingerprint: str
    observed_at: str
    amount_minor: int
    currency: str
    freshness: str
    requires_live_confirmation: bool


class WatchHistoryResponse(BaseModel):
    watch_id: str
    snapshots: list[WatchPriceSnapshotResponse]


def create_app(
    *,
    watch_session_factory: async_sessionmaker[AsyncSession] | None = None,
    settings: AppSettings | None = None,
    agent_intent_adapter: AgentIntentAdapter | None = None,
    deal_discovery_service: DealDiscoveryService | None = None,
    provider_instances: dict[str, AviasalesSearchAdapter] | None = None,
    agent_provider_gateway: object | None = None,
) -> FastAPI:
    load_env_file()
    settings = settings or AppSettings.from_env()
    app = FastAPI(title="Flight Hunter", version=__version__)
    registry = ProviderRegistry.default(clock=lambda: datetime.now(UTC), settings=settings)
    provider_instances = (
        provider_instances if provider_instances is not None else _provider_instances(settings)
    )
    search_service = DemoSearchService(
        registry=registry,
        clock=lambda: datetime.now(UTC),
        providers=provider_instances,
        enabled_external_source_ids=settings.ru_clickout_enabled_source_ids,
    )
    airport_service = AirportService(repository=DemoAirportRepository())
    date_matrix_planner = DateMatrixPlanner()
    price_source_catalog = PriceSourceCatalog.default()
    source_contract_catalog = SourceContractCatalog.default(settings=settings, registry=registry)
    browser_source_catalog = BrowserSourceCatalog.demo(
        enabled=settings.scraping_observer_enabled,
        clock=lambda: datetime.now(UTC),
    )
    telegram_webhook_handler = TelegramWebhookHandler(
        enabled=settings.telegram_enabled,
        secret_token=settings.telegram_webhook_secret,
    )
    session_factory = watch_session_factory or _watch_session_factory(settings.database_url)
    demo_place_directory = PlaceDirectory.from_snapshot(
        freeze_airport_catalog(DemoAirportRepository().all())
    )

    async def request_place_directory() -> PlaceDirectory:
        try:
            async with session_factory() as session:
                repository = AirportReferenceRepository(session)
                if await repository.latest_import_run() is not None:
                    return PlaceDirectory.from_snapshot(await repository.catalog_snapshot())
        except (SQLAlchemyError, TypeError, ValueError) as error:
            raise PlaceUnavailableError("catalog_read_failed", code="catalog") from error
        return demo_place_directory

    async def request_search_places(
        body: SearchRequestBody,
    ) -> tuple[PlaceDirectory, PlaceOption, PlaceOption]:
        directory = await request_place_directory()
        requested_origin = _resolve_request_place(
            directory,
            code=body.origin,
            kind=body.origin_kind,
            locale="ru",
        )
        requested_destination = _resolve_request_place(
            directory,
            code=body.destination,
            kind=body.destination_kind,
            locale="ru",
        )
        return directory, requested_origin, requested_destination

    async def request_search_intent(body: SearchRequestBody) -> SearchIntent:
        directory, requested_origin, requested_destination = await request_search_places(body)
        return _search_intent_from_body(
            body,
            directory=directory,
            requested_origin=requested_origin,
            requested_destination=requested_destination,
        )

    def agent_lifecycle_service(session: AsyncSession) -> AgentLifecycleService:
        resolver = ScopeResolver(repository=AirportReferenceRepository(session))

        def lifecycle_clock() -> datetime:
            return datetime.now(UTC)

        return AgentLifecycleService(
            session=session,
            parser=IntentParser(),
            builder=AgentPlanBuilder(
                clock=lifecycle_clock,
                settings=settings,
                scope_resolver=resolver,
            ),
            clock=lifecycle_clock,
            provider_gateway=agent_provider_gateway,
            booking_action_secret=settings.app_secret_key,
        )

    app.add_exception_handler(AgentRouteError, agent_route_error_handler)
    app.add_exception_handler(RequestValidationError, agent_validation_error_handler)
    app.add_exception_handler(PlaceDirectoryError, place_directory_error_handler)
    app.include_router(
        create_agent_router(
            session_factory=session_factory,
            provider_gateway=agent_provider_gateway,
            settings=settings,
        )
    )

    @app.get("/", response_class=HTMLResponse)
    def index() -> HTMLResponse:
        return HTMLResponse(render_index_html())

    @app.get("/manifest.webmanifest", response_class=JSONResponse)
    def web_manifest() -> JSONResponse:
        return JSONResponse(
            render_web_manifest(),
            media_type="application/manifest+json",
        )

    @app.get("/pwa-icon.svg", response_class=PlainTextResponse)
    def pwa_icon() -> PlainTextResponse:
        return PlainTextResponse(
            render_pwa_icon_svg(),
            media_type="image/svg+xml",
        )

    @app.get("/service-worker.js", response_class=PlainTextResponse)
    def service_worker() -> PlainTextResponse:
        return PlainTextResponse(
            render_service_worker_js(),
            media_type="application/javascript",
        )

    @app.get("/healthz", response_model=HealthResponse)
    def healthz() -> HealthResponse:
        return HealthResponse(
            app="Flight Hunter",
            status="ok",
            external_credentials_required=False,
        )

    @app.get("/readyz", response_model=ReadyResponse)
    async def readyz() -> ReadyResponse | JSONResponse:
        try:
            async with session_factory() as session:
                await session.execute(text("SELECT 1"))
        except SQLAlchemyError:
            return _coded_error_response(
                status_code=503,
                code="database_unavailable",
                message="database is unavailable",
            )
        try:
            async with session_factory() as session:
                revision = (
                    await session.execute(text("SELECT version_num FROM alembic_version"))
                ).scalar_one()
        except SQLAlchemyError:
            return _coded_error_response(
                status_code=503,
                code="migration_pending",
                message="database migration is pending",
            )
        if revision != current_alembic_head():
            return _coded_error_response(
                status_code=503,
                code="migration_pending",
                message="database migration is pending",
            )
        return ReadyResponse(status="ready", database="ok")

    @app.get("/api/v1/metrics", response_class=PlainTextResponse)
    async def application_metrics() -> PlainTextResponse:
        async with session_factory() as session:
            durable_snapshot = await WorkerHealthService(
                heartbeats=WorkerHeartbeatRepository(session),
                queues=WorkerQueueHealthRepository(session),
                control=WorkerControlRepository(session),
                agent_health=AgentOperationalHealthRepository(session),
            ).snapshot()
        return PlainTextResponse(
            render_application_metrics() + render_worker_health_prometheus(durable_snapshot),
            media_type="text/plain; version=0.0.4",
        )

    @app.post(
        "/api/v1/auth/bootstrap-invitation",
        response_model=BootstrapInvitationResponse,
        status_code=201,
    )
    async def bootstrap_invitation(
        body: BootstrapInvitationRequestBody,
        bootstrap_header: str | None = Header(
            default=None,
            alias="X-Flight-Hunter-Bootstrap-Token",
        ),
    ) -> BootstrapInvitationResponse | JSONResponse:
        if settings.auth_bootstrap_token is None:
            return _coded_error_response(
                status_code=403,
                code="auth_bootstrap_disabled",
                message="bootstrap invitation creation is disabled",
            )
        if bootstrap_header is None or not hmac.compare_digest(
            bootstrap_header,
            settings.auth_bootstrap_token,
        ):
            return _coded_error_response(
                status_code=403,
                code="auth_bootstrap_denied",
                message="bootstrap token is invalid",
            )
        now = datetime.now(UTC)
        household_id = uuid4()
        invitation_id = uuid4()
        invitation_code = new_secret_token()
        expires_at = now + timedelta(hours=body.ttl_hours)
        async with session_factory() as session:
            repository = IdentityRepository(session)
            await repository.add_household(
                household_id=household_id,
                name=body.household_name.strip(),
                created_at=now,
            )
            await repository.add_invitation(
                invitation_id=invitation_id,
                household_id=household_id,
                role=HouseholdRole.OWNER,
                code_hash=token_hash(invitation_code),
                recipient_label=body.recipient_label.strip()
                if body.recipient_label is not None
                else None,
                created_at=now,
                expires_at=expires_at,
            )
            await session.commit()
        return BootstrapInvitationResponse(
            invitation_id=str(invitation_id),
            household_id=str(household_id),
            invitation_code=invitation_code,
            expires_at=expires_at.isoformat(),
        )

    @app.post(
        "/api/v1/auth/accept-invitation",
        response_model=AuthSessionResponse,
        status_code=201,
    )
    async def accept_invitation(
        body: AcceptInvitationRequestBody,
    ) -> AuthSessionResponse | JSONResponse:
        now = datetime.now(UTC)
        user_id = uuid4()
        session_id = uuid4()
        session_token = new_secret_token()
        session_expires_at = now + timedelta(
            seconds=max(settings.auth_session_ttl_seconds, 60),
        )
        async with session_factory() as session:
            repository = IdentityRepository(session)
            invitation = await repository.invitation_by_code_hash(token_hash(body.invitation_code))
            if (
                invitation is None
                or invitation.expires_at <= now
                or invitation.accepted_at is not None
                or invitation.revoked_at is not None
            ):
                return _coded_error_response(
                    status_code=403,
                    code="invitation_invalid",
                    message="invitation is invalid or expired",
                )
            await repository.add_user(
                user_id=user_id,
                display_name=body.display_name.strip(),
                created_at=now,
            )
            await repository.add_membership(
                household_id=invitation.household_id,
                user_id=user_id,
                role=invitation.role,
                created_at=now,
            )
            accepted = await repository.mark_invitation_accepted(
                invitation_id=invitation.id,
                accepted_by_user_id=user_id,
                accepted_at=now,
            )
            if not accepted:
                return _coded_error_response(
                    status_code=403,
                    code="invitation_invalid",
                    message="invitation is invalid or expired",
                )
            await repository.add_session(
                session_id=session_id,
                household_id=invitation.household_id,
                user_id=user_id,
                token_hash=token_hash(session_token),
                created_at=now,
                expires_at=session_expires_at,
            )
            await session.commit()
        return AuthSessionResponse(
            session_token=session_token,
            household_id=str(invitation.household_id),
            user_id=str(user_id),
            role=invitation.role.value,
            expires_at=session_expires_at.isoformat(),
        )

    @app.get("/api/v1/auth/me", response_model=AuthMeResponse)
    async def auth_me(
        authorization_header: str | None = Header(default=None, alias="Authorization"),
    ) -> AuthMeResponse | JSONResponse:
        async with session_factory() as session:
            auth_session = await _auth_session_from_authorization(
                session,
                authorization_header,
            )
        if auth_session is None:
            return _auth_context_missing_response()
        return _auth_me_response(auth_session)

    @app.delete("/api/v1/account", response_model=AccountDeactivationResponse)
    async def delete_account(
        authorization_header: str | None = Header(default=None, alias="Authorization"),
    ) -> AccountDeactivationResponse | JSONResponse:
        async with session_factory() as session:
            auth_session = await _auth_session_from_authorization(session, authorization_header)
            if auth_session is None:
                return _auth_context_missing_response()
            now = datetime.now(UTC)
            household_id = auth_session.household_id
            user_id = auth_session.user_id
            identity = IdentityRepository(session)
            watches = HouseholdWatchRepository(session)
            audit = AuditEventRepository(session)
            owned_watches = await watches.list_active_watches_for_owner(
                household_id=household_id,
                owner_user_id=user_id,
            )
            owned_watches_deleted = 0
            for watch in owned_watches:
                result = await watches.delete_watch(
                    household_id=household_id,
                    watch_id=watch.id,
                    expected_version=watch.version,
                    deleted_at=now,
                    deleted_by_user_id=user_id,
                )
                if result.status != "deleted":
                    continue
                owned_watches_deleted += 1
                await audit.add_event(
                    NewAuditEvent(
                        id=uuid4(),
                        household_id=household_id,
                        actor_user_id=user_id,
                        action="watch.deleted",
                        entity_type="watch",
                        entity_id=watch.id,
                        summary="watch deleted by account deactivation",
                        created_at=now,
                    )
                )
            sessions_revoked = await identity.revoke_sessions(
                household_id=household_id,
                user_id=user_id,
                revoked_at=now,
            )
            membership_disabled = await identity.disable_membership(
                household_id=household_id,
                user_id=user_id,
                disabled_at=now,
            )
            telegram_account_revoked = await TelegramLinkRepository(
                session
            ).revoke_account_for_user(
                household_id=household_id,
                user_id=user_id,
                revoked_at=now,
            )
            await audit.add_event(
                NewAuditEvent(
                    id=uuid4(),
                    household_id=household_id,
                    actor_user_id=user_id,
                    action="account.deactivated",
                    entity_type="user",
                    entity_id=user_id,
                    summary="account deactivated",
                    created_at=now,
                )
            )
            await session.commit()
        return AccountDeactivationResponse(
            status="deactivated",
            household_id=str(household_id),
            user_id=str(user_id),
            sessions_revoked=sessions_revoked,
            membership_disabled=membership_disabled,
            telegram_account_revoked=telegram_account_revoked,
            owned_watches_deleted=owned_watches_deleted,
            retained_records=list(_ACCOUNT_DEACTIVATION_RETAINED_RECORDS),
        )

    @app.post("/api/v1/privacy/export", response_model=PrivacyExportResponse)
    async def privacy_export(
        authorization_header: str | None = Header(default=None, alias="Authorization"),
        household_header: str | None = Header(
            default=None,
            alias="X-Flight-Hunter-Household-Id",
        ),
        user_header: str | None = Header(
            default=None,
            alias="X-Flight-Hunter-User-Id",
        ),
    ) -> PrivacyExportResponse | JSONResponse:
        async with session_factory() as session:
            auth_context = await _auth_context_from_headers(
                session,
                settings=settings,
                authorization_header=authorization_header,
                household_header=household_header,
                user_header=user_header,
            )
            if auth_context is None:
                return _auth_context_missing_response()
            household_id, user_id = auth_context
            watches = await HouseholdWatchRepository(session).list_watches_for_export(
                household_id,
                limit=_privacy_export_fetch_limit("watches"),
            )
            audit_events = await AuditEventRepository(session).list_recent(
                household_id,
                limit=_privacy_export_fetch_limit("audit_events"),
            )
            manual_confirmations = await ManualPriceConfirmationRepository(session).list_for_export(
                household_id=household_id,
                user_id=user_id,
                limit=_privacy_export_fetch_limit("manual_price_confirmations"),
            )
            observed_offers = await BrowserObservedOfferRepository(session).list_for_export(
                household_id=household_id,
                user_id=user_id,
                limit=_privacy_export_fetch_limit("browser_observed_offers"),
            )
            deal_candidates = await DealCandidateRepository(session).list_for_export(
                household_id=household_id,
                user_id=user_id,
                limit=_privacy_export_fetch_limit("deal_candidates"),
            )
            exported_at = datetime.now(UTC)
            await AuditEventRepository(session).add_event(
                NewAuditEvent(
                    id=uuid4(),
                    household_id=household_id,
                    actor_user_id=user_id,
                    action="privacy.exported",
                    entity_type="household",
                    entity_id=household_id,
                    summary="privacy export generated",
                    created_at=exported_at,
                )
            )
            await session.commit()
        return _privacy_export_response(
            exported_at=exported_at,
            household_id=household_id,
            user_id=user_id,
            watches=watches,
            audit_events=audit_events,
            manual_confirmations=manual_confirmations,
            observed_offers=observed_offers,
            deal_candidates=deal_candidates,
        )

    @app.get("/api/v1/providers", response_model=ProvidersResponse)
    def providers() -> ProvidersResponse:
        return ProvidersResponse(
            providers=[_provider_status_response(status) for status in registry.statuses()]
        )

    @app.get("/api/v1/admin/providers/health", response_model=AdminProviderHealthResponse)
    def admin_provider_health() -> AdminProviderHealthResponse:
        return AdminProviderHealthResponse(
            checked_at=datetime.now(UTC).isoformat(),
            providers=[_admin_provider_health_response(status) for status in registry.statuses()],
        )

    @app.get("/api/v1/admin/sources/health", response_model=AdminSourceHealthResponse)
    async def admin_source_health(
        sources_limit: int = Query(default=100, ge=1, le=500),
        sources_offset: int = Query(default=0, ge=0, le=10_000),
        event_limit: int = Query(default=100, ge=1, le=500),
    ) -> AdminSourceHealthResponse:
        async with session_factory() as session:
            snapshot = await SourceHealthService(
                contracts=source_contract_catalog,
                events=SourceHealthEventRepository(session),
            ).snapshot(event_limit=event_limit)
        sources_window = snapshot.sources[sources_offset : sources_offset + sources_limit]
        return AdminSourceHealthResponse(
            checked_at=snapshot.checked_at.isoformat(),
            sources_limit=sources_limit,
            sources_offset=sources_offset,
            event_limit=event_limit,
            sources=[_admin_source_health_item_response(source) for source in sources_window],
        )

    @app.get("/api/v1/admin/workers/health", response_model=AdminWorkerHealthResponse)
    async def admin_worker_health(
        workers_limit: int = Query(default=20, ge=1, le=100),
        workers_offset: int = Query(default=0, ge=0, le=10_000),
    ) -> AdminWorkerHealthResponse:
        async with session_factory() as session:
            snapshot = await WorkerHealthService(
                heartbeats=WorkerHeartbeatRepository(session),
                queues=WorkerQueueHealthRepository(session),
                control=WorkerControlRepository(session),
                agent_health=AgentOperationalHealthRepository(session),
            ).snapshot(limit=workers_limit, offset=workers_offset)
        return AdminWorkerHealthResponse(
            checked_at=snapshot.checked_at.isoformat(),
            workers_limit=workers_limit,
            workers_offset=workers_offset,
            control=_admin_worker_control_response(snapshot.control),
            workers=[_admin_worker_health_item_response(worker) for worker in snapshot.workers],
            queues=[_admin_worker_queue_health_response(queue) for queue in snapshot.queues],
            alerts=[_admin_worker_health_alert_response(alert) for alert in snapshot.alerts],
            agent=_admin_agent_operational_health_response(snapshot.agent),
        )

    @app.get("/api/v1/admin/workers/metrics", response_class=PlainTextResponse)
    async def admin_worker_metrics(
        workers_limit: int = Query(default=20, ge=1, le=100),
        workers_offset: int = Query(default=0, ge=0, le=10_000),
    ) -> PlainTextResponse:
        async with session_factory() as session:
            snapshot = await WorkerHealthService(
                heartbeats=WorkerHeartbeatRepository(session),
                queues=WorkerQueueHealthRepository(session),
                control=WorkerControlRepository(session),
                agent_health=AgentOperationalHealthRepository(session),
            ).snapshot(limit=workers_limit, offset=workers_offset)
        return PlainTextResponse(
            render_worker_health_prometheus(snapshot),
            media_type="text/plain; version=0.0.4",
        )

    @app.patch("/api/v1/admin/workers/control", response_model=AdminWorkerControlResponse)
    async def update_admin_worker_control(
        body: AdminWorkerControlUpdateRequest,
        authorization_header: str | None = Header(default=None, alias="Authorization"),
        household_header: str | None = Header(
            default=None,
            alias="X-Flight-Hunter-Household-Id",
        ),
        user_header: str | None = Header(
            default=None,
            alias="X-Flight-Hunter-User-Id",
        ),
    ) -> AdminWorkerControlResponse | JSONResponse:
        async with session_factory() as session:
            auth_context = await _auth_context_from_headers(
                session,
                settings=settings,
                authorization_header=authorization_header,
                household_header=household_header,
                user_header=user_header,
            )
            if auth_context is None:
                return _auth_context_missing_response()
            household_id, user_id = auth_context
            state = await WorkerControlService(
                control=WorkerControlRepository(session),
                audit=AuditEventRepository(session),
            ).set_drain(
                drain_requested=body.drain_requested,
                reason=body.reason,
                actor_household_id=household_id,
                actor_user_id=user_id,
            )
            await session.commit()
        return _admin_worker_control_response(state)

    @app.get("/api/v1/admin/audit-events", response_model=AdminAuditEventsResponse)
    async def admin_audit_events(
        limit: int = Query(default=50, ge=1, le=200),
        offset: int = Query(default=0, ge=0, le=10_000),
        authorization_header: str | None = Header(default=None, alias="Authorization"),
        household_header: str | None = Header(
            default=None,
            alias="X-Flight-Hunter-Household-Id",
        ),
        user_header: str | None = Header(
            default=None,
            alias="X-Flight-Hunter-User-Id",
        ),
    ) -> AdminAuditEventsResponse | JSONResponse:
        async with session_factory() as session:
            auth_context = await _auth_context_from_headers(
                session,
                settings=settings,
                authorization_header=authorization_header,
                household_header=household_header,
                user_header=user_header,
            )
            if auth_context is None:
                return _auth_context_missing_response()
            household_id, _user_id = auth_context
            recent_events = await AuditEventRepository(session).list_recent(
                household_id,
                limit=limit,
                offset=offset,
            )
        return AdminAuditEventsResponse(
            limit=limit,
            offset=offset,
            audit_events=[_admin_audit_event_response(event) for event in recent_events],
        )

    @app.get("/api/v1/price-sources", response_model=PriceSourcesResponse)
    def price_sources() -> PriceSourcesResponse:
        return PriceSourcesResponse(
            strategy="external_clickout",
            sources=[_price_source_response(source) for source in price_source_catalog.sources],
        )

    @app.get("/api/v1/source-contracts", response_model=SourceContractsResponse)
    def source_contracts() -> SourceContractsResponse:
        sources = source_contract_catalog.readiness()
        return SourceContractsResponse(
            summary=_source_contract_summary_response(sources),
            sources=[_source_contract_response(source) for source in sources],
        )

    @app.post("/api/v1/deals/discover", response_model=DealDiscoveryResponse)
    async def discover_deals(
        body: DealDiscoveryRequestBody,
        authorization_header: str | None = Header(default=None, alias="Authorization"),
        household_header: str | None = Header(
            default=None,
            alias="X-Flight-Hunter-Household-Id",
        ),
        user_header: str | None = Header(
            default=None,
            alias="X-Flight-Hunter-User-Id",
        ),
    ) -> DealDiscoveryResponse | JSONResponse:
        service = deal_discovery_service or _deal_discovery_service(settings)
        if service is None:
            return _coded_error_response(
                status_code=503,
                code="deal_discovery_disabled",
                message="deal discovery requires enabled SearXNG and Crawl4AI settings",
            )
        try:
            candidates = await service.discover(
                await request_search_intent(body.search_intent),
                limit=body.limit,
            )
        except DealUrlPolicyError as exc:
            await _try_record_source_health_event(
                session_factory,
                source_id="deal_discovery",
                event_type="deal_discovery",
                status="failed",
                message=f"deal discovery URL rejected; code={exc}",
            )
            return _coded_error_response(
                status_code=502,
                code="deal_discovery_url_rejected",
                message="deal discovery rejected an unsafe source URL",
            )
        except (Crawl4AiClientError, SearxngClientError) as exc:
            await _try_record_source_health_event(
                session_factory,
                source_id="deal_discovery",
                event_type="deal_discovery",
                status="failed",
                message=f"deal discovery failed; code={exc}",
            )
            return _coded_error_response(
                status_code=502,
                code="deal_discovery_source_failed",
                message="deal discovery source failed",
            )
        expires_at = datetime.now(UTC) + timedelta(
            seconds=max(1, settings.deal_candidate_ttl_seconds),
        )
        candidates = tuple(replace(candidate, expires_at=expires_at) for candidate in candidates)
        await _try_record_source_health_event(
            session_factory,
            source_id="deal_discovery",
            event_type="deal_discovery",
            status="ok",
            message=f"deal discovery succeeded; candidates={len(candidates)}",
        )
        if body.search_id and _auth_headers_present(
            settings=settings,
            authorization_header=authorization_header,
            household_header=household_header,
            user_header=user_header,
        ):
            async with session_factory() as session:
                auth_context = await _optional_auth_context_from_headers(
                    session,
                    settings=settings,
                    authorization_header=authorization_header,
                    household_header=household_header,
                    user_header=user_header,
                )
                if auth_context is not None:
                    household_id, user_id = auth_context
                    repository = DealCandidateRepository(session)
                    for candidate in candidates:
                        await repository.add_candidate(
                            NewDealCandidate(
                                id=uuid4(),
                                household_id=household_id,
                                user_id=user_id,
                                search_id=body.search_id,
                                candidate=candidate,
                                expires_at=expires_at,
                            )
                        )
                    await session.commit()
        return DealDiscoveryResponse(
            candidates=[_deal_candidate_response(candidate) for candidate in candidates],
            warnings=["deal_candidates_require_manual_verification"],
        )

    @app.post(
        "/api/v1/deals/discovery-jobs",
        response_model=DealDiscoveryJobCreateResponse,
        status_code=202,
    )
    async def create_deal_discovery_job(
        body: DealDiscoveryJobRequestBody,
        authorization_header: str | None = Header(default=None, alias="Authorization"),
        household_header: str | None = Header(
            default=None,
            alias="X-Flight-Hunter-Household-Id",
        ),
        user_header: str | None = Header(
            default=None,
            alias="X-Flight-Hunter-User-Id",
        ),
        idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    ) -> DealDiscoveryJobCreateResponse | JSONResponse:
        if idempotency_key is None or not idempotency_key.strip():
            return _coded_error_response(
                status_code=400,
                code="idempotency_key_required",
                message="Idempotency-Key header is required",
            )
        async with session_factory() as session:
            auth_context = await _auth_context_from_headers(
                session,
                settings=settings,
                authorization_header=authorization_header,
                household_header=household_header,
                user_header=user_header,
            )
            if auth_context is None:
                return _auth_context_missing_response()
            if deal_discovery_service is None and (
                not settings.searxng_enabled or not settings.crawl4ai_enabled
            ):
                return _coded_error_response(
                    status_code=503,
                    code="deal_discovery_disabled",
                    message="deal discovery requires enabled SearXNG and Crawl4AI settings",
                )
            intent = await request_search_intent(body.search_intent)
            household_id, user_id = auth_context
            repository = DealDiscoveryJobRepository(session)
            scoped_idempotency_key = _scoped_idempotency_key(
                "deal_discovery",
                household_id=household_id,
                user_id=user_id,
                idempotency_key=idempotency_key,
            )
            existing = await repository.get_idempotent_job(
                household_id=household_id,
                user_id=user_id,
                idempotency_key=scoped_idempotency_key,
            )
            if existing is not None:
                return DealDiscoveryJobCreateResponse(
                    job_id=str(existing.id),
                    search_id=existing.search_id,
                    status=existing.status,
                    idempotent_replay=True,
                )
            now = datetime.now(UTC)
            job = NewDealDiscoveryJob(
                id=uuid4(),
                household_id=household_id,
                user_id=user_id,
                search_id=body.search_id,
                idempotency_key=scoped_idempotency_key,
                status="queued",
                attempts=0,
                max_attempts=3,
                deadline_at=now
                + timedelta(seconds=max(1, settings.deal_discovery_job_deadline_seconds)),
                created_at=now,
                search_intent_json=_deal_search_intent_json(intent),
                limit=body.limit,
            )
            created = await repository.enqueue_job(job)
            if not created:
                existing = await repository.get_idempotent_job(
                    household_id=household_id,
                    user_id=user_id,
                    idempotency_key=scoped_idempotency_key,
                )
                if existing is not None:
                    return DealDiscoveryJobCreateResponse(
                        job_id=str(existing.id),
                        search_id=existing.search_id,
                        status=existing.status,
                        idempotent_replay=True,
                    )
                return _coded_error_response(
                    status_code=409,
                    code="deal_discovery_job_conflict",
                    message="deal discovery job idempotency conflict",
                )
            await session.commit()
        return DealDiscoveryJobCreateResponse(
            job_id=str(job.id),
            search_id=job.search_id,
            status=job.status,
            idempotent_replay=False,
        )

    @app.get(
        "/api/v1/deals/discovery-jobs/{job_id}",
        response_model=DealDiscoveryJobResponse,
    )
    async def get_deal_discovery_job(
        job_id: UUID,
        authorization_header: str | None = Header(default=None, alias="Authorization"),
        household_header: str | None = Header(
            default=None,
            alias="X-Flight-Hunter-Household-Id",
        ),
        user_header: str | None = Header(
            default=None,
            alias="X-Flight-Hunter-User-Id",
        ),
    ) -> DealDiscoveryJobResponse | JSONResponse:
        async with session_factory() as session:
            auth_context = await _auth_context_from_headers(
                session,
                settings=settings,
                authorization_header=authorization_header,
                household_header=household_header,
                user_header=user_header,
            )
            if auth_context is None:
                return _auth_context_missing_response()
            household_id, user_id = auth_context
            job = await DealDiscoveryJobRepository(session).get_job(job_id)
            if job is None or job.household_id != household_id or job.user_id != user_id:
                return _coded_error_response(
                    status_code=404,
                    code="deal_discovery_job_not_found",
                    message="deal discovery job not found",
                )
            candidates = await DealCandidateRepository(session).list_recent(
                household_id=household_id,
                user_id=user_id,
                search_id=job.search_id,
                now=datetime.now(UTC),
            )
        return _deal_discovery_job_response(job, candidates)

    @app.post(
        "/api/v1/manual-price-confirmations",
        response_model=ManualPriceConfirmationResponse,
        status_code=201,
    )
    async def create_manual_price_confirmation(
        body: ManualPriceConfirmationRequestBody,
        authorization_header: str | None = Header(default=None, alias="Authorization"),
        household_header: str | None = Header(
            default=None,
            alias="X-Flight-Hunter-Household-Id",
        ),
        user_header: str | None = Header(
            default=None,
            alias="X-Flight-Hunter-User-Id",
        ),
    ) -> ManualPriceConfirmationResponse | JSONResponse:
        price = (
            Money(body.amount_minor, body.currency)
            if body.amount_minor is not None and body.currency is not None
            else None
        )
        async with session_factory() as session:
            auth_context = await _auth_context_from_headers(
                session,
                settings=settings,
                authorization_header=authorization_header,
                household_header=household_header,
                user_header=user_header,
            )
            if auth_context is None:
                return _auth_context_missing_response()
            household_id, user_id = auth_context
            confirmation = ManualPriceConfirmation(
                id=uuid4(),
                household_id=household_id,
                user_id=user_id,
                target_kind=body.target_kind,
                target_id=body.target_id,
                source_id=body.source_id,
                status=body.status,
                confirmed_price=price,
                note=body.note,
                confirmed_at=datetime.now(UTC),
            )
            await ManualPriceConfirmationRepository(session).add_confirmation(confirmation)
            await session.commit()
        return _manual_price_confirmation_response(confirmation)

    @app.get(
        "/api/v1/manual-price-confirmations",
        response_model=ManualPriceConfirmationsResponse,
    )
    async def manual_price_confirmations(
        authorization_header: str | None = Header(default=None, alias="Authorization"),
        household_header: str | None = Header(
            default=None,
            alias="X-Flight-Hunter-Household-Id",
        ),
        user_header: str | None = Header(
            default=None,
            alias="X-Flight-Hunter-User-Id",
        ),
        target_kind: str | None = Query(default=None, pattern=_RESULT_KIND_PATTERN),
        target_id: str | None = Query(default=None, min_length=1, max_length=160),
        limit: int = Query(default=50, ge=1, le=100),
    ) -> ManualPriceConfirmationsResponse | JSONResponse:
        async with session_factory() as session:
            auth_context = await _auth_context_from_headers(
                session,
                settings=settings,
                authorization_header=authorization_header,
                household_header=household_header,
                user_header=user_header,
            )
            if auth_context is None:
                return _auth_context_missing_response()
            household_id, user_id = auth_context
            confirmations = await ManualPriceConfirmationRepository(session).list_recent(
                household_id=household_id,
                user_id=user_id,
                limit=limit,
                target_kind=target_kind,
                target_id=target_id,
            )
        return ManualPriceConfirmationsResponse(
            confirmations=[
                _manual_price_confirmation_response(confirmation) for confirmation in confirmations
            ],
        )

    @app.get("/api/v1/browser-sources", response_model=BrowserSourcesResponse)
    def browser_sources() -> BrowserSourcesResponse:
        now = datetime.now(UTC)
        return BrowserSourcesResponse(
            sources=[
                _browser_source_response(source, now=now)
                for source in browser_source_catalog.sources()
            ]
            + [
                _personal_browser_source_response(spec, settings=settings)
                for spec in default_ru_aggregator_specs()
                if spec.browser_observation_allowed
            ],
        )

    @app.post(
        "/api/v1/browser-sources/{source_id}/test-parser",
        response_model=BrowserParserTestResponse,
    )
    async def test_browser_source_parser(
        source_id: str,
        body: BrowserParserTestRequestBody,
        authorization_header: str | None = Header(default=None, alias="Authorization"),
        household_header: str | None = Header(
            default=None,
            alias="X-Flight-Hunter-Household-Id",
        ),
        user_header: str | None = Header(
            default=None,
            alias="X-Flight-Hunter-User-Id",
        ),
    ) -> BrowserParserTestResponse | JSONResponse:
        async with session_factory() as session:
            auth_context = await _auth_context_from_headers(
                session,
                settings=settings,
                authorization_header=authorization_header,
                household_header=household_header,
                user_header=user_header,
            )
        if auth_context is None:
            return _auth_context_missing_response()

        spec = _personal_browser_source_spec(source_id)
        if spec is None:
            return _coded_error_response(
                status_code=404,
                code="browser_source_not_found",
                message="browser source not found",
            )
        if not spec.browser_observation_allowed:
            return _coded_error_response(
                status_code=403,
                code="source_not_observable",
                message="source does not allow browser observation",
            )

        intent = await request_search_intent(body.search_intent)
        final_url = body.final_url or RuClickoutLinkBuilder((spec,)).build(spec, intent).url
        url_denial = _browser_parser_test_url_denial(final_url, settings=settings)
        if url_denial is not None:
            status_code, code, message = url_denial
            return _coded_error_response(status_code=status_code, code=code, message=message)

        captured_at = datetime.now(UTC)
        snapshot = DomSnapshot.from_html(
            source_id=spec.source_id,
            final_url=final_url,
            html=body.html,
            captured_at=captured_at,
            title=body.title,
        )
        extraction = BrowserOfferParserPipeline(
            source_names={spec.source_id: spec.display_name},
            scrapling_enabled=settings.scrapling_enabled,
            crawl4ai_diagnostics_enabled=settings.crawl4ai_enabled,
        ).extract(snapshot, intent)
        return BrowserParserTestResponse(
            source_id=spec.source_id,
            final_url=final_url,
            captured_at=captured_at.isoformat(),
            html_hash=snapshot.html_hash,
            visible_text_hash=snapshot.visible_text_hash,
            confidence=extraction.confidence.value,
            warnings=list(extraction.warnings),
            offers=[_browser_observed_offer_response(offer) for offer in extraction.offers],
            raw_price_candidates=[
                _browser_parser_price_candidate_response(candidate)
                for candidate in extraction.raw_price_candidates
            ],
        )

    @app.get("/api/v1/agent/presets", response_model=AgentPresetsResponse)
    def agent_presets() -> AgentPresetsResponse:
        return AgentPresetsResponse(
            mode=_agent_mode_response(settings),
            presets=[_agent_preset_response(preset) for preset in list_presets()],
        )

    @app.post("/api/v1/agent/plan", response_model=DurableAgentPlanResponse)
    async def agent_plan(
        body: AgentPlanRequestBody,
        authorization_header: str | None = Header(default=None, alias="Authorization"),
        household_header: str | None = Header(
            default=None,
            alias="X-Flight-Hunter-Household-Id",
        ),
        user_header: str | None = Header(
            default=None,
            alias="X-Flight-Hunter-User-Id",
        ),
    ) -> DurableAgentPlanResponse:
        try:
            selections = apply_preset_edits(body.preset_id, body.slots)
        except (KeyError, ValueError) as exc:
            raise HTTPException(status_code=400, detail="unknown agent preset") from exc
        async with session_factory() as auth_session:
            auth_context = await _optional_auth_context_from_headers(
                auth_session,
                settings=settings,
                authorization_header=authorization_header,
                household_header=household_header,
                user_header=user_header,
            )
        if auth_context is None:
            raise AgentRouteError("auth_context_missing")
        household_id, user_id = auth_context
        async with session_factory() as session:
            try:
                plan = await agent_lifecycle_service(session).create_plan(
                    CreateAgentPlan(
                        household_id=household_id,
                        user_id=user_id,
                        text="",
                        selections=selections,
                        preset_id=body.preset_id,
                    )
                )
            except AgentLifecycleError as error:
                raise agent_lifecycle_route_error(error) from error
        return DurableAgentPlanResponse.from_view(plan)

    @app.post("/api/v1/agent/chat/turn", response_model=AgentChatTurnResponse)
    async def agent_chat_turn(
        body: AgentChatTurnRequestBody,
        authorization_header: str | None = Header(default=None, alias="Authorization"),
        household_header: str | None = Header(
            default=None,
            alias="X-Flight-Hunter-Household-Id",
        ),
        user_header: str | None = Header(
            default=None,
            alias="X-Flight-Hunter-User-Id",
        ),
    ) -> AgentChatTurnResponse:
        async with session_factory() as auth_session:
            auth_context = await _optional_auth_context_from_headers(
                auth_session,
                settings=settings,
                authorization_header=authorization_header,
                household_header=household_header,
                user_header=user_header,
            )
        if auth_context is None:
            raise AgentRouteError("auth_context_missing")
        household_id, user_id = auth_context
        async with session_factory() as session:
            service = AgentChatService(
                plan_creator=agent_lifecycle_service(session),
            )
            try:
                response = await service.handle_turn(
                    AgentTurnRequest(
                        message=body.message,
                        household_id=household_id,
                        user_id=user_id,
                        selected_origin=body.selected_origin,
                        selected_destination=body.selected_destination,
                        departure_date=(
                            body.departure_date.isoformat() if body.departure_date else None
                        ),
                        return_date=body.return_date.isoformat() if body.return_date else None,
                        date_mode=body.date_mode.value if body.date_mode else None,
                        passengers=body.passengers,
                        adults=body.adults,
                        children=body.children,
                        infants=body.infants,
                        currency=body.currency,
                    )
                )
            except AgentLifecycleError as error:
                raise agent_lifecycle_route_error(error) from error
            audit_repository = AgentAuditRepository(session)
            for event in response.audit_events:
                await audit_repository.add_event(
                    NewAgentAuditEvent(
                        id=uuid4(),
                        household_id=household_id,
                        user_id=user_id,
                        event_type=event.event_type,
                        tool_name=event.tool_name,
                        summary=event.summary,
                        policy_decision=event.policy_decision,
                        related_id=event.related_id,
                        created_at=datetime.now(UTC),
                    )
                )
            await session.commit()
        return _agent_chat_turn_response(response)

    @app.get("/api/v1/places/suggest", response_model=PlaceEnvelopeResponse)
    async def places_suggest(
        q: str = Query(default="", max_length=80),
        locale: str = Query(default="ru", min_length=2, max_length=16),
        limit: int = Query(default=10, ge=1, le=20),
    ) -> PlaceEnvelopeResponse:
        try:
            directory = await request_place_directory()
        except PlaceUnavailableError:
            return _place_unavailable_envelope()
        options = directory.suggest(q, locale=locale, limit=limit) if len(q.strip()) >= 2 else ()
        return PlaceEnvelopeResponse(
            catalog_status="ready",
            enrichment_status="disabled",
            directory_version=directory.directory_version,
            items=[_place_lookup_item_response(option=option) for option in options],
        )

    @app.post("/api/v1/places/lookup", response_model=PlaceEnvelopeResponse)
    async def places_lookup(body: PlaceLookupRequestBody) -> PlaceEnvelopeResponse:
        try:
            directory = await request_place_directory()
        except PlaceUnavailableError:
            return _place_unavailable_envelope()
        items: list[PlaceLookupItemResponse] = []
        for requested in body.places:
            ref = PlaceRef(requested.kind, requested.code)
            try:
                option = directory.lookup(ref, locale=body.locale)
            except PlaceDirectoryError as error:
                items.append(_place_lookup_item_response(ref=ref, error=error))
            else:
                items.append(_place_lookup_item_response(option=option))
        return PlaceEnvelopeResponse(
            catalog_status="ready",
            enrichment_status="disabled",
            directory_version=directory.directory_version,
            items=items,
        )

    @app.post("/api/v1/searches", response_model=SearchResponse, status_code=201)
    async def searches(
        body: SearchRequestBody,
        authorization_header: str | None = Header(default=None, alias="Authorization"),
        household_header: str | None = Header(
            default=None,
            alias="X-Flight-Hunter-Household-Id",
        ),
        user_header: str | None = Header(
            default=None,
            alias="X-Flight-Hunter-User-Id",
        ),
    ) -> SearchResponse | JSONResponse:
        started_at = perf_counter()
        household_id_for_log: UUID | None = None
        directory, requested_origin, requested_destination = await request_search_places(body)
        result = search_service.search(
            SearchRequest(
                origin=requested_origin.ref.code,
                destination=requested_destination.ref.code,
                departure_date=body.departure_date,
                return_date=body.return_date,
                passengers=body.passengers,
                currency=body.currency,
                provider_ids=tuple(body.provider_ids) if body.provider_ids is not None else None,
                adults=body.adults,
                children=body.children,
                infants=body.infants,
                trip_type=body.trip_type,
                origin_kind=requested_origin.ref.kind,
                destination_kind=requested_destination.ref.kind,
                origin_airport_codes=requested_origin.airport_codes,
                destination_airport_codes=requested_destination.airport_codes,
                directory_version=directory.directory_version,
                origin_membership_version=requested_origin.membership_version,
                destination_membership_version=requested_destination.membership_version,
                requested_origin=requested_origin,
                requested_destination=requested_destination,
            )
        )
        if _auth_headers_present(
            settings=settings,
            authorization_header=authorization_header,
            household_header=household_header,
            user_header=user_header,
        ):
            async with session_factory() as session:
                auth_context = await _optional_auth_context_from_headers(
                    session,
                    settings=settings,
                    authorization_header=authorization_header,
                    household_header=household_header,
                    user_header=user_header,
                )
                if auth_context is not None:
                    household_id, user_id = auth_context
                    household_id_for_log = household_id
                    observed_offers = await BrowserObservedOfferRepository(session).list_recent(
                        household_id=household_id,
                        user_id=user_id,
                        search_id=result.search_id,
                        now=datetime.now(UTC),
                    )
                    deal_candidates = await DealCandidateRepository(session).list_recent(
                        household_id=household_id,
                        user_id=user_id,
                        search_id=result.search_id,
                        now=datetime.now(UTC),
                    )
                    result = with_browser_observed_offers_and_deal_candidates(
                        result,
                        browser_observed_offers=observed_offers,
                        deal_candidates=deal_candidates,
                    )
        log_event(
            "search_started",
            search_id=result.search_id,
            household_id=household_id_for_log,
            priced_offer_count=len(result.priced_offers),
            provider_isolated_offer_count=len(result.provider_isolated_offers),
            browser_observed_offer_count=len(result.browser_observed_offers),
            deal_candidate_count=len(result.deal_candidates),
            duration_ms=_duration_ms(started_at),
        )
        return _search_response(result, booking_secret=settings.app_secret_key)

    @app.post(
        "/api/v1/live-observation-grants",
        response_model=LiveObservationGrantResponse,
        status_code=201,
    )
    async def issue_live_observation_grant(
        body: LiveObservationGrantRequestBody,
        authorization_header: str | None = Header(default=None, alias="Authorization"),
        user_header: str | None = Header(
            default=None,
            alias="X-Flight-Hunter-User-Id",
        ),
    ) -> LiveObservationGrantResponse | JSONResponse:
        async with session_factory() as session:
            user_id = await _user_context_from_headers(
                session,
                settings=settings,
                authorization_header=authorization_header,
                user_header=user_header,
            )
            if user_id is None:
                return _auth_context_missing_response()
            service = DurableLiveObservationService(
                catalog=browser_source_catalog,
                repository=LiveObservationRepository(session),
                clock=lambda: datetime.now(UTC),
                grant_ttl=timedelta(minutes=5),
            )
            decision = await service.issue_grant(
                user_id=user_id,
                source_id=body.source_id,
                search_intent=await request_search_intent(body.search_intent),
                source=GrantSource.WEB_CLICK,
            )
            await session.commit()
        if not decision.allowed or decision.grant_token is None or decision.expires_at is None:
            return _coded_error_response(
                status_code=403,
                code=decision.code.value,
                message=decision.message,
            )
        return LiveObservationGrantResponse(
            source_id=body.source_id,
            grant_token=decision.grant_token,
            expires_at=decision.expires_at.isoformat(),
        )

    @app.post(
        "/api/v1/live-observations",
        response_model=LiveObservationCreateResponse,
        status_code=202,
    )
    async def create_live_observation(
        body: LiveObservationCreateRequestBody,
        authorization_header: str | None = Header(default=None, alias="Authorization"),
        user_header: str | None = Header(
            default=None,
            alias="X-Flight-Hunter-User-Id",
        ),
        idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    ) -> LiveObservationCreateResponse | JSONResponse:
        if idempotency_key is None or not idempotency_key.strip():
            return _coded_error_response(
                status_code=400,
                code="idempotency_key_required",
                message="Idempotency-Key header is required",
            )
        async with session_factory() as session:
            user_id = await _user_context_from_headers(
                session,
                settings=settings,
                authorization_header=authorization_header,
                user_header=user_header,
            )
            if user_id is None:
                return _auth_context_missing_response()
            service = DurableLiveObservationService(
                catalog=browser_source_catalog,
                repository=LiveObservationRepository(session),
                clock=lambda: datetime.now(UTC),
            )
            decision = await service.create_observation(
                user_id=user_id,
                source_id=body.source_id,
                search_intent=await request_search_intent(body.search_intent),
                grant_token=body.grant_token,
                idempotency_key=idempotency_key,
                context=ExecutionContext.WEB_USER_ACTION,
            )
            await session.commit()
        if not decision.accepted or decision.observation_id is None:
            return _coded_error_response(
                status_code=403,
                code=decision.code.value,
                message=decision.message,
            )
        return LiveObservationCreateResponse(
            observation_id=str(decision.observation_id),
            status=decision.initial_status.value if decision.initial_status is not None else "",
        )

    @app.get(
        "/api/v1/live-observations/{observation_id}",
        response_model=LiveObservationResponse,
    )
    async def get_live_observation(
        observation_id: UUID,
        authorization_header: str | None = Header(default=None, alias="Authorization"),
        user_header: str | None = Header(
            default=None,
            alias="X-Flight-Hunter-User-Id",
        ),
    ) -> LiveObservationResponse | JSONResponse:
        async with session_factory() as session:
            user_id = await _user_context_from_headers(
                session,
                settings=settings,
                authorization_header=authorization_header,
                user_header=user_header,
            )
            if user_id is None:
                return _auth_context_missing_response()
            service = DurableLiveObservationService(
                catalog=browser_source_catalog,
                repository=LiveObservationRepository(session),
                clock=lambda: datetime.now(UTC),
            )
            observation = await service.get_observation(
                user_id=user_id,
                observation_id=observation_id,
            )
        if observation is None:
            return _coded_error_response(
                status_code=404,
                code="observation_not_found",
                message="live observation not found",
            )
        return _live_observation_response(observation)

    @app.post(
        "/api/v1/personal-observations/grants",
        response_model=PersonalObservationGrantResponse,
        status_code=201,
    )
    async def issue_personal_observation_grant(
        body: PersonalObservationGrantRequestBody,
        authorization_header: str | None = Header(default=None, alias="Authorization"),
        user_header: str | None = Header(
            default=None,
            alias="X-Flight-Hunter-User-Id",
        ),
    ) -> PersonalObservationGrantResponse | JSONResponse:
        async with session_factory() as session:
            user_id = await _user_context_from_headers(
                session,
                settings=settings,
                authorization_header=authorization_header,
                user_header=user_header,
            )
            if user_id is None:
                return _auth_context_missing_response()
            service = _personal_observation_service(
                session=session,
                settings=settings,
                clock=lambda: datetime.now(UTC),
            )
            decision = await service.issue_grant(
                user_id=user_id,
                source_id=body.source_id,
                search_intent=await request_search_intent(body.search_intent),
                source=GrantSource.WEB_CLICK,
            )
            await session.commit()
        if not decision.allowed or decision.grant_token is None or decision.expires_at is None:
            return _coded_error_response(
                status_code=403,
                code=decision.code.value,
                message=decision.message,
            )
        return PersonalObservationGrantResponse(
            source_id=body.source_id,
            grant_token=decision.grant_token,
            expires_at=decision.expires_at.isoformat(),
        )

    @app.post(
        "/api/v1/personal-observations",
        response_model=PersonalObservationCreateResponse,
        status_code=202,
    )
    async def create_personal_observation(
        body: PersonalObservationCreateRequestBody,
        authorization_header: str | None = Header(default=None, alias="Authorization"),
        household_header: str | None = Header(
            default=None,
            alias="X-Flight-Hunter-Household-Id",
        ),
        user_header: str | None = Header(
            default=None,
            alias="X-Flight-Hunter-User-Id",
        ),
        idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    ) -> PersonalObservationCreateResponse | JSONResponse:
        if idempotency_key is None or not idempotency_key.strip():
            return _coded_error_response(
                status_code=400,
                code="idempotency_key_required",
                message="Idempotency-Key header is required",
            )
        async with session_factory() as session:
            auth_context = await _auth_context_from_headers(
                session,
                settings=settings,
                authorization_header=authorization_header,
                household_header=household_header,
                user_header=user_header,
            )
            if auth_context is None:
                return _auth_context_missing_response()
            household_id, user_id = auth_context
            service = _personal_observation_service(
                session=session,
                settings=settings,
                clock=lambda: datetime.now(UTC),
            )
            decision = await service.create_job(
                household_id=household_id,
                user_id=user_id,
                source_id=body.source_id,
                search_id=body.search_id,
                search_intent=await request_search_intent(body.search_intent),
                grant_token=body.grant_token,
                idempotency_key=idempotency_key,
            )
            await session.commit()
        if not decision.accepted or decision.job_id is None:
            return _coded_error_response(
                status_code=403,
                code=decision.code.value,
                message=decision.message,
            )
        return PersonalObservationCreateResponse(
            job_id=str(decision.job_id),
            status=decision.initial_status.value if decision.initial_status is not None else "",
            idempotent_replay=decision.idempotent_replay,
        )

    @app.get(
        "/api/v1/personal-observations/{job_id}",
        response_model=PersonalObservationResponse,
    )
    async def get_personal_observation(
        job_id: UUID,
        authorization_header: str | None = Header(default=None, alias="Authorization"),
        household_header: str | None = Header(
            default=None,
            alias="X-Flight-Hunter-Household-Id",
        ),
        user_header: str | None = Header(
            default=None,
            alias="X-Flight-Hunter-User-Id",
        ),
    ) -> PersonalObservationResponse | JSONResponse:
        async with session_factory() as session:
            auth_context = await _auth_context_from_headers(
                session,
                settings=settings,
                authorization_header=authorization_header,
                household_header=household_header,
                user_header=user_header,
            )
            if auth_context is None:
                return _auth_context_missing_response()
            household_id, user_id = auth_context
            service = _personal_observation_service(
                session=session,
                settings=settings,
                clock=lambda: datetime.now(UTC),
            )
            job = await service.get_job(
                household_id=household_id,
                user_id=user_id,
                job_id=job_id,
            )
            if job is None:
                return _coded_error_response(
                    status_code=404,
                    code="personal_observation_not_found",
                    message="personal observation not found",
                )
            observed = await BrowserObservedOfferRepository(session).list_recent(
                household_id=household_id,
                user_id=user_id,
                search_id=job.search_id,
                now=datetime.now(UTC),
            )
        return _personal_observation_response(job, observed)

    @app.post(
        "/api/v1/personal-observations/{job_id}/resume",
        response_model=PersonalObservationResponse,
    )
    async def resume_personal_observation(
        job_id: UUID,
        authorization_header: str | None = Header(default=None, alias="Authorization"),
        household_header: str | None = Header(
            default=None,
            alias="X-Flight-Hunter-Household-Id",
        ),
        user_header: str | None = Header(
            default=None,
            alias="X-Flight-Hunter-User-Id",
        ),
    ) -> PersonalObservationResponse | JSONResponse:
        async with session_factory() as session:
            auth_context = await _auth_context_from_headers(
                session,
                settings=settings,
                authorization_header=authorization_header,
                household_header=household_header,
                user_header=user_header,
            )
            if auth_context is None:
                return _auth_context_missing_response()
            household_id, user_id = auth_context
            service = _personal_observation_service(
                session=session,
                settings=settings,
                clock=lambda: datetime.now(UTC),
            )
            decision = await service.request_operator_resume(
                household_id=household_id,
                user_id=user_id,
                job_id=job_id,
            )
            if not decision.accepted or decision.job is None:
                return _coded_error_response(
                    status_code=404 if decision.job is None else 409,
                    code=decision.code.value,
                    message=decision.message,
                )
            observed = await BrowserObservedOfferRepository(session).list_recent(
                household_id=household_id,
                user_id=user_id,
                search_id=decision.job.search_id,
                now=datetime.now(UTC),
            )
            await session.commit()
        return _personal_observation_response(decision.job, observed)

    @app.post(
        "/api/v1/personal-observations/{job_id}/abort",
        response_model=PersonalObservationResponse,
    )
    async def abort_personal_observation(
        job_id: UUID,
        authorization_header: str | None = Header(default=None, alias="Authorization"),
        household_header: str | None = Header(
            default=None,
            alias="X-Flight-Hunter-Household-Id",
        ),
        user_header: str | None = Header(
            default=None,
            alias="X-Flight-Hunter-User-Id",
        ),
    ) -> PersonalObservationResponse | JSONResponse:
        async with session_factory() as session:
            auth_context = await _auth_context_from_headers(
                session,
                settings=settings,
                authorization_header=authorization_header,
                household_header=household_header,
                user_header=user_header,
            )
            if auth_context is None:
                return _auth_context_missing_response()
            household_id, user_id = auth_context
            service = _personal_observation_service(
                session=session,
                settings=settings,
                clock=lambda: datetime.now(UTC),
            )
            decision = await service.request_operator_abort(
                household_id=household_id,
                user_id=user_id,
                job_id=job_id,
            )
            if not decision.accepted or decision.job is None:
                return _coded_error_response(
                    status_code=404 if decision.job is None else 409,
                    code=decision.code.value,
                    message=decision.message,
                )
            observed = await BrowserObservedOfferRepository(session).list_recent(
                household_id=household_id,
                user_id=user_id,
                search_id=decision.job.search_id,
                now=datetime.now(UTC),
            )
            await session.commit()
        return _personal_observation_response(decision.job, observed)

    @app.post(
        "/api/v1/personal-observations/{job_id}/confirm",
        response_model=ManualPriceConfirmationResponse,
        status_code=201,
    )
    async def confirm_personal_observation(
        job_id: UUID,
        body: PersonalObservationConfirmRequestBody,
        authorization_header: str | None = Header(default=None, alias="Authorization"),
        household_header: str | None = Header(
            default=None,
            alias="X-Flight-Hunter-Household-Id",
        ),
        user_header: str | None = Header(
            default=None,
            alias="X-Flight-Hunter-User-Id",
        ),
    ) -> ManualPriceConfirmationResponse | JSONResponse:
        price = (
            Money(body.amount_minor, body.currency)
            if body.amount_minor is not None and body.currency is not None
            else None
        )
        async with session_factory() as session:
            auth_context = await _auth_context_from_headers(
                session,
                settings=settings,
                authorization_header=authorization_header,
                household_header=household_header,
                user_header=user_header,
            )
            if auth_context is None:
                return _auth_context_missing_response()
            household_id, user_id = auth_context
            service = _personal_observation_service(
                session=session,
                settings=settings,
                clock=lambda: datetime.now(UTC),
            )
            job = await service.get_job(
                household_id=household_id,
                user_id=user_id,
                job_id=job_id,
            )
            if job is None:
                return _coded_error_response(
                    status_code=404,
                    code="personal_observation_not_found",
                    message="personal observation not found",
                )
            confirmation = ManualPriceConfirmation(
                id=uuid4(),
                household_id=household_id,
                user_id=user_id,
                target_kind=ResultKind.BROWSER_OBSERVATION,
                target_id=str(job.id),
                source_id=job.source_id,
                status=body.status,
                confirmed_price=price,
                note=body.note,
                confirmed_at=datetime.now(UTC),
            )
            await ManualPriceConfirmationRepository(session).add_confirmation(confirmation)
            await session.commit()
        return _manual_price_confirmation_response(confirmation)

    @app.post(
        "/api/v1/personal-observations/{job_id}/mark-stale",
        response_model=ManualPriceConfirmationResponse,
        status_code=201,
    )
    async def mark_personal_observation_stale(
        job_id: UUID,
        body: PersonalObservationMarkStaleRequestBody,
        authorization_header: str | None = Header(default=None, alias="Authorization"),
        household_header: str | None = Header(
            default=None,
            alias="X-Flight-Hunter-Household-Id",
        ),
        user_header: str | None = Header(
            default=None,
            alias="X-Flight-Hunter-User-Id",
        ),
    ) -> ManualPriceConfirmationResponse | JSONResponse:
        async with session_factory() as session:
            auth_context = await _auth_context_from_headers(
                session,
                settings=settings,
                authorization_header=authorization_header,
                household_header=household_header,
                user_header=user_header,
            )
            if auth_context is None:
                return _auth_context_missing_response()
            household_id, user_id = auth_context
            service = _personal_observation_service(
                session=session,
                settings=settings,
                clock=lambda: datetime.now(UTC),
            )
            job = await service.get_job(
                household_id=household_id,
                user_id=user_id,
                job_id=job_id,
            )
            if job is None:
                return _coded_error_response(
                    status_code=404,
                    code="personal_observation_not_found",
                    message="personal observation not found",
                )
            confirmation = ManualPriceConfirmation(
                id=uuid4(),
                household_id=household_id,
                user_id=user_id,
                target_kind=ResultKind.BROWSER_OBSERVATION,
                target_id=str(job.id),
                source_id=job.source_id,
                status=body.status,
                confirmed_price=None,
                note=body.note,
                confirmed_at=datetime.now(UTC),
            )
            await ManualPriceConfirmationRepository(session).add_confirmation(confirmation)
            await session.commit()
        return _manual_price_confirmation_response(confirmation)

    @app.get("/api/v1/airports/autocomplete", response_model=AirportAutocompleteResponse)
    def airport_autocomplete(q: str) -> AirportAutocompleteResponse:
        return AirportAutocompleteResponse(
            airports=[
                _airport_autocomplete_response(match) for match in airport_service.autocomplete(q)
            ]
        )

    @app.get("/api/v1/airports/search", response_model=AirportSearchResponse)
    async def airport_search(q: str) -> AirportSearchResponse:
        try:
            async with session_factory() as session:
                repository = AirportReferenceRepository(session)
                import_run = await repository.latest_import_run()
                if import_run is not None:
                    matches = await repository.search(q)
                    return AirportSearchResponse(
                        airports=[_airport_search_match_response(match) for match in matches],
                        import_status=AirportImportStatusResponse(
                            source=import_run.source,
                            imported_at=import_run.imported_at.isoformat(),
                            rows_imported=import_run.rows_imported,
                        ),
                    )
        except SQLAlchemyError:
            fallback_source = "demo"
        else:
            fallback_source = "demo"

        return AirportSearchResponse(
            airports=[
                _airport_autocomplete_response(match) for match in airport_service.autocomplete(q)
            ],
            import_status=AirportImportStatusResponse(
                source=fallback_source,
                imported_at=None,
                rows_imported=None,
            ),
        )

    @app.get("/api/v1/airports/nearby", response_model=NearbyAirportsResponse)
    def airport_nearby(iata_code: str, radius_km: int = 150) -> NearbyAirportsResponse:
        return NearbyAirportsResponse(
            airports=[
                _nearby_airport_response(airport)
                for airport in airport_service.nearby(iata_code, radius_km=radius_km)
            ]
        )

    @app.post("/api/v1/searches/date-matrix", response_model=DateMatrixResponse)
    def date_matrix(body: DateMatrixRequestBody) -> DateMatrixResponse:
        matrix = date_matrix_planner.plan(
            DateMatrixRequest(
                departure_date=body.departure_date,
                return_date=body.return_date,
                flexibility_days=body.flexibility_days,
                min_stay_days=body.min_stay_days,
                max_stay_days=body.max_stay_days,
            )
        )
        signals, denials, provider_calls = _date_matrix_mobile_calendar_signals(
            body,
            settings=settings,
            provider_instances=provider_instances,
        )
        if signals:
            try:
                matrix = date_matrix_planner.overlay_discovery(
                    matrix,
                    signals=signals,
                    context=_date_matrix_discovery_context(body),
                    freshness=Freshness.LIVE,
                )
            except (TypeError, ValueError):
                denials = [AviasalesSearchSchemaError.code]
        return _date_matrix_response(
            matrix,
            pricing_denials=denials,
            provider_calls_required=provider_calls,
        )

    @app.get("/api/v1/aviasales/suggest", response_model=AviasalesSuggestResponse)
    def aviasales_suggest(
        q: str = Query(min_length=1, max_length=80),
        locale: str = Query(default="ru", min_length=2, max_length=8),
        max_results: int = Query(default=5, ge=1, le=20),
    ) -> AviasalesSuggestResponse | JSONResponse:
        provider, error = _aviasales_search_provider_or_error(settings, provider_instances)
        if error is not None:
            return error
        assert provider is not None
        try:
            places = provider.suggest_places(q, locale=locale, max_results=max_results)
        except AviasalesSearchError as exc:
            return _aviasales_error_response(exc)
        return AviasalesSuggestResponse(
            places=[
                AviasalesSuggestItemResponse(
                    code=place.code,
                    name=place.name,
                    place_type=place.place_type,
                    country_code=place.country_code,
                )
                for place in places
            ]
        )

    @app.get("/api/v1/aviasales/hot-offers", response_model=AviasalesHotOffersResponse)
    def aviasales_hot_offers(
        origin: str = Query(min_length=3, max_length=3),
        origin_type: str = Query(default="city", min_length=3, max_length=16),
        market: str = Query(default="RU", min_length=2, max_length=8),
        currency: str = Query(default="rub", min_length=3, max_length=3),
        one_way: bool = True,
    ) -> AviasalesHotOffersResponse | JSONResponse:
        provider, error = _aviasales_search_provider_or_error(settings, provider_instances)
        if error is not None:
            return error
        assert provider is not None
        try:
            offers = provider.hot_offers(
                origin=origin,
                origin_type=origin_type,
                market=market,
                currency=currency,
                one_way=one_way,
            )
        except AviasalesSearchError as exc:
            return _aviasales_error_response(exc)
        return AviasalesHotOffersResponse(
            offers=[
                AviasalesHotOfferResponse(
                    origin=offer.origin,
                    destination=offer.destination,
                    departure_date=offer.departure_date,
                    return_date=offer.return_date,
                    amount_minor=offer.price_minor_units,
                    currency=offer.currency,
                )
                for offer in offers
            ]
        )

    @app.get("/api/v1/aviasales/calendar", response_model=AviasalesCalendarResponse)
    def aviasales_calendar(
        depart_from: date,
        depart_to: date,
        origin: str = Query(min_length=3, max_length=3),
        destination: str = Query(min_length=3, max_length=3),
        one_way: bool = True,
        currency: str = Query(default="rub", min_length=3, max_length=3),
    ) -> AviasalesCalendarResponse | JSONResponse:
        provider, error = _aviasales_search_provider_or_error(settings, provider_instances)
        if error is not None:
            return error
        assert provider is not None
        try:
            validate_calendar_price_rows(
                (),
                origin=origin,
                destination=destination,
                depart_from=depart_from,
                depart_to=depart_to,
                one_way=one_way,
                currency=currency,
            )
            prices = provider.calendar_prices(
                origin=origin,
                destination=destination,
                depart_from=depart_from.isoformat(),
                depart_to=depart_to.isoformat(),
                one_way=one_way,
                currency=currency,
            )
            prices = validate_calendar_price_rows(
                prices,
                origin=origin,
                destination=destination,
                depart_from=depart_from,
                depart_to=depart_to,
                one_way=one_way,
                currency=currency,
            )
        except AviasalesSearchError as exc:
            return _aviasales_error_response(exc)
        except (TypeError, ValueError):
            return _aviasales_error_response(AviasalesSearchSchemaError())
        observed_at = datetime.now(UTC)
        evidence_namespace = uuid4()
        try:
            signals = tuple(
                map_calendar_price_to_discovery(
                    price,
                    observed_at=observed_at,
                    evidence_namespace=evidence_namespace,
                )
                for price in prices
            )
        except (TypeError, ValueError):
            return _aviasales_error_response(AviasalesSearchSchemaError())
        return AviasalesCalendarResponse(
            prices=[
                AviasalesCalendarPriceResponse(
                    origin=signal.origin,
                    destination=signal.destination,
                    departure_date=signal.departure_date.isoformat(),
                    return_date=(
                        signal.return_date.isoformat() if signal.return_date is not None else None
                    ),
                    amount_minor=signal.observed_amount.minor_units,
                    currency=signal.observed_amount.currency,
                    observed_at=signal.observed_at,
                )
                for signal in signals
            ]
        )

    @app.get(
        "/api/v1/aviasales/graphql/main-page-blocks",
        response_model=AviasalesGraphqlBlocksResponse,
    )
    def aviasales_main_page_blocks(
        origin: str = Query(default="MOW", min_length=3, max_length=3),
        origin_type: str = Query(default="CITY", min_length=3, max_length=16),
        market: str = Query(default="RU", min_length=2, max_length=8),
        currency: str = Query(default="rub", min_length=3, max_length=3),
        language: str = Query(default="ru", min_length=2, max_length=8),
        one_way: bool = True,
    ) -> AviasalesGraphqlBlocksResponse | JSONResponse:
        provider, error = _aviasales_search_provider_or_error(settings, provider_instances)
        if error is not None:
            return error
        assert provider is not None
        try:
            blocks = provider.main_page_blocks(
                origin=origin,
                origin_type=origin_type,
                market=market,
                currency=currency,
                language=language,
                one_way=one_way,
            )
        except AviasalesSearchError as exc:
            return _aviasales_error_response(exc)
        return AviasalesGraphqlBlocksResponse(
            blocks=[AviasalesGraphqlBlockResponse(typename=block.typename) for block in blocks]
        )

    @app.post("/api/v1/booking-actions/resolve", response_model=BookingResolveResponse)
    def resolve_booking_action(
        body: BookingResolveRequestBody,
    ) -> BookingResolveResponse | JSONResponse:
        if not settings.app_secret_key:
            raise HTTPException(status_code=503, detail="booking_action_secret_missing")
        try:
            payload = verify_booking_action_token(
                body.token,
                secret_key=settings.app_secret_key,
                now=datetime.now(UTC),
            )
            ref = decode_booking_ref(payload.ref)
        except BookingActionTokenError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        if (
            payload.provider_id != "aviasales_search"
            or ref.get("provider_id") != payload.provider_id
        ):
            raise HTTPException(status_code=400, detail="booking_action_provider_mismatch")
        provider, error = _aviasales_search_provider_or_error(settings, provider_instances)
        if error is not None:
            return error
        assert provider is not None
        try:
            url = provider.resolve_purchase_url(
                search_id=_required_ref_str(ref, "search_id"),
                proposal_id=_required_ref_str(ref, "proposal_id"),
                results_url=_required_ref_str(ref, "results_url"),
                request_fingerprint="booking-action:" + payload.provider_id,
                context=ExecutionContext.WEB_USER_ACTION,
            )
        except AviasalesSearchError as exc:
            return _aviasales_error_response(exc)
        except BookingActionTokenError as exc:
            raise HTTPException(status_code=502, detail="booking_action_unavailable") from exc
        return BookingResolveResponse(status="resolved" if url else "unavailable", url=url)

    @app.post("/api/v1/watches", response_model=WatchResponse, status_code=201)
    async def create_watch(
        body: WatchCreateRequestBody,
        authorization_header: str | None = Header(default=None, alias="Authorization"),
        household_header: str | None = Header(
            default=None,
            alias="X-Flight-Hunter-Household-Id",
        ),
        user_header: str | None = Header(
            default=None,
            alias="X-Flight-Hunter-User-Id",
        ),
    ) -> WatchResponse | JSONResponse:
        async with session_factory() as session:
            auth_context = await _auth_context_from_headers(
                session,
                settings=settings,
                authorization_header=authorization_header,
                household_header=household_header,
                user_header=user_header,
            )
            if auth_context is None:
                return _auth_context_missing_response()
            household_id, user_id = auth_context
            directory = await request_place_directory()
            requested_origin = _resolve_request_place(
                directory,
                code=body.origin,
                kind=body.origin_kind,
                locale="ru",
            )
            requested_destination = _resolve_request_place(
                directory,
                code=body.destination,
                kind=body.destination_kind,
                locale="ru",
            )
            service = WatchService(
                HouseholdWatchRepository(session),
                audit_repository=AuditEventRepository(session),
            )
            watch = await service.create_watch(
                CreateWatchCommand(
                    household_id=household_id,
                    owner_user_id=user_id,
                    origin=body.origin,
                    destination=body.destination,
                    origin_kind=requested_origin.ref.kind,
                    destination_kind=requested_destination.ref.kind,
                    origin_airport_codes=requested_origin.airport_codes,
                    destination_airport_codes=requested_destination.airport_codes,
                    directory_version=directory.directory_version,
                    origin_membership_version=requested_origin.membership_version,
                    destination_membership_version=requested_destination.membership_version,
                    departure_date=body.departure_date,
                    return_date=body.return_date,
                    passengers=body.passengers,
                    currency=body.currency,
                    scan_interval_seconds=settings.watch_scan_interval_seconds,
                    allowed_provider_ids=tuple(body.allowed_provider_ids),
                )
            )
            await session.commit()
        return _watch_response(watch)

    @app.get("/api/v1/watches", response_model=WatchesResponse)
    async def watches(
        authorization_header: str | None = Header(default=None, alias="Authorization"),
        household_header: str | None = Header(
            default=None,
            alias="X-Flight-Hunter-Household-Id",
        ),
        user_header: str | None = Header(
            default=None,
            alias="X-Flight-Hunter-User-Id",
        ),
    ) -> WatchesResponse | JSONResponse:
        async with session_factory() as session:
            auth_context = await _auth_context_from_headers(
                session,
                settings=settings,
                authorization_header=authorization_header,
                household_header=household_header,
                user_header=user_header,
            )
            if auth_context is None:
                return _auth_context_missing_response()
            household_id, _user_id = auth_context
            service = WatchService(HouseholdWatchRepository(session))
            records = await service.list_watches(household_id)
        return WatchesResponse(watches=[_watch_response(record) for record in records])

    @app.get("/api/v1/watches/{watch_id}", response_model=WatchResponse)
    async def watch_detail(
        watch_id: UUID,
        authorization_header: str | None = Header(default=None, alias="Authorization"),
        household_header: str | None = Header(
            default=None,
            alias="X-Flight-Hunter-Household-Id",
        ),
        user_header: str | None = Header(
            default=None,
            alias="X-Flight-Hunter-User-Id",
        ),
    ) -> WatchResponse | JSONResponse:
        async with session_factory() as session:
            auth_context = await _auth_context_from_headers(
                session,
                settings=settings,
                authorization_header=authorization_header,
                household_header=household_header,
                user_header=user_header,
            )
            if auth_context is None:
                return _auth_context_missing_response()
            household_id, _user_id = auth_context
            watch = await WatchService(HouseholdWatchRepository(session)).get_watch(
                household_id,
                watch_id,
            )
        if watch is None:
            return _watch_not_found_response()
        return _watch_response(watch)

    @app.patch("/api/v1/watches/{watch_id}", response_model=WatchResponse)
    async def update_watch(
        watch_id: UUID,
        body: WatchUpdateRequestBody,
        authorization_header: str | None = Header(default=None, alias="Authorization"),
        household_header: str | None = Header(
            default=None,
            alias="X-Flight-Hunter-Household-Id",
        ),
        user_header: str | None = Header(
            default=None,
            alias="X-Flight-Hunter-User-Id",
        ),
    ) -> WatchResponse | JSONResponse:
        async with session_factory() as session:
            auth_context = await _auth_context_from_headers(
                session,
                settings=settings,
                authorization_header=authorization_header,
                household_header=household_header,
                user_header=user_header,
            )
            if auth_context is None:
                return _auth_context_missing_response()
            household_id, user_id = auth_context
            service = WatchService(
                HouseholdWatchRepository(session),
                audit_repository=AuditEventRepository(session),
            )
            current = await service.get_watch(household_id, watch_id)
            if current is None:
                return _watch_not_found_response()
            updates = _watch_update_request_fields(body)
            origin_changed = bool({"origin", "origin_kind"} & body.model_fields_set)
            destination_changed = bool({"destination", "destination_kind"} & body.model_fields_set)
            if origin_changed or destination_changed:
                directory = await request_place_directory()
                if origin_changed:
                    requested_origin = _resolve_request_place(
                        directory,
                        code=body.origin if body.origin is not None else current.origin,
                        kind=(
                            body.origin_kind
                            if "origin_kind" in body.model_fields_set
                            else (
                                None if "origin" in body.model_fields_set else current.origin_kind
                            )
                        ),
                        locale="ru",
                    )
                    updates.update(
                        origin=requested_origin.ref.code,
                        origin_kind=requested_origin.ref.kind,
                        origin_airport_codes=requested_origin.airport_codes,
                        origin_membership_version=requested_origin.membership_version,
                    )
                if destination_changed:
                    requested_destination = _resolve_request_place(
                        directory,
                        code=(
                            body.destination
                            if body.destination is not None
                            else current.destination
                        ),
                        kind=(
                            body.destination_kind
                            if "destination_kind" in body.model_fields_set
                            else (
                                None
                                if "destination" in body.model_fields_set
                                else current.destination_kind
                            )
                        ),
                        locale="ru",
                    )
                    updates.update(
                        destination=requested_destination.ref.code,
                        destination_kind=requested_destination.ref.kind,
                        destination_airport_codes=requested_destination.airport_codes,
                        destination_membership_version=requested_destination.membership_version,
                    )
                updates["directory_version"] = directory.directory_version
            result = await service.update_watch(
                UpdateWatchCommand(
                    household_id=household_id,
                    watch_id=watch_id,
                    actor_user_id=user_id,
                    expected_version=body.expected_version,
                    updates=updates,
                )
            )
            await session.commit()
        if result.status == "not_found":
            return _watch_not_found_response()
        if result.status == "version_conflict":
            return _watch_version_conflict_response(result.current_version)
        if result.watch is None:
            return _watch_not_found_response()
        return _watch_response(result.watch)

    @app.post("/api/v1/watches/{watch_id}/pause", response_model=WatchResponse)
    async def pause_watch(
        watch_id: UUID,
        body: WatchPauseRequestBody | None = None,
        authorization_header: str | None = Header(default=None, alias="Authorization"),
        household_header: str | None = Header(
            default=None,
            alias="X-Flight-Hunter-Household-Id",
        ),
        user_header: str | None = Header(
            default=None,
            alias="X-Flight-Hunter-User-Id",
        ),
    ) -> WatchResponse | JSONResponse:
        async with session_factory() as session:
            auth_context = await _auth_context_from_headers(
                session,
                settings=settings,
                authorization_header=authorization_header,
                household_header=household_header,
                user_header=user_header,
            )
            if auth_context is None:
                return _auth_context_missing_response()
            household_id, user_id = auth_context
            service = WatchService(
                HouseholdWatchRepository(session),
                audit_repository=AuditEventRepository(session),
            )
            watch = await service.pause_watch(
                household_id=household_id,
                watch_id=watch_id,
                actor_user_id=user_id,
                paused_until=body.paused_until if body is not None else None,
            )
            await session.commit()
        if watch is None:
            return _watch_not_found_response()
        return _watch_response(watch)

    @app.post("/api/v1/watches/{watch_id}/resume", response_model=WatchResponse)
    async def resume_watch(
        watch_id: UUID,
        authorization_header: str | None = Header(default=None, alias="Authorization"),
        household_header: str | None = Header(
            default=None,
            alias="X-Flight-Hunter-Household-Id",
        ),
        user_header: str | None = Header(
            default=None,
            alias="X-Flight-Hunter-User-Id",
        ),
    ) -> WatchResponse | JSONResponse:
        async with session_factory() as session:
            auth_context = await _auth_context_from_headers(
                session,
                settings=settings,
                authorization_header=authorization_header,
                household_header=household_header,
                user_header=user_header,
            )
            if auth_context is None:
                return _auth_context_missing_response()
            household_id, user_id = auth_context
            service = WatchService(
                HouseholdWatchRepository(session),
                audit_repository=AuditEventRepository(session),
            )
            watch = await service.resume_watch(
                household_id=household_id,
                watch_id=watch_id,
                actor_user_id=user_id,
            )
            await session.commit()
        if watch is None:
            return _watch_not_found_response()
        return _watch_response(watch)

    @app.post("/api/v1/watches/{watch_id}/archive", response_model=WatchLifecycleResponse)
    async def archive_watch(
        watch_id: UUID,
        body: WatchVersionRequestBody,
        authorization_header: str | None = Header(default=None, alias="Authorization"),
        household_header: str | None = Header(
            default=None,
            alias="X-Flight-Hunter-Household-Id",
        ),
        user_header: str | None = Header(
            default=None,
            alias="X-Flight-Hunter-User-Id",
        ),
    ) -> WatchLifecycleResponse | JSONResponse:
        async with session_factory() as session:
            auth_context = await _auth_context_from_headers(
                session,
                settings=settings,
                authorization_header=authorization_header,
                household_header=household_header,
                user_header=user_header,
            )
            if auth_context is None:
                return _auth_context_missing_response()
            household_id, user_id = auth_context
            service = WatchService(
                HouseholdWatchRepository(session),
                audit_repository=AuditEventRepository(session),
            )
            result = await service.archive_watch(
                WatchLifecycleCommand(
                    household_id=household_id,
                    watch_id=watch_id,
                    actor_user_id=user_id,
                    expected_version=body.expected_version,
                )
            )
            await session.commit()
        return _watch_lifecycle_response(watch_id=watch_id, result=result, success="archived")

    @app.delete("/api/v1/watches/{watch_id}", response_model=WatchLifecycleResponse)
    async def delete_watch(
        watch_id: UUID,
        body: WatchVersionRequestBody,
        authorization_header: str | None = Header(default=None, alias="Authorization"),
        household_header: str | None = Header(
            default=None,
            alias="X-Flight-Hunter-Household-Id",
        ),
        user_header: str | None = Header(
            default=None,
            alias="X-Flight-Hunter-User-Id",
        ),
    ) -> WatchLifecycleResponse | JSONResponse:
        async with session_factory() as session:
            auth_context = await _auth_context_from_headers(
                session,
                settings=settings,
                authorization_header=authorization_header,
                household_header=household_header,
                user_header=user_header,
            )
            if auth_context is None:
                return _auth_context_missing_response()
            household_id, user_id = auth_context
            service = WatchService(
                HouseholdWatchRepository(session),
                audit_repository=AuditEventRepository(session),
            )
            result = await service.delete_watch(
                WatchLifecycleCommand(
                    household_id=household_id,
                    watch_id=watch_id,
                    actor_user_id=user_id,
                    expected_version=body.expected_version,
                )
            )
            await session.commit()
        return _watch_lifecycle_response(watch_id=watch_id, result=result, success="deleted")

    @app.get("/api/v1/watches/{watch_id}/history", response_model=WatchHistoryResponse)
    async def watch_history(
        watch_id: UUID,
        authorization_header: str | None = Header(default=None, alias="Authorization"),
        household_header: str | None = Header(
            default=None,
            alias="X-Flight-Hunter-Household-Id",
        ),
        user_header: str | None = Header(
            default=None,
            alias="X-Flight-Hunter-User-Id",
        ),
    ) -> WatchHistoryResponse | JSONResponse:
        async with session_factory() as session:
            auth_context = await _auth_context_from_headers(
                session,
                settings=settings,
                authorization_header=authorization_header,
                household_header=household_header,
                user_header=user_header,
            )
            if auth_context is None:
                return _auth_context_missing_response()
            household_id, _user_id = auth_context
            watch_repository = HouseholdWatchRepository(session)
            watch = await WatchService(watch_repository).get_watch(household_id, watch_id)
            if watch is None:
                return _watch_not_found_response()
            snapshots = await PriceSnapshotRepository(session).list_history(household_id, watch_id)
        return WatchHistoryResponse(
            watch_id=str(watch_id),
            snapshots=[_watch_snapshot_response(snapshot) for snapshot in snapshots],
        )

    @app.post("/api/v1/telegram/link-code", response_model=TelegramLinkCodeResponse)
    async def create_telegram_link_code(
        authorization_header: str | None = Header(default=None, alias="Authorization"),
        household_header: str | None = Header(
            default=None,
            alias="X-Flight-Hunter-Household-Id",
        ),
        user_header: str | None = Header(
            default=None,
            alias="X-Flight-Hunter-User-Id",
        ),
    ) -> TelegramLinkCodeResponse | JSONResponse:
        async with session_factory() as session:
            auth_context = await _auth_context_from_headers(
                session,
                settings=settings,
                authorization_header=authorization_header,
                household_header=household_header,
                user_header=user_header,
            )
            if auth_context is None:
                return _auth_context_missing_response()
            household_id, user_id = auth_context
            service = TelegramLinkService(
                repository=TelegramLinkRepository(session),
                clock=lambda: datetime.now(UTC),
            )
            link_code = await service.create_link_code(
                household_id=household_id,
                user_id=user_id,
                ttl=timedelta(minutes=10),
            )
            await session.commit()
        return TelegramLinkCodeResponse(
            code=link_code.code,
            expires_at=link_code.expires_at.isoformat(),
        )

    @app.post(
        "/api/v1/telegram/webhook",
        response_model=TelegramWebhookResponse,
    )
    async def telegram_webhook(
        body: dict[str, object],
        x_telegram_secret: str | None = Header(
            default=None,
            alias="X-Telegram-Bot-Api-Secret-Token",
        ),
    ) -> JSONResponse:
        decision = telegram_webhook_handler.handle_update(
            provided_secret=x_telegram_secret,
            update=body,
        )
        code = decision.code
        if code == TelegramWebhookDecisionCode.ACCEPTED:
            update_id = _telegram_update_id(body)
            if update_id is None:
                code = TelegramWebhookDecisionCode.INVALID_UPDATE
            else:
                received_at = datetime.now(UTC)
                async with session_factory() as session:
                    repository = TelegramUpdateRepository(session)
                    recorded = await repository.record_update(
                        update_id=update_id,
                        received_at=received_at,
                    )
                    if recorded and (link_command := _telegram_link_command(body)) is not None:
                        telegram_user_id, chat_id, link_code = link_command
                        link_service = TelegramLinkService(
                            repository=TelegramLinkRepository(session),
                            clock=lambda: received_at,
                        )
                        await link_service.consume_link_code(
                            code=link_code,
                            telegram_user_id=telegram_user_id,
                            chat_id=chat_id,
                        )
                    elif (
                        recorded
                        and update_id is not None
                        and (watches_command := _telegram_watches_command(body)) is not None
                    ):
                        telegram_user_id = watches_command
                        command_service = TelegramWatchCommandService(
                            links=TelegramLinkRepository(session),
                            watches=HouseholdWatchRepository(session),
                            outbox=TelegramNotificationOutboxRepository(session),
                            clock=lambda: received_at,
                        )
                        await command_service.handle_watches_command(
                            telegram_user_id=telegram_user_id,
                            update_id=update_id,
                        )
                    elif (
                        recorded
                        and update_id is not None
                        and (watch_callback := _telegram_watch_callback(body)) is not None
                    ):
                        telegram_user_id, callback_query_id, callback_data = watch_callback
                        command_service = TelegramWatchCommandService(
                            links=TelegramLinkRepository(session),
                            watches=HouseholdWatchRepository(session),
                            outbox=TelegramNotificationOutboxRepository(session),
                            audit_repository=AuditEventRepository(session),
                            personal_observation_service=_personal_observation_service(
                                session=session,
                                settings=settings,
                                clock=lambda: received_at,
                            ),
                            observation_source_id=settings.telegram_watch_check_source_id,
                            clock=lambda: received_at,
                        )
                        await command_service.handle_watch_callback(
                            telegram_user_id=telegram_user_id,
                            callback_query_id=callback_query_id,
                            callback_data=callback_data,
                            update_id=update_id,
                        )
                    await session.commit()
                if not recorded:
                    code = TelegramWebhookDecisionCode.DUPLICATE

        status_code, status = _telegram_response_status(code)
        return JSONResponse(
            status_code=status_code,
            content={"code": code.value, "status": status},
        )

    return app


def _watch_session_factory(database_url: str) -> async_sessionmaker[AsyncSession]:
    engine = create_database_engine(database_url)
    return async_sessionmaker(engine, expire_on_commit=False)


def _provider_instances(settings: AppSettings) -> dict[str, AviasalesSearchAdapter]:
    if not settings.aviasales_search_credentials_valid:
        return {}
    return {
        "aviasales_search": AviasalesSearchAdapter(
            client=AviasalesSearchClient(
                signature=settings.aviasales_search_signature or "",
                marker=settings.aviasales_search_marker or "",
            ),
            enabled=settings.aviasales_search_enabled,
            credentials_present=settings.aviasales_search_credentials_present,
            internal_rpm=settings.aviasales_search_internal_rpm,
            clock=lambda: datetime.now(UTC),
        )
    }


def _aviasales_search_provider_or_error(
    settings: AppSettings,
    provider_instances: dict[str, AviasalesSearchAdapter],
) -> tuple[AviasalesSearchAdapter | None, JSONResponse | None]:
    if not settings.aviasales_search_enabled:
        return None, _coded_error_response(
            status_code=503,
            code="aviasales_search_disabled",
            message="provider is disabled",
        )
    provider = provider_instances.get("aviasales_search")
    if provider is not None:
        return provider, None
    code = _aviasales_configuration_error_code(settings)
    return None, _coded_error_response(
        status_code=503,
        code=code,
        message="provider is not configured",
    )


def _aviasales_configuration_error_code(settings: AppSettings) -> str:
    if not settings.aviasales_search_enabled:
        return "aviasales_search_disabled"
    if not settings.aviasales_search_credentials_present:
        return "aviasales_search_credentials_missing"
    if not settings.aviasales_search_credentials_valid:
        return "aviasales_search_credentials_invalid"
    return "aviasales_search_unavailable"


def _aviasales_error_response(exc: AviasalesSearchError) -> JSONResponse:
    if isinstance(exc, AviasalesSearchRateLimited):
        headers = (
            {"Retry-After": str(exc.retry_after_seconds)}
            if exc.retry_after_seconds is not None
            else {}
        )
        return JSONResponse(
            status_code=429,
            content={
                "code": exc.code,
                "message": "provider rate limited",
            },
            headers=headers,
        )
    code = {
        AviasalesSearchAuthFailed: "aviasales_search_auth_failed",
        AviasalesSearchBlocked: "aviasales_search_blocked",
        AviasalesSearchSchemaError: "aviasales_search_schema_error",
    }.get(type(exc), "aviasales_search_unavailable")
    return _coded_error_response(
        status_code=502,
        code=code,
        message="provider unavailable",
    )


def _required_ref_str(ref: dict[str, object], key: str) -> str:
    value = ref.get(key)
    if not isinstance(value, str) or not value:
        raise BookingActionTokenError("booking_action_ref_malformed")
    return value


async def _auth_context_from_headers(
    session: AsyncSession,
    *,
    settings: AppSettings,
    authorization_header: str | None,
    household_header: str | None,
    user_header: str | None,
) -> tuple[UUID, UUID] | None:
    auth_session = await _auth_session_from_authorization(session, authorization_header)
    if auth_session is not None:
        return auth_session.household_id, auth_session.user_id
    if not settings.auth_allow_legacy_headers:
        return None
    return _auth_context(household_header, user_header)


async def _optional_auth_context_from_headers(
    session: AsyncSession,
    *,
    settings: AppSettings,
    authorization_header: str | None,
    household_header: str | None,
    user_header: str | None,
) -> tuple[UUID, UUID] | None:
    auth_session = await _auth_session_from_authorization(session, authorization_header)
    if auth_session is not None:
        return auth_session.household_id, auth_session.user_id
    if not settings.auth_allow_legacy_headers:
        return None
    return _auth_context(household_header, user_header)


async def _user_context_from_headers(
    session: AsyncSession,
    *,
    settings: AppSettings,
    authorization_header: str | None,
    user_header: str | None,
) -> UUID | None:
    auth_session = await _auth_session_from_authorization(session, authorization_header)
    if auth_session is not None:
        return auth_session.user_id
    if not settings.auth_allow_legacy_headers:
        return None
    return _user_context(user_header)


def _auth_headers_present(
    *,
    settings: AppSettings,
    authorization_header: str | None,
    household_header: str | None,
    user_header: str | None,
) -> bool:
    if authorization_header is not None:
        return True
    return (
        settings.auth_allow_legacy_headers
        and household_header is not None
        and user_header is not None
    )


def _duration_ms(started_at: float) -> int:
    return max(0, int((perf_counter() - started_at) * 1000))


def _scoped_idempotency_key(
    prefix: str,
    *,
    household_id: UUID,
    user_id: UUID,
    idempotency_key: str,
) -> str:
    return f"{prefix}:{household_id}:{user_id}:{idempotency_key.strip()}"


async def _auth_session_from_authorization(
    session: AsyncSession,
    authorization_header: str | None,
) -> AuthSession | None:
    token = _bearer_token(authorization_header)
    if token is None:
        return None
    return await IdentityRepository(session).session_by_token_hash(
        token_hash=token_hash(token),
        now=datetime.now(UTC),
    )


def _bearer_token(authorization_header: str | None) -> str | None:
    if authorization_header is None:
        return None
    scheme, separator, token = authorization_header.strip().partition(" ")
    if not separator or scheme.lower() != "bearer" or not token.strip():
        return None
    return token.strip()


def _auth_context(
    household_header: str | None,
    user_header: str | None,
) -> tuple[UUID, UUID] | None:
    if household_header is None or user_header is None:
        return None
    try:
        return UUID(household_header), UUID(user_header)
    except ValueError:
        return None


def _auth_context_missing_response() -> JSONResponse:
    return JSONResponse(
        status_code=401,
        content={
            "code": "auth_context_missing",
            "message": "household context is required",
        },
    )


def _coded_error_response(*, status_code: int, code: str, message: str) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={"code": code, "message": message},
    )


def _user_context(user_header: str | None) -> UUID | None:
    if user_header is None:
        return None
    try:
        return UUID(user_header)
    except ValueError:
        return None


def _household_context(household_header: str | None) -> UUID | None:
    if household_header is None:
        return None
    try:
        return UUID(household_header)
    except ValueError:
        return None


async def _try_record_source_health_event(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    source_id: str,
    event_type: str,
    status: str,
    message: str,
) -> None:
    try:
        async with session_factory() as session:
            await SourceHealthEventRepository(session).add_event(
                NewSourceHealthEvent(
                    id=uuid4(),
                    source_id=source_id,
                    event_type=event_type,
                    status=status,
                    message=message,
                    observed_at=datetime.now(UTC),
                )
            )
            await session.commit()
    except SQLAlchemyError:
        return


def _provider_status_response(status: ProviderStatus) -> ProviderStatusResponse:
    return ProviderStatusResponse(
        provider_id=status.provider_id,
        enabled=status.enabled,
        credentials_present=status.credentials_present,
        access_approved=status.access_approved,
        data_kind=status.data_kind.value,
        merge_scope=status.merge_scope.value,
        background_requests_allowed=status.background_requests_allowed,
        user_action_required=status.user_action_required,
        blocked_reasons=list(status.blocked_reasons),
        notes=status.notes,
    )


def _admin_provider_health_response(status: ProviderStatus) -> AdminProviderHealthItemResponse:
    return AdminProviderHealthItemResponse(
        provider_id=status.provider_id,
        enabled=status.enabled,
        credentials_present=status.credentials_present,
        secret_present=status.credentials_present,
        access_approved=status.access_approved,
        data_kind=status.data_kind.value,
        background_requests_allowed=status.background_requests_allowed,
        blocked_reasons=list(status.blocked_reasons),
    )


def _admin_source_health_item_response(source: SourceHealthItem) -> AdminSourceHealthItemResponse:
    return AdminSourceHealthItemResponse(
        source_id=source.source_id,
        display_name=source.display_name,
        contract_known=source.contract_known,
        stage=source.stage,
        enabled=source.enabled,
        data_kind=source.data_kind,
        merge_scope=source.merge_scope,
        background_requests_allowed=source.background_requests_allowed,
        user_action_required=source.user_action_required,
        blocked_reasons=list(source.blocked_reasons),
        current_status=source.current_status,
        latest_event=(
            _admin_source_health_event_response(source.latest_event)
            if source.latest_event is not None
            else None
        ),
    )


def _admin_source_health_event_response(
    event: SourceHealthEventView,
) -> AdminSourceHealthEventResponse:
    return AdminSourceHealthEventResponse(
        id=str(event.id),
        event_type=event.event_type,
        status=event.status,
        message=event.message,
        observed_at=event.observed_at.isoformat(),
        cooldown_until=event.cooldown_until.isoformat()
        if event.cooldown_until is not None
        else None,
    )


def _admin_worker_health_item_response(worker: WorkerHealthItem) -> AdminWorkerHealthItemResponse:
    return AdminWorkerHealthItemResponse(
        worker_id=worker.worker_id,
        role=worker.role,
        status=worker.status,
        effective_status=worker.effective_status,
        current_phase=worker.current_phase,
        current_job_kind=worker.current_job_kind,
        current_job_id=worker.current_job_id,
        started_at=worker.started_at.isoformat(),
        last_seen_at=worker.last_seen_at.isoformat(),
        stopping_at=worker.stopping_at.isoformat() if worker.stopping_at is not None else None,
        stopped_at=worker.stopped_at.isoformat() if worker.stopped_at is not None else None,
        last_summary=dict(worker.last_summary),
    )


def _admin_worker_queue_health_response(
    queue: WorkerQueueHealthItem,
) -> AdminWorkerQueueHealthResponse:
    return AdminWorkerQueueHealthResponse(
        lane=queue.lane,
        status_counts=dict(queue.status_counts),
        due_count=queue.due_count,
        delayed_count=queue.delayed_count,
        stale_count=queue.stale_count,
        expired_count=queue.expired_count,
        oldest_queued_age_seconds=queue.oldest_queued_age_seconds,
        oldest_locked_age_seconds=queue.oldest_locked_age_seconds,
        warning_level=queue.warning_level,
    )


def _admin_worker_health_alert_response(
    alert: WorkerHealthAlert,
) -> AdminWorkerHealthAlertResponse:
    return AdminWorkerHealthAlertResponse(
        severity=alert.severity,
        code=alert.code,
        subject_kind=alert.subject_kind,
        subject_id=alert.subject_id,
        message=alert.message,
    )


def _admin_agent_operational_health_response(
    agent: AgentOperationalHealthItem | None,
) -> AdminAgentOperationalHealthResponse:
    if agent is None:
        raise RuntimeError("agent operational health is unavailable")
    return AdminAgentOperationalHealthResponse(
        operation_status_counts=dict(agent.operation_status_counts),
        run_status_counts=dict(agent.run_status_counts),
        due_operation_count=agent.due_operation_count,
        oldest_due_operation_age_seconds=agent.oldest_due_operation_age_seconds,
        circuit_state_counts=dict(agent.circuit_state_counts),
        estimated_logical_operations=agent.estimated_logical_operations,
        actual_logical_operations=agent.actual_logical_operations,
        estimated_http_attempts=agent.estimated_http_attempts,
        actual_http_attempts=agent.actual_http_attempts,
        confirmed_candidates=agent.confirmed_candidates,
        provider_denials=agent.provider_denials,
        terminal_run_count=agent.terminal_run_count,
        terminal_run_duration_seconds=agent.terminal_run_duration_seconds,
        recovered_operations=agent.recovered_operations,
    )


def _admin_worker_control_response(state: WorkerControlState) -> AdminWorkerControlResponse:
    return AdminWorkerControlResponse(
        drain_requested=state.drain_requested,
        reason=state.reason,
        requested_at=state.requested_at.isoformat() if state.requested_at is not None else None,
        cleared_at=state.cleared_at.isoformat() if state.cleared_at is not None else None,
        updated_at=state.updated_at.isoformat() if state.updated_at is not None else None,
    )


def _admin_audit_event_response(event: AuditEventRecord) -> AdminAuditEventResponse:
    return AdminAuditEventResponse(
        id=str(event.id),
        actor_user_id=str(event.actor_user_id) if event.actor_user_id is not None else None,
        action=event.action,
        entity_type=event.entity_type,
        entity_id=str(event.entity_id),
        summary=event.summary,
        created_at=event.created_at.isoformat(),
    )


def _privacy_export_fetch_limit(collection: str) -> int:
    return _PRIVACY_EXPORT_LIMITS[collection] + 1


def _privacy_export_response(
    *,
    exported_at: datetime,
    household_id: UUID,
    user_id: UUID,
    watches: tuple[WatchRecord, ...],
    audit_events: tuple[AuditEventRecord, ...],
    manual_confirmations: tuple[ManualPriceConfirmation, ...],
    observed_offers: tuple[BrowserObservedOffer, ...],
    deal_candidates: tuple[DealCandidate, ...],
) -> PrivacyExportResponse:
    limits = dict(_PRIVACY_EXPORT_LIMITS)
    return PrivacyExportResponse(
        format_version=1,
        exported_at=exported_at.isoformat(),
        household_id=str(household_id),
        user_id=str(user_id),
        collection_limits=limits,
        truncated={
            "watches": len(watches) > limits["watches"],
            "audit_events": len(audit_events) > limits["audit_events"],
            "manual_price_confirmations": (
                len(manual_confirmations) > limits["manual_price_confirmations"]
            ),
            "browser_observed_offers": (len(observed_offers) > limits["browser_observed_offers"]),
            "deal_candidates": len(deal_candidates) > limits["deal_candidates"],
        },
        omitted_fields=list(_PRIVACY_EXPORT_OMITTED_FIELDS),
        watches=[_privacy_watch_response(watch) for watch in watches[: limits["watches"]]],
        audit_events=[
            _admin_audit_event_response(event) for event in audit_events[: limits["audit_events"]]
        ],
        manual_price_confirmations=[
            _manual_price_confirmation_response(confirmation)
            for confirmation in manual_confirmations[: limits["manual_price_confirmations"]]
        ],
        browser_observed_offers=[
            _browser_observed_offer_response(offer)
            for offer in observed_offers[: limits["browser_observed_offers"]]
        ],
        deal_candidates=[
            _deal_candidate_response(candidate)
            for candidate in deal_candidates[: limits["deal_candidates"]]
        ],
    )


def _privacy_watch_response(watch: WatchRecord) -> PrivacyWatchResponse:
    return PrivacyWatchResponse(
        id=str(watch.id),
        household_id=str(watch.household_id),
        owner_user_id=str(watch.owner_user_id),
        origin=watch.origin,
        destination=watch.destination,
        origin_kind=watch.origin_kind,
        destination_kind=watch.destination_kind,
        origin_airport_codes=list(watch.origin_airport_codes),
        destination_airport_codes=list(watch.destination_airport_codes),
        directory_version=watch.directory_version,
        origin_membership_version=watch.origin_membership_version,
        destination_membership_version=watch.destination_membership_version,
        departure_date=watch.departure_date,
        return_date=watch.return_date,
        passengers=watch.passengers,
        currency=watch.currency,
        allowed_provider_ids=list(watch.allowed_provider_ids),
        enabled=watch.enabled,
        paused_until=watch.paused_until.isoformat() if watch.paused_until is not None else None,
        next_eligible_at=(
            watch.next_eligible_at.isoformat() if watch.next_eligible_at is not None else None
        ),
        scan_interval_seconds=watch.scan_interval_seconds,
        last_scanned_at=(
            watch.last_scanned_at.isoformat() if watch.last_scanned_at is not None else None
        ),
        last_scan_status=watch.last_scan_status,
        last_scan_error_code=watch.last_scan_error_code,
        created_at=watch.created_at.isoformat(),
        updated_at=watch.updated_at.isoformat(),
        version=watch.version,
        archived_at=watch.archived_at.isoformat() if watch.archived_at is not None else None,
        archived_by_user_id=(
            str(watch.archived_by_user_id) if watch.archived_by_user_id is not None else None
        ),
        deleted_at=watch.deleted_at.isoformat() if watch.deleted_at is not None else None,
        deleted_by_user_id=(
            str(watch.deleted_by_user_id) if watch.deleted_by_user_id is not None else None
        ),
    )


def _price_source_response(source: PriceSource) -> PriceSourceResponse:
    return PriceSourceResponse(
        id=source.id,
        name=source.name,
        source_type=source.source_type.value,
        price_kind=source.price_kind.value,
        supports_rub=source.supports_rub,
        in_app_booking=source.in_app_booking,
        purchase_flow=source.purchase_flow,
        requires_manual_confirmation=source.requires_manual_confirmation,
        setup_required_ru=source.setup_required_ru,
        notes_ru=source.notes_ru,
    )


def _source_contract_summary_response(
    sources: tuple[SourceReadiness, ...],
) -> SourceContractSummaryResponse:
    return SourceContractSummaryResponse(
        total=len(sources),
        implemented=sum(1 for source in sources if source.stage.value == "implemented"),
        policy_skeleton=sum(1 for source in sources if source.stage.value == "policy_skeleton"),
        contract_only=sum(1 for source in sources if source.stage.value == "contract_only"),
    )


def _source_contract_response(source: SourceReadiness) -> SourceContractResponse:
    return SourceContractResponse(
        source_id=source.source_id,
        display_name=source.display_name,
        stage=source.stage.value,
        adapter_module=source.adapter_module,
        contract_file=source.contract_file,
        terms_url=source.terms_url,
        required_env=list(source.required_env),
        operations=list(source.operations),
        invariants=list(source.invariants),
        egress_policy=list(source.egress_policy),
        notes=source.notes,
        enabled=source.enabled,
        credentials_present=source.credentials_present,
        access_approved=source.access_approved,
        data_kind=source.data_kind,
        merge_scope=source.merge_scope,
        background_requests_allowed=source.background_requests_allowed,
        user_action_required=source.user_action_required,
        blocked_reasons=list(source.blocked_reasons),
    )


def _personal_browser_source_spec(source_id: str) -> RuAggregatorSpec | None:
    return next(
        (spec for spec in default_ru_aggregator_specs() if spec.source_id == source_id),
        None,
    )


def _browser_parser_test_url_denial(
    url: str,
    *,
    settings: AppSettings,
) -> tuple[int, str, str] | None:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        return (422, "invalid_final_url", "final_url must be http(s) with a host")
    if parsed.username is not None or parsed.password is not None:
        return (422, "invalid_final_url", "final_url must not contain credentials")
    host = parsed.hostname.lower()
    if host not in settings.personal_observer_allowed_hosts:
        return (403, "host_not_allowed", "final_url host is not allowed for parser testing")
    return None


def _browser_parser_price_candidate_response(
    candidate: PriceCandidate,
) -> BrowserParserPriceCandidateResponse:
    return BrowserParserPriceCandidateResponse(
        raw_text=candidate.raw_text,
        amount=_money_response(candidate.amount),
        accepted=candidate.accepted,
        rejection_reason=candidate.rejection_reason,
    )


def _browser_source_response(source: BrowserSource, *, now: datetime) -> BrowserSourceResponse:
    return BrowserSourceResponse(
        source_id=source.source_id,
        display_name=source.display_name,
        enabled=source.enabled,
        permission_status=source.permission_status(now).value,
        user_action_required=True,
        background_allowed=source.background_allowed,
        supported_routes=list(source.supported_routes),
        current_health=source.current_health,
    )


def _personal_browser_source_response(
    spec: RuAggregatorSpec,
    *,
    settings: AppSettings,
) -> BrowserSourceResponse:
    host_allowed = any(
        host in settings.personal_observer_allowed_hosts for host in spec.allowed_hosts
    )
    source_enabled = (
        settings.personal_observer_enabled
        and spec.source_id in settings.ru_aggregators_enabled
        and host_allowed
    )
    if not host_allowed:
        current_health = "host_not_allowed"
        permission_status = "missing"
    elif source_enabled:
        current_health = "healthy"
        permission_status = "active"
    else:
        current_health = "disabled"
        permission_status = "active"
    return BrowserSourceResponse(
        source_id=spec.source_id,
        display_name=spec.display_name,
        enabled=source_enabled,
        permission_status=permission_status,
        user_action_required=True,
        background_allowed=False,
        supported_routes=["manual_user_action"],
        current_health=current_health,
    )


def _agent_mode_response(settings: AppSettings) -> AgentModeResponse:
    return AgentModeResponse(
        enabled=settings.agent_mode_enabled,
        provider=settings.agent_provider,
        mcp_enabled=settings.agent_mcp_enabled,
        mcp_server_configured=settings.agent_mcp_server is not None,
    )


def _agent_preset_response(preset: AgentPreset) -> AgentPresetResponse:
    return AgentPresetResponse(
        id=preset.id.value,
        title_ru=preset.title_ru,
        description_ru=preset.description_ru,
        required_slots=list(preset.required_slots),
        risk_level=preset.risk_level.value,
    )


def _agent_chat_turn_response(response: AgentTurnResponse) -> AgentChatTurnResponse:
    return AgentChatTurnResponse(
        reply_ru=response.reply_ru,
        proposed_plan=DurableAgentPlanResponse.from_view(response.proposed_plan),
        extracted=response.extracted,
        missing_slots=list(response.missing_slots),
        airport_options={
            key: [_agent_airport_option_response(option) for option in options]
            for key, options in response.airport_options.items()
        },
        actions=[_agent_action_response(action) for action in response.actions],
        audit_events=[_agent_audit_event_response(event) for event in response.audit_events],
        runtime=_agent_runtime_response(response.runtime),
    )


def _agent_runtime_response(runtime: AgentRuntimeInfo) -> AgentRuntimeResponse:
    return AgentRuntimeResponse(
        backend=runtime.backend,
        agentic_loop=runtime.agentic_loop,
        model=runtime.model,
        fallback_backend=runtime.fallback_backend,
        live_calls_allowed=runtime.live_calls_allowed,
        cloudflare_ready=runtime.cloudflare_ready,
    )


def _agent_airport_option_response(option: AirportOption) -> AgentAirportOptionResponse:
    return AgentAirportOptionResponse(
        iata_code=option.iata_code,
        label=option.label,
        name=option.name,
        municipality=option.municipality,
        country_code=option.country_code,
    )


def _agent_action_response(action: AgentAction) -> AgentActionResponse:
    return AgentActionResponse(
        kind=action.kind,
        title_ru=action.title_ru,
        parameters=action.parameters,
        requires_user_action=action.requires_user_action,
        policy_decision=action.policy_decision,
        related_id=action.related_id,
    )


def _agent_audit_event_response(event: AgentAuditEvent) -> AgentAuditEventResponse:
    return AgentAuditEventResponse(
        event_type=event.event_type,
        tool_name=event.tool_name,
        summary=event.summary,
        policy_decision=event.policy_decision,
        related_id=event.related_id,
    )


def _resolve_request_place(
    directory: PlaceDirectory,
    *,
    code: str,
    kind: PlaceKind | None,
    locale: str,
) -> PlaceOption:
    try:
        if kind is None:
            return directory.resolve_legacy(code, locale=locale)
        return directory.lookup(PlaceRef(kind, code), locale=locale)
    except (TypeError, ValueError):
        raise PlaceUnknownError("invalid_place_code", code=code) from None


def _place_search_error_response(error: PlaceDirectoryError) -> JSONResponse:
    return JSONResponse(
        status_code=503 if isinstance(error, PlaceUnavailableError) else 422,
        content={
            "error": {
                "code": error.code,
                "message": "place could not be resolved",
            }
        },
    )


async def place_directory_error_handler(
    _request: Request,
    error: Exception,
) -> JSONResponse:
    if not isinstance(error, PlaceDirectoryError):
        raise error
    return _place_search_error_response(error)


def _place_unavailable_envelope() -> PlaceEnvelopeResponse:
    return PlaceEnvelopeResponse(
        catalog_status="unavailable",
        enrichment_status="disabled",
        directory_version=None,
        items=[],
    )


def _place_lookup_item_response(
    *,
    option: PlaceOption | None = None,
    ref: PlaceRef | None = None,
    error: PlaceDirectoryError | None = None,
) -> PlaceLookupItemResponse:
    if option is not None:
        if ref is not None or error is not None:
            raise ValueError("resolved place item cannot include ref or error overrides")
        return PlaceLookupItemResponse(
            ref=_place_ref_response(option.ref),
            resolved=True,
            display_name=_place_label_response(option.display_name),
            city_name=_optional_place_label_response(option.city_name),
            country_code=option.country_code,
            country_name=_optional_place_label_response(option.country_name),
            airport_codes=list(option.airport_codes),
            directory_version=option.directory_version,
            membership_version=option.membership_version,
            membership_observed_at=option.membership_observed_at,
            error=None,
        )
    if ref is None or error is None:
        raise ValueError("unresolved place item requires ref and error")
    return PlaceLookupItemResponse(
        ref=_place_ref_response(ref),
        resolved=False,
        display_name=None,
        city_name=None,
        country_code=None,
        country_name=None,
        airport_codes=[],
        directory_version=None,
        membership_version=None,
        membership_observed_at=None,
        error=PlaceLookupErrorResponse(code=error.code, reason=error.reason),
    )


def _place_option_response(option: PlaceOption) -> PlaceOptionResponse:
    return PlaceOptionResponse(
        ref=_place_ref_response(option.ref),
        display_name=_place_label_response(option.display_name),
        city_name=_optional_place_label_response(option.city_name),
        country_code=option.country_code,
        country_name=_optional_place_label_response(option.country_name),
        airport_codes=list(option.airport_codes),
        directory_version=option.directory_version,
        membership_version=option.membership_version,
        membership_observed_at=option.membership_observed_at,
    )


def _place_ref_response(ref: PlaceRef) -> PlaceRefResponse:
    return PlaceRefResponse(kind=ref.kind, code=ref.code)


def _place_label_response(label: PlaceLabel) -> PlaceLabelResponse:
    return PlaceLabelResponse(
        text=label.text,
        resolved_locale=label.resolved_locale,
        provenance=label.provenance,
        fallback_reason=label.fallback_reason,
    )


def _optional_place_label_response(label: PlaceLabel | None) -> PlaceLabelResponse | None:
    return _place_label_response(label) if label is not None else None


def _search_response(result: SearchResult, *, booking_secret: str | None = None) -> SearchResponse:
    if result.requested_route is None:
        raise ValueError("search response requires a requested route")
    priced_offers = [
        _offer_response(
            offer,
            ranking_reasons=result.ranking_reasons.get(offer_ranking_key(offer), ()),
            booking_secret=booking_secret,
        )
        for offer in result.priced_offers
    ]
    return SearchResponse(
        search_id=result.search_id,
        requested_route=RequestedRouteResponse(
            origin=_place_option_response(result.requested_route.origin),
            destination=_place_option_response(result.requested_route.destination),
        ),
        offers=priced_offers,
        priced_offers=priced_offers,
        provider_isolated_offers=[
            _offer_response(offer, ranking_reasons=(), booking_secret=booking_secret)
            for offer in result.provider_isolated_offers
        ],
        browser_observed_offers=[
            _browser_observed_offer_response(offer) for offer in result.browser_observed_offers
        ],
        external_links=[_external_search_link_response(link) for link in result.external_links],
        deal_candidates=[
            _deal_candidate_response(candidate) for candidate in result.deal_candidates
        ],
        denied_providers={
            provider_id: ProviderDenialResponse(code=denial.code, message=denial.message)
            for provider_id, denial in result.denied_providers.items()
        },
        warnings=list(result.warnings),
        freshness_summary=_freshness_summary_response(result.freshness_summary),
    )


def _search_intent_from_body(
    body: SearchRequestBody,
    *,
    directory: PlaceDirectory,
    requested_origin: PlaceOption,
    requested_destination: PlaceOption,
) -> SearchIntent:
    return SearchIntent(
        origin=requested_origin.ref.code,
        destination=requested_destination.ref.code,
        departure_date=body.departure_date,
        return_date=body.return_date,
        passengers=body.passengers,
        currency=body.currency,
        adults=body.adults,
        children=body.children,
        infants=body.infants,
        trip_type=body.trip_type,
        origin_kind=requested_origin.ref.kind,
        destination_kind=requested_destination.ref.kind,
        origin_airport_codes=requested_origin.airport_codes,
        destination_airport_codes=requested_destination.airport_codes,
        directory_version=directory.directory_version,
        origin_membership_version=requested_origin.membership_version,
        destination_membership_version=requested_destination.membership_version,
    )


def _deal_search_intent_json(intent: SearchIntent) -> str:
    payload = {
        "origin": intent.origin,
        "destination": intent.destination,
        "departure_date": intent.departure_date,
        "return_date": intent.return_date,
        "passengers": intent.passengers,
        "adults": intent.adults,
        "children": intent.children,
        "infants": intent.infants,
        "trip_type": str(intent.trip_type),
        "currency": intent.currency,
        "origin_kind": PlaceKind(intent.origin_kind).value,
        "destination_kind": PlaceKind(intent.destination_kind).value,
        "origin_airport_codes": list(intent.origin_airport_codes),
        "destination_airport_codes": list(intent.destination_airport_codes),
        "directory_version": intent.directory_version,
        "origin_membership_version": intent.origin_membership_version,
        "destination_membership_version": intent.destination_membership_version,
    }
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def _live_observation_response(observation: LiveObservation) -> LiveObservationResponse:
    observed_at = observation.completed_at or observation.started_at
    return LiveObservationResponse(
        observation_id=str(observation.observation_id),
        source_id=observation.source_id,
        status=observation.status.value,
        result_scope="live_observed" if observation.offers else "none",
        observed_at=observed_at.isoformat() if observed_at is not None else None,
        offers=[_offer_response(offer, ranking_reasons=()) for offer in observation.offers],
        error_code=observation.error_code.value if observation.error_code is not None else None,
        error_message=observation.error_message,
    )


def _personal_observation_service(
    *,
    session: AsyncSession,
    settings: AppSettings,
    clock: Callable[[], datetime],
) -> PersonalObservationService:
    runner = PersonalObserverRunnerAdapter(
        PersonalObserverRunner(
            config=PersonalObserverConfig.from_settings(settings),
            clock=clock,
            crawl4ai_markdown_provider=crawl4ai_browser_markdown_provider_from_settings(settings),
        )
    )
    return PersonalObservationService(
        jobs=BrowserObservationJobRepository(session),
        grants=LiveObservationRepository(session),
        observed_offers=BrowserObservedOfferRepository(session),
        runner=runner,
        observer_enabled=settings.personal_observer_enabled,
        clock=clock,
        result_ttl=timedelta(seconds=settings.personal_observer_result_ttl_seconds),
    )


def _deal_discovery_service(settings: AppSettings) -> DealDiscoveryService | None:
    if not settings.searxng_enabled or not settings.crawl4ai_enabled:
        return None
    return DealDiscoveryService(
        search_client=SearxngClient(
            base_url=settings.searxng_base_url,
            timeout_seconds=settings.searxng_timeout_seconds,
        ),
        markdown_client=Crawl4AiMarkdownClient(
            enabled=settings.crawl4ai_enabled,
            mode=settings.crawl4ai_mode,
            base_url=settings.crawl4ai_base_url,
            api_token=settings.crawl4ai_api_token,
            timeout_seconds=settings.crawl4ai_timeout_seconds,
        ),
        url_policy=DealUrlPolicy(allowed_hosts=settings.deal_discovery_allowed_hosts),
    )


def _personal_observation_response(
    job: BrowserObservationJobRecord,
    offers: tuple[BrowserObservedOffer, ...],
) -> PersonalObservationResponse:
    return PersonalObservationResponse(
        job_id=str(job.id),
        source_id=job.source_id,
        search_id=job.search_id,
        status=job.status.value,
        attempts=job.attempts,
        created_at=job.created_at.isoformat(),
        started_at=job.started_at.isoformat() if job.started_at is not None else None,
        waiting_since=job.waiting_since.isoformat() if job.waiting_since is not None else None,
        operator_resume_requested_at=(
            job.operator_resume_requested_at.isoformat()
            if job.operator_resume_requested_at is not None
            else None
        ),
        operator_abort_requested_at=(
            job.operator_abort_requested_at.isoformat()
            if job.operator_abort_requested_at is not None
            else None
        ),
        completed_at=job.completed_at.isoformat() if job.completed_at is not None else None,
        next_retry_at=job.next_retry_at.isoformat() if job.next_retry_at is not None else None,
        expires_at=job.expires_at.isoformat(),
        operator_instruction=_personal_observation_instruction(job),
        error_code=job.error_code.value if job.error_code is not None else None,
        error_message=job.error_message,
        browser_observed_offers=[_browser_observed_offer_response(offer) for offer in offers],
    )


def _deal_discovery_job_response(
    job: DealDiscoveryJobRecord,
    candidates: tuple[DealCandidate, ...],
) -> DealDiscoveryJobResponse:
    return DealDiscoveryJobResponse(
        job_id=str(job.id),
        search_id=job.search_id,
        status=job.status,
        attempts=job.attempts,
        max_attempts=job.max_attempts,
        created_at=job.created_at.isoformat(),
        started_at=job.started_at.isoformat() if job.started_at is not None else None,
        completed_at=job.completed_at.isoformat() if job.completed_at is not None else None,
        next_retry_at=job.next_retry_at.isoformat() if job.next_retry_at is not None else None,
        deadline_at=job.deadline_at.isoformat(),
        result_count=job.result_count,
        error_code=job.error_code,
        error_message=job.error_message,
        candidates=[_deal_candidate_response(candidate) for candidate in candidates],
    )


def _personal_observation_instruction(job: BrowserObservationJobRecord) -> str | None:
    if job.operator_abort_requested_at is not None:
        return "Abort requested; the worker will stop this browser observation checkpoint."
    if job.operator_resume_requested_at is not None:
        return "Resume requested; the worker will capture the visible provider result page."
    return {
        ObservationStatus.WAITING_FOR_USER: (
            "Complete any provider-side checks in the opened browser; Flight Hunter will capture "
            "the visible result page after resume or local checkpoint timeout."
        ),
        ObservationStatus.NEEDS_HUMAN: "Open the provider page and verify the price manually.",
        ObservationStatus.SOURCE_CHALLENGE: (
            "The source showed a challenge page; verify manually before trusting this result."
        ),
        ObservationStatus.SELECTOR_DRIFT: (
            "The parser could not match expected selectors; run the sanitized fixture parser."
        ),
    }.get(job.status)


def _offer_response(
    offer: FlightOffer,
    *,
    ranking_reasons: tuple[str, ...],
    booking_secret: str | None = None,
) -> OfferResponse:
    risk = assess_offer_risk(offer)
    booking_token = _booking_action_token(offer, booking_secret=booking_secret)
    return OfferResponse(
        provider_id=offer.provider_id,
        provider_offer_id=offer.provider_offer_id,
        origin=offer.origin,
        destination=offer.destination,
        departure_date=offer.departure_date,
        return_date=offer.return_date,
        total_price=_money_response(offer.total_price),
        passengers=offer.passengers,
        price_basis=PriceBasis(offer.price_basis).value,
        observed_at=offer.observed_at.isoformat(),
        freshness=offer.freshness.value,
        requires_live_confirmation=offer.requires_live_confirmation,
        baggage_summary=offer.baggage_summary,
        seller_name=offer.seller_name,
        segments=[_flight_segment_summary_response(segment) for segment in offer.segments],
        booking_action_available=booking_token is not None,
        booking_action_token=booking_token,
        ranking_reasons=list(ranking_reasons),
        risk=_offer_risk_response(risk),
    )


def _booking_action_token(offer: FlightOffer, *, booking_secret: str | None) -> str | None:
    if not booking_secret or not offer.booking_action_ref:
        return None
    return sign_booking_action_token(
        secret_key=booking_secret,
        provider_id=offer.provider_id,
        ref=offer.booking_action_ref,
        now=datetime.now(UTC),
    )


def _flight_segment_summary_response(segment: FlightSegmentSummary) -> FlightSegmentSummaryResponse:
    return FlightSegmentSummaryResponse(
        airline_code=segment.airline_code,
        airline_name=segment.airline_name,
        flight_number=segment.flight_number,
        origin=segment.origin,
        destination=segment.destination,
        depart_at=segment.depart_at,
        arrive_at=segment.arrive_at,
    )


def _offer_risk_response(risk: OfferRiskAssessment) -> OfferRiskResponse:
    return OfferRiskResponse(
        level=risk.level.value,
        flags=[flag.value for flag in risk.flags],
        explanations=list(risk.explanations),
    )


def _external_search_link_response(link: ExternalSearchLink) -> ExternalSearchLinkResponse:
    return ExternalSearchLinkResponse(
        kind=link.kind.value,
        source_id=link.source_id,
        source_name=link.source_name,
        url=link.url,
        origin=link.origin,
        destination=link.destination,
        departure_date=link.departure_date,
        return_date=link.return_date,
        passengers=link.passengers,
        adults=link.adults,
        children=link.children,
        infants=link.infants,
        currency=link.currency,
        source_type=link.source_type,
        purchase_flow=link.purchase_flow,
        price_known=link.price_known,
        requires_external_confirmation=link.requires_external_confirmation,
        notes_ru=link.notes_ru,
        warnings=list(link.warnings),
    )


def _browser_observed_offer_response(
    offer: BrowserObservedOffer,
) -> BrowserObservedOfferResponse:
    return BrowserObservedOfferResponse(
        kind=offer.kind.value,
        observation_id=str(offer.observation_id),
        source_id=offer.source_id,
        source_name=offer.source_name,
        provider_offer_id=offer.provider_offer_id,
        origin=offer.origin,
        destination=offer.destination,
        departure_date=offer.departure_date,
        return_date=offer.return_date,
        total_price=_money_response(offer.total_price) if offer.total_price is not None else None,
        passengers=offer.passengers,
        observed_at=offer.observed_at.isoformat(),
        final_url=offer.final_url,
        display_url=offer.display_url,
        freshness=offer.freshness.value,
        confidence=_confidence_value(offer.confidence),
        parser_version=offer.parser_version,
        parser_warnings=list(offer.parser_warnings),
        airline_name=offer.airline_name,
        airline_iata=offer.airline_iata,
        flight_number=offer.flight_number,
        departure_time_local=offer.departure_time_local,
        arrival_time_local=offer.arrival_time_local,
        duration_minutes=offer.duration_minutes,
        stops=offer.stops,
        baggage_summary=offer.baggage_summary,
        seller_name=offer.seller_name,
        requires_external_confirmation=offer.requires_external_confirmation,
    )


def _deal_candidate_response(candidate: DealCandidate) -> DealCandidateResponse:
    return DealCandidateResponse(
        kind=candidate.kind.value,
        source_id=candidate.source_id,
        url=candidate.url,
        title=candidate.title,
        summary_ru=candidate.summary_ru,
        extracted_price=(
            _money_response(candidate.extracted_price)
            if candidate.extracted_price is not None
            else None
        ),
        extracted_origin=candidate.extracted_origin,
        extracted_destination=candidate.extracted_destination,
        extracted_date_window=candidate.extracted_date_window,
        confidence=_confidence_value(candidate.confidence),
        discovered_at=candidate.discovered_at.isoformat(),
        expires_at=candidate.expires_at.isoformat() if candidate.expires_at is not None else None,
        requires_manual_verification=candidate.requires_manual_verification,
    )


def _auth_me_response(auth_session: AuthSession) -> AuthMeResponse:
    return AuthMeResponse(
        household_id=str(auth_session.household_id),
        user_id=str(auth_session.user_id),
        role=HouseholdRole(auth_session.role).value,
        expires_at=auth_session.expires_at.isoformat(),
    )


def _manual_price_confirmation_response(
    confirmation: ManualPriceConfirmation,
) -> ManualPriceConfirmationResponse:
    return ManualPriceConfirmationResponse(
        id=str(confirmation.id),
        household_id=str(confirmation.household_id),
        user_id=str(confirmation.user_id),
        target_kind=ResultKind(confirmation.target_kind).value,
        target_id=confirmation.target_id,
        source_id=confirmation.source_id,
        status=ManualConfirmationStatus(confirmation.status).value,
        confirmed_at=confirmation.confirmed_at.isoformat(),
        confirmed_price=(
            _money_response(confirmation.confirmed_price)
            if confirmation.confirmed_price is not None
            else None
        ),
        note=confirmation.note,
    )


def _freshness_summary_response(summary: FreshnessSummary) -> FreshnessSummaryResponse:
    return FreshnessSummaryResponse(
        best_price_source=summary.best_price_source,
        freshest_observation_at=(
            summary.freshest_observation_at.isoformat()
            if summary.freshest_observation_at is not None
            else None
        ),
        needs_external_confirmation=summary.needs_external_confirmation,
    )


def _confidence_value(confidence: Confidence | str) -> str:
    return Confidence(confidence).value


def _money_response(money: Money) -> MoneyResponse:
    return MoneyResponse(
        minor_units=money.minor_units,
        currency=money.currency,
        formatted=str(money),
    )


def _airport_autocomplete_response(
    match: AirportAutocompleteMatch,
) -> AirportAutocompleteItemResponse:
    airport = match.airport
    return AirportAutocompleteItemResponse(
        iata_code=airport.iata_code,
        name=airport.name,
        municipality=airport.municipality,
        country_code=airport.country_code,
        label=match.label,
    )


def _airport_search_match_response(match: AirportSearchMatch) -> AirportAutocompleteItemResponse:
    airport = match.airport
    return AirportAutocompleteItemResponse(
        iata_code=airport.iata_code,
        name=airport.name,
        municipality=airport.municipality,
        country_code=airport.country_code,
        label=match.label,
    )


def _nearby_airport_response(nearby: NearbyAirport) -> NearbyAirportResponse:
    airport = nearby.airport
    return NearbyAirportResponse(
        iata_code=airport.iata_code,
        name=airport.name,
        municipality=airport.municipality,
        country_code=airport.country_code,
        distance_km=nearby.distance_km,
        transfer_note=nearby.transfer_note,
    )


def _date_matrix_mobile_calendar_signals(
    body: DateMatrixRequestBody,
    *,
    settings: AppSettings,
    provider_instances: dict[str, AviasalesSearchAdapter],
) -> tuple[tuple[DiscoverySignal, ...], list[str], int]:
    if body.origin is None or body.destination is None:
        return (), ["route_required_for_pricing"], 0
    if body.provider_ids is not None and "aviasales_search" not in body.provider_ids:
        return (), ["aviasales_search_not_requested"], 0
    if body.passengers != 1 or body.children > 0 or body.infants > 0:
        return (), ["passenger_mix_not_supported"], 0
    departure_from = body.departure_date - timedelta(days=body.flexibility_days)
    departure_to = body.departure_date + timedelta(days=body.flexibility_days)
    try:
        _date_matrix_discovery_context(body)
        validate_calendar_price_rows(
            (),
            origin=body.origin,
            destination=body.destination,
            depart_from=departure_from,
            depart_to=departure_to,
            one_way=body.return_date is None,
            currency=body.currency,
        )
    except (AviasalesSearchError, TypeError, ValueError):
        return (), [AviasalesSearchSchemaError.code], 0
    provider = provider_instances.get("aviasales_search")
    if provider is None:
        return (), [_aviasales_configuration_error_code(settings)], 0
    try:
        prices = provider.calendar_prices(
            origin=body.origin,
            destination=body.destination,
            depart_from=departure_from.isoformat(),
            depart_to=departure_to.isoformat(),
            one_way=body.return_date is None,
            currency=body.currency,
        )
    except AviasalesSearchError as exc:
        return (), [exc.code], 1
    observed_at = datetime.now(UTC)
    evidence_namespace = uuid4()
    try:
        prices = validate_calendar_price_rows(
            prices,
            origin=body.origin,
            destination=body.destination,
            depart_from=departure_from,
            depart_to=departure_to,
            one_way=body.return_date is None,
            currency=body.currency,
        )
        signals = tuple(
            map_calendar_price_to_discovery(
                price,
                observed_at=observed_at,
                evidence_namespace=evidence_namespace,
            )
            for price in prices
        )
    except (AviasalesSearchError, TypeError, ValueError):
        return (), [AviasalesSearchSchemaError.code], 1
    if not signals:
        return (), ["aviasales_search_empty"], 1
    return signals, [], 1


def _date_matrix_response(
    matrix: DateMatrix,
    *,
    pricing_denials: list[str] | None = None,
    provider_calls_required: int | None = None,
) -> DateMatrixResponse:
    return DateMatrixResponse(
        cells=[_date_matrix_cell_response(cell) for cell in matrix.cells],
        provider_calls_required=(
            provider_calls_required
            if provider_calls_required is not None
            else matrix.provider_calls_required
        ),
        priced=matrix.priced,
        pricing_denials=pricing_denials or [],
    )


def _date_matrix_cell_response(cell: DateMatrixCell) -> DateMatrixCellResponse:
    signal = cell.discovery_signal
    return DateMatrixCellResponse(
        departure_date=cell.departure_date.isoformat(),
        return_date=cell.return_date.isoformat() if cell.return_date is not None else None,
        stay_days=cell.stay_days,
        amount_minor=signal.observed_amount.minor_units if signal is not None else None,
        currency=signal.observed_amount.currency if signal is not None else None,
        provider_id=signal.provider_id if signal is not None else None,
        source_kind=signal.source_kind if signal is not None else None,
        freshness=cell.freshness.value if cell.freshness is not None else None,
        observed_at=signal.observed_at.isoformat() if signal is not None else None,
        evidence_kind=cell.evidence_kind,
        confirmation_state=cell.confirmation_state,
        requires_live_confirmation=cell.requires_live_confirmation,
        passengers=signal.passengers if signal is not None else None,
        price_basis=(PriceBasis.PROVIDER_SINGLE_ADULT_TICKET if signal is not None else None),
    )


def _date_matrix_discovery_context(
    body: DateMatrixRequestBody,
) -> DateMatrixDiscoveryContext:
    if body.origin is None or body.destination is None:
        raise ValueError("date matrix discovery route is required")
    return DateMatrixDiscoveryContext(
        origin=body.origin,
        destination=body.destination,
        currency=body.currency,
        passengers=body.passengers,
        one_way=body.return_date is None,
    )


def _watch_response(watch: WatchRecord) -> WatchResponse:
    return WatchResponse(
        id=str(watch.id),
        household_id=str(watch.household_id),
        owner_user_id=str(watch.owner_user_id),
        origin=watch.origin,
        destination=watch.destination,
        origin_kind=watch.origin_kind,
        destination_kind=watch.destination_kind,
        origin_airport_codes=list(watch.origin_airport_codes),
        destination_airport_codes=list(watch.destination_airport_codes),
        directory_version=watch.directory_version,
        origin_membership_version=watch.origin_membership_version,
        destination_membership_version=watch.destination_membership_version,
        departure_date=watch.departure_date,
        return_date=watch.return_date,
        passengers=watch.passengers,
        currency=watch.currency,
        allowed_provider_ids=list(watch.allowed_provider_ids),
        enabled=watch.enabled,
        paused_until=watch.paused_until.isoformat() if watch.paused_until is not None else None,
        next_eligible_at=(
            watch.next_eligible_at.isoformat() if watch.next_eligible_at is not None else None
        ),
        scan_interval_seconds=watch.scan_interval_seconds,
        last_scanned_at=(
            watch.last_scanned_at.isoformat() if watch.last_scanned_at is not None else None
        ),
        last_scan_status=watch.last_scan_status,
        last_scan_error_code=watch.last_scan_error_code,
        created_at=watch.created_at.isoformat(),
        updated_at=watch.updated_at.isoformat(),
        version=watch.version,
        archived_at=watch.archived_at.isoformat() if watch.archived_at is not None else None,
        deleted_at=watch.deleted_at.isoformat() if watch.deleted_at is not None else None,
    )


def _watch_snapshot_response(snapshot: PriceSnapshotRecord) -> WatchPriceSnapshotResponse:
    return WatchPriceSnapshotResponse(
        provider_id=snapshot.provider_id,
        itinerary_fingerprint=snapshot.itinerary_fingerprint,
        observed_at=snapshot.observed_at.isoformat(),
        amount_minor=snapshot.price.minor_units,
        currency=snapshot.price.currency,
        freshness=snapshot.freshness.value,
        requires_live_confirmation=snapshot.requires_live_confirmation,
    )


def _watch_update_request_fields(body: WatchUpdateRequestBody) -> dict[str, object]:
    fields: dict[str, object] = {}
    for field in body.model_fields_set:
        if field == "expected_version":
            continue
        fields[field] = getattr(body, field)
    return fields


def _watch_lifecycle_response(
    *,
    watch_id: UUID,
    result: WatchMutationResult,
    success: str,
) -> WatchLifecycleResponse | JSONResponse:
    if result.status == "not_found":
        return _watch_not_found_response()
    if result.status == "version_conflict":
        return _watch_version_conflict_response(result.current_version)
    if result.status != success:
        return JSONResponse(
            status_code=409,
            content={
                "code": "watch_lifecycle_conflict",
                "message": "watch lifecycle operation was not applied",
                "status": result.status,
            },
        )
    return WatchLifecycleResponse(
        watch_id=str(watch_id),
        status=success,
        version=result.current_version or 1,
    )


def _watch_not_found_response() -> JSONResponse:
    return JSONResponse(
        status_code=404,
        content={"code": "watch_not_found", "message": "watch was not found"},
    )


def _watch_version_conflict_response(current_version: int | None) -> JSONResponse:
    return JSONResponse(
        status_code=409,
        content={
            "code": "watch_version_conflict",
            "message": "watch version is stale",
            "current_version": current_version,
        },
    )


def _telegram_update_id(body: dict[str, object]) -> int | None:
    update_id = body.get("update_id")
    return update_id if type(update_id) is int else None


def _telegram_link_command(body: dict[str, object]) -> tuple[int, int, str] | None:
    message = body.get("message")
    if not isinstance(message, dict):
        return None
    text = message.get("text")
    if not isinstance(text, str):
        return None
    parts = text.strip().split(maxsplit=1)
    if len(parts) != 2 or parts[0] != "/link":
        return None
    sender = message.get("from")
    chat = message.get("chat")
    if not isinstance(sender, dict) or not isinstance(chat, dict):
        return None
    telegram_user_id = sender.get("id")
    chat_id = chat.get("id")
    if type(telegram_user_id) is not int or type(chat_id) is not int:
        return None
    return telegram_user_id, chat_id, parts[1].strip()


def _telegram_watches_command(body: dict[str, object]) -> int | None:
    message = body.get("message")
    if not isinstance(message, dict):
        return None
    text = message.get("text")
    if not isinstance(text, str):
        return None
    command = text.strip().split(maxsplit=1)[0]
    if command != "/watches":
        return None
    sender = message.get("from")
    if not isinstance(sender, dict):
        return None
    telegram_user_id = sender.get("id")
    return telegram_user_id if type(telegram_user_id) is int else None


def _telegram_watch_callback(body: dict[str, object]) -> tuple[int, str, str] | None:
    callback_query = body.get("callback_query")
    if not isinstance(callback_query, dict):
        return None
    sender = callback_query.get("from")
    callback_query_id = callback_query.get("id")
    data = callback_query.get("data")
    if (
        not isinstance(sender, dict)
        or not isinstance(callback_query_id, str)
        or not isinstance(data, str)
    ):
        return None
    telegram_user_id = sender.get("id")
    if type(telegram_user_id) is not int:
        return None
    return telegram_user_id, callback_query_id, data


def _telegram_response_status(code: TelegramWebhookDecisionCode) -> tuple[int, str]:
    return {
        TelegramWebhookDecisionCode.ACCEPTED: (202, "accepted"),
        TelegramWebhookDecisionCode.DISABLED: (503, "rejected"),
        TelegramWebhookDecisionCode.DUPLICATE: (200, "ignored"),
        TelegramWebhookDecisionCode.INVALID_UPDATE: (400, "rejected"),
        TelegramWebhookDecisionCode.SECRET_MISMATCH: (403, "rejected"),
    }[code]


app = create_app()
