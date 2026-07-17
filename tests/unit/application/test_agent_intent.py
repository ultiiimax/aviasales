from __future__ import annotations

from collections.abc import Mapping
from datetime import date

import pytest
from pydantic import ValidationError

from flight_hunter.agent.presets import AgentPresetId
from flight_hunter.application.agent_intent import (
    ClarificationAction,
    IntentOverlay,
    IntentOverlayTransportError,
    IntentParser,
    merge_overlay,
)
from flight_hunter.domain.agent_search import (
    DateMode,
    LocationScope,
    LocationScopeKind,
    RouteStrategy,
    TravelIntent,
    TripShape,
)


def test_missing_date_returns_structured_clarification_and_rolling_action() -> None:
    parsed = IntentParser().parse("СПб → Франция", preset=None, selections={})

    assert parsed.origin_scope == LocationScope(LocationScopeKind.CITY, "LED")
    assert parsed.destination_scope == LocationScope(LocationScopeKind.COUNTRY, "FR")
    assert parsed.travel_intent is None
    assert tuple(item.field for item in parsed.clarifications) == ("date_constraint",)
    action = parsed.clarifications[0].actions[0]
    assert action.action_id == "use_rolling_90_days"
    assert action.date_mode is DateMode.ROLLING_90_DAYS
    assert action.selections == {"date_mode": "rolling_90_days"}


@pytest.mark.parametrize(
    ("text", "expected_origin", "expected_destination"),
    (
        (
            "airport:LED → airport:CDG",
            LocationScope(LocationScopeKind.AIRPORT, "LED"),
            LocationScope(LocationScopeKind.AIRPORT, "CDG"),
        ),
        (
            "Saint Petersburg → Париж",
            LocationScope(LocationScopeKind.CITY, "LED"),
            LocationScope(LocationScopeKind.CITY, "PAR"),
        ),
        (
            "Россия → France",
            LocationScope(LocationScopeKind.COUNTRY, "RU"),
            LocationScope(LocationScopeKind.COUNTRY, "FR"),
        ),
        (
            "Москва → Southern Europe",
            LocationScope(LocationScopeKind.CITY, "MOW"),
            LocationScope(LocationScopeKind.REGION, "southern_europe"),
        ),
        (
            "Moscow → куда угодно",
            LocationScope(LocationScopeKind.CITY, "MOW"),
            LocationScope(LocationScopeKind.ANYWHERE, None),
        ),
    ),
)
def test_ru_en_location_aliases_are_deterministic(
    text: str,
    expected_origin: LocationScope,
    expected_destination: LocationScope,
) -> None:
    parsed = IntentParser().parse(
        text,
        preset=None,
        selections={"departure_date": "2026-09-10"},
    )

    assert parsed.origin_scope == expected_origin
    assert parsed.destination_scope == expected_destination
    assert isinstance(parsed.travel_intent, TravelIntent)


@pytest.mark.parametrize(
    ("selections", "expected_mode", "expected_end", "expected_flex"),
    (
        ({"departure_date": "2026-09-10"}, DateMode.EXACT, None, 0),
        (
            {"departure_date": "2026-09-10", "date_mode": "flexible", "flex_days": 3},
            DateMode.FLEXIBLE,
            None,
            3,
        ),
        (
            {
                "date_mode": "range",
                "date_start": "2026-09-01",
                "date_end": "2026-09-30",
            },
            DateMode.RANGE,
            date(2026, 9, 30),
            0,
        ),
        ({"date_mode": "rolling_90_days"}, DateMode.ROLLING_90_DAYS, None, 0),
    ),
)
def test_exact_flexible_range_and_rolling_date_modes(
    selections: dict[str, object],
    expected_mode: DateMode,
    expected_end: date | None,
    expected_flex: int,
) -> None:
    parsed = IntentParser().parse("LED → CDG", preset=None, selections=selections)

    assert parsed.date_mode is expected_mode
    assert parsed.date_constraints[0].end_date == expected_end
    assert parsed.date_constraints[0].flex_days == expected_flex


def test_rolling_90_days_text_does_not_pollute_destination_alias() -> None:
    parsed = IntentParser().parse(
        "СПб → Франция, ближайшие 90 дней",
        preset=None,
        selections={},
    )

    assert parsed.destination_scope == LocationScope(LocationScopeKind.COUNTRY, "FR")
    assert parsed.date_mode is DateMode.ROLLING_90_DAYS
    assert parsed.clarifications == ()


def test_watch_baggage_and_split_ticket_phrases_stay_typed() -> None:
    parsed = IntentParser().parse(
        "LED → CDG 2026-09-10, с багажом, следи за ценой, можно отдельными билетами",  # noqa: RUF001
        preset=None,
        selections={},
    )

    assert parsed.clarifications == ()
    assert parsed.wants_watch is True
    assert parsed.baggage_preference == "checked"
    assert parsed.requested_strategies == (RouteStrategy.SPLIT_TICKET,)


def test_one_way_round_trip_open_jaw_and_ordered_multi_city() -> None:
    parser = IntentParser()
    one_way = parser.parse(
        "LED → CDG",
        preset=None,
        selections={"departure_date": "2026-09-10", "trip_shape": "one_way"},
    )
    round_trip = parser.parse(
        "LED → CDG",
        preset=None,
        selections={
            "departure_date": "2026-09-10",
            "return_date": "2026-09-20",
            "trip_shape": "round_trip",
        },
    )
    open_jaw = parser.parse(
        "",
        preset=None,
        selections={
            "trip_shape": "open_jaw",
            "legs": (
                {"origin": "LED", "destination": "CDG", "date": "2026-09-10"},
                {"origin": "NCE", "destination": "LED", "date": "2026-09-20"},
            ),
        },
    )
    multi_city = parser.parse(
        "",
        preset=None,
        selections={
            "trip_shape": "multi_city",
            "legs": (
                {"origin": "LED", "destination": "CDG", "date": "2026-09-10"},
                {"origin": "CDG", "destination": "FCO", "date": "2026-09-15"},
                {"origin": "FCO", "destination": "LED", "date": "2026-09-20"},
            ),
        },
    )

    intents = tuple(result.travel_intent for result in (one_way, round_trip, open_jaw, multi_city))
    assert all(isinstance(intent, TravelIntent) for intent in intents)
    assert tuple(intent.trip_shape for intent in intents if intent is not None) == tuple(TripShape)
    assert multi_city.travel_intent is not None
    assert tuple(leg.origin.value for leg in multi_city.travel_intent.legs) == (
        "LED",
        "CDG",
        "FCO",
    )


@pytest.mark.parametrize("return_date", ("2026-09-09", "2026-09-11"))
def test_flexible_round_trip_requires_return_after_full_outbound_window(
    return_date: str,
) -> None:
    parsed = IntentParser().parse(
        "LED → CDG",
        preset=None,
        selections={
            "departure_date": "2026-09-10",
            "date_mode": "flexible",
            "flex_days": 2,
            "return_date": return_date,
        },
    )

    assert parsed.travel_intent is None
    assert tuple(item.field for item in parsed.clarifications) == ("return_date_constraint",)
    assert tuple(item.code for item in parsed.clarifications) == (
        "return_before_outbound_window_end",
    )


def test_flexible_round_trip_accepts_return_at_outbound_window_end() -> None:
    parsed = IntentParser().parse(
        "LED → CDG",
        preset=None,
        selections={
            "departure_date": "2026-09-10",
            "date_mode": "flexible",
            "flex_days": 2,
            "return_date": "2026-09-12",
        },
    )

    assert parsed.clarifications == ()
    assert parsed.travel_intent is not None
    assert parsed.travel_intent.legs[1].date_constraint.start_date == date(2026, 9, 12)


@pytest.mark.parametrize("preset", tuple(AgentPresetId))
def test_every_existing_preset_produces_the_same_travel_intent_type(
    preset: AgentPresetId,
) -> None:
    parsed = IntentParser().parse(
        "LED → CDG",
        preset=preset,
        selections={"departure_date": "2026-09-10"},
    )

    assert type(parsed.travel_intent) is TravelIntent


def test_typed_overlay_can_change_only_allowed_planning_fields() -> None:
    base = IntentParser().parse(
        "LED → CDG",
        preset=None,
        selections={"departure_date": "2026-09-10"},
    )
    overlay = IntentOverlay(
        origin_text="invented origin",
        destination_text="invented destination",
        trip_shape=TripShape.ROUND_TRIP,
        date_mode=DateMode.FLEXIBLE,
        requested_strategy_ids=(RouteStrategy.SPLIT_TICKET,),
    )

    merged = merge_overlay(base, overlay)

    assert merged.origin_text == base.origin_text
    assert merged.destination_text == base.destination_text
    assert merged.trip_shape is TripShape.ROUND_TRIP
    assert merged.date_mode is DateMode.FLEXIBLE
    assert merged.requested_strategies == (RouteStrategy.SPLIT_TICKET,)
    with pytest.raises(ValidationError):
        IntentOverlay.model_validate({"budget": 1, "airport_codes": ["LED"]})


def test_overlay_transport_or_validation_failure_returns_deterministic_base() -> None:
    def transport_failure(*_args: object) -> IntentOverlay:
        raise IntentOverlayTransportError("model unavailable")

    def invalid_overlay(*_args: object) -> dict[str, object]:
        return {"price": 1, "airport_codes": ["INVENTED"]}

    selections = {"departure_date": "2026-09-10"}
    base = IntentParser().parse("LED → France", preset=None, selections=selections)

    assert (
        IntentParser(overlay_provider=transport_failure).parse(
            "LED → France",
            preset=None,
            selections=selections,
        )
        == base
    )
    assert (
        IntentParser(overlay_provider=invalid_overlay).parse(
            "LED → France",
            preset=None,
            selections=selections,
        )
        == base
    )


def test_parser_overlay_only_fills_fields_left_unresolved() -> None:
    def conflicting_overlay(*_args: object) -> IntentOverlay:
        return IntentOverlay(
            origin_text="MOW",
            destination_text="JFK",
            trip_shape=TripShape.ONE_WAY,
            date_mode=DateMode.FLEXIBLE,
            return_date="2026-09-20",
        )

    parsed = IntentParser(overlay_provider=conflicting_overlay).parse(
        "LED → CDG туда-обратно 2026-09-10",
        preset=None,
        selections={},
    )

    assert parsed.origin_scope == LocationScope(LocationScopeKind.AIRPORT, "LED")
    assert parsed.destination_scope == LocationScope(LocationScopeKind.AIRPORT, "CDG")
    assert parsed.trip_shape is TripShape.ROUND_TRIP
    assert parsed.date_mode is DateMode.EXACT
    assert parsed.legs[1].date_constraint.start_date == date(2026, 9, 20)


def test_overlay_fallback_does_not_swallow_unclassified_programming_errors() -> None:
    def programming_error(*_args: object) -> IntentOverlay:
        raise RuntimeError("bug")

    with pytest.raises(RuntimeError, match="bug"):
        IntentParser(overlay_provider=programming_error).parse(
            "LED → France",
            preset=None,
            selections={},
        )


@pytest.mark.parametrize(
    ("selections", "expected_code"),
    (
        (
            {"date_mode": "range", "date_start": "2026-09-01"},
            "date_range_end_required",
        ),
        (
            {
                "date_mode": "range",
                "date_start": "2026-09-30",
                "date_end": "2026-09-01",
            },
            "date_range_end_before_start",
        ),
        (
            {
                "date_mode": "flexible",
                "departure_date": "2026-09-10",
                "flex_days": 0,
            },
            "date_flex_days_invalid",
        ),
    ),
)
def test_invalid_date_mode_dependencies_are_structured_before_planning(
    selections: dict[str, object],
    expected_code: str,
) -> None:
    parsed = IntentParser().parse("LED → CDG", preset=None, selections=selections)

    assert parsed.travel_intent is None
    assert tuple(item.code for item in parsed.clarifications) == (expected_code,)


@pytest.mark.parametrize(
    ("text", "shape", "field"),
    (
        ("LED → CDG round trip 2026-09-10", TripShape.ROUND_TRIP, "return_date_constraint"),
        ("LED → CDG туда-обратно 2026-09-10", TripShape.ROUND_TRIP, "return_date_constraint"),
        ("LED → CDG open jaw 2026-09-10", TripShape.OPEN_JAW, "trip_legs"),
        ("LED → CDG разомкнутый маршрут 2026-09-10", TripShape.OPEN_JAW, "trip_legs"),
        ("LED → CDG multi-city 2026-09-10", TripShape.MULTI_CITY, "trip_legs"),
        ("LED → CDG сложный маршрут 2026-09-10", TripShape.MULTI_CITY, "trip_legs"),
    ),
)
def test_ru_en_trip_shape_aliases_are_bounded_and_stripped_from_route(
    text: str,
    shape: TripShape,
    field: str,
) -> None:
    parsed = IntentParser().parse(text, preset=None, selections={})

    assert parsed.trip_shape is shape
    assert parsed.destination_scope == LocationScope(LocationScopeKind.AIRPORT, "CDG")
    assert field in {item.field for item in parsed.clarifications}


def test_clarification_action_selections_are_deeply_immutable_mapping() -> None:
    source = {"date_mode": "rolling_90_days"}
    action = ClarificationAction(
        action_id="rolling",
        label_ru="90 дней",
        selections=source,
        date_mode=DateMode.ROLLING_90_DAYS,
    )
    source["date_mode"] = "exact"

    assert isinstance(action.selections, Mapping)
    assert action.selections == {"date_mode": "rolling_90_days"}
    with pytest.raises(TypeError):
        action.selections["date_mode"] = "exact"  # type: ignore[index]
