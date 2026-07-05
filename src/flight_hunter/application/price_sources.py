from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class PriceSourceType(StrEnum):
    API = "api"
    PARTNER_LINK = "partner_link"
    AGGREGATOR_SITE = "aggregator_site"
    CARRIER_SITE = "carrier_site"


class PriceKind(StrEnum):
    LIVE = "live"
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
                    id="aviasales_search",
                    name="Aviasales mobile API",
                    source_type=PriceSourceType.API,
                    price_kind=PriceKind.LIVE,
                    supports_rub=True,
                    in_app_booking=False,
                    purchase_flow="external_clickout",
                    requires_manual_confirmation=False,
                    setup_required_ru="AVIASALES_SEARCH_SIGNATURE and AVIASALES_SEARCH_MARKER.",
                    notes_ru=(
                        "Live Aviasales mobile search. Purchase URL is resolved only after an "
                        "explicit booking action."
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
                    setup_required_ru="Partner or normal Aviasales search link.",
                    notes_ru="User opens Aviasales and verifies the final price there.",
                ),
                PriceSource(
                    id="yandex_travel",
                    name="Yandex Travel",
                    source_type=PriceSourceType.PARTNER_LINK,
                    price_kind=PriceKind.USER_CONFIRMED_LIVE,
                    supports_rub=True,
                    in_app_booking=False,
                    purchase_flow="external_clickout",
                    requires_manual_confirmation=True,
                    setup_required_ru="Yandex Distribution access or manual search link.",
                    notes_ru="Click-out source; final price is confirmed on Yandex Travel.",
                ),
                PriceSource(
                    id="tutu",
                    name="Tutu",
                    source_type=PriceSourceType.PARTNER_LINK,
                    price_kind=PriceKind.USER_CONFIRMED_LIVE,
                    supports_rub=True,
                    in_app_booking=False,
                    purchase_flow="external_clickout",
                    requires_manual_confirmation=True,
                    setup_required_ru="Partner program or manual search link.",
                    notes_ru="Purchase and final price are confirmed on Tutu.",
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
                    setup_required_ru="Partner agreement or manual search link.",
                    notes_ru="User verifies the price outside Flight Hunter.",
                ),
                *_additional_carrier_sources(),
            )
        )


def _additional_carrier_sources() -> tuple[PriceSource, ...]:
    return tuple(
        _carrier_source(source_id=source_id, name=name)
        for source_id, name in (
            ("aeroflot", "Aeroflot"),
            ("pobeda", "Pobeda"),
            ("s7", "S7 Airlines"),
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
