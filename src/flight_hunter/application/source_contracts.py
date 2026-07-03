from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from urllib.parse import urlparse

from flight_hunter.application.provider_registry import ProviderRegistry, ProviderStatus
from flight_hunter.config import AppSettings


class ImplementationStage(StrEnum):
    IMPLEMENTED = "implemented"
    POLICY_SKELETON = "policy_skeleton"
    CONTRACT_ONLY = "contract_only"
    EXTERNAL_CLICKOUT = "external_clickout"


@dataclass(frozen=True, slots=True)
class SourceContract:
    source_id: str
    display_name: str
    stage: ImplementationStage
    adapter_module: str | None
    contract_file: str
    terms_url: str
    required_env: tuple[str, ...]
    operations: tuple[str, ...]
    invariants: tuple[str, ...]
    notes: str
    egress_policy: tuple[str, ...] = ()
    default_enabled: bool | None = None
    default_credentials_present: bool = True
    default_access_approved: bool = True
    default_data_kind: str = "reference"
    default_merge_scope: str = "not_applicable"
    default_background_requests_allowed: bool = True
    default_user_action_required: bool = False
    default_blocked_reasons: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class SourceReadiness:
    source_id: str
    display_name: str
    stage: ImplementationStage
    adapter_module: str | None
    contract_file: str
    terms_url: str
    required_env: tuple[str, ...]
    operations: tuple[str, ...]
    invariants: tuple[str, ...]
    egress_policy: tuple[str, ...]
    notes: str
    enabled: bool
    credentials_present: bool
    access_approved: bool
    data_kind: str
    merge_scope: str
    background_requests_allowed: bool
    user_action_required: bool
    blocked_reasons: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class SourceContractCatalog:
    contracts: tuple[SourceContract, ...]
    provider_statuses: tuple[ProviderStatus, ...]

    @classmethod
    def default(
        cls,
        *,
        settings: AppSettings,
        registry: ProviderRegistry,
    ) -> SourceContractCatalog:
        return cls(
            contracts=_default_contracts(settings),
            provider_statuses=registry.statuses(),
        )

    def readiness(self) -> tuple[SourceReadiness, ...]:
        provider_statuses = {status.provider_id: status for status in self.provider_statuses}
        readiness: list[SourceReadiness] = []
        for contract in self.contracts:
            status = provider_statuses.get(contract.source_id)
            readiness.append(_readiness_for(contract, status))
        return tuple(readiness)


def _readiness_for(
    contract: SourceContract,
    status: ProviderStatus | None,
) -> SourceReadiness:
    blocked_reasons = list(status.blocked_reasons if status is not None else ())
    blocked_reasons.extend(contract.default_blocked_reasons)
    if contract.stage in {ImplementationStage.POLICY_SKELETON, ImplementationStage.CONTRACT_ONLY}:
        blocked_reasons.append("adapter_not_implemented")

    if status is None:
        enabled = (
            contract.default_enabled
            if contract.default_enabled is not None
            else contract.stage == ImplementationStage.IMPLEMENTED
        )
        return SourceReadiness(
            source_id=contract.source_id,
            display_name=contract.display_name,
            stage=contract.stage,
            adapter_module=contract.adapter_module,
            contract_file=contract.contract_file,
            terms_url=contract.terms_url,
            required_env=contract.required_env,
            operations=contract.operations,
            invariants=contract.invariants,
            egress_policy=contract.egress_policy,
            notes=contract.notes,
            enabled=enabled,
            credentials_present=contract.default_credentials_present,
            access_approved=contract.default_access_approved,
            data_kind=contract.default_data_kind,
            merge_scope=contract.default_merge_scope,
            background_requests_allowed=contract.default_background_requests_allowed,
            user_action_required=contract.default_user_action_required,
            blocked_reasons=tuple(dict.fromkeys(blocked_reasons)),
        )

    return SourceReadiness(
        source_id=contract.source_id,
        display_name=contract.display_name,
        stage=contract.stage,
        adapter_module=contract.adapter_module,
        contract_file=contract.contract_file,
        terms_url=contract.terms_url,
        required_env=contract.required_env,
        operations=contract.operations,
        invariants=contract.invariants,
        egress_policy=contract.egress_policy,
        notes=contract.notes,
        enabled=status.enabled,
        credentials_present=status.credentials_present,
        access_approved=status.access_approved,
        data_kind=status.data_kind.value,
        merge_scope=status.merge_scope.value,
        background_requests_allowed=status.background_requests_allowed,
        user_action_required=status.user_action_required,
        blocked_reasons=tuple(dict.fromkeys(blocked_reasons)),
    )


def _default_contracts(settings: AppSettings) -> tuple[SourceContract, ...]:
    return (
        SourceContract(
            source_id="fake",
            display_name="Deterministic demo provider",
            stage=ImplementationStage.IMPLEMENTED,
            adapter_module="flight_hunter.providers.fake",
            contract_file="docs/provider-contracts/demo-browser-observer.md",
            terms_url="https://flight-hunter.local/policies/fake-provider",
            required_env=(),
            operations=("search", "watch_scheduler_fixture"),
            invariants=("no_external_network", "deterministic_fixtures", "no_live_claims"),
            notes="Demo-only provider used to exercise product flows without external keys.",
            egress_policy=("no_external_network",),
        ),
        SourceContract(
            source_id="aviasales_data",
            display_name="Aviasales / Travelpayouts Data API",
            stage=ImplementationStage.IMPLEMENTED,
            adapter_module="flight_hunter.providers.aviasales_data.adapter",
            contract_file="docs/provider-contracts/aviasales-data.md",
            terms_url=(
                "https://support.travelpayouts.com/hc/en-us/articles/203956163-Aviasales-Data-API"
            ),
            required_env=(
                "AVIASALES_DATA_ENABLED",
                "TRAVELPAYOUTS_API_TOKEN",
                "TRAVELPAYOUTS_MARKER",
            ),
            operations=(
                "cached_search",
                "price_range_cached_radar",
                "grouped_cached_radar",
                "latest_cached_radar",
                "week_matrix_cached_radar",
                "month_matrix_cached_radar",
                "nearest_places_cached_radar",
                "popular_directions_cached_radar",
                "special_offers_cached_radar",
                "cached_deal_seed_discovery",
                "safe_smoke_check",
            ),
            invariants=(
                "cached_not_live",
                "server_side_token_only",
                f"internal_rate_limit_rpm={settings.aviasales_data_internal_rpm}",
                "sanitized_rate_limit_headers",
                "no_raw_payload_persistence",
                "single_adult_ticket_price_basis_only",
                "cached_deal_seeds_candidate_only",
            ),
            notes=(
                "Typed HTTP client, query planner, mapper and smoke helper are implemented for "
                "prices_for_dates, search_by_price_range, grouped_prices, get_latest_prices, "
                "week-matrix, month-matrix, nearest-places-matrix, get_popular_directions and "
                "get_special_offers. Cached-radar rows can also be persisted as manual "
                "verification DealCandidate seeds without exposing provider booking links. "
                "Remaining Data API endpoints must stay explicit cached-radar follow-up work."
            ),
            egress_policy=("https://api.travelpayouts.com", "https://www.aviasales.ru"),
        ),
        SourceContract(
            source_id="aviasales_search",
            display_name="Aviasales Flight Search API",
            stage=ImplementationStage.POLICY_SKELETON,
            adapter_module=None,
            contract_file="docs/provider-contracts/aviasales-search.md",
            terms_url=(
                "https://support.travelpayouts.com/hc/en-us/articles/"
                "30565016140434-Aviasales-Flight-Search-API-real-time-and-multi-city-search"
            ),
            required_env=(
                "AVIASALES_SEARCH_ENABLED",
                "AVIASALES_SEARCH_ACCESS_APPROVED",
                "AVIASALES_SEARCH_CONFIRMED_MAU_50000",
                "AVIASALES_SEARCH_TOKEN",
                "AVIASALES_SEARCH_MARKER",
                "AVIASALES_SEARCH_REAL_HOST",
            ),
            operations=("user_action_live_search", "click_time_booking_action"),
            invariants=(
                "no_background_calls",
                "provider_isolated_results",
                "booking_link_click_gate",
                "no_booking_link_preload",
                "requires_real_user_ip",
            ),
            notes=(
                "Policy and gateway tests exist, but the adapter is intentionally not wired until "
                "approved access and current docs are re-verified."
            ),
            egress_policy=("not_configured_until_access_approved",),
        ),
        SourceContract(
            source_id="skyscanner_indicative",
            display_name="Skyscanner Indicative Prices",
            stage=ImplementationStage.CONTRACT_ONLY,
            adapter_module=None,
            contract_file="docs/PROVIDER_MATRIX.md",
            terms_url="https://developers.skyscanner.net/docs/flights-indicative-prices/overview",
            required_env=("SKYSCANNER_INDICATIVE_ENABLED", "SKYSCANNER_ACCESS_APPROVED"),
            operations=("indicative_flexible_discovery",),
            invariants=("disabled_until_partnership", "contract_flags_required"),
            notes=(
                "Not implemented; requires partnership approval and fixture-backed contract tests."
            ),
            egress_policy=("not_configured_until_access_approved",),
        ),
        SourceContract(
            source_id="skyscanner_live",
            display_name="Skyscanner Live Prices",
            stage=ImplementationStage.CONTRACT_ONLY,
            adapter_module=None,
            contract_file="docs/PROVIDER_MATRIX.md",
            terms_url="https://developers.skyscanner.net/docs/flights-live-prices/overview",
            required_env=("SKYSCANNER_LIVE_ENABLED", "SKYSCANNER_ACCESS_APPROVED"),
            operations=("user_generated_live_create_poll",),
            invariants=("no_background_calls", "user_action_required", "no_archived_sdk"),
            notes="Not implemented; must remain disabled until partnership approval.",
            egress_policy=("not_configured_until_access_approved",),
        ),
        SourceContract(
            source_id="duffel",
            display_name="Duffel Flights",
            stage=ImplementationStage.CONTRACT_ONLY,
            adapter_module=None,
            contract_file="docs/PROVIDER_MATRIX.md",
            terms_url="https://duffel.com/docs/api/v2/offer-requests",
            required_env=("DUFFEL_ENABLED", "DUFFEL_ACCESS_TOKEN", "DUFFEL_MODE"),
            operations=("offer_request", "offer_retrieve_before_purchase"),
            invariants=("test_live_mode_separation", "offer_expiry_required"),
            notes="Not implemented; future adapter must keep booking/payment feature-gated.",
            egress_policy=("not_configured_until_access_approved",),
        ),
        SourceContract(
            source_id="ourairports",
            display_name="OurAirports reference data",
            stage=ImplementationStage.IMPLEMENTED,
            adapter_module="flight_hunter.geo.ourairports_importer",
            contract_file="docs/PROVIDER_MATRIX.md",
            terms_url="https://ourairports.com/data/",
            required_env=("OURAIRPORTS_IMPORT_ENABLED",),
            operations=("airport_import", "airport_search", "nearby_airports"),
            invariants=("public_domain_csv", "provenance_visible", "no_airfare_savings_claim"),
            notes=(
                "SQLite-compatible importer and search repository exist; "
                "PostGIS remains future work."
            ),
            egress_policy=("operator_supplied_public_csv_files",),
        ),
        SourceContract(
            source_id="searxng",
            display_name="SearXNG deal URL discovery",
            stage=ImplementationStage.IMPLEMENTED,
            adapter_module="flight_hunter.deals.searxng_client",
            contract_file="docs/provider-contracts/searxng.md",
            terms_url="https://docs.searxng.org/dev/search_api.html",
            required_env=("SEARXNG_ENABLED", "SEARXNG_BASE_URL"),
            operations=("manual_deal_url_search", "safe_source_smoke"),
            invariants=(
                "deal_candidates_not_price_truth",
                "json_search_self_hosted",
                "public_url_policy_before_fetch",
                "no_raw_payload_persistence",
                "typed_sanitized_transport_errors",
            ),
            notes=(
                "SearXNG finds public candidate URLs only. Titles/snippets are untrusted hints and "
                "never enter priced offer ranking."
            ),
            egress_policy=(
                _base_url_policy("SEARXNG_BASE_URL", settings.searxng_base_url),
                "does_not_fetch_result_pages",
            ),
            default_enabled=settings.searxng_enabled,
            default_data_kind="deal_feed",
            default_merge_scope="candidate_only",
            default_background_requests_allowed=False,
            default_user_action_required=True,
            default_blocked_reasons=() if settings.searxng_enabled else ("searxng_disabled",),
        ),
        SourceContract(
            source_id="crawl4ai",
            display_name="Crawl4AI markdown extractor",
            stage=ImplementationStage.IMPLEMENTED,
            adapter_module="flight_hunter.deals.crawl4ai_client",
            contract_file="docs/provider-contracts/crawl4ai.md",
            terms_url="https://docs.crawl4ai.com/",
            required_env=("CRAWL4AI_ENABLED", "CRAWL4AI_MODE", "CRAWL4AI_BASE_URL"),
            operations=(
                "manual_deal_page_markdown",
                "browser_observation_markdown_diagnostic",
                "safe_source_smoke",
            ),
            invariants=(
                "url_policy_before_import_or_fetch",
                "markdown_untrusted_text",
                "size_cap_enforced",
                "no_llm_extraction_or_stealth",
                "browser_diagnostic_final_url_only",
            ),
            notes=(
                "Crawl4AI converts allowed public deal pages and already visited personal-observer "
                "final URLs to markdown diagnostics; it never confirms price availability."
            ),
            egress_policy=(
                _base_url_policy("CRAWL4AI_BASE_URL", settings.crawl4ai_base_url),
                "fetches_public_http_urls_after_deal_url_policy",
                _deal_page_allowlist_policy(settings.deal_discovery_allowed_hosts),
                "browser_diagnostics_final_url_only",
            ),
            default_enabled=settings.crawl4ai_enabled,
            default_data_kind="deal_feed",
            default_merge_scope="candidate_only",
            default_background_requests_allowed=False,
            default_user_action_required=True,
            default_blocked_reasons=() if settings.crawl4ai_enabled else ("crawl4ai_disabled",),
        ),
        SourceContract(
            source_id="deal_discovery",
            display_name="Manual deal discovery pipeline",
            stage=ImplementationStage.IMPLEMENTED,
            adapter_module="flight_hunter.deals.service",
            contract_file="docs/provider-contracts/searxng.md",
            terms_url="https://docs.searxng.org/dev/search_api.html",
            required_env=("SEARXNG_ENABLED", "CRAWL4AI_ENABLED"),
            operations=("manual_deal_discovery", "persist_manual_candidate"),
            invariants=(
                "requires_manual_verification",
                "not_priced_offer",
                "outside_merged_ranking",
                "dedupe_before_markdown_fetch",
                "markdown_evidence_only",
                "partial_page_fetch_success_preserved",
            ),
            notes=(
                "Orchestrates bounded SearXNG query strategy plus Crawl4AI markdown extraction. "
                "SearXNG title/content are URL-discovery metadata only; price, route and date "
                "evidence come from page markdown. Output is `DealCandidate` only."
            ),
            egress_policy=(
                "searxng_self_hosted_component",
                "crawl4ai_self_hosted_component",
                "public_http_urls_after_deal_url_policy",
                _deal_page_allowlist_policy(settings.deal_discovery_allowed_hosts),
            ),
            default_enabled=settings.searxng_enabled and settings.crawl4ai_enabled,
            default_data_kind="deal_feed",
            default_merge_scope="candidate_only",
            default_background_requests_allowed=False,
            default_user_action_required=True,
            default_blocked_reasons=tuple(
                reason
                for enabled, reason in (
                    (settings.searxng_enabled, "searxng_disabled"),
                    (settings.crawl4ai_enabled, "crawl4ai_disabled"),
                )
                if not enabled
            ),
        ),
    )


def _base_url_policy(env_name: str, value: str) -> str:
    parsed = urlparse(value)
    host = parsed.hostname or "unconfigured"
    return f"{env_name}_host={host}"


def _deal_page_allowlist_policy(allowed_hosts: tuple[str, ...]) -> str:
    if not allowed_hosts:
        return "DEAL_DISCOVERY_ALLOWED_HOSTS=public_http_after_policy"
    return "DEAL_DISCOVERY_ALLOWED_HOSTS=" + ",".join(allowed_hosts)
