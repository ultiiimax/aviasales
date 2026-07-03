from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from flight_hunter.browser.html_extractor import (
    BrowserOfferParserPipeline,
    DomSnapshot,
    GenericRuHtmlOfferExtractor,
    TutuRuHtmlOfferExtractor,
)
from flight_hunter.domain.money import Money
from flight_hunter.domain.offers import Freshness, SearchIntent
from flight_hunter.domain.search_results import Confidence

NOW = datetime(2026, 6, 29, 14, 0, tzinfo=UTC)
FIXTURE = Path("tests/fixtures/browser/tutu/search_result_sanitized.html")
TUTU_SOURCE_FIXTURE = Path("tests/fixtures/browser/tutu/search_result_source_specific.html")
TUTU_DRIFT_FIXTURE = Path("tests/fixtures/browser/tutu/search_result_source_specific_no_cards.html")
TUTU_CHALLENGE_FIXTURE = Path(
    "tests/fixtures/browser/tutu/search_result_source_specific_challenge.html"
)


def test_generic_ru_html_extractor_reads_sanitized_offer_card() -> None:
    snapshot = DomSnapshot.from_html(
        source_id="tutu",
        final_url="https://www.tutu.ru/avia/search/",
        html=FIXTURE.read_text(encoding="utf-8"),
        captured_at=NOW,
        title="Sanitized Tutu search result fixture",
    )
    extractor = GenericRuHtmlOfferExtractor(source_names={"tutu": "Туту"})

    result = extractor.extract(snapshot, _intent())

    assert result.confidence == Confidence.MEDIUM
    assert result.warnings == ()
    assert len(result.raw_price_candidates) == 1
    assert result.raw_price_candidates[0].accepted is True
    assert result.raw_price_candidates[0].amount == Money(1_842_000, "RUB")
    assert len(result.offers) == 1
    offer = result.offers[0]
    assert offer.source_id == "tutu"
    assert offer.source_name == "Туту"
    assert offer.provider_offer_id == "tutu-card-1"
    assert offer.origin == "MOW"
    assert offer.destination == "IST"
    assert offer.total_price == Money(1_842_000, "RUB")
    assert offer.observed_at == NOW
    assert offer.freshness == Freshness.BROWSER_OBSERVED
    assert offer.confidence == Confidence.MEDIUM
    assert offer.parser_version == extractor.parser_version
    assert offer.airline_name == "Turkish Airlines"
    assert offer.airline_iata == "TK"
    assert offer.stops == 1
    assert offer.seller_name == "Туту"


def test_generic_ru_html_extractor_does_not_accept_route_mismatch() -> None:
    snapshot = DomSnapshot.from_html(
        source_id="tutu",
        final_url="https://www.tutu.ru/avia/search/",
        html=FIXTURE.read_text(encoding="utf-8"),
        captured_at=NOW,
    )

    result = GenericRuHtmlOfferExtractor(source_names={"tutu": "Туту"}).extract(
        snapshot,
        SearchIntent(
            origin="WAW",
            destination="BCN",
            departure_date="2026-09-10",
            return_date="2026-09-20",
            passengers=1,
            currency="RUB",
        ),
    )

    assert result.offers == ()
    assert result.confidence == Confidence.LOW
    assert "route_mismatch" in result.warnings
    assert result.raw_price_candidates[0].accepted is False


def test_generic_ru_html_extractor_ignores_non_total_prices_without_offer_card() -> None:
    snapshot = DomSnapshot.from_html(
        source_id="tutu",
        final_url="https://www.tutu.ru/avia/search/",
        html="<html><body><span>Страховка 1 200 ₽</span></body></html>",
        captured_at=NOW,
    )

    result = GenericRuHtmlOfferExtractor(source_names={"tutu": "Туту"}).extract(
        snapshot,
        _intent(),
    )

    assert result.offers == ()
    assert result.raw_price_candidates == ()
    assert result.confidence == Confidence.NONE
    assert "no_offer_cards_found" in result.warnings


def test_tutu_source_specific_extractor_reads_sanitized_ticket_card() -> None:
    snapshot = DomSnapshot.from_html(
        source_id="tutu",
        final_url="https://www.tutu.ru/avia/search/",
        html=TUTU_SOURCE_FIXTURE.read_text(encoding="utf-8"),
        captured_at=NOW,
        title="Sanitized Tutu source-specific fixture",
    )
    extractor = TutuRuHtmlOfferExtractor(source_names={"tutu": "Tutu"})

    result = extractor.extract(snapshot, _intent())

    assert result.confidence == Confidence.MEDIUM
    assert result.warnings == ()
    assert len(result.raw_price_candidates) == 1
    assert result.raw_price_candidates[0].accepted is True
    assert result.raw_price_candidates[0].amount == Money(1_842_000, "RUB")
    assert len(result.offers) == 1
    offer = result.offers[0]
    assert offer.source_id == "tutu"
    assert offer.source_name == "Tutu"
    assert offer.provider_offer_id == "tutu-realistic-1"
    assert offer.origin == "MOW"
    assert offer.destination == "IST"
    assert offer.departure_date == "2026-09-10"
    assert offer.return_date == "2026-09-20"
    assert offer.total_price == Money(1_842_000, "RUB")
    assert offer.parser_version == extractor.parser_version
    assert offer.airline_name == "Turkish Airlines"
    assert offer.airline_iata == "TK"
    assert offer.stops == 1
    assert offer.baggage_summary == "baggage unknown"


def test_tutu_source_specific_extractor_reports_selector_drift() -> None:
    snapshot = DomSnapshot.from_html(
        source_id="tutu",
        final_url="https://www.tutu.ru/avia/search/",
        html=TUTU_DRIFT_FIXTURE.read_text(encoding="utf-8"),
        captured_at=NOW,
    )

    result = TutuRuHtmlOfferExtractor(source_names={"tutu": "Tutu"}).extract(
        snapshot,
        _intent(),
    )

    assert result.offers == ()
    assert result.raw_price_candidates == ()
    assert result.confidence == Confidence.NONE
    assert result.warnings == ("selector_drift",)


def test_tutu_source_specific_extractor_reports_source_challenge() -> None:
    snapshot = DomSnapshot.from_html(
        source_id="tutu",
        final_url="https://www.tutu.ru/avia/search/",
        html=TUTU_CHALLENGE_FIXTURE.read_text(encoding="utf-8"),
        captured_at=NOW,
    )

    result = TutuRuHtmlOfferExtractor(source_names={"tutu": "Tutu"}).extract(
        snapshot,
        _intent(),
    )

    assert result.offers == ()
    assert result.raw_price_candidates == ()
    assert result.confidence == Confidence.NONE
    assert result.warnings == ("source_challenge",)


def test_parser_pipeline_falls_back_after_source_specific_drift() -> None:
    snapshot = DomSnapshot.from_html(
        source_id="tutu",
        final_url="https://www.tutu.ru/avia/search/",
        html=FIXTURE.read_text(encoding="utf-8"),
        captured_at=NOW,
    )
    pipeline = BrowserOfferParserPipeline(
        source_names={"tutu": "Tutu"},
        scrapling_enabled=False,
    )

    result = pipeline.extract(snapshot, _intent())

    assert len(result.offers) == 1
    assert result.offers[0].provider_offer_id == "tutu-card-1"
    assert result.offers[0].parser_version.startswith("generic_ru_html_fixture:")
    assert "parser_stage:generic_html" in result.warnings
    assert "tutu:selector_drift" in result.warnings


def test_parser_pipeline_stops_on_source_challenge() -> None:
    snapshot = DomSnapshot.from_html(
        source_id="tutu",
        final_url="https://www.tutu.ru/avia/search/",
        html=TUTU_CHALLENGE_FIXTURE.read_text(encoding="utf-8"),
        captured_at=NOW,
    )
    pipeline = BrowserOfferParserPipeline(
        source_names={"tutu": "Tutu"},
        scrapling_enabled=False,
    )

    result = pipeline.extract(snapshot, _intent())

    assert result.offers == ()
    assert result.confidence == Confidence.NONE
    assert result.raw_price_candidates == ()
    assert result.warnings == ("parser_stage:tutu", "tutu:source_challenge")


def test_parser_pipeline_does_not_treat_visible_text_as_crawl4ai_markdown() -> None:
    snapshot = DomSnapshot.from_html(
        source_id="demo_browser",
        final_url="https://example.com/flight-hint",
        html="<html><body>MOW IST 2026-09-10 possible fare 18 420 RUB</body></html>",
        captured_at=NOW,
    )
    pipeline = BrowserOfferParserPipeline(
        source_names={"demo_browser": "Demo"},
        scrapling_enabled=False,
        crawl4ai_diagnostics_enabled=True,
    )

    result = pipeline.extract(snapshot, _intent())

    assert result.offers == ()
    assert result.confidence == Confidence.LOW
    assert result.raw_price_candidates[0].amount == Money(1_842_000, "RUB")
    assert result.raw_price_candidates[0].accepted is False
    assert result.raw_price_candidates[0].rejection_reason == "unstructured_text"
    assert "visible_text_price_hint:unstructured_price_candidates" in result.warnings
    assert "crawl4ai_markdown_hint:crawl4ai_hint_no_markdown" in result.warnings
    assert "crawl4ai_markdown_hint:crawl4ai_hint_price_candidates" not in result.warnings


def test_parser_pipeline_uses_injected_crawl4ai_markdown_for_diagnostic_hints() -> None:
    snapshot = DomSnapshot.from_html(
        source_id="demo_browser",
        final_url="https://example.com/flight-hint",
        html="<html><body>No structured offer cards here.</body></html>",
        captured_at=NOW,
    )
    seen_snapshots: list[DomSnapshot] = []

    def markdown_provider(value: DomSnapshot) -> str:
        seen_snapshots.append(value)
        return "# Deal note\n\nManual check saw MOW IST around 24 500 RUB."

    pipeline = BrowserOfferParserPipeline(
        source_names={"demo_browser": "Demo"},
        scrapling_enabled=False,
        crawl4ai_diagnostics_enabled=True,
        crawl4ai_markdown_provider=markdown_provider,
    )

    result = pipeline.extract(snapshot, _intent())

    assert seen_snapshots == [snapshot]
    assert result.offers == ()
    assert result.confidence == Confidence.LOW
    assert len(result.raw_price_candidates) == 1
    assert result.raw_price_candidates[0].amount == Money(2_450_000, "RUB")
    assert result.raw_price_candidates[0].accepted is False
    assert (
        result.raw_price_candidates[0].rejection_reason
        == "crawl4ai_hint_requires_manual_verification"
    )
    assert "visible_text_price_hint:no_unstructured_price_candidates" in result.warnings
    assert "crawl4ai_markdown_hint:crawl4ai_hint_price_candidates" in result.warnings


def test_parser_pipeline_sanitizes_crawl4ai_provider_errors() -> None:
    snapshot = DomSnapshot.from_html(
        source_id="demo_browser",
        final_url="https://example.com/flight-hint",
        html="<html><body>No structured offer cards here.</body></html>",
        captured_at=NOW,
    )

    def markdown_provider(_value: DomSnapshot) -> str:
        raise RuntimeError("crawl4ai_auth_failed")

    pipeline = BrowserOfferParserPipeline(
        source_names={"demo_browser": "Demo"},
        scrapling_enabled=False,
        crawl4ai_diagnostics_enabled=True,
        crawl4ai_markdown_provider=markdown_provider,
    )

    result = pipeline.extract(snapshot, _intent())

    assert result.offers == ()
    assert result.raw_price_candidates == ()
    assert (
        "crawl4ai_markdown_hint:crawl4ai_hint_unavailable:crawl4ai_auth_failed" in result.warnings
    )


def test_parser_pipeline_does_not_call_crawl4ai_provider_when_structured_offer_exists() -> None:
    snapshot = DomSnapshot.from_html(
        source_id="tutu",
        final_url="https://www.tutu.ru/avia/search/",
        html=TUTU_SOURCE_FIXTURE.read_text(encoding="utf-8"),
        captured_at=NOW,
    )
    seen_snapshots: list[DomSnapshot] = []

    def markdown_provider(value: DomSnapshot) -> str:
        seen_snapshots.append(value)
        return "This markdown should not be needed. MOW IST from 24 500 RUB."

    pipeline = BrowserOfferParserPipeline(
        source_names={"tutu": "Tutu"},
        scrapling_enabled=False,
        crawl4ai_diagnostics_enabled=True,
        crawl4ai_markdown_provider=markdown_provider,
    )

    result = pipeline.extract(snapshot, _intent())

    assert len(result.offers) == 1
    assert result.offers[0].provider_offer_id == "tutu-realistic-1"
    assert seen_snapshots == []
    assert not any(warning.startswith("crawl4ai_markdown_hint:") for warning in result.warnings)


def _intent() -> SearchIntent:
    return SearchIntent(
        origin="MOW",
        destination="IST",
        departure_date="2026-09-10",
        return_date="2026-09-20",
        passengers=1,
        currency="RUB",
    )
