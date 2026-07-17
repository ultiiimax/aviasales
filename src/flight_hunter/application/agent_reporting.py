from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from itertools import pairwise
from uuid import UUID

from flight_hunter.domain.agent_evidence import (
    ComposedRouteCandidate,
    ComposedRouteLeg,
    ConfirmedOfferEvidence,
    ConnectionAssumption,
    PriceComparisonStatus,
    ProtectionStatus,
    UnknownCost,
    UnknownCostKind,
    require_confirmed_rank_input,
)
from flight_hunter.domain.agent_search import TripShape
from flight_hunter.domain.money import Money
from flight_hunter.domain.offers import (
    FlightSegmentSummary,
    PassengerMix,
    PriceBasis,
)

RankInput = ConfirmedOfferEvidence | ComposedRouteCandidate

_CURRENCY_RE = re.compile(r"^[A-Z]{3}$")
_FINGERPRINT_RE = re.compile(r"^[0-9a-f]{64}$")
_UNKNOWN_METRIC = 2**63 - 1
_NORMALIZED_SCALE = 10_000


class CandidateKind(StrEnum):
    CONFIRMED_OFFER = "confirmed_offer"
    COMPOSED_ROUTE = "composed_route"


class RankingView(StrEnum):
    CHEAPEST = "cheapest"
    FASTEST = "fastest"
    LOW_RISK = "low_risk"
    BALANCED = "balanced"
    SPLIT_SELF_TRANSFER = "split_self_transfer"
    RISKY = "risky"


@dataclass(frozen=True, slots=True)
class CandidateReference:
    kind: CandidateKind
    id: UUID

    def __post_init__(self) -> None:
        object.__setattr__(self, "kind", CandidateKind(self.kind))
        if not isinstance(self.id, UUID):
            raise TypeError("candidate reference id must be UUID")


@dataclass(frozen=True, slots=True)
class BalancedWeights:
    price: int = 50
    duration: int = 30
    risk: int = 20

    def __post_init__(self) -> None:
        values = (self.price, self.duration, self.risk)
        if any(type(value) is not int for value in values):
            raise TypeError("balanced weights must be integers")
        if any(value < 0 for value in values):
            raise ValueError("balanced weights cannot be negative")
        if not any(values):
            raise ValueError("at least one balanced weight must be positive")


@dataclass(frozen=True, slots=True)
class RankedCandidate:
    reference: CandidateReference
    rank: int
    reasons: tuple[str, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.reference, CandidateReference):
            raise TypeError("reference must be CandidateReference")
        if type(self.rank) is not int or self.rank < 1:
            raise ValueError("rank must be a positive integer")
        reasons = _normalized_strings(self.reasons, "reasons")
        object.__setattr__(self, "reasons", reasons)


@dataclass(frozen=True, slots=True)
class RankingViewResult:
    name: RankingView
    candidates: tuple[RankedCandidate, ...]
    weights: BalancedWeights | None = None

    def __post_init__(self) -> None:
        name = RankingView(self.name)
        candidates = tuple(self.candidates)
        if not all(isinstance(candidate, RankedCandidate) for candidate in candidates):
            raise TypeError("ranking view candidates must be RankedCandidate values")
        if tuple(candidate.rank for candidate in candidates) != tuple(
            range(1, len(candidates) + 1)
        ):
            raise ValueError("ranking view ranks must be contiguous")
        references = tuple(candidate.reference for candidate in candidates)
        if len(set(references)) != len(references):
            raise ValueError("ranking view candidate references must be unique")
        if name is RankingView.BALANCED and self.weights is None:
            raise ValueError("balanced ranking view requires displayed weights")
        if name is not RankingView.BALANCED and self.weights is not None:
            raise ValueError("weights are only valid for the balanced ranking view")
        object.__setattr__(self, "name", name)
        object.__setattr__(self, "candidates", candidates)


@dataclass(frozen=True, slots=True)
class RankingSnapshot:
    confirmed_evidence_ids: tuple[UUID, ...]
    composed_candidate_ids: tuple[UUID, ...]
    comparison_currency: str | None
    views: tuple[RankingViewResult, ...]
    fingerprint: str

    def __post_init__(self) -> None:
        confirmed_ids = _normalized_uuid_tuple(
            self.confirmed_evidence_ids,
            "confirmed_evidence_ids",
        )
        composed_ids = _normalized_uuid_tuple(
            self.composed_candidate_ids,
            "composed_candidate_ids",
        )
        if not confirmed_ids and not composed_ids:
            raise ValueError("ranking snapshot requires at least one candidate")
        currency = _normalized_currency(self.comparison_currency)
        views = tuple(self.views)
        if not all(isinstance(view, RankingViewResult) for view in views):
            raise TypeError("views must contain RankingViewResult values")
        if tuple(view.name for view in views) != tuple(RankingView):
            raise ValueError("ranking snapshot must contain every view exactly once")
        known_references = {
            *(CandidateReference(CandidateKind.CONFIRMED_OFFER, value) for value in confirmed_ids),
            *(CandidateReference(CandidateKind.COMPOSED_ROUTE, value) for value in composed_ids),
        }
        if any(
            entry.reference not in known_references for view in views for entry in view.candidates
        ):
            raise ValueError("ranking view references an unknown candidate")
        if not isinstance(self.fingerprint, str) or not _FINGERPRINT_RE.fullmatch(self.fingerprint):
            raise ValueError("fingerprint must be a lowercase SHA-256 digest")
        object.__setattr__(self, "confirmed_evidence_ids", confirmed_ids)
        object.__setattr__(self, "composed_candidate_ids", composed_ids)
        object.__setattr__(self, "comparison_currency", currency)
        object.__setattr__(self, "views", views)

    @property
    def references(self) -> tuple[CandidateReference, ...]:
        return (
            *(
                CandidateReference(CandidateKind.CONFIRMED_OFFER, value)
                for value in self.confirmed_evidence_ids
            ),
            *(
                CandidateReference(CandidateKind.COMPOSED_ROUTE, value)
                for value in self.composed_candidate_ids
            ),
        )

    def view(self, name: RankingView) -> RankingViewResult:
        normalized_name = RankingView(name)
        for view in self.views:
            if view.name is normalized_name:
                return view
        raise ValueError(f"ranking view is missing: {normalized_name.value}")


@dataclass(frozen=True, slots=True)
class BookingActionDescriptor:
    available: bool
    token: str | None

    def __post_init__(self) -> None:
        if type(self.available) is not bool:
            raise TypeError("booking action availability must be bool")
        if self.available != (self.token is not None):
            raise ValueError("booking action availability must match token presence")
        if self.token is not None:
            if not isinstance(self.token, str) or not self.token.strip():
                raise ValueError("booking action requires a non-empty token")
            if "://" in self.token:
                raise ValueError("booking action accepts only an opaque pre-signed token")

    @classmethod
    def unavailable(cls) -> BookingActionDescriptor:
        return cls(available=False, token=None)

    @classmethod
    def from_token(cls, token: str) -> BookingActionDescriptor:
        return cls(available=True, token=token)


@dataclass(frozen=True, slots=True)
class TicketBoundary:
    ticket_index: int
    leg_ordinals: tuple[int, ...]
    confirmed_evidence_id: UUID
    segment_ids: tuple[str, ...]
    protection_status: ProtectionStatus

    def __post_init__(self) -> None:
        if type(self.ticket_index) is not int or self.ticket_index < 0:
            raise ValueError("ticket_index must be a non-negative integer")
        leg_ordinals = tuple(self.leg_ordinals)
        if not leg_ordinals or any(type(value) is not int or value < 0 for value in leg_ordinals):
            raise ValueError("leg_ordinals must contain non-negative integers")
        if len(set(leg_ordinals)) != len(leg_ordinals):
            raise ValueError("leg_ordinals must be unique")
        if not isinstance(self.confirmed_evidence_id, UUID):
            raise TypeError("confirmed_evidence_id must be UUID")
        segment_ids = _normalized_strings(self.segment_ids, "segment_ids")
        object.__setattr__(self, "leg_ordinals", leg_ordinals)
        object.__setattr__(self, "segment_ids", segment_ids)
        object.__setattr__(
            self,
            "protection_status",
            ProtectionStatus(self.protection_status),
        )


@dataclass(frozen=True, slots=True)
class RankingPlacement:
    view: RankingView
    rank: int
    reasons: tuple[str, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "view", RankingView(self.view))
        if type(self.rank) is not int or self.rank < 1:
            raise ValueError("ranking placement rank must be positive")
        object.__setattr__(self, "reasons", _normalized_strings(self.reasons, "reasons"))


@dataclass(frozen=True, slots=True)
class CandidateFact:
    reference: CandidateReference
    passengers: int
    passenger_mix: PassengerMix
    trip_shape: TripShape
    price_basis: PriceBasis
    total_amount: Money | None
    sources: tuple[str, ...]
    observed_at: datetime
    segments: tuple[FlightSegmentSummary, ...]
    ticket_boundaries: tuple[TicketBoundary, ...]
    ordered_legs: tuple[ComposedRouteLeg, ...]
    connection_assumptions: tuple[ConnectionAssumption, ...]
    price_comparison_status: PriceComparisonStatus
    unknown_costs: tuple[UnknownCost, ...]
    protection_status: ProtectionStatus
    baggage_summaries: tuple[str | None, ...]
    unknowns: tuple[str, ...]
    rankings: tuple[RankingPlacement, ...]
    booking_action: BookingActionDescriptor

    def __post_init__(self) -> None:
        if not isinstance(self.reference, CandidateReference):
            raise TypeError("reference must be CandidateReference")
        if type(self.passengers) is not int or self.passengers < 1:
            raise ValueError("passengers must be a positive integer")
        if not isinstance(self.passenger_mix, PassengerMix):
            raise TypeError("passenger_mix must be PassengerMix")
        if self.passenger_mix.total != self.passengers:
            raise ValueError("passenger_mix must match passengers")
        object.__setattr__(self, "trip_shape", TripShape(self.trip_shape))
        object.__setattr__(self, "price_basis", PriceBasis(self.price_basis))
        if self.total_amount is not None and not isinstance(self.total_amount, Money):
            raise TypeError("total_amount must be Money or None")
        sources = _normalized_strings(self.sources, "sources")
        _require_aware(self.observed_at, "observed_at")
        segments = tuple(self.segments)
        if not segments or not all(
            isinstance(segment, FlightSegmentSummary) for segment in segments
        ):
            raise TypeError("segments must contain FlightSegmentSummary values")
        boundaries = tuple(self.ticket_boundaries)
        if not boundaries or not all(
            isinstance(boundary, TicketBoundary) for boundary in boundaries
        ):
            raise TypeError("ticket_boundaries must contain TicketBoundary values")
        ordered_legs = tuple(self.ordered_legs)
        if not ordered_legs or not all(isinstance(leg, ComposedRouteLeg) for leg in ordered_legs):
            raise TypeError("ordered_legs must contain ComposedRouteLeg values")
        connections = tuple(self.connection_assumptions)
        if not all(isinstance(value, ConnectionAssumption) for value in connections):
            raise TypeError("connection_assumptions must contain ConnectionAssumption values")
        unknown_costs = tuple(self.unknown_costs)
        if not all(isinstance(value, UnknownCost) for value in unknown_costs):
            raise TypeError("unknown_costs must contain UnknownCost values")
        baggage = tuple(self.baggage_summaries)
        if not baggage or not all(value is None or isinstance(value, str) for value in baggage):
            raise TypeError("baggage_summaries must contain strings or None")
        unknowns = _normalized_strings(self.unknowns, "unknowns", allow_empty=True)
        rankings = tuple(self.rankings)
        if not all(isinstance(value, RankingPlacement) for value in rankings):
            raise TypeError("rankings must contain RankingPlacement values")
        if not isinstance(self.booking_action, BookingActionDescriptor):
            raise TypeError("booking_action must be BookingActionDescriptor")
        object.__setattr__(self, "sources", sources)
        object.__setattr__(self, "segments", segments)
        object.__setattr__(self, "ticket_boundaries", boundaries)
        object.__setattr__(self, "ordered_legs", ordered_legs)
        object.__setattr__(self, "connection_assumptions", connections)
        object.__setattr__(
            self,
            "price_comparison_status",
            PriceComparisonStatus(self.price_comparison_status),
        )
        object.__setattr__(self, "unknown_costs", unknown_costs)
        object.__setattr__(self, "protection_status", ProtectionStatus(self.protection_status))
        object.__setattr__(self, "baggage_summaries", baggage)
        object.__setattr__(self, "unknowns", unknowns)
        object.__setattr__(self, "rankings", rankings)


@dataclass(frozen=True, slots=True)
class FactReport:
    ranking: RankingSnapshot
    candidates: tuple[CandidateFact, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.ranking, RankingSnapshot):
            raise TypeError("ranking must be RankingSnapshot")
        candidates = tuple(self.candidates)
        if not candidates or not all(
            isinstance(candidate, CandidateFact) for candidate in candidates
        ):
            raise TypeError("candidates must contain CandidateFact values")
        references = tuple(candidate.reference for candidate in candidates)
        if references != self.ranking.references:
            raise ValueError("report candidates must match ranking references")
        object.__setattr__(self, "candidates", candidates)

    def candidate(self, reference: CandidateReference) -> CandidateFact:
        for candidate in self.candidates:
            if candidate.reference == reference:
                return candidate
        raise KeyError(reference)


def ranking_snapshot_to_payload(snapshot: RankingSnapshot) -> dict[str, object]:
    if not isinstance(snapshot, RankingSnapshot):
        raise TypeError("snapshot must be RankingSnapshot")
    expected_fingerprint = _ranking_fingerprint(
        confirmed_ids=snapshot.confirmed_evidence_ids,
        composed_ids=snapshot.composed_candidate_ids,
        comparison_currency=snapshot.comparison_currency,
        views=snapshot.views,
    )
    if snapshot.fingerprint != expected_fingerprint:
        raise ValueError("ranking snapshot fingerprint is invalid")
    return {
        "version": "candidate-ranker-v1",
        "comparison_currency": snapshot.comparison_currency,
        "confirmed_evidence_ids": [str(value) for value in snapshot.confirmed_evidence_ids],
        "composed_candidate_ids": [str(value) for value in snapshot.composed_candidate_ids],
        "views": [
            {
                "name": view.name.value,
                "weights": (
                    None
                    if view.weights is None
                    else {
                        "price": view.weights.price,
                        "duration": view.weights.duration,
                        "risk": view.weights.risk,
                    }
                ),
                "candidates": [
                    {
                        "kind": candidate.reference.kind.value,
                        "id": str(candidate.reference.id),
                        "rank": candidate.rank,
                        "reasons": list(candidate.reasons),
                    }
                    for candidate in view.candidates
                ],
            }
            for view in snapshot.views
        ],
        "fingerprint": snapshot.fingerprint,
    }


def ranking_snapshot_from_payload(payload: Mapping[str, object]) -> RankingSnapshot:
    root = _payload_mapping(payload, "ranking snapshot")
    if set(root) != {
        "version",
        "comparison_currency",
        "confirmed_evidence_ids",
        "composed_candidate_ids",
        "views",
        "fingerprint",
    }:
        raise ValueError("ranking snapshot payload fields are invalid")
    if _payload_text(root["version"], "version") != "candidate-ranker-v1":
        raise ValueError("ranking snapshot version is unsupported")
    confirmed_ids = tuple(
        UUID(_payload_text(value, "confirmed evidence id"))
        for value in _payload_sequence(
            root["confirmed_evidence_ids"],
            "confirmed_evidence_ids",
        )
    )
    composed_ids = tuple(
        UUID(_payload_text(value, "composed candidate id"))
        for value in _payload_sequence(
            root["composed_candidate_ids"],
            "composed_candidate_ids",
        )
    )
    raw_currency = root["comparison_currency"]
    comparison_currency = (
        None if raw_currency is None else _payload_text(raw_currency, "comparison_currency")
    )
    views: list[RankingViewResult] = []
    for raw_view in _payload_sequence(root["views"], "views"):
        view = _payload_mapping(raw_view, "ranking view")
        if set(view) != {"name", "weights", "candidates"}:
            raise ValueError("ranking view payload fields are invalid")
        raw_weights = view["weights"]
        weights = None
        if raw_weights is not None:
            weight_values = _payload_mapping(raw_weights, "balanced weights")
            if set(weight_values) != {"price", "duration", "risk"}:
                raise ValueError("balanced weights payload fields are invalid")
            weights = BalancedWeights(
                price=_payload_int(weight_values["price"], "price weight"),
                duration=_payload_int(weight_values["duration"], "duration weight"),
                risk=_payload_int(weight_values["risk"], "risk weight"),
            )
        ranked: list[RankedCandidate] = []
        for raw_candidate in _payload_sequence(view["candidates"], "ranked candidates"):
            candidate = _payload_mapping(raw_candidate, "ranked candidate")
            if set(candidate) != {"kind", "id", "rank", "reasons"}:
                raise ValueError("ranked candidate payload fields are invalid")
            ranked.append(
                RankedCandidate(
                    reference=CandidateReference(
                        CandidateKind(_payload_text(candidate["kind"], "candidate kind")),
                        UUID(_payload_text(candidate["id"], "candidate id")),
                    ),
                    rank=_payload_int(candidate["rank"], "candidate rank"),
                    reasons=tuple(
                        _payload_text(reason, "ranking reason")
                        for reason in _payload_sequence(candidate["reasons"], "ranking reasons")
                    ),
                )
            )
        views.append(
            RankingViewResult(
                name=RankingView(_payload_text(view["name"], "ranking view name")),
                candidates=tuple(ranked),
                weights=weights,
            )
        )
    fingerprint = _payload_text(root["fingerprint"], "fingerprint")
    snapshot = RankingSnapshot(
        confirmed_evidence_ids=confirmed_ids,
        composed_candidate_ids=composed_ids,
        comparison_currency=comparison_currency,
        views=tuple(views),
        fingerprint=fingerprint,
    )
    expected_fingerprint = _ranking_fingerprint(
        confirmed_ids=snapshot.confirmed_evidence_ids,
        composed_ids=snapshot.composed_candidate_ids,
        comparison_currency=snapshot.comparison_currency,
        views=snapshot.views,
    )
    if fingerprint != expected_fingerprint:
        raise ValueError("ranking snapshot fingerprint does not match its facts")
    return snapshot


@dataclass(frozen=True, slots=True)
class _CandidateMetrics:
    candidate: RankInput
    reference: CandidateReference
    total_amount: Money | None
    duration_seconds: int | None
    risk_score: int
    risk_reasons: tuple[str, ...]
    currency_comparable: bool
    fully_priced: bool
    freshness_key: int


class CandidateRanker:
    """Build immutable, deterministic views from confirmed evidence only."""

    def rank(
        self,
        candidates: Iterable[RankInput],
        *,
        balanced_weights: BalancedWeights | None = None,
        comparison_currency: str | None = None,
    ) -> RankingSnapshot:
        weights = balanced_weights or BalancedWeights()
        if not isinstance(weights, BalancedWeights):
            raise TypeError("balanced_weights must be BalancedWeights")
        values = tuple(require_confirmed_rank_input(candidate) for candidate in candidates)
        if not values:
            raise ValueError("at least one confirmed candidate is required")
        references = tuple(_reference(candidate) for candidate in values)
        if len(set(references)) != len(references):
            raise ValueError("duplicate candidate reference")

        currency = _comparison_currency(values, requested=comparison_currency)
        metrics = tuple(_metrics(candidate, comparison_currency=currency) for candidate in values)
        complete = tuple(metric for metric in metrics if metric.fully_priced)
        timed = tuple(metric for metric in metrics if metric.duration_seconds is not None)
        timed_complete = tuple(metric for metric in complete if metric.duration_seconds is not None)

        cheapest = sorted(complete, key=_cheapest_key)
        fastest = sorted(timed, key=_fastest_key)
        low_risk = sorted(metrics, key=_low_risk_key)
        balanced = _balanced_order(timed_complete, weights)
        split = sorted(
            (metric for metric in metrics if metric.reference.kind is CandidateKind.COMPOSED_ROUTE),
            key=_split_key,
        )
        risky = sorted(
            (metric for metric in metrics if metric.risk_reasons),
            key=_risky_key,
        )

        views = (
            _ranking_view(RankingView.CHEAPEST, cheapest, "known_comparable_total"),
            _ranking_view(RankingView.FASTEST, fastest, "known_elapsed_duration"),
            _ranking_view(RankingView.LOW_RISK, low_risk, "known_risk_factors"),
            _ranking_view(
                RankingView.BALANCED,
                balanced,
                "balanced_integer_weights",
                weights=weights,
            ),
            _ranking_view(
                RankingView.SPLIT_SELF_TRANSFER,
                split,
                "split_or_self_transfer",
            ),
            _risky_view(risky),
        )
        confirmed_ids = tuple(
            sorted(
                (
                    reference.id
                    for reference in references
                    if reference.kind is CandidateKind.CONFIRMED_OFFER
                ),
                key=str,
            )
        )
        composed_ids = tuple(
            sorted(
                (
                    reference.id
                    for reference in references
                    if reference.kind is CandidateKind.COMPOSED_ROUTE
                ),
                key=str,
            )
        )
        fingerprint = _ranking_fingerprint(
            confirmed_ids=confirmed_ids,
            composed_ids=composed_ids,
            comparison_currency=currency,
            views=views,
        )
        return RankingSnapshot(
            confirmed_evidence_ids=confirmed_ids,
            composed_candidate_ids=composed_ids,
            comparison_currency=currency,
            views=views,
            fingerprint=fingerprint,
        )


class FactReportBuilder:
    """Project pre-computed rankings and typed facts without price arithmetic."""

    def build(
        self,
        ranking: RankingSnapshot,
        candidates: Iterable[RankInput],
        *,
        booking_action_tokens: Mapping[CandidateReference, str] | None = None,
    ) -> FactReport:
        if not isinstance(ranking, RankingSnapshot):
            raise TypeError("ranking must be RankingSnapshot")
        values = tuple(require_confirmed_rank_input(candidate) for candidate in candidates)
        by_reference = {_reference(candidate): candidate for candidate in values}
        if len(by_reference) != len(values):
            raise ValueError("duplicate candidate reference")
        if set(by_reference) != set(ranking.references):
            raise ValueError("typed facts must match ranking references")

        tokens = dict(booking_action_tokens or {})
        unknown_token_references = set(tokens) - set(ranking.references)
        if unknown_token_references:
            raise ValueError("booking token references an unknown candidate")

        facts = tuple(
            self._candidate_fact(
                reference,
                by_reference[reference],
                token=tokens.get(reference),
                ranking=ranking,
            )
            for reference in ranking.references
        )
        return FactReport(ranking=ranking, candidates=facts)

    def _candidate_fact(
        self,
        reference: CandidateReference,
        candidate: RankInput,
        *,
        token: str | None,
        ranking: RankingSnapshot,
    ) -> CandidateFact:
        return CandidateFact(
            reference=reference,
            passengers=candidate.passengers,
            passenger_mix=_passenger_mix(candidate),
            trip_shape=_trip_shape(candidate),
            price_basis=candidate.price_basis,
            total_amount=_total_amount(candidate),
            sources=_sources(candidate),
            observed_at=candidate.observed_at,
            segments=candidate.segments,
            ticket_boundaries=_ticket_boundaries(candidate),
            ordered_legs=_ordered_legs(candidate),
            connection_assumptions=_connection_assumptions(candidate),
            price_comparison_status=_price_comparison_status(candidate),
            unknown_costs=_unknown_costs(candidate),
            protection_status=candidate.protection_status,
            baggage_summaries=_baggage_summaries(candidate),
            unknowns=_fact_unknowns(candidate),
            rankings=_placements(reference, ranking),
            booking_action=(
                BookingActionDescriptor.unavailable()
                if token is None
                else BookingActionDescriptor.from_token(token)
            ),
        )


def _reference(candidate: RankInput) -> CandidateReference:
    if isinstance(candidate, ConfirmedOfferEvidence):
        return CandidateReference(CandidateKind.CONFIRMED_OFFER, candidate.id)
    return CandidateReference(CandidateKind.COMPOSED_ROUTE, candidate.id)


def _total_amount(candidate: RankInput) -> Money | None:
    amount: Money | None = candidate.total_amount
    if amount is not None and not isinstance(amount, Money):
        raise TypeError("candidate total_amount must be Money or None")
    return amount


def _comparison_currency(
    candidates: Sequence[RankInput],
    *,
    requested: str | None,
) -> str | None:
    normalized_requested = _normalized_currency(requested)
    if normalized_requested is not None:
        return normalized_requested
    currencies = {
        amount.currency
        for candidate in candidates
        if (amount := _total_amount(candidate)) is not None
    }
    if len(currencies) == 1:
        return next(iter(currencies))
    return None


def _metrics(
    candidate: RankInput,
    *,
    comparison_currency: str | None,
) -> _CandidateMetrics:
    total_amount = _total_amount(candidate)
    duration_seconds = _candidate_elapsed_seconds(candidate)
    airport_change = any(
        assumption.airport_change for assumption in _connection_assumptions(candidate)
    ) or any(
        inbound.destination != outbound.origin
        for inbound, outbound in _connection_segment_pairs(candidate)
    )
    unknown_mandatory_cost = any(
        cost.kind is UnknownCostKind.GROUND_TRANSFER for cost in _unknown_costs(candidate)
    )
    currency_comparable = (
        total_amount is not None
        and comparison_currency is not None
        and total_amount.currency == comparison_currency
    )
    fully_priced = (
        currency_comparable
        and _price_comparison_status(candidate) is PriceComparisonStatus.FULLY_PRICED
        and not unknown_mandatory_cost
    )
    reasons = _risk_reasons(
        candidate,
        total_amount=total_amount,
        duration_seconds=duration_seconds,
        comparison_currency=comparison_currency,
        airport_change=airport_change,
    )
    return _CandidateMetrics(
        candidate=candidate,
        reference=_reference(candidate),
        total_amount=total_amount,
        duration_seconds=duration_seconds,
        risk_score=_risk_score(candidate, reasons),
        risk_reasons=reasons,
        currency_comparable=currency_comparable,
        fully_priced=fully_priced,
        freshness_key=-_epoch_microseconds(candidate.observed_at),
    )


def _risk_reasons(
    candidate: RankInput,
    *,
    total_amount: Money | None,
    duration_seconds: int | None,
    comparison_currency: str | None,
    airport_change: bool,
) -> tuple[str, ...]:
    reasons: list[str] = []
    if total_amount is None:
        reasons.append("non_comparable_total")
    elif comparison_currency is None or total_amount.currency != comparison_currency:
        reasons.append("currency_not_comparable")
    if airport_change:
        reasons.append("airport_change")
    if any(cost.kind is UnknownCostKind.GROUND_TRANSFER for cost in _unknown_costs(candidate)):
        reasons.append("unknown_mandatory_transfer_cost")
    if candidate.protection_status is ProtectionStatus.UNKNOWN:
        reasons.append("protection_unknown")
    elif candidate.protection_status is ProtectionStatus.SELF_TRANSFER:
        reasons.append("self_transfer")
    if isinstance(candidate, ComposedRouteCandidate) and len(candidate.components) > 1:
        reasons.append("multiple_tickets")
    if any(summary is None for summary in _baggage_summaries(candidate)):
        reasons.append("baggage_unknown")
    if _has_overnight_connection(candidate):
        reasons.append("overnight_connection")
    if duration_seconds is None:
        reasons.append("duration_unknown")
    return tuple(reasons)


def _risk_score(candidate: RankInput, reasons: tuple[str, ...]) -> int:
    protection_score = {
        ProtectionStatus.EXPLICITLY_PROTECTED: 0,
        ProtectionStatus.UNKNOWN: 20,
        ProtectionStatus.SELF_TRANSFER: 60,
    }[candidate.protection_status]
    penalties = {
        "non_comparable_total": 200,
        "currency_not_comparable": 200,
        "airport_change": 40,
        "unknown_mandatory_transfer_cost": 100,
        "multiple_tickets": 20,
        "baggage_unknown": 5,
        "overnight_connection": 10,
        "duration_unknown": 100,
    }
    return protection_score + sum(penalties.get(reason, 0) for reason in reasons)


def _cheapest_key(metric: _CandidateMetrics) -> tuple[object, ...]:
    amount = metric.total_amount
    if amount is None:
        raise RuntimeError("fully priced candidate is missing total_amount")
    return (
        amount.minor_units,
        metric.risk_score,
        metric.duration_seconds if metric.duration_seconds is not None else _UNKNOWN_METRIC,
        metric.freshness_key,
        _reference_key(metric.reference),
    )


def _fastest_key(metric: _CandidateMetrics) -> tuple[object, ...]:
    if metric.duration_seconds is None:
        raise RuntimeError("fastest view candidate is missing duration")
    amount = metric.total_amount
    return (
        metric.duration_seconds,
        metric.risk_score,
        not metric.currency_comparable,
        amount.minor_units
        if amount is not None and metric.currency_comparable
        else _UNKNOWN_METRIC,
        metric.freshness_key,
        _reference_key(metric.reference),
    )


def _low_risk_key(metric: _CandidateMetrics) -> tuple[object, ...]:
    amount = metric.total_amount
    return (
        metric.risk_score,
        metric.duration_seconds if metric.duration_seconds is not None else _UNKNOWN_METRIC,
        not metric.currency_comparable,
        amount.minor_units
        if amount is not None and metric.currency_comparable
        else _UNKNOWN_METRIC,
        metric.freshness_key,
        _reference_key(metric.reference),
    )


def _balanced_order(
    metrics: Sequence[_CandidateMetrics],
    weights: BalancedWeights,
) -> list[_CandidateMetrics]:
    prices = tuple(
        metric.total_amount.minor_units for metric in metrics if metric.total_amount is not None
    )
    durations = tuple(
        metric.duration_seconds for metric in metrics if metric.duration_seconds is not None
    )
    risks = tuple(metric.risk_score for metric in metrics)

    def score(metric: _CandidateMetrics) -> int:
        amount = metric.total_amount
        duration = metric.duration_seconds
        if amount is None or duration is None:
            raise RuntimeError("balanced view requires complete price and duration")
        return (
            weights.price * _normalize(amount.minor_units, prices)
            + weights.duration * _normalize(duration, durations)
            + weights.risk * _normalize(metric.risk_score, risks)
        )

    return sorted(
        metrics,
        key=lambda metric: (
            score(metric),
            _cheapest_key(metric),
        ),
    )


def _split_key(metric: _CandidateMetrics) -> tuple[object, ...]:
    amount_minor = (
        metric.total_amount.minor_units if metric.total_amount is not None else _UNKNOWN_METRIC
    )
    return (
        not metric.fully_priced,
        amount_minor,
        metric.risk_score,
        metric.duration_seconds if metric.duration_seconds is not None else _UNKNOWN_METRIC,
        metric.freshness_key,
        _reference_key(metric.reference),
    )


def _risky_key(metric: _CandidateMetrics) -> tuple[object, ...]:
    return (
        -metric.risk_score,
        metric.total_amount.minor_units if metric.total_amount is not None else _UNKNOWN_METRIC,
        _reference_key(metric.reference),
    )


def _ranking_view(
    name: RankingView,
    metrics: Sequence[_CandidateMetrics],
    reason: str,
    *,
    weights: BalancedWeights | None = None,
) -> RankingViewResult:
    return RankingViewResult(
        name=name,
        candidates=tuple(
            RankedCandidate(
                reference=metric.reference,
                rank=index,
                reasons=(reason,),
            )
            for index, metric in enumerate(metrics, start=1)
        ),
        weights=weights,
    )


def _risky_view(metrics: Sequence[_CandidateMetrics]) -> RankingViewResult:
    return RankingViewResult(
        name=RankingView.RISKY,
        candidates=tuple(
            RankedCandidate(
                reference=metric.reference,
                rank=index,
                reasons=metric.risk_reasons,
            )
            for index, metric in enumerate(metrics, start=1)
        ),
    )


def _normalize(value: int, values: Sequence[int]) -> int:
    if not values:
        return 0
    minimum = min(values)
    maximum = max(values)
    if minimum == maximum:
        return 0
    return (value - minimum) * _NORMALIZED_SCALE // (maximum - minimum)


def _candidate_elapsed_seconds(candidate: RankInput) -> int | None:
    if isinstance(candidate, ComposedRouteCandidate) and candidate.ordered_legs:
        components = {component.id: component for component in candidate.components}
        total = 0
        for leg in candidate.ordered_legs:
            leg_segments = tuple(
                segment
                for component_id in leg.component_evidence_ids
                for segment in components[component_id].segments
            )
            elapsed = _elapsed_seconds(leg_segments)
            if elapsed is None:
                return None
            total += elapsed
        return total if total > 0 else None
    directions = _confirmed_directions(candidate)
    if directions is None:
        return _elapsed_seconds(candidate.segments)
    durations = tuple(_elapsed_seconds(direction) for direction in directions)
    if any(value is None for value in durations):
        return None
    total = sum(value for value in durations if value is not None)
    return total if total > 0 else None


def _elapsed_seconds(segments: Sequence[FlightSegmentSummary]) -> int | None:
    if not segments:
        return None
    depart_at = segments[0].depart_at_utc
    arrive_at = segments[-1].arrive_at_utc
    if depart_at is None or arrive_at is None:
        return None
    elapsed = arrive_at.astimezone(UTC) - depart_at.astimezone(UTC)
    seconds = elapsed.days * 86_400 + elapsed.seconds
    return seconds if seconds > 0 else None


def _has_overnight_connection(candidate: RankInput) -> bool:
    for inbound, outbound in _connection_segment_pairs(candidate):
        if inbound.destination != outbound.origin:
            continue
        arrive_at = _parse_display_datetime(inbound.arrive_at)
        depart_at = _parse_display_datetime(outbound.depart_at)
        if arrive_at is not None and depart_at is not None and depart_at.date() > arrive_at.date():
            return True
    return False


def _connection_segment_pairs(
    candidate: RankInput,
) -> tuple[tuple[FlightSegmentSummary, FlightSegmentSummary], ...]:
    if isinstance(candidate, ComposedRouteCandidate):
        components = {component.id: component for component in candidate.components}
        return tuple(
            (
                components[assumption.inbound_component_id].segments[-1],
                components[assumption.outbound_component_id].segments[0],
            )
            for assumption in candidate.connection_assumptions
        )
    directions = _confirmed_directions(candidate)
    if directions is None:
        directions = (candidate.segments,)
    return tuple(pair for direction in directions for pair in pairwise(direction))


def _parse_display_datetime(value: str) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    normalized = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    return parsed


def _epoch_microseconds(value: datetime) -> int:
    _require_aware(value, "observed_at")
    epoch = datetime(1970, 1, 1, tzinfo=UTC)
    elapsed = value.astimezone(UTC) - epoch
    return elapsed.days * 86_400_000_000 + elapsed.seconds * 1_000_000 + elapsed.microseconds


def _reference_key(reference: CandidateReference) -> tuple[str, str]:
    return reference.kind.value, str(reference.id)


def _ranking_fingerprint(
    *,
    confirmed_ids: tuple[UUID, ...],
    composed_ids: tuple[UUID, ...],
    comparison_currency: str | None,
    views: tuple[RankingViewResult, ...],
) -> str:
    payload = {
        "version": "candidate-ranker-v1",
        "comparison_currency": comparison_currency,
        "confirmed_evidence_ids": [str(value) for value in confirmed_ids],
        "composed_candidate_ids": [str(value) for value in composed_ids],
        "views": [
            {
                "name": view.name.value,
                "weights": (
                    None
                    if view.weights is None
                    else {
                        "price": view.weights.price,
                        "duration": view.weights.duration,
                        "risk": view.weights.risk,
                    }
                ),
                "candidates": [
                    {
                        "kind": candidate.reference.kind.value,
                        "id": str(candidate.reference.id),
                        "rank": candidate.rank,
                        "reasons": list(candidate.reasons),
                    }
                    for candidate in view.candidates
                ],
            }
            for view in views
        ],
    }
    canonical = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def _sources(candidate: RankInput) -> tuple[str, ...]:
    if isinstance(candidate, ConfirmedOfferEvidence):
        return (candidate.provider_id,)
    return _unique_in_order(component.provider_id for component in candidate.components)


def _passenger_mix(candidate: RankInput) -> PassengerMix:
    passenger_mix = candidate.passenger_mix
    if not isinstance(passenger_mix, PassengerMix):
        raise RuntimeError("candidate passenger mix is missing")
    return passenger_mix


def _trip_shape(candidate: RankInput) -> TripShape:
    if isinstance(candidate, ComposedRouteCandidate):
        return candidate.trip_shape
    return TripShape.ROUND_TRIP if candidate.return_date is not None else TripShape.ONE_WAY


def _price_comparison_status(candidate: RankInput) -> PriceComparisonStatus:
    if isinstance(candidate, ComposedRouteCandidate):
        return candidate.price_comparison_status
    return PriceComparisonStatus.FULLY_PRICED


def _connection_assumptions(
    candidate: RankInput,
) -> tuple[ConnectionAssumption, ...]:
    if isinstance(candidate, ComposedRouteCandidate):
        return candidate.connection_assumptions
    return ()


def _unknown_costs(candidate: RankInput) -> tuple[UnknownCost, ...]:
    if isinstance(candidate, ComposedRouteCandidate):
        return candidate.unknown_costs
    return ()


def _confirmed_directions(
    candidate: RankInput,
) -> tuple[tuple[FlightSegmentSummary, ...], ...] | None:
    if isinstance(candidate, ComposedRouteCandidate):
        return None
    segments = candidate.segments
    if (
        not segments
        or segments[0].origin != candidate.origin
        or not _provider_airport_changes_are_bound(candidate)
    ):
        return None
    if candidate.return_date is None:
        if segments[-1].destination != candidate.destination:
            return None
        return (segments,)
    for boundary in range(1, len(segments)):
        outbound = segments[:boundary]
        inbound = segments[boundary:]
        if (
            outbound[-1].destination == candidate.destination
            and inbound[0].origin == candidate.destination
            and inbound[-1].destination == candidate.origin
        ):
            return outbound, inbound
    return None


def _provider_airport_changes_are_bound(candidate: ConfirmedOfferEvidence) -> bool:
    actual = tuple(
        (previous.destination, current.origin)
        for previous, current in pairwise(candidate.segments)
        if previous.destination != current.origin
    )
    return actual == candidate.provider_airport_changes


def _ordered_legs(candidate: RankInput) -> tuple[ComposedRouteLeg, ...]:
    if isinstance(candidate, ComposedRouteCandidate):
        if candidate.ordered_legs:
            return candidate.ordered_legs
        return (
            ComposedRouteLeg(
                0,
                candidate.components[0].origin,
                candidate.components[-1].destination,
                candidate.components[0].departure_date,
                candidate.component_evidence_ids,
            ),
        )
    directions = _confirmed_directions(candidate)
    if directions is None:
        directions = (candidate.segments,)
    departure_dates = (
        (candidate.departure_date,)
        if candidate.return_date is None
        else (candidate.departure_date, candidate.return_date)
    )
    return tuple(
        ComposedRouteLeg(
            ordinal,
            direction[0].origin,
            direction[-1].destination,
            departure_dates[ordinal],
            (candidate.id,),
        )
        for ordinal, direction in enumerate(directions)
    )


def _baggage_summaries(candidate: RankInput) -> tuple[str | None, ...]:
    if isinstance(candidate, ConfirmedOfferEvidence):
        return (candidate.baggage_summary,)
    return tuple(component.baggage_summary for component in candidate.components)


def _ticket_boundaries(candidate: RankInput) -> tuple[TicketBoundary, ...]:
    if isinstance(candidate, ConfirmedOfferEvidence):
        return (
            TicketBoundary(
                ticket_index=0,
                leg_ordinals=tuple(leg.ordinal for leg in _ordered_legs(candidate)),
                confirmed_evidence_id=candidate.id,
                segment_ids=candidate.segment_ids,
                protection_status=candidate.protection_status,
            ),
        )
    components = {component.id: component for component in candidate.components}
    return tuple(
        TicketBoundary(
            ticket_index=boundary.ticket_index,
            leg_ordinals=(boundary.leg_ordinal,),
            confirmed_evidence_id=boundary.component_evidence_id,
            segment_ids=boundary.segment_refs,
            protection_status=components[boundary.component_evidence_id].protection_status,
        )
        for boundary in candidate.ticket_boundaries
    )


def _fact_unknowns(candidate: RankInput) -> tuple[str, ...]:
    unknowns: list[str] = ["fare_rules"]
    if _total_amount(candidate) is None:
        unknowns.append("comparable_total")
    if candidate.protection_status is ProtectionStatus.UNKNOWN:
        unknowns.append("protection")
    if any(summary is None for summary in _baggage_summaries(candidate)):
        unknowns.append("baggage")
    if any(cost.kind is UnknownCostKind.GROUND_TRANSFER for cost in _unknown_costs(candidate)):
        unknowns.append("mandatory_airport_transfer_cost")
    return tuple(unknowns)


def _placements(
    reference: CandidateReference,
    ranking: RankingSnapshot,
) -> tuple[RankingPlacement, ...]:
    return tuple(
        RankingPlacement(view=view.name, rank=entry.rank, reasons=entry.reasons)
        for view in ranking.views
        for entry in view.candidates
        if entry.reference == reference
    )


def _unique_in_order(values: Iterable[str]) -> tuple[str, ...]:
    seen: set[str] = set()
    ordered: list[str] = []
    for value in values:
        if value not in seen:
            seen.add(value)
            ordered.append(value)
    return tuple(ordered)


def _normalized_strings(
    values: Iterable[str],
    field_name: str,
    *,
    allow_empty: bool = False,
) -> tuple[str, ...]:
    if isinstance(values, str):
        raise TypeError(f"{field_name} must be an ordered collection")
    normalized = tuple(values)
    if not allow_empty and not normalized:
        raise ValueError(f"{field_name} cannot be empty")
    if not all(isinstance(value, str) and value for value in normalized):
        raise ValueError(f"{field_name} must contain non-empty strings")
    if len(set(normalized)) != len(normalized):
        raise ValueError(f"{field_name} must be unique")
    return normalized


def _normalized_uuid_tuple(values: Iterable[UUID], field_name: str) -> tuple[UUID, ...]:
    if isinstance(values, (str, bytes)):
        raise TypeError(f"{field_name} must be an ordered UUID collection")
    normalized = tuple(values)
    if not all(isinstance(value, UUID) for value in normalized):
        raise TypeError(f"{field_name} must contain UUID values")
    if len(set(normalized)) != len(normalized):
        raise ValueError(f"{field_name} must be unique")
    return normalized


def _normalized_currency(value: str | None) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise TypeError("comparison_currency must be a string")
    normalized = value.upper()
    if not _CURRENCY_RE.fullmatch(normalized):
        raise ValueError("comparison_currency must be ISO 4217 alpha-3")
    return normalized


def _require_aware(value: datetime, field_name: str) -> None:
    if not isinstance(value, datetime):
        raise TypeError(f"{field_name} must be datetime")
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")


def _payload_mapping(value: object, field_name: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping) or not all(isinstance(key, str) for key in value):
        raise TypeError(f"{field_name} must be an object")
    return value


def _payload_sequence(value: object, field_name: str) -> Sequence[object]:
    if isinstance(value, (str, bytes, bytearray)) or not isinstance(value, Sequence):
        raise TypeError(f"{field_name} must be an ordered collection")
    return value


def _payload_text(value: object, field_name: str) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{field_name} must be a non-empty string")
    return value


def _payload_int(value: object, field_name: str) -> int:
    if type(value) is not int:
        raise TypeError(f"{field_name} must be an integer")
    return value
