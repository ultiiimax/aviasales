from __future__ import annotations

import asyncio
import re
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime

from flight_hunter.domain.agent_evidence import ConfirmedOfferEvidence, DiscoverySignal
from flight_hunter.domain.agent_search import (
    CapabilityState,
    LocationScopeKind,
    ProviderCapabilitySnapshot,
)
from flight_hunter.domain.policy import ExecutionContext, ProviderOperation, ProviderPolicy
from flight_hunter.policy.guard import ProviderPolicyGuard
from flight_hunter.providers.aviasales_search.client import (
    AviasalesSearchClient,
    AviasalesSearchError,
    AviasalesSearchSchemaError,
    CalendarPrice,
    SearchStartParams,
)
from flight_hunter.providers.aviasales_search.mapper import (
    map_calendar_price_to_discovery,
    map_parsed_ticket_to_evidence,
)
from flight_hunter.providers.aviasales_search.schemas import (
    AviasalesSearchParseError,
    ProviderLocation,
    parse_chunks,
)

_ISO_CURRENCY_RE = re.compile(r"^[A-Z]{3}$")


class AviasalesSearchCapabilityError(AviasalesSearchError):
    code = "aviasales_search_capability_error"

    def __init__(self, reason: str) -> None:
        super().__init__(f"{self.code}:{reason}")


class AviasalesSearchPolicyDenied(AviasalesSearchError):
    code = "aviasales_search_policy_denied"

    def __init__(self, reason: str) -> None:
        super().__init__(f"{self.code}:{reason}")


@dataclass(frozen=True, slots=True, repr=False)
class ExactSearchContinuation:
    """Opaque state for server-side exact-search resumption only."""

    search_id: str
    results_url: str
    last_update_timestamp: int
    request_id: str

    def __post_init__(self) -> None:
        if not self.search_id:
            raise ValueError("search_id is required")
        if not self.results_url:
            raise ValueError("results_url is required")
        if type(self.last_update_timestamp) is not int or self.last_update_timestamp < 0:
            raise ValueError("last_update_timestamp must be a non-negative integer")
        if not self.request_id:
            raise ValueError("request_id is required")

    def __repr__(self) -> str:
        return "ExactSearchContinuation(<private>)"


@dataclass(frozen=True, slots=True)
class ExactPollOutcome:
    evidence: tuple[ConfirmedOfferEvidence, ...]
    next_cursor: int
    complete: bool

    def __post_init__(self) -> None:
        evidence = tuple(self.evidence)
        if not all(isinstance(item, ConfirmedOfferEvidence) for item in evidence):
            raise TypeError("evidence must contain ConfirmedOfferEvidence values")
        if type(self.next_cursor) is not int or self.next_cursor < 0:
            raise ValueError("next_cursor must be a non-negative integer")
        if type(self.complete) is not bool:
            raise TypeError("complete must be a boolean")
        object.__setattr__(self, "evidence", evidence)


@dataclass(frozen=True, slots=True)
class CalendarSearchParams:
    origin: ProviderLocation
    destination: ProviderLocation
    depart_from: date
    depart_to: date
    one_way: bool
    currency: str
    adults: int = 1
    children: int = 0
    infants: int = 0

    def __post_init__(self) -> None:
        if not isinstance(self.origin, ProviderLocation):
            raise TypeError("origin must be ProviderLocation")
        if not isinstance(self.destination, ProviderLocation):
            raise TypeError("destination must be ProviderLocation")
        if type(self.depart_from) is not date or type(self.depart_to) is not date:
            raise TypeError("calendar bounds must be dates")
        if self.depart_to < self.depart_from:
            raise ValueError("depart_to cannot be before depart_from")
        if type(self.one_way) is not bool:
            raise TypeError("one_way must be a boolean")
        if not isinstance(self.currency, str):
            raise TypeError("currency must be a string")
        currency = self.currency.upper()
        if not _ISO_CURRENCY_RE.fullmatch(currency):
            raise ValueError("currency must be an ISO 4217 alpha-3 code")
        for field_name in ("adults", "children", "infants"):
            value = getattr(self, field_name)
            minimum = 1 if field_name == "adults" else 0
            if type(value) is not int or value < minimum:
                raise ValueError(f"{field_name} has an invalid value")
        object.__setattr__(self, "currency", currency)

    @property
    def passengers(self) -> int:
        return self.adults + self.children + self.infants


class AviasalesSearchGateway:
    """Single-attempt, policy-checked boundary for durable agent operations."""

    def __init__(
        self,
        *,
        client: AviasalesSearchClient,
        policy: ProviderPolicy,
        capability_snapshot: ProviderCapabilitySnapshot,
        clock: Callable[[], datetime] | None = None,
        guard: ProviderPolicyGuard | None = None,
    ) -> None:
        if client.max_retries != 0:
            raise ValueError("orchestrator client must use max_retries=0")
        if policy.provider_id != "aviasales_search":
            raise ValueError("gateway policy must belong to aviasales_search")
        if capability_snapshot.provider_id != "aviasales_search":
            raise ValueError("capability snapshot must belong to aviasales_search")
        self._client = client
        self._policy = policy
        self._capabilities = capability_snapshot
        self._clock = clock or (lambda: datetime.now(UTC))
        self._guard = guard or ProviderPolicyGuard(clock=self._clock)

    async def start_exact(
        self,
        params: SearchStartParams,
        *,
        request_fingerprint: str,
        context: ExecutionContext = ExecutionContext.WORKER,
    ) -> ExactSearchContinuation:
        if not isinstance(params, SearchStartParams):
            raise TypeError("params must be SearchStartParams")
        self._require_location_capability(params.origin)
        self._require_location_capability(params.destination)
        self._authorize(request_fingerprint=request_fingerprint, context=context)
        start = await asyncio.to_thread(self._client.start_search, params)
        return ExactSearchContinuation(
            search_id=start.search_id,
            results_url=start.results_url,
            last_update_timestamp=0,
            request_id=str(uuid.uuid4()),
        )

    async def poll_exact_once(
        self,
        continuation: ExactSearchContinuation,
        *,
        passengers: int,
        request_fingerprint: str,
        context: ExecutionContext = ExecutionContext.WORKER,
        limit: int = 50,
    ) -> ExactPollOutcome:
        if not isinstance(continuation, ExactSearchContinuation):
            raise TypeError("continuation must be ExactSearchContinuation")
        if type(passengers) is not int or passengers < 1:
            raise ValueError("passengers must be a positive integer")
        self._authorize(request_fingerprint=request_fingerprint, context=context)
        result = await asyncio.to_thread(
            self._client.poll_results_once,
            continuation.results_url,
            continuation.search_id,
            last_update_timestamp=continuation.last_update_timestamp,
            limit=limit,
            request_id=continuation.request_id,
        )
        try:
            parsed = parse_chunks([dict(chunk) for chunk in result.chunks])
            observed_at = self._clock()
            evidence = tuple(
                map_parsed_ticket_to_evidence(
                    ticket,
                    observed_at=observed_at,
                    passengers=passengers,
                )
                for ticket in parsed
            )
        except (AviasalesSearchParseError, TypeError, ValueError):
            raise AviasalesSearchSchemaError() from None
        return ExactPollOutcome(
            evidence=evidence,
            next_cursor=result.last_update_timestamp,
            # The verified fixture/API contract has no terminal-search field.
            # Ticket presence therefore cannot prove upstream completion.
            complete=False,
        )

    async def calendar(
        self,
        params: CalendarSearchParams,
        *,
        request_fingerprint: str,
        context: ExecutionContext = ExecutionContext.WORKER,
    ) -> tuple[DiscoverySignal, ...]:
        if not isinstance(params, CalendarSearchParams):
            raise TypeError("params must be CalendarSearchParams")
        self._require_location_capability(params.origin)
        self._require_location_capability(params.destination)
        if (params.adults, params.children, params.infants) != (1, 0, 0):
            raise AviasalesSearchCapabilityError("passenger_mix_not_supported")
        self._authorize(request_fingerprint=request_fingerprint, context=context)
        prices = await asyncio.to_thread(
            self._client.calendar_prices,
            origin=params.origin.code,
            destination=params.destination.code,
            depart_from=params.depart_from.isoformat(),
            depart_to=params.depart_to.isoformat(),
            one_way=params.one_way,
            currency=params.currency,
            origin_type=params.origin.kind.value,
            destination_type=params.destination.kind.value,
            locale="ru_RU",
        )
        observed_at = self._clock()
        try:
            return tuple(
                map_calendar_price_to_discovery(
                    price,
                    observed_at=observed_at,
                    passengers=params.passengers,
                )
                for price in prices
                if _calendar_price_matches(price, params)
            )
        except (TypeError, ValueError):
            raise AviasalesSearchSchemaError() from None

    def _require_location_capability(self, location: ProviderLocation) -> None:
        state = (
            self._capabilities.airport_location_semantics
            if location.kind is LocationScopeKind.AIRPORT
            else self._capabilities.city_location_semantics
        )
        if state is not CapabilityState.SUPPORTED:
            raise AviasalesSearchCapabilityError(
                f"{location.kind.value}_location_semantics_{state.value}"
            )

    def _authorize(
        self,
        *,
        request_fingerprint: str,
        context: ExecutionContext,
    ) -> None:
        if not request_fingerprint:
            raise ValueError("request_fingerprint is required")
        decision = self._guard.authorize(
            self._policy,
            operation=ProviderOperation.SEARCH,
            context=context,
            request_fingerprint=request_fingerprint,
        )
        if not decision.allowed:
            raise AviasalesSearchPolicyDenied(decision.code.value)


def _calendar_price_matches(price: CalendarPrice, params: CalendarSearchParams) -> bool:
    parsed_departure = date.fromisoformat(price.departure_date)
    return (
        price.origin == params.origin.code
        and price.destination == params.destination.code
        and params.depart_from <= parsed_departure <= params.depart_to
    )
