from __future__ import annotations

import hashlib
import importlib
import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from html import escape
from html.parser import HTMLParser
from typing import Protocol
from urllib.parse import urlsplit, urlunsplit
from uuid import NAMESPACE_URL, uuid5

from flight_hunter.domain.money import Money
from flight_hunter.domain.offers import Freshness, SearchIntent
from flight_hunter.domain.policy import require_aware_datetime
from flight_hunter.domain.search_results import BrowserObservedOffer, Confidence

PRICE_RE = re.compile(
    "(?<!\\d)(\\d[\\d\\s\u00a0]{2,8})\\s*(\u20bd|\u0440\u0443\u0431\\.?|RUB)(?!\\w)",
    re.IGNORECASE,
)
ROUTE_RE = re.compile(r"\b([A-Z]{3})\s*(?:->|→|-)\s*([A-Z]{3})\b")
STOPS_RE = re.compile(r"\b(\d+)\s*(?:stop|stops|пересад)", re.IGNORECASE)
WARNING_CODE_RE = re.compile(r"[^a-z0-9_.:-]+")
MIN_AIRFARE_RUB = 500
MAX_AIRFARE_RUB = 2_000_000
_DROPPED_SANITIZER_TAGS = frozenset({"script", "style", "template", "noscript"})
_VOID_SANITIZER_TAGS = frozenset(
    {
        "area",
        "base",
        "br",
        "col",
        "embed",
        "hr",
        "img",
        "input",
        "link",
        "meta",
        "param",
        "source",
        "track",
        "wbr",
    }
)
_SENSITIVE_ATTR_NAMES = frozenset(
    {
        "content",
        "nonce",
        "srcdoc",
        "value",
    }
)
_SENSITIVE_ATTR_KEYWORDS = (
    "auth",
    "bearer",
    "cookie",
    "csrf",
    "jwt",
    "password",
    "secret",
    "session",
    "token",
)
_URL_ATTR_NAMES = frozenset({"action", "href", "poster", "src"})
_EMAIL_RE = re.compile(r"(?i)\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b")
_SECRET_ASSIGNMENT_RE = re.compile(
    r"(?i)\b(token|secret|session|cookie|password|csrf|authorization)\s*[:=]\s*[^\s<>'\"]+"
)
_SECRET_LITERAL_RE = re.compile(
    r"(?i)\b(?:bearer\s+)?(?:sk-[A-Za-z0-9_-]{10,}|eyJ[A-Za-z0-9_-]{20,}|"
    r"[A-Za-z0-9_-]{24,}\.[A-Za-z0-9_-]{6,}\.[A-Za-z0-9_-]{6,})"
)


@dataclass(frozen=True, slots=True)
class DomSnapshot:
    source_id: str
    final_url: str
    title: str | None
    html: str
    text: str
    captured_at: datetime
    visible_text_hash: str
    html_hash: str
    screenshot_path: str | None = None

    @classmethod
    def from_html(
        cls,
        *,
        source_id: str,
        final_url: str,
        html: str,
        captured_at: datetime,
        title: str | None = None,
        screenshot_path: str | None = None,
    ) -> DomSnapshot:
        text = _visible_text(html)
        return cls(
            source_id=source_id,
            final_url=final_url,
            title=title,
            html=html,
            text=text,
            captured_at=captured_at,
            visible_text_hash=_sha256(text),
            html_hash=_sha256(html),
            screenshot_path=screenshot_path,
        )

    def __post_init__(self) -> None:
        if not self.source_id:
            raise ValueError("source_id is required")
        if not self.final_url.startswith(("https://", "http://")):
            raise ValueError("final_url must be http(s)")
        if not self.html:
            raise ValueError("html is required")
        require_aware_datetime(self.captured_at, "captured_at")


def sanitize_dom_html_for_fixture(html: str) -> str:
    """Return a diagnostic DOM fixture without active code or obvious secret-bearing fields."""
    parser = _SanitizingHtmlParser()
    parser.feed(html)
    parser.close()
    return parser.sanitized_html()


@dataclass(frozen=True, slots=True)
class PriceCandidate:
    raw_text: str
    amount: Money
    context: str
    accepted: bool
    rejection_reason: str | None = None


@dataclass(frozen=True, slots=True)
class BrowserExtractionResult:
    offers: tuple[BrowserObservedOffer, ...]
    warnings: tuple[str, ...]
    confidence: Confidence
    raw_price_candidates: tuple[PriceCandidate, ...]


class BrowserOfferExtractor(Protocol):
    parser_id: str
    parser_version: str

    def extract(self, snapshot: DomSnapshot, intent: SearchIntent) -> BrowserExtractionResult: ...


class BrowserOfferParserPipeline:
    parser_id = "browser_offer_parser_pipeline"
    parser_version = "browser_offer_parser_pipeline:2026-06-29"

    def __init__(
        self,
        *,
        source_names: Mapping[str, str] | None = None,
        scrapling_enabled: bool = True,
        crawl4ai_diagnostics_enabled: bool = False,
        crawl4ai_markdown_provider: Callable[[DomSnapshot], str | None] | None = None,
    ) -> None:
        self._source_names = dict(source_names or {})
        self._scrapling_enabled = scrapling_enabled
        self._crawl4ai_diagnostics_enabled = crawl4ai_diagnostics_enabled
        self._crawl4ai_markdown_provider = crawl4ai_markdown_provider

    def extract(self, snapshot: DomSnapshot, intent: SearchIntent) -> BrowserExtractionResult:
        warnings: list[str] = []
        raw_price_candidates: list[PriceCandidate] = []
        for stage_id, extractor_factory in self._stage_factories(snapshot.source_id):
            try:
                extractor = extractor_factory()
                result = extractor.extract(snapshot, intent)
            except ImportError:
                warnings.append(f"{stage_id}:unavailable")
                continue
            except (AttributeError, TypeError, ValueError):
                warnings.append(f"{stage_id}:failed")
                continue

            raw_price_candidates.extend(result.raw_price_candidates)
            if result.offers:
                return _pipeline_result(
                    result,
                    stage_id=stage_id,
                    prior_warnings=warnings,
                )
            warnings.extend(_stage_warnings(stage_id, result.warnings))
            if "source_challenge" in result.warnings:
                return BrowserExtractionResult(
                    offers=(),
                    warnings=tuple(_unique(("parser_stage:" + stage_id, *warnings))),
                    confidence=result.confidence,
                    raw_price_candidates=tuple(raw_price_candidates),
                )

        confidence = Confidence.LOW if raw_price_candidates else Confidence.NONE
        return BrowserExtractionResult(
            offers=(),
            warnings=tuple(_unique(warnings or ("parser_no_offers",))),
            confidence=confidence,
            raw_price_candidates=tuple(raw_price_candidates),
        )

    def _stage_factories(
        self,
        source_id: str,
    ) -> tuple[tuple[str, Callable[[], BrowserOfferExtractor]], ...]:
        stages: list[tuple[str, Callable[[], BrowserOfferExtractor]]] = []
        if source_id == "tutu":
            stages.append(
                (
                    "tutu",
                    lambda: TutuRuHtmlOfferExtractor(source_names=self._source_names),
                )
            )
        if self._scrapling_enabled:
            stages.append(
                (
                    "scrapling",
                    lambda: ScraplingRuHtmlOfferExtractor(source_names=self._source_names),
                )
            )
        stages.append(
            (
                "generic_html",
                lambda: GenericRuHtmlOfferExtractor(source_names=self._source_names),
            )
        )
        stages.append(("visible_text_price_hint", VisibleTextRuPriceHintExtractor))
        if self._crawl4ai_diagnostics_enabled:
            stages.append(
                (
                    "crawl4ai_markdown_hint",
                    lambda: Crawl4AiMarkdownHintExtractor(
                        markdown_provider=self._crawl4ai_markdown_provider,
                    ),
                )
            )
        return tuple(stages)


class GenericRuHtmlOfferExtractor:
    parser_id = "generic_ru_html_fixture"
    parser_version = "generic_ru_html_fixture:2026-06-29"
    supported_source_ids = ("tutu", "yandex_travel", "onetwotrip", "demo_browser")

    def __init__(self, *, source_names: Mapping[str, str] | None = None) -> None:
        self._source_names = dict(source_names or {})

    def extract(self, snapshot: DomSnapshot, intent: SearchIntent) -> BrowserExtractionResult:
        parser = _OfferHtmlParser()
        parser.feed(snapshot.html)
        cards = tuple(parser.cards)
        if not cards:
            return BrowserExtractionResult(
                offers=(),
                warnings=("no_offer_cards_found",),
                confidence=Confidence.NONE,
                raw_price_candidates=(),
            )

        offers: list[BrowserObservedOffer] = []
        candidates: list[PriceCandidate] = []
        warnings: set[str] = set()
        for card in cards:
            price = _first_price(card.price_text)
            if price is None:
                warnings.add("card_missing_price")
                continue
            route_matches = _matches_route(card, intent)
            date_matches = _matches_dates(card, intent)
            accepted = route_matches and date_matches
            if not route_matches:
                warnings.add("route_mismatch")
            if not date_matches:
                warnings.add("date_mismatch")
            candidates.append(
                PriceCandidate(
                    raw_text=price.raw_text,
                    amount=price.amount,
                    context=card.text,
                    accepted=accepted,
                    rejection_reason=None if accepted else "intent_mismatch",
                )
            )
            if not accepted:
                continue
            offers.append(
                self._offer_from_card(card, snapshot=snapshot, intent=intent, price=price)
            )

        if not offers:
            warnings.add("parser_no_offers")
        confidence = Confidence.MEDIUM if offers else Confidence.LOW
        return BrowserExtractionResult(
            offers=tuple(offers),
            warnings=tuple(sorted(warnings)),
            confidence=confidence,
            raw_price_candidates=tuple(candidates),
        )

    def _offer_from_card(
        self,
        card: _OfferCard,
        *,
        snapshot: DomSnapshot,
        intent: SearchIntent,
        price: _ParsedPrice,
    ) -> BrowserObservedOffer:
        parser_warnings: list[str] = []
        if not card.baggage_summary:
            parser_warnings.append("baggage_unknown")
        observation_seed = "|".join(
            (
                snapshot.source_id,
                snapshot.final_url,
                card.source_offer_id or card.text,
                str(price.amount.minor_units),
                snapshot.html_hash,
            )
        )
        return BrowserObservedOffer(
            observation_id=uuid5(NAMESPACE_URL, observation_seed),
            source_id=snapshot.source_id,
            source_name=self._source_names.get(snapshot.source_id, snapshot.source_id),
            provider_offer_id=card.source_offer_id or f"{snapshot.source_id}:{snapshot.html_hash}",
            origin=card.origin or intent.origin,
            destination=card.destination or intent.destination,
            departure_date=card.departure_date or intent.departure_date,
            return_date=card.return_date or intent.return_date,
            total_price=price.amount,
            passengers=intent.passengers,
            observed_at=snapshot.captured_at,
            final_url=snapshot.final_url,
            display_url=_display_url(snapshot.final_url),
            freshness=Freshness.BROWSER_OBSERVED,
            confidence=Confidence.MEDIUM,
            parser_version=self.parser_version,
            parser_warnings=tuple(parser_warnings),
            airline_name=card.airline_name,
            airline_iata=card.airline_iata,
            stops=card.stops,
            baggage_summary=card.baggage_summary,
            seller_name=card.seller_name,
        )


class TutuRuHtmlOfferExtractor:
    parser_id = "tutu"
    parser_version = "tutu:2026-06-29"
    supported_source_ids = ("tutu",)

    def __init__(self, *, source_names: Mapping[str, str] | None = None) -> None:
        self._source_names = dict(source_names or {})

    def extract(self, snapshot: DomSnapshot, intent: SearchIntent) -> BrowserExtractionResult:
        if _looks_like_source_challenge(snapshot.text):
            return BrowserExtractionResult(
                offers=(),
                warnings=("source_challenge",),
                confidence=Confidence.NONE,
                raw_price_candidates=(),
            )

        parser = _TutuHtmlParser()
        parser.feed(snapshot.html)
        cards = tuple(parser.cards)
        if not cards:
            return BrowserExtractionResult(
                offers=(),
                warnings=("selector_drift",),
                confidence=Confidence.NONE,
                raw_price_candidates=(),
            )

        generic = GenericRuHtmlOfferExtractor(source_names=self._source_names)
        offers: list[BrowserObservedOffer] = []
        candidates: list[PriceCandidate] = []
        warnings: set[str] = set()
        for card in cards:
            price = _first_price(card.price_text)
            if price is None:
                warnings.add("card_missing_price")
                continue
            route_matches = _matches_route(card, intent)
            date_matches = _matches_dates(card, intent)
            accepted = route_matches and date_matches
            if not route_matches:
                warnings.add("route_mismatch")
            if not date_matches:
                warnings.add("date_mismatch")
            candidates.append(
                PriceCandidate(
                    raw_text=price.raw_text,
                    amount=price.amount,
                    context=card.text,
                    accepted=accepted,
                    rejection_reason=None if accepted else "intent_mismatch",
                )
            )
            if not accepted:
                continue
            offer = generic._offer_from_card(
                card,
                snapshot=snapshot,
                intent=intent,
                price=price,
            )
            offers.append(_replace_parser_version(offer, self.parser_version))

        if not offers:
            warnings.add("parser_no_offers")
        confidence = Confidence.MEDIUM if offers else Confidence.LOW
        return BrowserExtractionResult(
            offers=tuple(offers),
            warnings=tuple(sorted(warnings)),
            confidence=confidence,
            raw_price_candidates=tuple(candidates),
        )


class ScraplingRuHtmlOfferExtractor:
    parser_id = "scrapling_ru_html_fixture"
    parser_version = "scrapling_ru_html_fixture:2026-06-29"
    supported_source_ids = GenericRuHtmlOfferExtractor.supported_source_ids

    def __init__(self, *, source_names: Mapping[str, str] | None = None) -> None:
        self._generic = GenericRuHtmlOfferExtractor(source_names=source_names)

    def extract(self, snapshot: DomSnapshot, intent: SearchIntent) -> BrowserExtractionResult:
        parser_module = importlib.import_module("scrapling.parser")
        adaptor = parser_module.Adaptor(snapshot.html, url=snapshot.final_url)
        cards = adaptor.css("[data-flight-offer]")
        if not cards:
            return BrowserExtractionResult(
                offers=(),
                warnings=("no_offer_cards_found",),
                confidence=Confidence.NONE,
                raw_price_candidates=(),
            )
        result = self._generic.extract(snapshot, intent)
        offers = tuple(
            _replace_parser_version(offer, self.parser_version) for offer in result.offers
        )
        return BrowserExtractionResult(
            offers=offers,
            warnings=result.warnings,
            confidence=result.confidence,
            raw_price_candidates=result.raw_price_candidates,
        )


class VisibleTextRuPriceHintExtractor:
    parser_id = "visible_text_price_hint"
    parser_version = "visible_text_price_hint:2026-06-29"

    def extract(self, snapshot: DomSnapshot, intent: SearchIntent) -> BrowserExtractionResult:
        del intent
        candidates = tuple(
            PriceCandidate(
                raw_text=price.raw_text,
                amount=price.amount,
                context=_context_around(snapshot.text, price.raw_text),
                accepted=False,
                rejection_reason="unstructured_text",
            )
            for price in _prices_from_text(snapshot.text)
        )
        return BrowserExtractionResult(
            offers=(),
            warnings=(
                ("unstructured_price_candidates",)
                if candidates
                else ("no_unstructured_price_candidates",)
            ),
            confidence=Confidence.LOW if candidates else Confidence.NONE,
            raw_price_candidates=candidates,
        )


class Crawl4AiMarkdownHintExtractor:
    parser_id = "crawl4ai_markdown_hint"
    parser_version = "crawl4ai_markdown_hint:2026-06-29"

    def __init__(
        self,
        *,
        markdown_provider: Callable[[DomSnapshot], str | None] | None = None,
    ) -> None:
        self._markdown_provider = markdown_provider

    def extract(self, snapshot: DomSnapshot, intent: SearchIntent) -> BrowserExtractionResult:
        del intent
        try:
            markdown_text = (
                self._markdown_provider(snapshot) if self._markdown_provider is not None else None
            )
        except (RuntimeError, ValueError) as exc:
            return BrowserExtractionResult(
                offers=(),
                warnings=(f"crawl4ai_hint_unavailable:{_safe_warning_code(str(exc))}",),
                confidence=Confidence.NONE,
                raw_price_candidates=(),
            )
        if not markdown_text:
            return BrowserExtractionResult(
                offers=(),
                warnings=("crawl4ai_hint_no_markdown",),
                confidence=Confidence.NONE,
                raw_price_candidates=(),
            )
        candidates = tuple(
            PriceCandidate(
                raw_text=price.raw_text,
                amount=price.amount,
                context=_context_around(markdown_text, price.raw_text),
                accepted=False,
                rejection_reason="crawl4ai_hint_requires_manual_verification",
            )
            for price in _prices_from_text(markdown_text)
        )
        return BrowserExtractionResult(
            offers=(),
            warnings=(
                ("crawl4ai_hint_price_candidates",)
                if candidates
                else ("crawl4ai_hint_no_price_candidates",)
            ),
            confidence=Confidence.LOW if candidates else Confidence.NONE,
            raw_price_candidates=candidates,
        )


@dataclass(frozen=True, slots=True)
class _OfferCard:
    source_offer_id: str | None
    origin: str | None
    destination: str | None
    departure_date: str | None
    return_date: str | None
    airline_name: str | None
    airline_iata: str | None
    stops: int | None
    baggage_summary: str | None
    seller_name: str | None
    price_text: str
    text: str


@dataclass(frozen=True, slots=True)
class _ParsedPrice:
    raw_text: str
    amount: Money


class _CardBuilder:
    def __init__(self, attrs: Mapping[str, str]) -> None:
        self.source_offer_id = attrs.get("data-source-offer-id")
        self.origin = _upper_or_none(attrs.get("data-origin"))
        self.destination = _upper_or_none(attrs.get("data-destination"))
        self.departure_date = attrs.get("data-departure-date")
        self.return_date = attrs.get("data-return-date")
        self.airline_name = attrs.get("data-airline-name")
        self.airline_iata = _upper_or_none(attrs.get("data-airline-iata"))
        self.stops = _int_or_none(attrs.get("data-stops"))
        self.baggage_summary = attrs.get("data-baggage-summary")
        self.seller_name = attrs.get("data-seller-name")
        self.price_parts: list[str] = []
        self.text_parts: list[str] = []

    def build(self) -> _OfferCard:
        return _OfferCard(
            source_offer_id=self.source_offer_id,
            origin=self.origin,
            destination=self.destination,
            departure_date=self.departure_date,
            return_date=self.return_date,
            airline_name=self.airline_name,
            airline_iata=self.airline_iata,
            stops=self.stops,
            baggage_summary=self.baggage_summary,
            seller_name=self.seller_name,
            price_text=" ".join(self.price_parts),
            text=_normalize_text(" ".join(self.text_parts)),
        )


class _OfferHtmlParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.cards: list[_OfferCard] = []
        self._current: _CardBuilder | None = None
        self._card_depth = 0
        self._price_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attr_map = {key: value or "" for key, value in attrs}
        starts_card = "data-flight-offer" in attr_map
        if starts_card and self._current is None:
            self._current = _CardBuilder(attr_map)
            self._card_depth = 1
        elif self._current is not None:
            self._card_depth += 1

        if self._current is not None and "data-price" in attr_map:
            self._price_depth = 1
        elif self._price_depth > 0:
            self._price_depth += 1

    def handle_endtag(self, tag: str) -> None:
        if self._price_depth > 0:
            self._price_depth -= 1
        if self._current is None:
            return
        self._card_depth -= 1
        if self._card_depth == 0:
            self.cards.append(self._current.build())
            self._current = None

    def handle_data(self, data: str) -> None:
        if self._current is None:
            return
        stripped = data.strip()
        if not stripped:
            return
        self._current.text_parts.append(stripped)
        if self._price_depth > 0:
            self._current.price_parts.append(stripped)


class _TutuCardBuilder:
    def __init__(self, attrs: Mapping[str, str]) -> None:
        self.source_offer_id = attrs.get("data-offer-id") or attrs.get("data-source-offer-id")
        self.origin = _upper_or_none(attrs.get("data-origin"))
        self.destination = _upper_or_none(attrs.get("data-destination"))
        self.departure_date = attrs.get("data-departure-date")
        self.return_date = attrs.get("data-return-date")
        self.airline_name = attrs.get("data-airline-name")
        self.airline_iata = _upper_or_none(attrs.get("data-airline-iata"))
        self.stops = _int_or_none(attrs.get("data-stops"))
        self.baggage_summary = attrs.get("data-baggage-summary")
        self.seller_name = attrs.get("data-seller-name") or "Tutu"
        self.price_parts: list[str] = []
        self.text_parts: list[str] = []
        self._airline_parts: list[str] = []
        self._airline_iata_parts: list[str] = []
        self._stops_parts: list[str] = []
        self._baggage_parts: list[str] = []

    def build(self) -> _OfferCard:
        text = _normalize_text(" ".join(self.text_parts))
        route = _route_from_text(text)
        if route is not None:
            origin, destination = route
            self.origin = self.origin or origin
            self.destination = self.destination or destination
        if self.airline_name is None:
            self.airline_name = _normalize_text(" ".join(self._airline_parts)) or None
        if self.airline_iata is None:
            self.airline_iata = _upper_or_none(_normalize_text(" ".join(self._airline_iata_parts)))
        if self.stops is None:
            self.stops = _stops_from_text(_normalize_text(" ".join(self._stops_parts)))
        if self.baggage_summary is None:
            self.baggage_summary = _normalize_text(" ".join(self._baggage_parts)) or None

        return _OfferCard(
            source_offer_id=self.source_offer_id,
            origin=self.origin,
            destination=self.destination,
            departure_date=self.departure_date,
            return_date=self.return_date,
            airline_name=self.airline_name,
            airline_iata=self.airline_iata,
            stops=self.stops,
            baggage_summary=self.baggage_summary,
            seller_name=self.seller_name,
            price_text=" ".join(self.price_parts),
            text=text,
        )


class _TutuHtmlParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.cards: list[_OfferCard] = []
        self._current: _TutuCardBuilder | None = None
        self._card_depth = 0
        self._capture: str | None = None
        self._capture_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attr_map = {key: value or "" for key, value in attrs}
        starts_card = _has_class(attr_map, "tutu-flight-card") or attr_map.get("data-testid") in {
            "ticket-card",
            "tutu-ticket-card",
        }
        if starts_card and self._current is None:
            self._current = _TutuCardBuilder(attr_map)
            self._card_depth = 1
        elif self._current is not None:
            self._card_depth += 1

        if self._current is None:
            return

        if _has_class(attr_map, "depart-date") and attr_map.get("datetime"):
            self._current.departure_date = attr_map["datetime"][:10]
        if _has_class(attr_map, "return-date") and attr_map.get("datetime"):
            self._current.return_date = attr_map["datetime"][:10]

        capture = _tutu_capture_kind(attr_map)
        if capture is not None:
            self._capture = capture
            self._capture_depth = 1
        elif self._capture_depth > 0:
            self._capture_depth += 1

    def handle_endtag(self, tag: str) -> None:
        if self._capture_depth > 0:
            self._capture_depth -= 1
            if self._capture_depth == 0:
                self._capture = None
        if self._current is None:
            return
        self._card_depth -= 1
        if self._card_depth == 0:
            self.cards.append(self._current.build())
            self._current = None

    def handle_data(self, data: str) -> None:
        if self._current is None:
            return
        stripped = data.strip()
        if not stripped:
            return
        self._current.text_parts.append(stripped)
        if self._capture == "price":
            self._current.price_parts.append(stripped)
        elif self._capture == "airline":
            self._current._airline_parts.append(stripped)
        elif self._capture == "airline_iata":
            self._current._airline_iata_parts.append(stripped)
        elif self._capture == "stops":
            self._current._stops_parts.append(stripped)
        elif self._capture == "baggage":
            self._current._baggage_parts.append(stripped)


class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []

    def handle_data(self, data: str) -> None:
        stripped = data.strip()
        if stripped:
            self.parts.append(stripped)


def _visible_text(html: str) -> str:
    parser = _TextExtractor()
    parser.feed(html)
    return _normalize_text(" ".join(parser.parts))


def _first_price(value: str) -> _ParsedPrice | None:
    return next(iter(_prices_from_text(value)), None)


def _prices_from_text(value: str) -> tuple[_ParsedPrice, ...]:
    prices: list[_ParsedPrice] = []
    for match in PRICE_RE.finditer(value):
        raw_number = match.group(1)
        rub = int(re.sub(r"[\s\u00a0]", "", raw_number))
        if rub < MIN_AIRFARE_RUB or rub > MAX_AIRFARE_RUB:
            continue
        prices.append(
            _ParsedPrice(
                raw_text=match.group(0),
                amount=Money(rub * 100, "RUB"),
            )
        )
    return tuple(prices)


def _matches_route(card: _OfferCard, intent: SearchIntent) -> bool:
    return (card.origin is None or card.origin == intent.origin) and (
        card.destination is None or card.destination == intent.destination
    )


def _matches_dates(card: _OfferCard, intent: SearchIntent) -> bool:
    return (card.departure_date is None or card.departure_date == intent.departure_date) and (
        card.return_date is None or card.return_date == intent.return_date
    )


def _display_url(url: str) -> str:
    return url.removeprefix("https://").removeprefix("http://").split("/", 1)[0]


def _looks_like_source_challenge(text: str) -> bool:
    normalized = text.lower()
    return any(
        marker in normalized
        for marker in (
            "captcha",
            "access denied",
            "robot check",
            "verify you are human",
        )
    )


def _route_from_text(text: str) -> tuple[str, str] | None:
    match = ROUTE_RE.search(text)
    if match is None:
        return None
    return match.group(1).upper(), match.group(2).upper()


def _stops_from_text(text: str) -> int | None:
    match = STOPS_RE.search(text)
    if match is None:
        if "direct" in text.lower() or "nonstop" in text.lower():
            return 0
        return None
    return int(match.group(1))


def _has_class(attrs: Mapping[str, str], class_name: str) -> bool:
    classes = attrs.get("class", "").split()
    return class_name in classes


def _tutu_capture_kind(attrs: Mapping[str, str]) -> str | None:
    data_testid = attrs.get("data-testid")
    if data_testid == "ticket-price" or _has_class(attrs, "ticket-price"):
        return "price"
    if data_testid == "airline" or _has_class(attrs, "airline"):
        return "airline"
    if _has_class(attrs, "airline-iata"):
        return "airline_iata"
    if _has_class(attrs, "stops"):
        return "stops"
    if _has_class(attrs, "baggage"):
        return "baggage"
    return None


def _upper_or_none(value: str | None) -> str | None:
    if value is None or not value.strip():
        return None
    return value.strip().upper()


def _int_or_none(value: str | None) -> int | None:
    if value is None or not value.strip():
        return None
    try:
        return int(value)
    except ValueError:
        return None


def _normalize_text(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def _sha256(value: str) -> str:
    return "sha256:" + hashlib.sha256(value.encode("utf-8")).hexdigest()


def _replace_parser_version(
    offer: BrowserObservedOffer,
    parser_version: str,
) -> BrowserObservedOffer:
    return BrowserObservedOffer(
        observation_id=offer.observation_id,
        source_id=offer.source_id,
        source_name=offer.source_name,
        provider_offer_id=offer.provider_offer_id,
        origin=offer.origin,
        destination=offer.destination,
        departure_date=offer.departure_date,
        return_date=offer.return_date,
        total_price=offer.total_price,
        passengers=offer.passengers,
        observed_at=offer.observed_at,
        final_url=offer.final_url,
        display_url=offer.display_url,
        freshness=offer.freshness,
        confidence=offer.confidence,
        parser_version=parser_version,
        parser_warnings=offer.parser_warnings,
        airline_name=offer.airline_name,
        airline_iata=offer.airline_iata,
        flight_number=offer.flight_number,
        departure_time_local=offer.departure_time_local,
        arrival_time_local=offer.arrival_time_local,
        duration_minutes=offer.duration_minutes,
        stops=offer.stops,
        baggage_summary=offer.baggage_summary,
        seller_name=offer.seller_name,
        requires_external_confirmation=offer.requires_external_confirmation,
    )


def _pipeline_result(
    result: BrowserExtractionResult,
    *,
    stage_id: str,
    prior_warnings: Sequence[str],
) -> BrowserExtractionResult:
    return BrowserExtractionResult(
        offers=result.offers,
        warnings=tuple(
            _unique(
                (
                    f"parser_stage:{stage_id}",
                    *prior_warnings,
                    *result.warnings,
                )
            )
        ),
        confidence=result.confidence,
        raw_price_candidates=result.raw_price_candidates,
    )


def _stage_warnings(stage_id: str, warnings: Sequence[str]) -> tuple[str, ...]:
    if not warnings:
        return (f"{stage_id}:no_offers",)
    return tuple(f"{stage_id}:{warning}" for warning in warnings)


def _safe_warning_code(value: str) -> str:
    normalized = WARNING_CODE_RE.sub("_", value.strip().lower()).strip("_")
    return normalized[:96] or "unknown"


def _unique(values: Sequence[str]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(value for value in values if value))


def _context_around(text: str, needle: str, *, radius: int = 80) -> str:
    index = text.find(needle)
    if index < 0:
        return text[: radius * 2].strip()
    start = max(0, index - radius)
    end = min(len(text), index + len(needle) + radius)
    return text[start:end].strip()


class _SanitizingHtmlParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._parts: list[str] = []
        self._drop_depth = 0

    def sanitized_html(self) -> str:
        return "".join(self._parts)

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        normalized = tag.lower()
        if self._drop_depth:
            if normalized in _DROPPED_SANITIZER_TAGS:
                self._drop_depth += 1
            return
        if normalized in _DROPPED_SANITIZER_TAGS:
            self._drop_depth = 1
            return
        self._parts.append(_render_start_tag(normalized, attrs, self_closing=False))

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        normalized = tag.lower()
        if self._drop_depth or normalized in _DROPPED_SANITIZER_TAGS:
            return
        self._parts.append(_render_start_tag(normalized, attrs, self_closing=True))

    def handle_endtag(self, tag: str) -> None:
        normalized = tag.lower()
        if self._drop_depth:
            if normalized in _DROPPED_SANITIZER_TAGS:
                self._drop_depth -= 1
            return
        if normalized not in _VOID_SANITIZER_TAGS:
            self._parts.append(f"</{normalized}>")

    def handle_data(self, data: str) -> None:
        if self._drop_depth:
            return
        self._parts.append(escape(_redact_sensitive_text(data), quote=False))

    def handle_comment(self, data: str) -> None:
        return


def _render_start_tag(
    tag: str,
    attrs: list[tuple[str, str | None]],
    *,
    self_closing: bool,
) -> str:
    rendered_attrs = "".join(_render_safe_attr(tag, name, value) for name, value in attrs)
    if self_closing and tag not in _VOID_SANITIZER_TAGS:
        return f"<{tag}{rendered_attrs} />"
    return f"<{tag}{rendered_attrs}>"


def _render_safe_attr(tag: str, name: str, value: str | None) -> str:
    normalized = name.lower()
    if _is_sensitive_attr_name(normalized):
        return ""
    if tag == "form" and normalized == "method":
        safe_value = "get"
    elif normalized in _URL_ATTR_NAMES:
        url_value = _sanitize_url_attr(value or "")
        if url_value is None:
            return ""
        return f' {escape(normalized, quote=True)}="{escape(url_value, quote=True)}"'
    elif value is None:
        return f" {escape(normalized, quote=True)}"
    else:
        safe_value = _redact_sensitive_text(value)
    return f' {escape(normalized, quote=True)}="{escape(safe_value, quote=True)}"'


def _is_sensitive_attr_name(name: str) -> bool:
    if name.startswith("on") or name in _SENSITIVE_ATTR_NAMES or name == "style":
        return True
    return any(keyword in name for keyword in _SENSITIVE_ATTR_KEYWORDS)


def _sanitize_url_attr(value: str) -> str | None:
    raw_value = value.strip()
    if not raw_value:
        return ""
    try:
        parsed = urlsplit(raw_value)
    except ValueError:
        return None
    if parsed.scheme and parsed.scheme.lower() not in {"http", "https"}:
        return None
    safe_path = _redact_sensitive_text(parsed.path)
    if parsed.scheme:
        hostname = parsed.hostname or ""
        if not hostname:
            return None
        netloc = hostname
        try:
            port = parsed.port
        except ValueError:
            return None
        if port is not None:
            netloc = f"{netloc}:{port}"
        return urlunsplit((parsed.scheme.lower(), netloc, safe_path, "", ""))
    if raw_value.startswith("//"):
        return None
    return urlunsplit(("", "", safe_path, "", ""))


def _redact_sensitive_text(value: str) -> str:
    without_emails = _EMAIL_RE.sub("[redacted-email]", value)
    without_assignments = _SECRET_ASSIGNMENT_RE.sub(
        lambda match: f"{match.group(1)}=[redacted]",
        without_emails,
    )
    return _SECRET_LITERAL_RE.sub("[redacted-secret]", without_assignments)
