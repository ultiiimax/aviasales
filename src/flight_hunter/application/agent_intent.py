# ruff: noqa: RUF001

from __future__ import annotations

import re
import unicodedata
from collections.abc import Mapping
from dataclasses import dataclass, replace
from datetime import date, timedelta
from typing import Protocol

from pydantic import BaseModel, ConfigDict

from flight_hunter.agent.presets import AgentPresetId
from flight_hunter.domain.agent_search import (
    DateConstraint,
    DateMode,
    LocationScope,
    LocationScopeKind,
    RouteStrategy,
    TravelIntent,
    TravelLeg,
    TripShape,
)

_ROUTE_SEPARATOR_RE = re.compile(r"\s*(?:→|->|⟶)\s*")
_EXACT_DATE_RE = re.compile(r"\b(\d{4}-\d{2}-\d{2})\b")
_RANGE_DATE_RE = re.compile(r"(\d{4}-\d{2}-\d{2})\s*(?:\.\.|—|–)\s*(\d{4}-\d{2}-\d{2})")
_FLEX_DATE_RE = re.compile(r"(\d{4}-\d{2}-\d{2})\s*(?:±|\+/-)\s*(\d+)")
_ROLLING_DATE_RE = re.compile(
    r"\s*,?\s*(?:rolling\s+90\s+days|(?:ближайшие\s+)?90\s+дней)\b",
    re.IGNORECASE,
)
_IATA_RE = re.compile(r"^[A-Z]{3}$")
_COUNTRY_CODE_RE = re.compile(r"^[A-Z]{2}$")

_CITY_ALIASES = {
    "москва": "MOW",
    "moscow": "MOW",
    "париж": "PAR",
    "paris": "PAR",
    "санкт петербург": "LED",
    "saint petersburg": "LED",
    "spb": "LED",
    "st petersburg": "LED",
    "спб": "LED",
}
_COUNTRY_ALIASES = {
    "france": "FR",
    "japan": "JP",
    "russia": "RU",
    "россия": "RU",
    "франция": "FR",
    "япония": "JP",
}
_REGION_ALIASES = {
    "southern europe": "southern-europe",
    "western europe": "western-europe",
    "южная европа": "southern-europe",
    "западная европа": "western-europe",
}
_ANYWHERE_ALIASES = {
    "anywhere",
    "куда угодно",
    "любая точка",
    "любой город",
    "везде",
}


@dataclass(frozen=True, slots=True)
class ClarificationAction:
    action_id: str
    label_ru: str
    selections: dict[str, str]
    date_mode: DateMode | None = None


@dataclass(frozen=True, slots=True)
class IntentClarification:
    field: str
    code: str
    message_ru: str
    actions: tuple[ClarificationAction, ...] = ()


@dataclass(frozen=True, slots=True)
class ParsedDateConstraint:
    mode: DateMode
    start_date: date | None = None
    end_date: date | None = None
    flex_days: int = 0

    def __post_init__(self) -> None:
        object.__setattr__(self, "mode", DateMode(self.mode))

    def materialize(
        self,
        *,
        today: date | None,
        mode: DateMode | None = None,
    ) -> DateConstraint | None:
        effective_mode = mode or self.mode
        if effective_mode is DateMode.ROLLING_90_DAYS:
            if today is None:
                return None
            return DateConstraint(
                effective_mode,
                today,
                today + timedelta(days=89),
            )
        if self.start_date is None:
            return None
        if effective_mode is DateMode.EXACT:
            return DateConstraint(effective_mode, self.start_date)
        if effective_mode is DateMode.FLEXIBLE:
            return DateConstraint(
                effective_mode,
                self.start_date,
                flex_days=self.flex_days or 3,
            )
        return DateConstraint(
            effective_mode,
            self.start_date,
            self.end_date,
        )


@dataclass(frozen=True, slots=True)
class ParsedLeg:
    origin: LocationScope | None
    destination: LocationScope | None
    date_constraint: ParsedDateConstraint


@dataclass(frozen=True, slots=True)
class ParsedIntent:
    origin_text: str | None
    destination_text: str | None
    trip_shape: TripShape
    date_mode: DateMode
    legs: tuple[ParsedLeg, ...]
    adults: int = 1
    currency: str = "RUB"
    children: int = 0
    infants: int = 0
    requested_strategies: tuple[RouteStrategy, ...] = ()
    clarifications: tuple[IntentClarification, ...] = ()
    preset_id: AgentPresetId | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "trip_shape", TripShape(self.trip_shape))
        object.__setattr__(self, "date_mode", DateMode(self.date_mode))
        object.__setattr__(
            self,
            "requested_strategies",
            tuple(RouteStrategy(value) for value in self.requested_strategies),
        )

    @property
    def origin_scope(self) -> LocationScope | None:
        return self.legs[0].origin if self.legs else None

    @property
    def destination_scope(self) -> LocationScope | None:
        return self.legs[0].destination if self.legs else None

    @property
    def date_constraints(self) -> tuple[ParsedDateConstraint, ...]:
        return tuple(leg.date_constraint for leg in self.legs)

    @property
    def travel_intent(self) -> TravelIntent | None:
        return self.to_travel_intent(today=None)

    @property
    def intent(self) -> TravelIntent | None:
        return self.travel_intent

    def to_travel_intent(self, *, today: date | None) -> TravelIntent | None:
        if self.clarifications or not self.legs:
            return None
        materialized: list[TravelLeg] = []
        for leg in self.legs:
            constraint = leg.date_constraint.materialize(today=today, mode=self.date_mode)
            if leg.origin is None or leg.destination is None or constraint is None:
                return None
            materialized.append(TravelLeg(leg.origin, leg.destination, constraint))
        return TravelIntent(
            trip_shape=self.trip_shape,
            legs=tuple(materialized),
            adults=self.adults,
            children=self.children,
            infants=self.infants,
            currency=self.currency,
            requested_strategies=self.requested_strategies,
        )


class IntentOverlay(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    origin_text: str | None = None
    destination_text: str | None = None
    trip_shape: TripShape | None = None
    date_mode: DateMode | None = None
    requested_strategy_ids: tuple[RouteStrategy, ...] = ()


def merge_overlay(base: ParsedIntent, overlay: IntentOverlay) -> ParsedIntent:
    return replace(
        base,
        trip_shape=overlay.trip_shape or base.trip_shape,
        date_mode=overlay.date_mode or base.date_mode,
        requested_strategies=overlay.requested_strategy_ids or base.requested_strategies,
    )


class IntentOverlayProvider(Protocol):
    def __call__(
        self,
        text: str,
        preset: AgentPresetId | None,
        selections: Mapping[str, object],
    ) -> IntentOverlay | Mapping[str, object]: ...


class IntentParser:
    def __init__(self, *, overlay_provider: IntentOverlayProvider | None = None) -> None:
        self._overlay_provider = overlay_provider

    def parse(
        self,
        text: str,
        preset: AgentPresetId | str | None,
        selections: Mapping[str, object] | None,
    ) -> ParsedIntent:
        if not isinstance(text, str):
            raise TypeError("text must be a string")
        normalized_preset = AgentPresetId(preset) if preset is not None else None
        selected = selections or {}
        if not isinstance(selected, Mapping):
            raise TypeError("selections must be a mapping")

        clarifications: list[IntentClarification] = []
        raw_legs = selected.get("legs")
        if raw_legs is not None:
            legs = _parse_explicit_legs(raw_legs, clarifications)
            origin_text = _scope_text(legs[0].origin) if legs else None
            destination_text = _scope_text(legs[0].destination) if legs else None
        else:
            route_parts = _route_parts(text)
            origin_value = selected.get("origin", route_parts[0])
            destination_value = selected.get("destination", route_parts[1])
            origin_text = _optional_text(origin_value)
            destination_text = _optional_text(destination_value)
            origin = _parse_scope(origin_value)
            destination = _parse_scope(destination_value)
            if origin is None:
                clarifications.append(_location_clarification("origin"))
            if destination is None:
                clarifications.append(_location_clarification("destination"))
            date_constraint = _parse_date_constraint(text, selected)
            if (
                date_constraint.start_date is None
                and date_constraint.mode is not DateMode.ROLLING_90_DAYS
            ):
                clarifications.append(_date_clarification())
            legs = (ParsedLeg(origin, destination, date_constraint),)

        trip_shape = _trip_shape(selected, legs)
        if raw_legs is None and trip_shape is TripShape.ROUND_TRIP:
            return_constraint = _return_constraint(selected)
            if return_constraint.start_date is None:
                clarifications.append(_return_date_clarification())
            first = legs[0]
            legs = (
                first,
                ParsedLeg(first.destination, first.origin, return_constraint),
            )

        date_mode = legs[0].date_constraint.mode if legs else DateMode.EXACT
        parsed = ParsedIntent(
            origin_text=origin_text,
            destination_text=destination_text,
            trip_shape=trip_shape,
            date_mode=date_mode,
            legs=legs,
            adults=_positive_int(selected.get("adults", 1), "adults"),
            children=_non_negative_int(selected.get("children", 0), "children"),
            infants=_non_negative_int(selected.get("infants", 0), "infants"),
            currency=_string(selected.get("currency", "RUB"), "currency"),
            requested_strategies=_strategies(selected, normalized_preset),
            clarifications=tuple(_unique_clarifications(clarifications)),
            preset_id=normalized_preset,
        )
        if self._overlay_provider is None:
            return parsed
        raw_overlay = self._overlay_provider(text, normalized_preset, selected)
        overlay = (
            raw_overlay
            if isinstance(raw_overlay, IntentOverlay)
            else IntentOverlay.model_validate(raw_overlay)
        )
        return merge_overlay(parsed, overlay)


def _parse_explicit_legs(
    value: object,
    clarifications: list[IntentClarification],
) -> tuple[ParsedLeg, ...]:
    if isinstance(value, (str, bytes)) or not isinstance(value, (tuple, list)):
        raise TypeError("legs must be an ordered collection")
    result: list[ParsedLeg] = []
    for index, item in enumerate(value):
        if not isinstance(item, Mapping):
            raise TypeError("each leg must be a mapping")
        origin = _parse_scope(item.get("origin"))
        destination = _parse_scope(item.get("destination"))
        if origin is None:
            clarifications.append(_location_clarification(f"legs.{index}.origin"))
        if destination is None:
            clarifications.append(_location_clarification(f"legs.{index}.destination"))
        date_value = item.get("date")
        constraint = ParsedDateConstraint(
            DateMode.EXACT,
            _parse_date(date_value) if date_value is not None else None,
        )
        if constraint.start_date is None:
            clarifications.append(_date_clarification(field=f"legs.{index}.date_constraint"))
        result.append(ParsedLeg(origin, destination, constraint))
    return tuple(result)


def _parse_date_constraint(
    text: str,
    selections: Mapping[str, object],
) -> ParsedDateConstraint:
    explicit_mode = selections.get("date_mode")
    mode = DateMode(_string(explicit_mode, "date_mode")) if explicit_mode is not None else None
    if mode is DateMode.ROLLING_90_DAYS or (mode is None and _contains_rolling_alias(text)):
        return ParsedDateConstraint(DateMode.ROLLING_90_DAYS)

    date_start = selections.get("date_start")
    date_end = selections.get("date_end")
    if mode is DateMode.RANGE or date_start is not None or date_end is not None:
        return ParsedDateConstraint(
            DateMode.RANGE,
            _parse_date(date_start) if date_start is not None else None,
            _parse_date(date_end) if date_end is not None else None,
        )

    departure = selections.get("departure_date")
    if departure is not None:
        parsed_departure = _parse_date(departure)
        if mode is DateMode.FLEXIBLE:
            return ParsedDateConstraint(
                DateMode.FLEXIBLE,
                parsed_departure,
                flex_days=_positive_int(selections.get("flex_days", 3), "flex_days"),
            )
        return ParsedDateConstraint(DateMode.EXACT, parsed_departure)

    range_match = _RANGE_DATE_RE.search(text)
    if range_match:
        return ParsedDateConstraint(
            DateMode.RANGE,
            date.fromisoformat(range_match.group(1)),
            date.fromisoformat(range_match.group(2)),
        )
    flex_match = _FLEX_DATE_RE.search(text)
    if flex_match:
        return ParsedDateConstraint(
            DateMode.FLEXIBLE,
            date.fromisoformat(flex_match.group(1)),
            flex_days=int(flex_match.group(2)),
        )
    exact_match = _EXACT_DATE_RE.search(text)
    return ParsedDateConstraint(
        DateMode.EXACT,
        date.fromisoformat(exact_match.group(1)) if exact_match else None,
    )


def _return_constraint(selections: Mapping[str, object]) -> ParsedDateConstraint:
    value = selections.get("return_date")
    return ParsedDateConstraint(
        DateMode.EXACT,
        _parse_date(value) if value is not None else None,
    )


def _trip_shape(selections: Mapping[str, object], legs: tuple[ParsedLeg, ...]) -> TripShape:
    explicit = selections.get("trip_shape")
    if explicit is not None:
        return TripShape(_string(explicit, "trip_shape"))
    if len(legs) > 1:
        return TripShape.MULTI_CITY
    if selections.get("return_date") is not None:
        return TripShape.ROUND_TRIP
    return TripShape.ONE_WAY


def _strategies(
    selections: Mapping[str, object],
    preset: AgentPresetId | None,
) -> tuple[RouteStrategy, ...]:
    explicit = selections.get("requested_strategies")
    if explicit is not None:
        if isinstance(explicit, str):
            values = tuple(part.strip() for part in explicit.split(",") if part.strip())
        elif isinstance(explicit, (tuple, list)):
            values = tuple(explicit)
        else:
            raise TypeError("requested_strategies must be an ordered collection")
        return tuple(RouteStrategy(_string(value, "requested_strategies")) for value in values)
    if preset is AgentPresetId.HIDDEN_CITY:
        return (RouteStrategy.HIDDEN_CITY,)
    if preset is AgentPresetId.SPLIT_TICKET:
        return (RouteStrategy.SPLIT_TICKET,)
    return ()


def _route_parts(text: str) -> tuple[str | None, str | None]:
    route_text = _RANGE_DATE_RE.sub("", text)
    route_text = _FLEX_DATE_RE.sub("", route_text)
    route_text = _EXACT_DATE_RE.sub("", route_text)
    route_text = _ROLLING_DATE_RE.sub("", route_text)
    parts = _ROUTE_SEPARATOR_RE.split(route_text, maxsplit=1)
    if len(parts) != 2:
        return None, None
    return parts[0].strip() or None, parts[1].strip() or None


def _parse_scope(value: object) -> LocationScope | None:
    if isinstance(value, LocationScope):
        return value
    if not isinstance(value, str) or not value.strip():
        return None
    raw = value.strip()
    normalized = _normalize_text(raw)
    prefixes = (
        ("airport", LocationScopeKind.AIRPORT),
        ("аэропорт", LocationScopeKind.AIRPORT),
        ("city", LocationScopeKind.CITY),
        ("город", LocationScopeKind.CITY),
        ("country", LocationScopeKind.COUNTRY),
        ("страна", LocationScopeKind.COUNTRY),
        ("region", LocationScopeKind.REGION),
        ("регион", LocationScopeKind.REGION),
    )
    for prefix, kind in prefixes:
        marker = f"{prefix}:"
        if normalized.startswith(marker):
            scope_value = raw.split(":", 1)[1].strip()
            return LocationScope(kind, scope_value)
    if normalized in _ANYWHERE_ALIASES:
        return LocationScope(LocationScopeKind.ANYWHERE, None)
    if normalized in _CITY_ALIASES:
        return LocationScope(LocationScopeKind.CITY, _CITY_ALIASES[normalized])
    if normalized in _COUNTRY_ALIASES:
        return LocationScope(LocationScopeKind.COUNTRY, _COUNTRY_ALIASES[normalized])
    if normalized in _REGION_ALIASES:
        return LocationScope(LocationScopeKind.REGION, _REGION_ALIASES[normalized])
    upper = raw.upper()
    if _IATA_RE.fullmatch(upper):
        return LocationScope(LocationScopeKind.AIRPORT, upper)
    if _COUNTRY_CODE_RE.fullmatch(upper):
        return LocationScope(LocationScopeKind.COUNTRY, upper)
    return None


def _normalize_text(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value).casefold()
    normalized = re.sub(r"[_\-]+", " ", normalized)
    return " ".join(normalized.split())


def _contains_rolling_alias(text: str) -> bool:
    normalized = _normalize_text(text)
    return "rolling 90 days" in normalized or "90 дней" in normalized


def _date_clarification(*, field: str = "date_constraint") -> IntentClarification:
    return IntentClarification(
        field=field,
        code="date_required",
        message_ru="Укажите дату или период поиска.",
        actions=(
            ClarificationAction(
                action_id="use_rolling_90_days",
                label_ru="Искать в ближайшие 90 дней",
                selections={"date_mode": DateMode.ROLLING_90_DAYS.value},
                date_mode=DateMode.ROLLING_90_DAYS,
            ),
        ),
    )


def _return_date_clarification() -> IntentClarification:
    return IntentClarification(
        field="return_date_constraint",
        code="return_date_required",
        message_ru="Укажите дату возвращения.",
    )


def _location_clarification(field: str) -> IntentClarification:
    return IntentClarification(
        field=field,
        code="location_required_or_unknown",
        message_ru="Укажите известный аэропорт, город, страну или регион.",
    )


def _unique_clarifications(
    values: list[IntentClarification],
) -> tuple[IntentClarification, ...]:
    seen: set[str] = set()
    result: list[IntentClarification] = []
    for value in values:
        if value.field not in seen:
            seen.add(value.field)
            result.append(value)
    return tuple(result)


def _parse_date(value: object) -> date:
    if type(value) is date:
        return value
    if not isinstance(value, str):
        raise TypeError("date values must be ISO dates")
    return date.fromisoformat(value)


def _positive_int(value: object, field: str) -> int:
    if type(value) is not int or value <= 0:
        raise ValueError(f"{field} must be a positive integer")
    return value


def _non_negative_int(value: object, field: str) -> int:
    if type(value) is not int or value < 0:
        raise ValueError(f"{field} must be a non-negative integer")
    return value


def _string(value: object, field: str) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{field} must be a non-empty string")
    return value


def _optional_text(value: object) -> str | None:
    return value if isinstance(value, str) and value.strip() else None


def _scope_text(scope: LocationScope | None) -> str | None:
    return scope.value if scope is not None else None
