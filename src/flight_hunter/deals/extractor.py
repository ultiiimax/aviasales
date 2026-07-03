from __future__ import annotations

import re
from collections.abc import Callable
from datetime import UTC, datetime
from urllib.parse import urlsplit

from flight_hunter.deals.models import DealPageMarkdown, SearxngSearchResult
from flight_hunter.domain.money import Money
from flight_hunter.domain.offers import SearchIntent
from flight_hunter.domain.search_results import Confidence, DealCandidate

_PRICE_RE = re.compile(
    r"(?<!\d)(?P<amount>\d[\d\s\u00a0]{2,8})\s*(?:\u20bd|\u0440\u0443\u0431\.?|RUB)(?!\w)",
    re.IGNORECASE,
)
_DATE_RE = re.compile(r"\b20\d{2}[-/.](?:0[1-9]|1[0-2])[-/.](?:0[1-9]|[12]\d|3[01])\b")
_MIN_AIRFARE_MINOR_UNITS = 500 * 100
_MAX_AIRFARE_MINOR_UNITS = 2_000_000 * 100


class DealMarkdownExtractor:
    def __init__(self, *, clock: Callable[[], datetime] | None = None) -> None:
        self._clock = clock or (lambda: datetime.now(UTC))

    def extract(
        self,
        *,
        search_result: SearxngSearchResult,
        page: DealPageMarkdown,
        intent: SearchIntent,
    ) -> DealCandidate:
        page_text = _normalized_text(page.markdown)
        price = _extract_price(page_text)
        has_route = _has_route_match(page_text, intent)
        has_date_match = _has_date_match(page_text, intent)
        date_window = _extract_date_window(page_text)
        confidence = (
            Confidence.MEDIUM
            if price is not None and has_route and has_date_match
            else Confidence.LOW
        )
        return DealCandidate(
            source_id="deal_discovery",
            url=page.url,
            title=_candidate_title(page),
            summary_ru=_summary(page_text),
            extracted_price=price,
            extracted_origin=intent.origin if has_route else None,
            extracted_destination=intent.destination if has_route else None,
            extracted_date_window=date_window,
            confidence=confidence,
            discovered_at=self._clock(),
            requires_manual_verification=True,
        )


def _extract_price(text: str) -> Money | None:
    for match in _PRICE_RE.finditer(text):
        amount_text = match.group("amount").replace("\u00a0", " ")
        amount = int(re.sub(r"\s+", "", amount_text))
        minor_units = amount * 100
        if _MIN_AIRFARE_MINOR_UNITS <= minor_units <= _MAX_AIRFARE_MINOR_UNITS:
            return Money(minor_units, "RUB")
    return None


def _extract_date_window(text: str) -> str | None:
    dates = _DATE_RE.findall(text)
    if not dates:
        return None
    unique_dates = tuple(dict.fromkeys(date.replace("/", "-").replace(".", "-") for date in dates))
    return " - ".join(unique_dates[:2])


def _has_route_match(text: str, intent: SearchIntent) -> bool:
    return _contains_iata(text, intent.origin) and _contains_iata(text, intent.destination)


def _contains_iata(text: str, code: str) -> bool:
    return (
        re.search(rf"(?<![A-Z0-9]){re.escape(code.upper())}(?![A-Z0-9])", text.upper()) is not None
    )


def _has_date_match(text: str, intent: SearchIntent) -> bool:
    normalized_dates = {date.replace("/", "-").replace(".", "-") for date in _DATE_RE.findall(text)}
    intent_dates = {intent.departure_date}
    if intent.return_date is not None:
        intent_dates.add(intent.return_date)
    if normalized_dates.intersection(intent_dates):
        return True
    intent_months = {date[:7] for date in intent_dates}
    return any(month in text for month in intent_months)


def _summary(text: str) -> str:
    cleaned = text.strip()
    if not cleaned:
        return "Manual verification required."
    if len(cleaned) <= 240:
        return cleaned
    return cleaned[:237].rstrip() + "..."


def _candidate_title(page: DealPageMarkdown) -> str:
    for line in page.markdown.splitlines():
        normalized = line.strip()
        if normalized.startswith("#"):
            heading = normalized.lstrip("#").strip()
            if heading:
                return _summary(heading)
    title = page.title.strip()
    if title:
        return _summary(title)
    host = urlsplit(page.url).netloc
    return f"Deal candidate from {host}" if host else "Deal candidate"


def _normalized_text(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()
