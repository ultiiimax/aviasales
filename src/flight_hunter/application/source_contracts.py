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
            source_id="aviasales_search",
            display_name="Aviasales mobile API",
            stage=ImplementationStage.IMPLEMENTED,
            adapter_module="flight_hunter.providers.aviasales_search.adapter",
            contract_file="docs/provider-contracts/aviasales-search.md",
            terms_url="https://tickets-api.aviasales.ru",
            required_env=(
                "AVIASALES_SEARCH_ENABLED",
                "AVIASALES_SEARCH_SIGNATURE",
                "AVIASALES_SEARCH_MARKER",
            ),
            operations=(
                "live_search",
                "lazy_purchase_url",
                "suggest_places",
                "hot_offers",
                "calendar_prices",
                "typed_graphql_blocks",
                "safe_smoke_check",
            ),
            invariants=(
                "live_source",
                "mergeable_results",
                "background_watch_scans_allowed",
                f"internal_rate_limit_rpm={settings.aviasales_search_internal_rpm}",
                "no_raw_payload_persistence",
                "no_secret_logging",
                "purchase_url_explicit_resolve",
                "no_signed_purchase_url_in_callbacks",
            ),
            notes=(
                "Typed Aviasales mobile API adapter. Exact search is live and mergeable; purchase "
                "URLs are resolved only by explicit booking action token. Suggest, hot offers, "
                "calendar/explore and selected GraphQL feed blocks are typed operations, not a "
                "generic proxy."
            ),
            egress_policy=(
                "https://tickets-api.aviasales.ru",
                "https://suggest.aviasales.ru",
                "https://explore-api.aviasales.ru",
                "https://ariadne.aviasales.ru",
                "https://www.aviasales.ru",
            ),
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
