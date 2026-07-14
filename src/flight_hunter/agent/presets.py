# ruff: noqa: RUF001

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from types import MappingProxyType

from flight_hunter.domain.agent_search import DateMode, RouteStrategy


class AgentPresetId(StrEnum):
    BUY_TIMING = "buy_timing"
    FLEXIBLE_DATES = "flexible_dates"
    NEARBY_AIRPORTS = "nearby_airports"
    HIDDEN_CITY = "hidden_city"
    SPLIT_TICKET = "split_ticket"
    ERROR_FARE_SOURCES = "error_fare_sources"
    GEO_CURRENCY = "geo_currency"


class RiskLevel(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class AnalysisMode(StrEnum):
    BUY_TIMING = "buy_timing"
    ERROR_FARE = "error_fare"
    CURRENCY_COMPARE = "currency_compare"


@dataclass(frozen=True, slots=True)
class PlanEdits:
    analysis_modes: tuple[AnalysisMode, ...] = ()
    default_flex_days: int | None = None
    nearby_radius_km: int | None = None
    strategies: tuple[RouteStrategy, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "analysis_modes",
            tuple(AnalysisMode(value) for value in self.analysis_modes),
        )
        object.__setattr__(
            self,
            "strategies",
            tuple(RouteStrategy(value) for value in self.strategies),
        )
        if self.default_flex_days is not None and self.default_flex_days <= 0:
            raise ValueError("default_flex_days must be positive")
        if self.nearby_radius_km is not None and self.nearby_radius_km <= 0:
            raise ValueError("nearby_radius_km must be positive")


@dataclass(frozen=True, slots=True)
class AgentPreset:
    id: AgentPresetId
    title_ru: str
    description_ru: str
    required_slots: tuple[str, ...]
    risk_level: RiskLevel


PRESETS: Mapping[AgentPresetId, AgentPreset] = MappingProxyType(
    {
        AgentPresetId.BUY_TIMING: AgentPreset(
            id=AgentPresetId.BUY_TIMING,
            title_ru="Когда покупать",
            description_ru="Оценить момент покупки только по накопленной истории цен.",
            required_slots=("origin", "destination", "departure_date"),
            risk_level=RiskLevel.LOW,
        ),
        AgentPresetId.FLEXIBLE_DATES: AgentPreset(
            id=AgentPresetId.FLEXIBLE_DATES,
            title_ru="Даты ±3 дня",
            description_ru="Сравнить соседние даты после подтверждения плана.",
            required_slots=("origin", "destination", "departure_date"),
            risk_level=RiskLevel.LOW,
        ),
        AgentPresetId.NEARBY_AIRPORTS: AgentPreset(
            id=AgentPresetId.NEARBY_AIRPORTS,
            title_ru="Аэропорты рядом",
            description_ru="Проверить аэропорты вылета и прилёта в радиусе 150 км.",
            required_slots=("origin", "destination"),
            risk_level=RiskLevel.LOW,
        ),
        AgentPresetId.HIDDEN_CITY: AgentPreset(
            id=AgentPresetId.HIDDEN_CITY,
            title_ru="Скрытый город",
            description_ru="Отдельное исследование с дополнительным предупреждением о рисках.",
            required_slots=("origin", "destination", "departure_date"),
            risk_level=RiskLevel.HIGH,
        ),
        AgentPresetId.SPLIT_TICKET: AgentPreset(
            id=AgentPresetId.SPLIT_TICKET,
            title_ru="Разбить билет",
            description_ru="Сравнить единый маршрут и отдельные подтверждённые сегменты.",
            required_slots=("origin", "destination", "departure_date"),
            risk_level=RiskLevel.MEDIUM,
        ),
        AgentPresetId.ERROR_FARE_SOURCES: AgentPreset(
            id=AgentPresetId.ERROR_FARE_SOURCES,
            title_ru="Аномально низкие цены",
            description_ru="Искать только доказуемые подозрения на ценовую аномалию.",
            required_slots=("region",),
            risk_level=RiskLevel.MEDIUM,
        ),
        AgentPresetId.GEO_CURRENCY: AgentPreset(
            id=AgentPresetId.GEO_CURRENCY,
            title_ru="Страна сайта и валюта",
            description_ru="Сравнить сопоставимые предложения с подтверждённым FX.",
            required_slots=("flight",),
            risk_level=RiskLevel.MEDIUM,
        ),
    }
)


PRESET_EDITS: Mapping[str, PlanEdits] = MappingProxyType(
    {
        AgentPresetId.BUY_TIMING.value: PlanEdits(analysis_modes=(AnalysisMode.BUY_TIMING,)),
        AgentPresetId.FLEXIBLE_DATES.value: PlanEdits(default_flex_days=3),
        AgentPresetId.NEARBY_AIRPORTS.value: PlanEdits(nearby_radius_km=150),
        AgentPresetId.HIDDEN_CITY.value: PlanEdits(strategies=(RouteStrategy.HIDDEN_CITY,)),
        AgentPresetId.SPLIT_TICKET.value: PlanEdits(strategies=(RouteStrategy.SPLIT_TICKET,)),
        AgentPresetId.ERROR_FARE_SOURCES.value: PlanEdits(
            analysis_modes=(AnalysisMode.ERROR_FARE,)
        ),
        AgentPresetId.GEO_CURRENCY.value: PlanEdits(
            analysis_modes=(AnalysisMode.CURRENCY_COMPARE,)
        ),
    }
)


def list_presets() -> tuple[AgentPreset, ...]:
    return tuple(PRESETS.values())


def apply_preset_edits(
    preset_id: AgentPresetId | str,
    selections: Mapping[str, object],
) -> dict[str, object]:
    normalized = AgentPresetId(preset_id)
    edits = PRESET_EDITS[normalized.value]
    result = {key: value for key, value in selections.items() if value not in (None, "")}
    if edits.default_flex_days is not None and result.get("departure_date") is not None:
        result.setdefault("date_mode", DateMode.FLEXIBLE.value)
        result.setdefault("flex_days", edits.default_flex_days)
    if edits.strategies:
        result.setdefault(
            "requested_strategies",
            [strategy.value for strategy in edits.strategies],
        )
    return result
