from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime

from flight_hunter.domain.offers import FlightOffer, SearchIntent
from flight_hunter.domain.policy import (
    ExecutionContext,
    ProviderOperation,
    ProviderPolicy,
)
from flight_hunter.policy.guard import PolicyDecision, ProviderPolicyGuard
from flight_hunter.providers.aviasales_search.client import (
    AviasalesSearchClient,
    AviasalesSearchSchemaError,
    CalendarPrice,
    GraphqlFeedBlock,
    HotOffer,
    SearchStartParams,
    SuggestPlace,
)
from flight_hunter.providers.aviasales_search.mapper import map_parsed_ticket
from flight_hunter.providers.aviasales_search.schemas import AviasalesSearchParseError, parse_chunks


class AviasalesSearchAdapter:
    """Live Aviasales mobile API search adapter.

    Local hobby project: live data, background watch scans allowed, results are
    mergeable. Booking (purchase) URL is resolved lazily via
    :meth:`resolve_purchase_url` on explicit user click, not preloaded.
    """

    def __init__(
        self,
        *,
        client: AviasalesSearchClient,
        enabled: bool,
        credentials_present: bool,
        internal_rpm: int = 20,
        clock: Callable[[], datetime] | None = None,
        poll_rounds: int = 8,
        poll_delay: float = 2.0,
        poll_limit: int = 50,
    ) -> None:
        self._client = client
        self._clock = clock or (lambda: datetime.now(UTC))
        self._poll_rounds = poll_rounds
        self._poll_delay = poll_delay
        self._poll_limit = poll_limit
        now = self._clock()
        self.policy = ProviderPolicy.aviasales_search_live(
            terms_verified_at=now,
            credentials_present=credentials_present,
            enabled=enabled,
            internal_rpm=internal_rpm,
        )
        self._guard = ProviderPolicyGuard(clock=self._clock)

    def authorize(
        self,
        *,
        operation: ProviderOperation,
        context: ExecutionContext,
        request_fingerprint: str,
    ) -> PolicyDecision:
        return self._guard.authorize(
            self.policy,
            operation=operation,
            context=context,
            request_fingerprint=request_fingerprint,
        )

    def search(
        self,
        intent: SearchIntent,
        *,
        request_fingerprint: str,
        context: ExecutionContext = ExecutionContext.WEB_USER_ACTION,
    ) -> tuple[FlightOffer, ...]:
        decision = self.authorize(
            operation=ProviderOperation.SEARCH,
            context=context,
            request_fingerprint=request_fingerprint,
        )
        if not decision.allowed:
            return ()

        params = SearchStartParams(
            origin=intent.origin,
            destination=intent.destination,
            departure_date=intent.departure_date,
            return_date=intent.return_date,
            adults=intent.passenger_mix.adults,
            children=intent.passenger_mix.children,
            infants=intent.passenger_mix.infants,
            trip_class="Y",
            currency=intent.currency,
            market="RU",
        )
        start = self._client.start_search(params)
        chunks = self._client.poll_results(
            start.results_url,
            start.search_id,
            rounds=self._poll_rounds,
            delay=self._poll_delay,
            limit=self._poll_limit,
        )
        try:
            parsed = parse_chunks(chunks)
        except AviasalesSearchParseError as exc:
            raise AviasalesSearchSchemaError() from exc
        observed_at = self._clock()
        return tuple(
            map_parsed_ticket(
                ticket,
                observed_at=observed_at,
                passengers=intent.passengers,
                search_id=start.search_id,
                results_url=start.results_url,
            )
            for ticket in parsed
        )

    def resolve_purchase_url(
        self,
        *,
        search_id: str,
        proposal_id: str,
        results_url: str,
        request_fingerprint: str,
        context: ExecutionContext = ExecutionContext.WEB_USER_ACTION,
    ) -> str | None:
        decision = self.authorize(
            operation=ProviderOperation.BOOKING_ACTION,
            context=context,
            request_fingerprint=request_fingerprint,
        )
        if not decision.allowed:
            return None
        return self._client.get_purchase_url(search_id, proposal_id, results_url)

    def suggest_places(
        self,
        term: str,
        *,
        locale: str = "ru",
        place_types: tuple[str, ...] = ("city", "airport"),
        max_results: int = 5,
    ) -> tuple[SuggestPlace, ...]:
        return self._client.suggest_places(
            term,
            locale=locale,
            place_types=place_types,
            max_results=max_results,
        )

    def hot_offers(
        self,
        *,
        origin: str,
        origin_type: str = "city",
        market: str = "RU",
        currency: str = "rub",
        one_way: bool = True,
    ) -> tuple[HotOffer, ...]:
        return self._client.hot_offers(
            origin=origin,
            origin_type=origin_type,
            market=market,
            currency=currency,
            one_way=one_way,
        )

    def calendar_prices(
        self,
        *,
        origin: str,
        destination: str,
        depart_from: str,
        depart_to: str,
        one_way: bool,
        currency: str = "rub",
    ) -> tuple[CalendarPrice, ...]:
        return self._client.calendar_prices(
            origin=origin,
            destination=destination,
            depart_from=depart_from,
            depart_to=depart_to,
            one_way=one_way,
            currency=currency,
        )

    def main_page_blocks(
        self,
        *,
        origin: str,
        origin_type: str = "CITY",
        market: str = "RU",
        currency: str = "rub",
        language: str = "ru",
        one_way: bool = True,
    ) -> tuple[GraphqlFeedBlock, ...]:
        return self._client.main_page_blocks(
            origin=origin,
            origin_type=origin_type,
            market=market,
            currency=currency,
            language=language,
            one_way=one_way,
        )
