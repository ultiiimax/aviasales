# ruff: noqa: RUF001

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class PriceSourceType(StrEnum):
    API = "api"
    PARTNER_LINK = "partner_link"
    AGGREGATOR_SITE = "aggregator_site"
    CARRIER_SITE = "carrier_site"


class PriceKind(StrEnum):
    CACHED = "cached"
    USER_CONFIRMED_LIVE = "user_confirmed_live"


@dataclass(frozen=True, slots=True)
class PriceSource:
    id: str
    name: str
    source_type: PriceSourceType
    price_kind: PriceKind
    supports_rub: bool
    in_app_booking: bool
    purchase_flow: str
    requires_manual_confirmation: bool
    setup_required_ru: str
    notes_ru: str


@dataclass(frozen=True, slots=True)
class PriceSourceCatalog:
    sources: tuple[PriceSource, ...]

    @classmethod
    def default(cls) -> PriceSourceCatalog:
        return cls(
            sources=(
                PriceSource(
                    id="aviasales_data",
                    name="Aviasales / Travelpayouts Data API",
                    source_type=PriceSourceType.API,
                    price_kind=PriceKind.CACHED,
                    supports_rub=True,
                    in_app_booking=False,
                    purchase_flow="external_clickout",
                    requires_manual_confirmation=True,
                    setup_required_ru="Travelpayouts account и API token.",
                    notes_ru=(
                        "Официальный cached API. Цена не считается live и всегда требует "
                        "проверки перед покупкой."
                    ),
                ),
                PriceSource(
                    id="aviasales_clickout",
                    name="Aviasales",
                    source_type=PriceSourceType.PARTNER_LINK,
                    price_kind=PriceKind.USER_CONFIRMED_LIVE,
                    supports_rub=True,
                    in_app_booking=False,
                    purchase_flow="external_clickout",
                    requires_manual_confirmation=True,
                    setup_required_ru="Партнерская ссылка или обычная ссылка на поиск.",
                    notes_ru="Пользователь открывает Aviasales и подтверждает актуальную цену там.",
                ),
                PriceSource(
                    id="yandex_travel",
                    name="Яндекс Путешествия",
                    source_type=PriceSourceType.PARTNER_LINK,
                    price_kind=PriceKind.USER_CONFIRMED_LIVE,
                    supports_rub=True,
                    in_app_booking=False,
                    purchase_flow="external_clickout",
                    requires_manual_confirmation=True,
                    setup_required_ru="Заявка в Yandex Distribution для партнерских ссылок.",
                    notes_ru=(
                        "Для авиа обычно используем click-out. API в документации Яндекса "
                        "описан прежде всего для отелей."
                    ),
                ),
                PriceSource(
                    id="tutu",
                    name="Туту",
                    source_type=PriceSourceType.PARTNER_LINK,
                    price_kind=PriceKind.USER_CONFIRMED_LIVE,
                    supports_rub=True,
                    in_app_booking=False,
                    purchase_flow="external_clickout",
                    requires_manual_confirmation=True,
                    setup_required_ru="Партнерская программа/ссылка, если доступна для проекта.",
                    notes_ru="Покупка и финальная цена подтверждаются на стороне Туту.",
                ),
                PriceSource(
                    id="onetwotrip",
                    name="OneTwoTrip",
                    source_type=PriceSourceType.AGGREGATOR_SITE,
                    price_kind=PriceKind.USER_CONFIRMED_LIVE,
                    supports_rub=True,
                    in_app_booking=False,
                    purchase_flow="external_clickout",
                    requires_manual_confirmation=True,
                    setup_required_ru="Партнерская договоренность или ручная ссылка на поиск.",
                    notes_ru="Не используем скрытый scraping; пользователь проверяет цену снаружи.",
                ),
                PriceSource(
                    id="aeroflot",
                    name="Аэрофлот",
                    source_type=PriceSourceType.CARRIER_SITE,
                    price_kind=PriceKind.USER_CONFIRMED_LIVE,
                    supports_rub=True,
                    in_app_booking=False,
                    purchase_flow="external_clickout",
                    requires_manual_confirmation=True,
                    setup_required_ru="Официальный сайт перевозчика, без API-обхода.",
                    notes_ru="Подходит для проверки цены напрямую у перевозчика.",
                ),
                PriceSource(
                    id="pobeda",
                    name="Победа",
                    source_type=PriceSourceType.CARRIER_SITE,
                    price_kind=PriceKind.USER_CONFIRMED_LIVE,
                    supports_rub=True,
                    in_app_booking=False,
                    purchase_flow="external_clickout",
                    requires_manual_confirmation=True,
                    setup_required_ru="Официальный сайт перевозчика, без API-обхода.",
                    notes_ru="Важно отдельно учитывать багаж и выбор места.",
                ),
                PriceSource(
                    id="s7",
                    name="S7 Airlines",
                    source_type=PriceSourceType.CARRIER_SITE,
                    price_kind=PriceKind.USER_CONFIRMED_LIVE,
                    supports_rub=True,
                    in_app_booking=False,
                    purchase_flow="external_clickout",
                    requires_manual_confirmation=True,
                    setup_required_ru="Официальный сайт перевозчика, без API-обхода.",
                    notes_ru="Подходит для прямой проверки тарифа и правил у перевозчика.",
                ),
                *_additional_carrier_sources(),
            )
        )


def _additional_carrier_sources() -> tuple[PriceSource, ...]:
    return tuple(
        _carrier_source(source_id=source_id, name=name)
        for source_id, name in (
            ("ural_airlines", "Ural Airlines"),
            ("nordwind", "Nordwind"),
            ("red_wings", "Red Wings"),
            ("smartavia", "Smartavia"),
            ("azimuth", "Azimuth"),
            ("utair", "Utair"),
            ("rossiya", "Rossiya Airlines"),
            ("turkish_airlines", "Turkish Airlines"),
            ("air_serbia", "Air Serbia"),
            ("pegasus", "Pegasus"),
            ("uzbekistan_airways", "Uzbekistan Airways"),
            ("emirates", "Emirates"),
            ("qatar_airways", "Qatar Airways"),
            ("etihad", "Etihad"),
            ("flydubai", "flydubai"),
        )
    )


def _carrier_source(*, source_id: str, name: str) -> PriceSource:
    return PriceSource(
        id=source_id,
        name=name,
        source_type=PriceSourceType.CARRIER_SITE,
        price_kind=PriceKind.USER_CONFIRMED_LIVE,
        supports_rub=True,
        in_app_booking=False,
        purchase_flow="external_clickout",
        requires_manual_confirmation=True,
        setup_required_ru="Official carrier website, no API bypass.",
        notes_ru=(
            "Open the official carrier website and verify route, dates, fare rules, baggage and "
            "final price manually. Flight Hunter does not treat this link as a found ticket."
        ),
    )
