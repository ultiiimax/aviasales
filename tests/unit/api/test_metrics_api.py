from __future__ import annotations

import pytest

from flight_hunter.ops.application_metrics import reset_application_metrics
from flight_hunter.ops.structured_logging import log_event


@pytest.mark.anyio
async def test_metrics_endpoint_returns_application_prometheus_text_without_secret_ids(
    agent_api_harness,
) -> None:
    reset_application_metrics()
    log_event(
        "alert_sent",
        watch_id="watch-secret-not-a-label",
        notification_id="notification-secret-not-a-label",
        household_id="household-secret-not-a-label",
        reason="price_drop",
    )
    response = agent_api_harness.client.get("/api/v1/metrics")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/plain")
    assert 'flight_hunter_alerts_sent_total{reason="price_drop"} 1' in response.text
    assert "flight_hunter_agent_provider_denials 0" in response.text
    assert "flight_hunter_agent_recovered_operations 0" in response.text
    assert "secret-not-a-label" not in response.text
