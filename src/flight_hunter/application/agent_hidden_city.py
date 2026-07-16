from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum
from itertools import pairwise

from flight_hunter.domain.agent_evidence import (
    CheckedBaggageState,
    ConfirmedOfferEvidence,
)
from flight_hunter.domain.agent_search import TicketShape
from flight_hunter.domain.offers import FlightSegmentSummary

HIDDEN_CITY_WARNING_VERSION = "hidden-city-v1"
_IATA_RE = re.compile(r"^[A-Z]{3}$")


class HiddenCityActionability(StrEnum):
    ELIGIBLE = "eligible"
    RESEARCH_ONLY_NOT_ACTIONABLE = "research_only_not_actionable"


class HiddenCityRejectionCode(StrEnum):
    NOT_FINAL_PLAN_LEG = "not_final_plan_leg"
    ONE_WAY_TICKET_REQUIRED = "one_way_ticket_required"
    DESIRED_AIRPORT_NOT_INTERMEDIATE = "desired_airport_not_intermediate"
    LATER_JOURNEY_DEPENDENCY = "later_journey_dependency"
    CHECKED_BAGGAGE_KNOWN = "checked_baggage_known"
    TICKET_SEGMENTS_INVALID = "ticket_segments_invalid"


@dataclass(frozen=True, slots=True)
class HiddenCityWarning:
    code: str
    message_ru: str
    message_en: str

    def __post_init__(self) -> None:
        if not self.code or not self.message_ru or not self.message_en:
            raise ValueError("hidden-city warning fields are required")


HIDDEN_CITY_WARNINGS = (
    HiddenCityWarning(
        code="checked_baggage_continues",
        message_ru="Сданный багаж может улететь до указанного в билете конечного аэропорта.",
        message_en="Checked baggage may continue to the ticketed destination.",
    ),
    HiddenCityWarning(
        code="later_segments_may_be_cancelled",
        message_ru="Пропуск сегмента может отменить все последующие сегменты этого билета.",
        message_en="Skipping a segment may cancel every later segment on the same ticket.",
    ),
    HiddenCityWarning(
        code="carrier_contract_risk",
        message_ru="Маршрут может нарушать правила тарифа или договор перевозчика.",
        message_en="The itinerary may conflict with fare rules or the carrier contract.",
    ),
)


@dataclass(frozen=True, slots=True)
class HiddenCityContext:
    plan_leg_index: int
    final_plan_leg_index: int
    intended_later_airports: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if (
            type(self.plan_leg_index) is not int
            or type(self.final_plan_leg_index) is not int
            or self.plan_leg_index < 0
            or self.final_plan_leg_index < 0
            or self.plan_leg_index > self.final_plan_leg_index
        ):
            raise ValueError("hidden-city plan leg indexes are invalid")
        later_airports = tuple(
            _iata(value, "intended later airport") for value in self.intended_later_airports
        )
        object.__setattr__(self, "intended_later_airports", later_airports)


@dataclass(frozen=True, slots=True)
class HiddenCityCandidate:
    source_evidence: ConfirmedOfferEvidence
    desired_airport: str
    ticketed_destination: str
    flown_segments: tuple[FlightSegmentSummary, ...]
    skipped_segments: tuple[FlightSegmentSummary, ...]
    actionability: HiddenCityActionability
    warnings: tuple[HiddenCityWarning, ...] = HIDDEN_CITY_WARNINGS
    booking_action_available: bool = False
    watch_available: bool = False

    def __post_init__(self) -> None:
        if not isinstance(self.source_evidence, ConfirmedOfferEvidence):
            raise TypeError("source_evidence must be ConfirmedOfferEvidence")
        desired_airport = _iata(self.desired_airport, "desired airport")
        ticketed_destination = _iata(self.ticketed_destination, "ticketed destination")
        flown_segments = tuple(self.flown_segments)
        skipped_segments = tuple(self.skipped_segments)
        if not flown_segments or not skipped_segments:
            raise ValueError("hidden-city candidate requires flown and skipped segments")
        if flown_segments[-1].destination != desired_airport:
            raise ValueError("flown segments must end at the desired airport")
        if skipped_segments[-1].destination != ticketed_destination:
            raise ValueError("skipped segments must end at the ticketed destination")
        if self.booking_action_available or self.watch_available:
            raise ValueError("hidden-city actions must remain unavailable")
        warnings = tuple(self.warnings)
        if warnings != HIDDEN_CITY_WARNINGS:
            raise ValueError("hidden-city warnings must use the current complete warning set")
        object.__setattr__(self, "desired_airport", desired_airport)
        object.__setattr__(self, "ticketed_destination", ticketed_destination)
        object.__setattr__(self, "flown_segments", flown_segments)
        object.__setattr__(self, "skipped_segments", skipped_segments)
        object.__setattr__(
            self,
            "actionability",
            HiddenCityActionability(self.actionability),
        )
        object.__setattr__(self, "warnings", warnings)


@dataclass(frozen=True, slots=True)
class HiddenCityDecision:
    candidate: HiddenCityCandidate | None
    rejection_code: HiddenCityRejectionCode | None

    def __post_init__(self) -> None:
        if (self.candidate is None) == (self.rejection_code is None):
            raise ValueError("hidden-city decision requires exactly one outcome")
        if self.rejection_code is not None:
            object.__setattr__(
                self,
                "rejection_code",
                HiddenCityRejectionCode(self.rejection_code),
            )

    @classmethod
    def rejected(cls, code: HiddenCityRejectionCode) -> HiddenCityDecision:
        return cls(candidate=None, rejection_code=code)

    @classmethod
    def accepted(cls, candidate: HiddenCityCandidate) -> HiddenCityDecision:
        return cls(candidate=candidate, rejection_code=None)


def classify_hidden_city(
    ticket: ConfirmedOfferEvidence,
    desired_airport: str,
    context: HiddenCityContext,
) -> HiddenCityDecision:
    if not isinstance(ticket, ConfirmedOfferEvidence):
        raise TypeError("ticket must be ConfirmedOfferEvidence")
    if not isinstance(context, HiddenCityContext):
        raise TypeError("context must be HiddenCityContext")
    desired = _iata(desired_airport, "desired airport")
    if context.plan_leg_index != context.final_plan_leg_index:
        return HiddenCityDecision.rejected(HiddenCityRejectionCode.NOT_FINAL_PLAN_LEG)
    if ticket.ticket_shape is not TicketShape.ONE_WAY:
        return HiddenCityDecision.rejected(HiddenCityRejectionCode.ONE_WAY_TICKET_REQUIRED)
    if context.intended_later_airports:
        return HiddenCityDecision.rejected(HiddenCityRejectionCode.LATER_JOURNEY_DEPENDENCY)

    segments = ticket.segments
    if (
        not segments
        or segments[0].origin != ticket.origin
        or segments[-1].destination != ticket.destination
        or any(previous.destination != current.origin for previous, current in pairwise(segments))
    ):
        return HiddenCityDecision.rejected(HiddenCityRejectionCode.TICKET_SEGMENTS_INVALID)
    exit_indexes = tuple(
        index for index, segment in enumerate(segments[:-1]) if segment.destination == desired
    )
    if len(exit_indexes) != 1:
        return HiddenCityDecision.rejected(HiddenCityRejectionCode.DESIRED_AIRPORT_NOT_INTERMEDIATE)
    if ticket.checked_baggage is CheckedBaggageState.INCLUDED:
        return HiddenCityDecision.rejected(HiddenCityRejectionCode.CHECKED_BAGGAGE_KNOWN)

    exit_index = exit_indexes[0]
    actionability = (
        HiddenCityActionability.RESEARCH_ONLY_NOT_ACTIONABLE
        if ticket.checked_baggage is CheckedBaggageState.UNKNOWN
        else HiddenCityActionability.ELIGIBLE
    )
    return HiddenCityDecision.accepted(
        HiddenCityCandidate(
            source_evidence=ticket,
            desired_airport=desired,
            ticketed_destination=ticket.destination,
            flown_segments=segments[: exit_index + 1],
            skipped_segments=segments[exit_index + 1 :],
            actionability=actionability,
        )
    )


def _iata(value: str, field_name: str) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{field_name} must be a string")
    normalized = value.strip().upper()
    if not _IATA_RE.fullmatch(normalized):
        raise ValueError(f"{field_name} must be an IATA code")
    return normalized
