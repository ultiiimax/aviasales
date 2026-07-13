from __future__ import annotations

import hashlib
from collections.abc import Callable, Mapping
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from typing import Protocol

from flight_hunter.application.provider_registry import ProviderRegistry
from flight_hunter.application.search_planner import SearchPlanner
from flight_hunter.domain.offers import FlightOffer, SearchIntent
from flight_hunter.domain.policy import ExecutionContext, MergeScope
from flight_hunter.domain.provider_errors import ProviderOperationError
from flight_hunter.domain.ranking import OfferRanker, offer_ranking_key
from flight_hunter.domain.search_results import (
    BrowserObservedOffer,
    DealCandidate,
    ExternalSearchLink,
    FreshnessSummary,
)
from flight_hunter.providers.fake import FakeFlightProvider
from flight_hunter.providers.ru_clickout import RuClickoutLinkBuilder, default_ru_aggregator_specs


class SearchProvider(Protocol):
    def search(
        self,
        intent: SearchIntent,
        *,
        request_fingerprint: str,
        context: ExecutionContext,
    ) -> tuple[FlightOffer, ...]: ...


@dataclass(frozen=True, slots=True)
class SearchRequest:
    origin: str
    destination: str
    departure_date: str
    return_date: str | None
    passengers: int
    currency: str
    provider_ids: tuple[str, ...] | None
    adults: int | None = None
    children: int = 0
    infants: int = 0
    trip_type: str | None = None


@dataclass(frozen=True, slots=True)
class ProviderDenial:
    provider_id: str
    code: str
    message: str


@dataclass(frozen=True, slots=True)
class SearchResult:
    search_id: str
    priced_offers: tuple[FlightOffer, ...]
    mergeable_offers: tuple[FlightOffer, ...]
    provider_isolated_offers: tuple[FlightOffer, ...]
    browser_observed_offers: tuple[BrowserObservedOffer, ...]
    external_links: tuple[ExternalSearchLink, ...]
    deal_candidates: tuple[DealCandidate, ...]
    ranking_reasons: dict[str, tuple[str, ...]]
    denied_providers: dict[str, ProviderDenial]
    warnings: tuple[str, ...]
    freshness_summary: FreshnessSummary


class DemoSearchService:
    def __init__(
        self,
        *,
        registry: ProviderRegistry,
        clock: Callable[[], datetime] | None = None,
        providers: Mapping[str, SearchProvider] | None = None,
        link_builder: RuClickoutLinkBuilder | None = None,
        enabled_external_source_ids: tuple[str, ...] | None = None,
    ) -> None:
        self._registry = registry
        self._clock = clock or (lambda: datetime.now(UTC))
        self._planner = SearchPlanner(clock=self._clock)
        self._ranker = OfferRanker()
        self._fake_provider = FakeFlightProvider(clock=self._clock)
        self._providers: dict[str, SearchProvider] = {"fake": self._fake_provider}
        if providers is not None:
            self._providers.update(providers)
        self._link_builder = link_builder or RuClickoutLinkBuilder(default_ru_aggregator_specs())
        self._enabled_external_source_ids = enabled_external_source_ids

    def search(self, request: SearchRequest) -> SearchResult:
        intent = SearchIntent(
            origin=request.origin,
            destination=request.destination,
            departure_date=request.departure_date,
            return_date=request.return_date,
            passengers=request.passengers,
            currency=request.currency,
            adults=request.adults,
            children=request.children,
            infants=request.infants,
            trip_type=request.trip_type,
        )
        request_fingerprint = self._fingerprint(request)
        plan = self._planner.plan(
            list(self._registry.planning_candidates(request.provider_ids)),
            context=ExecutionContext.WEB_USER_ACTION,
            request_fingerprint=request_fingerprint,
        )
        denied = {
            provider_id: ProviderDenial(
                provider_id=provider_id,
                code=decision.code.value,
                message=decision.message,
            )
            for provider_id, decision in plan.denied.items()
        }

        mergeable: list[FlightOffer] = []
        provider_isolated: list[FlightOffer] = []
        for step in plan.allowed:
            provider = self._providers.get(step.provider_id)
            if provider is None:
                continue
            try:
                offers = provider.search(
                    intent,
                    request_fingerprint=request_fingerprint,
                    context=ExecutionContext.WEB_USER_ACTION,
                )
            except ProviderOperationError as exc:
                denied[step.provider_id] = ProviderDenial(
                    provider_id=step.provider_id,
                    code=exc.code,
                    message="provider request failed",
                )
                continue
            if step.merge_scope == MergeScope.MERGEABLE:
                mergeable.extend(offers)
            elif step.merge_scope == MergeScope.PROVIDER_ISOLATED:
                provider_isolated.extend(offers)

        ranked_mergeable = self._ranker.rank(tuple(mergeable))
        priced_offers = tuple(item.offer for item in ranked_mergeable)
        external_links = self._link_builder.build_all(
            intent,
            enabled_source_ids=self._enabled_external_source_ids,
        )
        warnings = _warnings_for_result(external_links)
        return SearchResult(
            search_id=request_fingerprint,
            priced_offers=priced_offers,
            mergeable_offers=priced_offers,
            provider_isolated_offers=tuple(provider_isolated),
            browser_observed_offers=(),
            external_links=external_links,
            deal_candidates=(),
            ranking_reasons={
                offer_ranking_key(item.offer): item.reasons for item in ranked_mergeable
            },
            denied_providers=denied,
            warnings=warnings,
            freshness_summary=_freshness_summary(
                priced_offers=priced_offers,
                browser_observed_offers=(),
                external_links=external_links,
            ),
        )

    @staticmethod
    def _fingerprint(request: SearchRequest) -> str:
        provider_part = ",".join(request.provider_ids or ())
        raw = "|".join(
            (
                request.origin.upper(),
                request.destination.upper(),
                request.departure_date,
                request.return_date or "",
                str(request.passengers),
                str(request.adults) if request.adults is not None else "",
                str(request.children),
                str(request.infants),
                request.trip_type or "",
                request.currency.upper(),
                provider_part,
            )
        )
        return "sha256:" + hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _warnings_for_result(external_links: tuple[ExternalSearchLink, ...]) -> tuple[str, ...]:
    warnings: list[str] = []
    if external_links:
        warnings.append("external_links_are_not_prices")
    link_warnings = sorted({warning for link in external_links for warning in link.warnings})
    warnings.extend(link_warnings)
    return tuple(warnings)


def _freshness_summary(
    *,
    priced_offers: tuple[FlightOffer, ...],
    browser_observed_offers: tuple[BrowserObservedOffer, ...],
    external_links: tuple[ExternalSearchLink, ...],
) -> FreshnessSummary:
    observed_times = [offer.observed_at for offer in priced_offers]
    observed_times.extend(offer.observed_at for offer in browser_observed_offers)
    return FreshnessSummary(
        best_price_source=priced_offers[0].provider_id if priced_offers else None,
        freshest_observation_at=max(observed_times) if observed_times else None,
        needs_external_confirmation=(
            any(offer.requires_live_confirmation for offer in priced_offers)
            or any(offer.requires_external_confirmation for offer in browser_observed_offers)
            or any(link.requires_external_confirmation for link in external_links)
        ),
    )


def with_browser_observed_offers(
    result: SearchResult,
    browser_observed_offers: tuple[BrowserObservedOffer, ...],
) -> SearchResult:
    return with_browser_observed_offers_and_deal_candidates(
        result,
        browser_observed_offers=browser_observed_offers,
        deal_candidates=result.deal_candidates,
    )


def with_browser_observed_offers_and_deal_candidates(
    result: SearchResult,
    *,
    browser_observed_offers: tuple[BrowserObservedOffer, ...],
    deal_candidates: tuple[DealCandidate, ...],
) -> SearchResult:
    warnings = list(result.warnings)
    if deal_candidates and "deal_candidates_require_manual_verification" not in warnings:
        warnings.append("deal_candidates_require_manual_verification")
    return replace(
        result,
        browser_observed_offers=browser_observed_offers,
        deal_candidates=deal_candidates,
        warnings=tuple(warnings),
        freshness_summary=_freshness_summary(
            priced_offers=result.priced_offers,
            browser_observed_offers=browser_observed_offers,
            external_links=result.external_links,
        ),
    )
