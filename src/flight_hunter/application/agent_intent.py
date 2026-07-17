# ruff: noqa: RUF001

from __future__ import annotations

import re
import unicodedata
from collections.abc import Mapping
from dataclasses import dataclass, replace
from dataclasses import field as dataclass_field
from datetime import date, timedelta
from types import MappingProxyType
from typing import Literal, Protocol, cast

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from flight_hunter.agent.presets import PRESET_EDITS, AgentPresetId
from flight_hunter.application.agent_scope import (
    GeographyChoice,
    GeographyClarification,
    ScopeResolver,
)
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
from flight_hunter.geo.airports import AirportCatalogSnapshot

_ROUTE_SEPARATOR_RE = re.compile(r"\s*(?:→|->|⟶)\s*")
_NATURAL_ROUTE_RE = re.compile(
    r"(?:^|\s)(?:из|с)\s+(?P<origin>.+?)\s+(?:в|во|до)\s+(?P<destination>.+?)\s*$",
    re.IGNORECASE,
)
_EXACT_DATE_RE = re.compile(r"\b(\d{4}-\d{2}-\d{2})\b")
_RANGE_DATE_RE = re.compile(r"(\d{4}-\d{2}-\d{2})\s*(?:\.\.|—|–)\s*(\d{4}-\d{2}-\d{2})")
_FLEX_DATE_RE = re.compile(r"(\d{4}-\d{2}-\d{2})\s*(?:±|\+/-)\s*(\d+)")
_RU_ROUND_TRIP_DATE_RE = re.compile(
    r"\bс\s+(?P<departure_day>\d{1,2})\s+по\s+(?P<return_day>\d{1,2})\s+"
    r"(?P<month>[а-яё]+)\s+(?P<year>\d{4})(?:\s+года?)?\b",
    re.IGNORECASE,
)
_ROLLING_DATE_RE = re.compile(
    r"\s*,?\s*(?:rolling\s+90\s+days|(?:ближайшие\s+)?90\s+дней)\b",
    re.IGNORECASE,
)
_TRAILING_CONSTRAINT_RE = re.compile(
    r"(?:\s*,?\s+(?:с\s+багажом|с\s+ручной\s+кладью|без\s+багажа|"
    r"следи(?:ть)?\s+за\s+цен(?:ой|ами)|отслеживай\s+цен(?:у|ы)|"
    r"можно\s+отдельными\s+билетами|разбей\s+билет|самопересадк\w*))+$",
    re.IGNORECASE,
)
_TRAILING_TRAVEL_DETAILS_RE = re.compile(
    r"(?:\s*,?\s*(?:\d+\s+(?:взросл\w*|пассажир\w*|дет\w*|реб[её]н\w*|младен\w*)|"
    r"эконом(?:\s*класс)?|бизнес(?:\s*класс)?|первый\s+класс))+\s*$",
    re.IGNORECASE,
)
_PASSENGER_COUNT_PATTERNS = {
    "adults": re.compile(
        r"\b(?P<count>\d{1,2})\s*(?:взросл\w*|пассажир\w*|adults?|passengers?)\b",
        re.IGNORECASE,
    ),
    "children": re.compile(
        r"\b(?P<count>\d{1,2})\s*(?:дет\w*|реб[её]н\w*|children?|kids?)\b",
        re.IGNORECASE,
    ),
    "infants": re.compile(
        r"\b(?P<count>\d{1,2})\s*(?:младен\w*|infants?|bab(?:y|ies))\b",
        re.IGNORECASE,
    ),
}
_IATA_RE = re.compile(r"^[A-Z]{3}$")
_COUNTRY_CODE_RE = re.compile(r"^[A-Z]{2}$")
_TRIP_SHAPE_PATTERNS = (
    (
        TripShape.ROUND_TRIP,
        re.compile(r"\b(?:round[\s-]*trip|туда[\s-]*обратно)\b", re.IGNORECASE),
    ),
    (
        TripShape.OPEN_JAW,
        re.compile(r"\b(?:open[\s-]*jaw|разомкнутый\s+маршрут)\b", re.IGNORECASE),
    ),
    (
        TripShape.MULTI_CITY,
        re.compile(r"\b(?:multi[\s-]*city|сложный\s+маршрут)\b", re.IGNORECASE),
    ),
    (
        TripShape.ONE_WAY,
        re.compile(r"\b(?:one[\s-]*way|в\s+одну\s+сторону)\b", re.IGNORECASE),
    ),
)

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
_RU_MONTH_NUMBERS = {
    "января": 1,
    "февраля": 2,
    "марта": 3,
    "апреля": 4,
    "мая": 5,
    "июня": 6,
    "июля": 7,
    "августа": 8,
    "сентября": 9,
    "октября": 10,
    "ноября": 11,
    "декабря": 12,
}
_ANYWHERE_ALIASES = {
    "anywhere",
    "куда угодно",
    "любая точка",
    "любой город",
    "везде",
}
_INFLECTED_LOCATION_ALIASES = {
    "санкт петербурга": "Санкт Петербург",
    "францию": "Франция",
}


class _TaxonomyOnlyAirportCatalog:
    async def catalog_snapshot(self) -> AirportCatalogSnapshot:
        raise RuntimeError("taxonomy-only resolver cannot access an airport catalog")


_TAXONOMY_RESOLVER = ScopeResolver(repository=_TaxonomyOnlyAirportCatalog())


@dataclass(frozen=True, slots=True)
class ClarificationAction:
    action_id: str
    label_ru: str
    selections: Mapping[str, str]
    date_mode: DateMode | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.selections, Mapping) or not all(
            isinstance(key, str) and isinstance(value, str)
            for key, value in self.selections.items()
        ):
            raise TypeError("clarification selections must map strings to strings")
        object.__setattr__(self, "selections", MappingProxyType(dict(self.selections)))
        if self.date_mode is not None:
            object.__setattr__(self, "date_mode", DateMode(self.date_mode))


@dataclass(frozen=True, slots=True)
class IntentClarification:
    field: str
    code: str
    message_ru: str
    actions: tuple[ClarificationAction, ...] = ()
    geography: GeographyClarification | None = None
    details: Mapping[str, int | str] = dataclass_field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.details, Mapping) or not all(
            isinstance(key, str) and not isinstance(value, bool) and isinstance(value, (int, str))
            for key, value in self.details.items()
        ):
            raise TypeError("clarification details must map strings to integers or strings")
        object.__setattr__(self, "details", MappingProxyType(dict(self.details)))


@dataclass(frozen=True, slots=True)
class ParsedDateConstraint:
    mode: DateMode
    start_date: date | None = None
    end_date: date | None = None
    flex_days: int = 0

    def __post_init__(self) -> None:
        object.__setattr__(self, "mode", DateMode(self.mode))
        if self.start_date is not None and type(self.start_date) is not date:
            raise TypeError("start_date must be a date")
        if self.end_date is not None and type(self.end_date) is not date:
            raise TypeError("end_date must be a date")
        if type(self.flex_days) is not int:
            raise TypeError("flex_days must be an integer")

    def clarifications(self, *, field: str) -> tuple[IntentClarification, ...]:
        if self.mode is DateMode.ROLLING_90_DAYS:
            return ()
        if self.start_date is None:
            return (_date_clarification(field=field),)
        if self.mode is DateMode.FLEXIBLE:
            if self.flex_days <= 0:
                return (
                    IntentClarification(
                        field=field,
                        code="date_flex_days_invalid",
                        message_ru="Гибкость дат должна быть больше нуля.",
                    ),
                )
            return ()
        if self.mode is DateMode.RANGE:
            if self.end_date is None:
                return (
                    IntentClarification(
                        field=field,
                        code="date_range_end_required",
                        message_ru="Для диапазона нужна конечная дата.",
                    ),
                )
            if self.end_date < self.start_date:
                return (
                    IntentClarification(
                        field=field,
                        code="date_range_end_before_start",
                        message_ru="Конечная дата не может быть раньше начальной.",
                    ),
                )
        return ()

    def materialize(
        self,
        *,
        today: date | None,
        mode: DateMode | None = None,
    ) -> DateConstraint | None:
        effective = replace(self, mode=mode or self.mode)
        if effective.clarifications(field="date_constraint"):
            return None
        if effective.mode is DateMode.ROLLING_90_DAYS:
            if today is None:
                return None
            return DateConstraint(
                effective.mode,
                today,
                today + timedelta(days=89),
            )
        assert effective.start_date is not None
        if effective.mode is DateMode.EXACT:
            return DateConstraint(effective.mode, effective.start_date)
        if effective.mode is DateMode.FLEXIBLE:
            return DateConstraint(
                effective.mode,
                effective.start_date,
                flex_days=effective.flex_days,
            )
        return DateConstraint(
            effective.mode,
            effective.start_date,
            effective.end_date,
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
    nearby_radius_km: int = 0
    requested_strategies: tuple[RouteStrategy, ...] = ()
    clarifications: tuple[IntentClarification, ...] = ()
    preset_id: AgentPresetId | None = None
    baggage_preference: Literal["checked", "carry_on", "none", "unspecified"] = "unspecified"
    wants_watch: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(self, "trip_shape", TripShape(self.trip_shape))
        object.__setattr__(self, "date_mode", DateMode(self.date_mode))
        object.__setattr__(self, "legs", tuple(self.legs))
        if type(self.nearby_radius_km) is not int or not 0 <= self.nearby_radius_km <= 500:
            raise ValueError("nearby_radius_km must be between 0 and 500")
        object.__setattr__(
            self,
            "requested_strategies",
            tuple(RouteStrategy(value) for value in self.requested_strategies),
        )
        object.__setattr__(self, "clarifications", tuple(self.clarifications))
        if self.baggage_preference not in {"checked", "carry_on", "none", "unspecified"}:
            raise ValueError("baggage_preference is invalid")
        if type(self.wants_watch) is not bool:
            raise TypeError("wants_watch must be a boolean")

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
        if self.clarifications or not _leg_count_is_valid(self.trip_shape, len(self.legs)):
            return None
        materialized: list[TravelLeg] = []
        for index, leg in enumerate(self.legs):
            constraint = leg.date_constraint.materialize(
                today=today,
                mode=self.date_mode if index == 0 else None,
            )
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
    departure_date: str | None = None
    return_date: str | None = None
    date_hint: str | None = None
    adults: int | None = Field(default=None, ge=1, le=9)
    children: int | None = Field(default=None, ge=0, le=9)
    infants: int | None = Field(default=None, ge=0, le=9)
    currency: str | None = Field(default=None, min_length=3, max_length=3)
    nearby_radius_km: int | None = Field(default=None, ge=0, le=500)
    requested_strategy_ids: tuple[RouteStrategy, ...] = ()
    baggage_preference: Literal["checked", "carry_on", "none", "unspecified"] = "unspecified"
    wants_watch: bool = False


class IntentOverlayTransportError(RuntimeError):
    """Expected optional-model transport failure with deterministic fallback."""


class IntentInputError(ValueError):
    """A deterministic user-supplied intent value failed validation."""


def merge_overlay(base: ParsedIntent, overlay: IntentOverlay) -> ParsedIntent:
    retained = list(base.clarifications)
    if overlay.date_mode is not None:
        retained = [item for item in retained if item.field != "date_constraint"]
    if overlay.trip_shape is not None:
        retained = [
            item for item in retained if item.field not in {"return_date_constraint", "trip_legs"}
        ]
    merged = replace(
        base,
        trip_shape=overlay.trip_shape or base.trip_shape,
        date_mode=overlay.date_mode or base.date_mode,
        requested_strategies=overlay.requested_strategy_ids or base.requested_strategies,
        baggage_preference=(
            overlay.baggage_preference
            if overlay.baggage_preference != "unspecified"
            else base.baggage_preference
        ),
        wants_watch=overlay.wants_watch or base.wants_watch,
        clarifications=tuple(retained),
    )
    return _with_semantic_clarifications(merged)


class IntentOverlayProvider(Protocol):
    def __call__(
        self,
        text: str,
        preset: AgentPresetId | None,
        selections: Mapping[str, object],
    ) -> IntentOverlay | Mapping[str, object]: ...


@dataclass(frozen=True, slots=True)
class _ScopeParseResult:
    scope: LocationScope | None
    geography: GeographyClarification | None = None


class IntentParser:
    def __init__(
        self,
        *,
        overlay_provider: IntentOverlayProvider | None = None,
        taxonomy_resolver: ScopeResolver | None = None,
    ) -> None:
        self._overlay_provider = overlay_provider
        self._taxonomy_resolver = taxonomy_resolver or _TAXONOMY_RESOLVER

    def parse(
        self,
        text: str,
        preset: AgentPresetId | str | None,
        selections: Mapping[str, object] | None,
    ) -> ParsedIntent:
        try:
            parsed, normalized_preset, selected = self._parse_deterministic(
                text,
                preset,
                selections,
            )
        except (TypeError, ValueError) as error:
            raise IntentInputError("agent intent input is invalid") from error
        return self._apply_overlay(text, normalized_preset, selected, parsed)

    def _parse_deterministic(
        self,
        text: str,
        preset: AgentPresetId | str | None,
        selections: Mapping[str, object] | None,
    ) -> tuple[ParsedIntent, AgentPresetId | None, Mapping[str, object]]:
        if not isinstance(text, str):
            raise TypeError("text must be a string")
        normalized_preset = AgentPresetId(preset) if preset is not None else None
        selected = selections or {}
        if not isinstance(selected, Mapping):
            raise TypeError("selections must be a mapping")
        selected = dict(selected)
        natural_round_trip = _natural_round_trip_dates(text)
        if natural_round_trip is not None:
            selected.setdefault("departure_date", natural_round_trip[0].isoformat())
            selected.setdefault("return_date", natural_round_trip[1].isoformat())

        clarifications: list[IntentClarification] = []
        raw_legs = selected.get("legs")
        if raw_legs is not None:
            legs = _parse_explicit_legs(raw_legs, clarifications, self._taxonomy_resolver)
            origin_text = _scope_text(legs[0].origin) if legs else None
            destination_text = _scope_text(legs[0].destination) if legs else None
        else:
            route_parts = _route_parts(text)
            origin_value = selected.get("origin", route_parts[0])
            destination_value = selected.get("destination", route_parts[1])
            origin_text = _optional_text(origin_value)
            destination_text = _optional_text(destination_value)
            origin_result = _parse_scope(origin_value, self._taxonomy_resolver)
            destination_result = _parse_scope(destination_value, self._taxonomy_resolver)
            _append_scope_clarification(clarifications, "origin", origin_result)
            _append_scope_clarification(clarifications, "destination", destination_result)
            date_constraint = _parse_date_constraint(text, selected)
            clarifications.extend(date_constraint.clarifications(field="date_constraint"))
            legs = (
                ParsedLeg(
                    origin_result.scope,
                    destination_result.scope,
                    date_constraint,
                ),
            )

        trip_shape = _trip_shape(selected, legs, text)
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
        adults, children, infants = _passenger_counts(text, selected)
        parsed = _with_semantic_clarifications(
            ParsedIntent(
                origin_text=origin_text,
                destination_text=destination_text,
                trip_shape=trip_shape,
                date_mode=date_mode,
                legs=legs,
                adults=adults,
                children=children,
                infants=infants,
                nearby_radius_km=_nearby_radius_km(text, selected, normalized_preset),
                currency=_string(selected.get("currency", "RUB"), "currency"),
                requested_strategies=_strategies(selected, normalized_preset, text),
                clarifications=tuple(_unique_clarifications(clarifications)),
                preset_id=normalized_preset,
                baggage_preference=_baggage_preference(text, selected),
                wants_watch=_wants_watch(text, selected),
            )
        )
        return parsed, normalized_preset, selected

    def _apply_overlay(
        self,
        text: str,
        normalized_preset: AgentPresetId | None,
        selected: Mapping[str, object],
        parsed: ParsedIntent,
    ) -> ParsedIntent:
        if self._overlay_provider is None or not parsed.clarifications:
            return parsed
        try:
            raw_overlay = self._overlay_provider(text, normalized_preset, selected)
            overlay = (
                raw_overlay
                if isinstance(raw_overlay, IntentOverlay)
                else IntentOverlay.model_validate(raw_overlay)
            )
        except (IntentOverlayTransportError, ValidationError):
            return parsed
        augmented = dict(selected)
        if parsed.origin_scope is None and overlay.origin_text is not None:
            augmented["origin"] = overlay.origin_text
        if parsed.destination_scope is None and overlay.destination_text is not None:
            augmented["destination"] = overlay.destination_text
        if (
            "trip_shape" not in augmented
            and _trip_shape_from_text(text) is None
            and overlay.trip_shape is not None
        ):
            augmented["trip_shape"] = overlay.trip_shape.value
        date_missing = any(item.field == "date_constraint" for item in parsed.clarifications)
        if date_missing and "departure_date" not in augmented and overlay.departure_date:
            augmented["departure_date"] = overlay.departure_date
        if date_missing and "date_mode" not in augmented and overlay.date_mode is not None:
            augmented["date_mode"] = overlay.date_mode.value
        return_missing = any(
            item.field == "return_date_constraint" for item in parsed.clarifications
        )
        if return_missing and "return_date" not in augmented and overlay.return_date:
            augmented["return_date"] = overlay.return_date
        for field_name in ("adults", "children", "infants", "currency", "nearby_radius_km"):
            value = getattr(overlay, field_name)
            if field_name not in augmented and value is not None:
                augmented[field_name] = value
        if (
            "requested_strategies" not in augmented
            and not parsed.requested_strategies
            and overlay.requested_strategy_ids
        ):
            augmented["requested_strategies"] = [
                strategy.value for strategy in overlay.requested_strategy_ids
            ]
        if "baggage_preference" not in augmented and parsed.baggage_preference == "unspecified":
            augmented["baggage_preference"] = overlay.baggage_preference
        if "wants_watch" not in augmented and not parsed.wants_watch:
            augmented["wants_watch"] = overlay.wants_watch
        try:
            merged, _preset, _selected = self._parse_deterministic(
                text,
                normalized_preset,
                augmented,
            )
        except (TypeError, ValueError):
            return parsed
        return merged


def _parse_explicit_legs(
    value: object,
    clarifications: list[IntentClarification],
    taxonomy_resolver: ScopeResolver,
) -> tuple[ParsedLeg, ...]:
    if isinstance(value, (str, bytes)) or not isinstance(value, (tuple, list)):
        raise TypeError("legs must be an ordered collection")
    result: list[ParsedLeg] = []
    for index, item in enumerate(value):
        if not isinstance(item, Mapping):
            raise TypeError("each leg must be a mapping")
        origin = _parse_scope(item.get("origin"), taxonomy_resolver)
        destination = _parse_scope(item.get("destination"), taxonomy_resolver)
        _append_scope_clarification(clarifications, f"legs.{index}.origin", origin)
        _append_scope_clarification(clarifications, f"legs.{index}.destination", destination)
        date_value = item.get("date")
        constraint = ParsedDateConstraint(
            DateMode.EXACT,
            _parse_date(date_value) if date_value is not None else None,
        )
        clarifications.extend(constraint.clarifications(field=f"legs.{index}.date_constraint"))
        result.append(ParsedLeg(origin.scope, destination.scope, constraint))
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
                flex_days=_integer(selections.get("flex_days", 3), "flex_days"),
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
    if mode is DateMode.FLEXIBLE:
        return ParsedDateConstraint(
            DateMode.FLEXIBLE,
            date.fromisoformat(exact_match.group(1)) if exact_match else None,
            flex_days=_integer(selections.get("flex_days", 3), "flex_days"),
        )
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


def _trip_shape(
    selections: Mapping[str, object],
    legs: tuple[ParsedLeg, ...],
    text: str,
) -> TripShape:
    explicit = selections.get("trip_shape")
    if explicit is not None:
        return TripShape(_string(explicit, "trip_shape"))
    detected = _trip_shape_from_text(text)
    if detected is not None:
        return detected
    if len(legs) > 1:
        return TripShape.MULTI_CITY
    if selections.get("return_date") is not None:
        return TripShape.ROUND_TRIP
    return TripShape.ONE_WAY


def _strategies(
    selections: Mapping[str, object],
    preset: AgentPresetId | None,
    text: str,
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
    normalized = _normalize_text(text)
    detected: list[RouteStrategy] = []
    patterns = (
        (RouteStrategy.HIDDEN_CITY, r"(?:скрыт\w*\s+город|выйти\s+на\s+пересадке)"),
        (RouteStrategy.SPLIT_TICKET, r"(?:отдельн\w*\s+билет|разб(?:ей|ить)\s+маршрут)"),
        (RouteStrategy.SELF_TRANSFER, r"(?:самопересадк\w*|self[\s-]*transfer)"),
        (RouteStrategy.THROUGH_TICKET, r"(?:сквозн\w*\s+билет|единым\s+билетом)"),
        (RouteStrategy.DIRECT, r"(?:прям(?:ой|ым)\s+рейс|без\s+пересадок)"),
    )
    for strategy, pattern in patterns:
        if re.search(pattern, normalized):
            detected.append(strategy)
    return tuple(detected)


def _nearby_radius_km(
    text: str,
    selections: Mapping[str, object],
    preset: AgentPresetId | None,
) -> int:
    explicit = selections.get("nearby_radius_km")
    if explicit is not None:
        if type(explicit) is not int or not 0 <= explicit <= 500:
            raise ValueError("nearby_radius_km must be between 0 and 500")
        return explicit
    if preset is not None:
        preset_radius = PRESET_EDITS[preset.value].nearby_radius_km
        if preset_radius is not None:
            return preset_radius
    normalized = _normalize_text(text)
    if re.search(
        r"(?:аэропорт\w*\s+(?:рядом|поблизости)|близлежащ\w*\s+аэропорт\w*|nearby\s+airports?)",
        normalized,
    ):
        return 150
    return 0


def _baggage_preference(
    text: str,
    selections: Mapping[str, object],
) -> Literal["checked", "carry_on", "none", "unspecified"]:
    explicit = selections.get("baggage_preference")
    if explicit is not None:
        value = _string(explicit, "baggage_preference")
        if value not in {"checked", "carry_on", "none", "unspecified"}:
            raise ValueError("baggage_preference is invalid")
        return cast(Literal["checked", "carry_on", "none", "unspecified"], value)
    normalized = _normalize_text(text)
    if re.search(r"(?:без\s+багажа|только\s+ручн\w+\s+кладь)", normalized):
        return "none"
    if re.search(r"(?:с\s+ручн\w+\s+кладью|carry[\s-]*on)", normalized):
        return "carry_on"
    if re.search(r"(?:с\s+багажом|checked\s+baggage)", normalized):
        return "checked"
    return "unspecified"


def _wants_watch(text: str, selections: Mapping[str, object]) -> bool:
    explicit = selections.get("wants_watch")
    if explicit is not None:
        if type(explicit) is not bool:
            raise TypeError("wants_watch must be a boolean")
        return explicit
    return bool(
        re.search(
            r"(?:следи(?:ть)?\s+за\s+цен|отслеживай\s+цен|уведоми\s+когда)",
            _normalize_text(text),
        )
    )


def _route_parts(text: str) -> tuple[str | None, str | None]:
    route_text = _RANGE_DATE_RE.sub("", text)
    route_text = _FLEX_DATE_RE.sub("", route_text)
    route_text = _EXACT_DATE_RE.sub("", route_text)
    route_text = _RU_ROUND_TRIP_DATE_RE.sub("", route_text)
    route_text = _ROLLING_DATE_RE.sub("", route_text)
    for _, pattern in _TRIP_SHAPE_PATTERNS:
        route_text = pattern.sub("", route_text)
    route_text = _TRAILING_CONSTRAINT_RE.sub("", route_text)
    route_text = _TRAILING_TRAVEL_DETAILS_RE.sub("", route_text)
    parts = _ROUTE_SEPARATOR_RE.split(route_text, maxsplit=1)
    if len(parts) == 2:
        return parts[0].strip(" ,") or None, parts[1].strip(" ,") or None
    natural = _NATURAL_ROUTE_RE.search(route_text)
    if natural is None:
        return None, None
    return (
        natural.group("origin").strip(" ,") or None,
        natural.group("destination").strip(" ,") or None,
    )


def _natural_round_trip_dates(text: str) -> tuple[date, date] | None:
    match = _RU_ROUND_TRIP_DATE_RE.search(text)
    if match is None:
        return None
    month = _RU_MONTH_NUMBERS.get(_normalize_text(match.group("month")))
    if month is None:
        return None
    year = int(match.group("year"))
    try:
        departure = date(year, month, int(match.group("departure_day")))
        return_date = date(year, month, int(match.group("return_day")))
    except ValueError:
        return None
    return departure, return_date


def _trip_shape_from_text(text: str) -> TripShape | None:
    found = tuple(shape for shape, pattern in _TRIP_SHAPE_PATTERNS if pattern.search(text))
    return found[0] if len(found) == 1 else None


def _parse_scope(value: object, taxonomy_resolver: ScopeResolver) -> _ScopeParseResult:
    if isinstance(value, LocationScope):
        return _ScopeParseResult(value)
    if not isinstance(value, str) or not value.strip():
        return _ScopeParseResult(None)
    raw = value.strip()
    normalized = _normalize_text(raw)
    raw = _INFLECTED_LOCATION_ALIASES.get(normalized, raw)
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
            return _resolve_prefixed_scope(kind, scope_value, taxonomy_resolver)
    if normalized in _ANYWHERE_ALIASES:
        return _ScopeParseResult(LocationScope(LocationScopeKind.ANYWHERE, None))
    if normalized in _CITY_ALIASES:
        return _ScopeParseResult(LocationScope(LocationScopeKind.CITY, _CITY_ALIASES[normalized]))
    upper = raw.upper()
    if _IATA_RE.fullmatch(upper):
        return _ScopeParseResult(LocationScope(LocationScopeKind.AIRPORT, upper))
    if _COUNTRY_CODE_RE.fullmatch(upper):
        return _ScopeParseResult(LocationScope(LocationScopeKind.COUNTRY, upper))
    country = taxonomy_resolver.resolve_country_text(raw)
    if isinstance(country, GeographyChoice):
        return _ScopeParseResult(country.scope)
    if country.reason == "ambiguous_geography":
        return _ScopeParseResult(None, country)
    region = taxonomy_resolver.resolve_region_text(raw)
    if isinstance(region, GeographyChoice):
        return _ScopeParseResult(region.scope)
    return _ScopeParseResult(None)


def _resolve_prefixed_scope(
    kind: LocationScopeKind,
    value: str,
    taxonomy_resolver: ScopeResolver,
) -> _ScopeParseResult:
    if kind is LocationScopeKind.COUNTRY and not _COUNTRY_CODE_RE.fullmatch(value.upper()):
        resolved = taxonomy_resolver.resolve_country_text(value)
        return _scope_result_from_geography(resolved)
    if kind is LocationScopeKind.REGION:
        resolved = taxonomy_resolver.resolve_region_text(value)
        return _scope_result_from_geography(resolved)
    return _ScopeParseResult(LocationScope(kind, value))


def _scope_result_from_geography(
    resolved: GeographyChoice | GeographyClarification,
) -> _ScopeParseResult:
    if isinstance(resolved, GeographyChoice):
        return _ScopeParseResult(resolved.scope)
    return _ScopeParseResult(None, resolved)


def _append_scope_clarification(
    clarifications: list[IntentClarification],
    field: str,
    result: _ScopeParseResult,
) -> None:
    if result.geography is not None:
        clarifications.append(
            IntentClarification(
                field=f"{field}_scope",
                code=result.geography.reason,
                message_ru="Уточните географию маршрута.",
                geography=result.geography,
            )
        )
    elif result.scope is None:
        clarifications.append(_location_clarification(field))


def _with_semantic_clarifications(parsed: ParsedIntent) -> ParsedIntent:
    clarifications = list(parsed.clarifications)
    if parsed.legs:
        effective = replace(parsed.legs[0].date_constraint, mode=parsed.date_mode)
        clarifications.extend(effective.clarifications(field="date_constraint"))
    if parsed.trip_shape is TripShape.ROUND_TRIP:
        if len(parsed.legs) < 2 or parsed.legs[1].date_constraint.start_date is None:
            clarifications.append(_return_date_clarification())
        else:
            outbound_end = _parsed_date_upper_bound(
                replace(parsed.legs[0].date_constraint, mode=parsed.date_mode)
            )
            return_date = parsed.legs[1].date_constraint.start_date
            if outbound_end is not None and return_date < outbound_end:
                clarifications.append(return_before_outbound_window_end_clarification())
    elif parsed.trip_shape in {TripShape.OPEN_JAW, TripShape.MULTI_CITY} and len(parsed.legs) < 2:
        clarifications.append(
            IntentClarification(
                field="trip_legs",
                code="trip_legs_required",
                message_ru="Для этой формы маршрута нужны как минимум два упорядоченных плеча.",
            )
        )
    return replace(parsed, clarifications=tuple(_unique_clarifications(clarifications)))


def _leg_count_is_valid(shape: TripShape, count: int) -> bool:
    if shape is TripShape.ONE_WAY:
        return count == 1
    if shape in {TripShape.ROUND_TRIP, TripShape.OPEN_JAW}:
        return count == 2
    return count >= 2


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


def return_before_outbound_window_end_clarification() -> IntentClarification:
    return IntentClarification(
        field="return_date_constraint",
        code="return_before_outbound_window_end",
        message_ru=("Дата возвращения не может быть раньше последней допустимой даты вылета."),
    )


def _parsed_date_upper_bound(constraint: ParsedDateConstraint) -> date | None:
    if constraint.start_date is None:
        return None
    if constraint.mode is DateMode.EXACT:
        return constraint.start_date
    if constraint.mode is DateMode.FLEXIBLE:
        if constraint.flex_days <= 0:
            return None
        return constraint.start_date + timedelta(days=constraint.flex_days)
    if constraint.mode is DateMode.RANGE:
        if constraint.end_date is None or constraint.end_date < constraint.start_date:
            return None
        return constraint.end_date
    return None


def _location_clarification(field: str) -> IntentClarification:
    return IntentClarification(
        field=field,
        code="location_required_or_unknown",
        message_ru="Укажите известный аэропорт, город, страну или регион.",
    )


def _unique_clarifications(
    values: list[IntentClarification],
) -> tuple[IntentClarification, ...]:
    seen: set[tuple[str, str]] = set()
    result: list[IntentClarification] = []
    for value in values:
        key = (value.field, value.code)
        if key not in seen:
            seen.add(key)
            result.append(value)
    return tuple(result)


def _parse_date(value: object) -> date:
    if type(value) is date:
        return value
    if not isinstance(value, str):
        raise TypeError("date values must be ISO dates")
    return date.fromisoformat(value)


def _integer(value: object, field: str) -> int:
    if type(value) is not int:
        raise ValueError(f"{field} must be an integer")
    return value


def _passenger_counts(
    text: str,
    selections: Mapping[str, object],
) -> tuple[int, int, int]:
    values = {
        "adults": selections.get("adults", 1),
        "children": selections.get("children", 0),
        "infants": selections.get("infants", 0),
    }
    for field_name, pattern in _PASSENGER_COUNT_PATTERNS.items():
        if match := pattern.search(text):
            values[field_name] = int(match.group("count"))
    return (
        _positive_int(values["adults"], "adults"),
        _non_negative_int(values["children"], "children"),
        _non_negative_int(values["infants"], "infants"),
    )


def _positive_int(value: object, field: str) -> int:
    parsed = _integer(value, field)
    if parsed <= 0:
        raise ValueError(f"{field} must be a positive integer")
    return parsed


def _non_negative_int(value: object, field: str) -> int:
    parsed = _integer(value, field)
    if parsed < 0:
        raise ValueError(f"{field} must be a non-negative integer")
    return parsed


def _string(value: object, field: str) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{field} must be a non-empty string")
    return value


def _optional_text(value: object) -> str | None:
    return value if isinstance(value, str) and value.strip() else None


def _scope_text(scope: LocationScope | None) -> str | None:
    return scope.value if scope is not None else None
