from __future__ import annotations

import asyncio
import re
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime
from uuid import UUID

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
    SearchStartParams,
    normalize_results_host,
    validate_calendar_price_rows,
)
from flight_hunter.providers.aviasales_search.mapper import (
    map_calendar_price_to_discovery,
    map_parsed_ticket_to_evidence,
)
from flight_hunter.providers.aviasales_search.schemas import (
    AviasalesSearchParseError,
    ParsedTicket,
    ProviderLocation,
    parse_chunks,
)

_ISO_CURRENCY_RE = re.compile(r"^[A-Z]{3}$")
_IATA_RE = re.compile(r"^[A-Z]{3}$")


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
    evidence_namespace: UUID
    expected_origin: str
    expected_destination: str
    expected_departure_date: date
    expected_return_date: date | None
    expected_currency: str
    passengers: int

    def __post_init__(self) -> None:
        if not isinstance(self.search_id, str) or not self.search_id:
            raise ValueError("search_id is required")
        object.__setattr__(self, "results_url", normalize_results_host(self.results_url))
        if type(self.last_update_timestamp) is not int or self.last_update_timestamp < 0:
            raise ValueError("last_update_timestamp must be a non-negative integer")
        if not isinstance(self.request_id, str) or not self.request_id:
            raise ValueError("request_id is required")
        if not isinstance(self.evidence_namespace, UUID):
            raise TypeError("evidence_namespace must be UUID")
        origin = _normalized_iata(self.expected_origin, "expected_origin")
        destination = _normalized_iata(self.expected_destination, "expected_destination")
        if type(self.expected_departure_date) is not date:
            raise TypeError("expected_departure_date must be a date")
        if self.expected_return_date is not None:
            if type(self.expected_return_date) is not date:
                raise TypeError("expected_return_date must be a date")
            if self.expected_return_date < self.expected_departure_date:
                raise ValueError("expected_return_date cannot precede departure")
        if not isinstance(self.expected_currency, str):
            raise TypeError("expected_currency must be a string")
        currency = self.expected_currency.upper()
        if not _ISO_CURRENCY_RE.fullmatch(currency):
            raise ValueError("expected_currency must be an ASCII ISO currency")
        if type(self.passengers) is not int or self.passengers < 1:
            raise ValueError("passengers must be a positive integer")
        object.__setattr__(self, "expected_origin", origin)
        object.__setattr__(self, "expected_destination", destination)
        object.__setattr__(self, "expected_currency", currency)

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
        evidence_namespace: UUID,
        request_fingerprint: str,
        context: ExecutionContext = ExecutionContext.WORKER,
    ) -> ExactSearchContinuation:
        if not isinstance(params, SearchStartParams):
            raise TypeError("params must be SearchStartParams")
        if not isinstance(evidence_namespace, UUID):
            raise TypeError("evidence_namespace must be UUID")
        self._require_location_capability(params.origin)
        self._require_location_capability(params.destination)
        self._authorize(request_fingerprint=request_fingerprint, context=context)
        start = await asyncio.to_thread(self._client.start_search, params)
        return ExactSearchContinuation(
            search_id=start.search_id,
            results_url=start.results_url,
            last_update_timestamp=0,
            request_id=str(uuid.uuid4()),
            evidence_namespace=evidence_namespace,
            expected_origin=params.origin.code,
            expected_destination=params.destination.code,
            expected_departure_date=date.fromisoformat(params.departure_date),
            expected_return_date=(
                date.fromisoformat(params.return_date) if params.return_date is not None else None
            ),
            expected_currency=params.currency,
            passengers=params.passengers,
        )

    async def poll_exact_once(
        self,
        continuation: ExactSearchContinuation,
        *,
        request_fingerprint: str,
        context: ExecutionContext = ExecutionContext.WORKER,
        limit: int = 50,
    ) -> ExactPollOutcome:
        if not isinstance(continuation, ExactSearchContinuation):
            raise TypeError("continuation must be ExactSearchContinuation")
        continuation = _validated_continuation(continuation)
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
                    passengers=continuation.passengers,
                    evidence_namespace=continuation.evidence_namespace,
                )
                for ticket in parsed
                if _ticket_matches_continuation(ticket, continuation)
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
        evidence_namespace: UUID,
        request_fingerprint: str,
        context: ExecutionContext = ExecutionContext.WORKER,
    ) -> tuple[DiscoverySignal, ...]:
        if not isinstance(params, CalendarSearchParams):
            raise TypeError("params must be CalendarSearchParams")
        if not isinstance(evidence_namespace, UUID):
            raise TypeError("evidence_namespace must be UUID")
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
            prices = validate_calendar_price_rows(
                prices,
                origin=params.origin.code,
                destination=params.destination.code,
                depart_from=params.depart_from,
                depart_to=params.depart_to,
                one_way=params.one_way,
                currency=params.currency,
            )
            return tuple(
                map_calendar_price_to_discovery(
                    price,
                    observed_at=observed_at,
                    evidence_namespace=evidence_namespace,
                )
                for price in prices
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


def _validated_continuation(
    continuation: ExactSearchContinuation,
) -> ExactSearchContinuation:
    return ExactSearchContinuation(
        search_id=continuation.search_id,
        results_url=continuation.results_url,
        last_update_timestamp=continuation.last_update_timestamp,
        request_id=continuation.request_id,
        evidence_namespace=continuation.evidence_namespace,
        expected_origin=continuation.expected_origin,
        expected_destination=continuation.expected_destination,
        expected_departure_date=continuation.expected_departure_date,
        expected_return_date=continuation.expected_return_date,
        expected_currency=continuation.expected_currency,
        passengers=continuation.passengers,
    )


def _ticket_matches_continuation(
    ticket: ParsedTicket,
    continuation: ExactSearchContinuation,
) -> bool:
    if (
        ticket.origin != continuation.expected_origin
        or ticket.destination != continuation.expected_destination
        or ticket.departure_date != continuation.expected_departure_date.isoformat()
        or ticket.return_date
        != (
            continuation.expected_return_date.isoformat()
            if continuation.expected_return_date is not None
            else None
        )
        or ticket.best_proposal.currency != continuation.expected_currency
        or type(ticket.best_proposal.price_minor_units) is not int
        or ticket.best_proposal.price_minor_units < 0
    ):
        raise AviasalesSearchParseError("aviasales_search_ticket_mismatch")
    return True


def _normalized_iata(value: str, field_name: str) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{field_name} must be a string")
    normalized = value.upper()
    if not _IATA_RE.fullmatch(normalized):
        raise ValueError(f"{field_name} must be an ASCII IATA code")
    return normalized
