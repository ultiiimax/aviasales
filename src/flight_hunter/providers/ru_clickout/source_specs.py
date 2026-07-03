from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

LinkStrategy = Literal["known_template", "search_page", "query_search", "manual"]


@dataclass(frozen=True, slots=True)
class RuAggregatorSpec:
    source_id: str
    display_name: str
    base_url: str
    allowed_hosts: tuple[str, ...]
    supports_one_way: bool
    supports_round_trip: bool
    supports_multi_city: bool
    supports_passenger_mix: bool
    supports_children: bool
    supports_infants: bool
    supports_baggage_query: bool
    supports_currency_param: bool
    default_currency: str
    link_strategy: LinkStrategy
    browser_observation_allowed: bool
    parser_id: str | None
    source_type: Literal["aggregator", "carrier", "search", "deal"] = "aggregator"


def default_ru_aggregator_specs() -> tuple[RuAggregatorSpec, ...]:
    return (
        RuAggregatorSpec(
            source_id="aviasales_clickout",
            display_name="Aviasales",
            base_url="https://www.aviasales.ru/",
            allowed_hosts=("www.aviasales.ru", "aviasales.ru"),
            supports_one_way=True,
            supports_round_trip=True,
            supports_multi_city=False,
            supports_passenger_mix=False,
            supports_children=False,
            supports_infants=False,
            supports_baggage_query=False,
            supports_currency_param=True,
            default_currency="RUB",
            link_strategy="search_page",
            browser_observation_allowed=False,
            parser_id="aviasales_page",
        ),
        RuAggregatorSpec(
            source_id="travelpayouts_aviasales_deeplink",
            display_name="Aviasales partner link",
            base_url="https://www.aviasales.ru/",
            allowed_hosts=("www.aviasales.ru", "aviasales.ru"),
            supports_one_way=True,
            supports_round_trip=True,
            supports_multi_city=False,
            supports_passenger_mix=False,
            supports_children=False,
            supports_infants=False,
            supports_baggage_query=False,
            supports_currency_param=True,
            default_currency="RUB",
            link_strategy="search_page",
            browser_observation_allowed=False,
            parser_id=None,
        ),
        RuAggregatorSpec(
            source_id="yandex_travel",
            display_name="Яндекс Путешествия",
            base_url="https://travel.yandex.ru/avia/",
            allowed_hosts=("travel.yandex.ru",),
            supports_one_way=True,
            supports_round_trip=True,
            supports_multi_city=False,
            supports_passenger_mix=False,
            supports_children=False,
            supports_infants=False,
            supports_baggage_query=False,
            supports_currency_param=False,
            default_currency="RUB",
            link_strategy="search_page",
            browser_observation_allowed=True,
            parser_id="yandex_travel",
        ),
        RuAggregatorSpec(
            source_id="tutu",
            display_name="Туту",
            base_url="https://www.tutu.ru/",
            allowed_hosts=("www.tutu.ru", "tutu.ru", "avia.tutu.ru"),
            supports_one_way=True,
            supports_round_trip=True,
            supports_multi_city=False,
            supports_passenger_mix=False,
            supports_children=False,
            supports_infants=False,
            supports_baggage_query=False,
            supports_currency_param=False,
            default_currency="RUB",
            link_strategy="search_page",
            browser_observation_allowed=True,
            parser_id="tutu",
        ),
        RuAggregatorSpec(
            source_id="onetwotrip",
            display_name="OneTwoTrip",
            base_url="https://www.onetwotrip.com/",
            allowed_hosts=("www.onetwotrip.com", "onetwotrip.com"),
            supports_one_way=True,
            supports_round_trip=True,
            supports_multi_city=False,
            supports_passenger_mix=False,
            supports_children=False,
            supports_infants=False,
            supports_baggage_query=False,
            supports_currency_param=True,
            default_currency="RUB",
            link_strategy="search_page",
            browser_observation_allowed=True,
            parser_id="onetwotrip",
        ),
        RuAggregatorSpec(
            source_id="aeroflot",
            display_name="Аэрофлот",
            base_url="https://www.aeroflot.ru/",
            allowed_hosts=("www.aeroflot.ru", "aeroflot.ru"),
            supports_one_way=True,
            supports_round_trip=True,
            supports_multi_city=False,
            supports_passenger_mix=False,
            supports_children=False,
            supports_infants=False,
            supports_baggage_query=False,
            supports_currency_param=False,
            default_currency="RUB",
            link_strategy="manual",
            browser_observation_allowed=False,
            parser_id="carrier_generic",
            source_type="carrier",
        ),
        RuAggregatorSpec(
            source_id="pobeda",
            display_name="Победа",
            base_url="https://www.pobeda.aero/",
            allowed_hosts=("www.pobeda.aero", "pobeda.aero"),
            supports_one_way=True,
            supports_round_trip=True,
            supports_multi_city=False,
            supports_passenger_mix=False,
            supports_children=False,
            supports_infants=False,
            supports_baggage_query=False,
            supports_currency_param=False,
            default_currency="RUB",
            link_strategy="manual",
            browser_observation_allowed=False,
            parser_id="carrier_generic",
            source_type="carrier",
        ),
        RuAggregatorSpec(
            source_id="s7",
            display_name="S7 Airlines",
            base_url="https://www.s7.ru/",
            allowed_hosts=("www.s7.ru", "s7.ru"),
            supports_one_way=True,
            supports_round_trip=True,
            supports_multi_city=False,
            supports_passenger_mix=False,
            supports_children=False,
            supports_infants=False,
            supports_baggage_query=False,
            supports_currency_param=False,
            default_currency="RUB",
            link_strategy="manual",
            browser_observation_allowed=False,
            parser_id="carrier_generic",
            source_type="carrier",
        ),
        *_additional_carrier_specs(),
    )


def _additional_carrier_specs() -> tuple[RuAggregatorSpec, ...]:
    return (
        _carrier_spec(
            source_id="ural_airlines",
            display_name="Ural Airlines",
            base_url="https://www.uralairlines.ru/",
            allowed_hosts=("www.uralairlines.ru", "uralairlines.ru"),
        ),
        _carrier_spec(
            source_id="nordwind",
            display_name="Nordwind",
            base_url="https://nordwindairlines.ru/",
            allowed_hosts=("nordwindairlines.ru", "www.nordwindairlines.ru"),
        ),
        _carrier_spec(
            source_id="red_wings",
            display_name="Red Wings",
            base_url="https://flyredwings.com/",
            allowed_hosts=("flyredwings.com", "www.flyredwings.com"),
        ),
        _carrier_spec(
            source_id="smartavia",
            display_name="Smartavia",
            base_url="https://flysmartavia.com/",
            allowed_hosts=("flysmartavia.com", "www.flysmartavia.com"),
        ),
        _carrier_spec(
            source_id="azimuth",
            display_name="Azimuth",
            base_url="https://azimuth.aero/",
            allowed_hosts=("azimuth.aero", "www.azimuth.aero"),
        ),
        _carrier_spec(
            source_id="utair",
            display_name="Utair",
            base_url="https://www.utair.ru/",
            allowed_hosts=("www.utair.ru", "utair.ru"),
        ),
        _carrier_spec(
            source_id="rossiya",
            display_name="Rossiya Airlines",
            base_url="https://www.rossiya-airlines.com/",
            allowed_hosts=("www.rossiya-airlines.com", "rossiya-airlines.com"),
        ),
        _carrier_spec(
            source_id="turkish_airlines",
            display_name="Turkish Airlines",
            base_url="https://www.turkishairlines.com/",
            allowed_hosts=("www.turkishairlines.com", "turkishairlines.com"),
        ),
        _carrier_spec(
            source_id="air_serbia",
            display_name="Air Serbia",
            base_url="https://www.airserbia.com/",
            allowed_hosts=("www.airserbia.com", "airserbia.com"),
        ),
        _carrier_spec(
            source_id="pegasus",
            display_name="Pegasus",
            base_url="https://www.flypgs.com/",
            allowed_hosts=("www.flypgs.com", "flypgs.com"),
        ),
        _carrier_spec(
            source_id="uzbekistan_airways",
            display_name="Uzbekistan Airways",
            base_url="https://www.uzairways.com/",
            allowed_hosts=("www.uzairways.com", "uzairways.com"),
        ),
        _carrier_spec(
            source_id="emirates",
            display_name="Emirates",
            base_url="https://www.emirates.com/",
            allowed_hosts=("www.emirates.com", "emirates.com"),
        ),
        _carrier_spec(
            source_id="qatar_airways",
            display_name="Qatar Airways",
            base_url="https://www.qatarairways.com/",
            allowed_hosts=("www.qatarairways.com", "qatarairways.com"),
        ),
        _carrier_spec(
            source_id="etihad",
            display_name="Etihad",
            base_url="https://www.etihad.com/",
            allowed_hosts=("www.etihad.com", "etihad.com"),
        ),
        _carrier_spec(
            source_id="flydubai",
            display_name="flydubai",
            base_url="https://www.flydubai.com/",
            allowed_hosts=("www.flydubai.com", "flydubai.com"),
        ),
    )


def _carrier_spec(
    *,
    source_id: str,
    display_name: str,
    base_url: str,
    allowed_hosts: tuple[str, ...],
) -> RuAggregatorSpec:
    return RuAggregatorSpec(
        source_id=source_id,
        display_name=display_name,
        base_url=base_url,
        allowed_hosts=allowed_hosts,
        supports_one_way=True,
        supports_round_trip=True,
        supports_multi_city=False,
        supports_passenger_mix=False,
        supports_children=False,
        supports_infants=False,
        supports_baggage_query=False,
        supports_currency_param=False,
        default_currency="RUB",
        link_strategy="manual",
        browser_observation_allowed=False,
        parser_id="carrier_generic",
        source_type="carrier",
    )
