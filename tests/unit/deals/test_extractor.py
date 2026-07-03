from __future__ import annotations

from datetime import UTC, datetime

from flight_hunter.deals.extractor import DealMarkdownExtractor
from flight_hunter.deals.models import DealPageMarkdown, SearxngSearchResult
from flight_hunter.domain.offers import SearchIntent
from flight_hunter.domain.search_results import Confidence

NOW = datetime(2026, 6, 29, 20, 15, tzinfo=UTC)


def test_deal_markdown_extractor_returns_manual_candidate_not_price_truth() -> None:
    candidate = DealMarkdownExtractor(clock=lambda: NOW).extract(
        search_result=_search_result(content="Search snippet also says 18 420 RUB."),
        page=_page("Public page: MOW - IST on 2026-09-10 from 18 420 RUB."),
        intent=_intent(),
    )

    assert candidate.extracted_price is not None
    assert candidate.extracted_price.minor_units == 1_842_000
    assert candidate.extracted_origin == "MOW"
    assert candidate.extracted_destination == "IST"
    assert candidate.extracted_date_window == "2026-09-10"
    assert candidate.confidence == Confidence.MEDIUM
    assert candidate.requires_manual_verification is True


def test_deal_markdown_extractor_ignores_price_route_and_date_from_search_snippet() -> None:
    candidate = DealMarkdownExtractor(clock=lambda: NOW).extract(
        search_result=_search_result(
            content="MOW IST 2026-09-10 promo from 18 420 RUB in untrusted search snippet."
        ),
        page=_page("Public article without a fare, route or travel date."),
        intent=_intent(),
    )

    assert candidate.extracted_price is None
    assert candidate.extracted_origin is None
    assert candidate.extracted_destination is None
    assert candidate.extracted_date_window is None
    assert candidate.confidence == Confidence.LOW
    assert candidate.requires_manual_verification is True
    assert "18 420" not in candidate.title
    assert "18 420" not in candidate.summary_ru


def test_deal_markdown_extractor_keeps_price_low_confidence_without_page_date_match() -> None:
    candidate = DealMarkdownExtractor(clock=lambda: NOW).extract(
        search_result=_search_result(),
        page=_page("Deal page mentions MOW - IST from 18 420 RUB but no travel date."),
        intent=_intent(),
    )

    assert candidate.extracted_price is not None
    assert candidate.extracted_price.minor_units == 1_842_000
    assert candidate.extracted_origin == "MOW"
    assert candidate.extracted_destination == "IST"
    assert candidate.extracted_date_window is None
    assert candidate.confidence == Confidence.LOW


def test_deal_markdown_extractor_ignores_ancillary_price_before_airfare() -> None:
    candidate = DealMarkdownExtractor(clock=lambda: NOW).extract(
        search_result=_search_result(),
        page=_page("MOW IST 2026-09-10 seat fee 300 RUB, airfare from 18 420 RUB."),
        intent=_intent(),
    )

    assert candidate.extracted_price is not None
    assert candidate.extracted_price.minor_units == 1_842_000
    assert candidate.confidence == Confidence.MEDIUM


def test_deal_markdown_extractor_accepts_matching_travel_month() -> None:
    candidate = DealMarkdownExtractor(clock=lambda: NOW).extract(
        search_result=_search_result(),
        page=_page("MOW IST promo for travel in 2026-09 from 18 420 RUB."),
        intent=_intent(),
    )

    assert candidate.extracted_price is not None
    assert candidate.extracted_price.minor_units == 1_842_000
    assert candidate.extracted_date_window is None
    assert candidate.confidence == Confidence.MEDIUM


def test_deal_markdown_extractor_keeps_low_confidence_for_wrong_travel_month() -> None:
    candidate = DealMarkdownExtractor(clock=lambda: NOW).extract(
        search_result=_search_result(),
        page=_page("MOW IST promo for travel in 2026-10 from 18 420 RUB."),
        intent=_intent(),
    )

    assert candidate.extracted_price is not None
    assert candidate.extracted_price.minor_units == 1_842_000
    assert candidate.extracted_date_window is None
    assert candidate.confidence == Confidence.LOW


def _intent() -> SearchIntent:
    return SearchIntent(
        origin="MOW",
        destination="IST",
        departure_date="2026-09-10",
        return_date="2026-09-20",
        passengers=1,
        currency="RUB",
    )


def _search_result(*, content: str = "Search result snippet") -> SearxngSearchResult:
    return SearxngSearchResult(
        title="SearXNG title MOW IST from 18 420 RUB",
        url="https://example.com/deal",
        content=content,
    )


def _page(markdown: str) -> DealPageMarkdown:
    return DealPageMarkdown(
        url="https://example.com/deal",
        title="Deal candidate page",
        markdown=markdown,
        fetched_at=NOW,
    )
