from __future__ import annotations

from flight_hunter.ops.application_metrics import (
    render_application_metrics,
    reset_application_metrics,
)
from flight_hunter.ops.structured_logging import log_event


def test_application_metrics_record_safe_observability_events() -> None:
    reset_application_metrics()

    log_event(
        "provider_call",
        provider="aviasales_data",
        endpoint="prices_for_dates",
        status_code=200,
        duration_ms=12,
    )
    log_event(
        "provider_call",
        provider="aviasales_data",
        endpoint="prices_for_dates",
        status_code=429,
        duration_ms=8,
    )
    log_event(
        "browser_observation_started",
        source="tutu",
        job_id="job-secret-not-a-label",
    )
    log_event(
        "parser_result",
        source="tutu",
        offers=3,
        confidence="medium",
        warnings=("parser_stage:tutu",),
    )
    log_event(
        "search_started",
        search_id="search-secret-not-a-label",
        duration_ms=250,
        household_id="household-secret-not-a-label",
    )
    log_event(
        "alert_sent",
        watch_id="watch-secret-not-a-label",
        notification_id="notification-secret-not-a-label",
        household_id="household-secret-not-a-label",
        reason="price_drop",
    )

    text = render_application_metrics()

    assert (
        'flight_hunter_provider_requests_total{endpoint="prices_for_dates",'
        'provider="aviasales_data",status="200"} 1'
    ) in text
    assert (
        'flight_hunter_provider_requests_total{endpoint="prices_for_dates",'
        'provider="aviasales_data",status="429"} 1'
    ) in text
    assert (
        'flight_hunter_provider_errors_total{endpoint="prices_for_dates",'
        'error="http_429",provider="aviasales_data"} 1'
    ) in text
    assert 'flight_hunter_browser_observation_jobs_total{source="tutu"} 1' in text
    assert (
        'flight_hunter_parser_offers_extracted_total{confidence="medium",source="tutu"} 3'
    ) in text
    assert "flight_hunter_search_duration_seconds_count 1" in text
    assert "flight_hunter_search_duration_seconds_sum 0.25" in text
    assert 'flight_hunter_alerts_sent_total{reason="price_drop"} 1' in text
    assert "secret-not-a-label" not in text


def test_application_metrics_escape_labels() -> None:
    reset_application_metrics()

    log_event(
        "provider_call",
        provider='provider"with\\chars',
        endpoint="line\nbreak",
        status_code=None,
        error_class="TimeoutError",
    )

    text = render_application_metrics()

    assert 'provider="provider\\"with\\\\chars"' in text
    assert 'endpoint="line\\nbreak"' in text
    assert 'status="transport_error"' in text
    assert 'error="TimeoutError"' in text
