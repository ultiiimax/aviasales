from __future__ import annotations

import flight_hunter.agent.presets as presets
from flight_hunter.agent.presets import AgentPresetId
from flight_hunter.domain.agent_search import RouteStrategy


def test_agent_presets_preserve_all_seven_compatibility_ids() -> None:
    listed = {preset.id for preset in presets.list_presets()}

    assert listed == set(AgentPresetId)
    assert set(presets.PRESET_EDITS) == {preset_id.value for preset_id in AgentPresetId}


def test_agent_preset_edits_are_typed_and_preserve_required_defaults() -> None:
    flexible = presets.PRESET_EDITS[AgentPresetId.FLEXIBLE_DATES.value]
    nearby = presets.PRESET_EDITS[AgentPresetId.NEARBY_AIRPORTS.value]
    hidden = presets.PRESET_EDITS[AgentPresetId.HIDDEN_CITY.value]
    split = presets.PRESET_EDITS[AgentPresetId.SPLIT_TICKET.value]

    assert flexible.default_flex_days == 3
    assert nearby.nearby_radius_km == 150
    assert hidden.strategies == (RouteStrategy.HIDDEN_CITY,)
    assert split.strategies == (RouteStrategy.SPLIT_TICKET,)
    assert presets.PRESET_EDITS[AgentPresetId.BUY_TIMING.value].analysis_modes == (
        presets.AnalysisMode.BUY_TIMING,
    )
    assert presets.PRESET_EDITS[AgentPresetId.ERROR_FARE_SOURCES.value].analysis_modes == (
        presets.AnalysisMode.ERROR_FARE,
    )
    assert presets.PRESET_EDITS[AgentPresetId.GEO_CURRENCY.value].analysis_modes == (
        presets.AnalysisMode.CURRENCY_COMPARE,
    )


def test_preset_edits_translate_only_supported_builder_selections() -> None:
    selections = presets.apply_preset_edits(
        AgentPresetId.FLEXIBLE_DATES,
        {"origin": "LED", "destination": "CDG", "departure_date": "2026-10-12"},
    )

    assert selections == {
        "origin": "LED",
        "destination": "CDG",
        "departure_date": "2026-10-12",
        "date_mode": "flexible",
        "flex_days": 3,
    }
