from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from uuid import UUID

from flight_hunter.domain.search_results import Confidence
from flight_hunter.ops.structured_logging import log_event


def test_log_event_emits_json_payload_with_safe_scalar_fields(caplog) -> None:
    caplog.set_level(logging.INFO, logger="flight_hunter.observability")

    log_event(
        "parser_result",
        job_id=UUID("33333333-3333-3333-3333-333333333333"),
        observed_at=datetime(2026, 6, 29, 12, 0, tzinfo=UTC),
        confidence=Confidence.MEDIUM,
        warnings=("parser_stage:tutu",),
        raw_payload=None,
    )

    payload = json.loads(caplog.records[0].getMessage())
    assert payload == {
        "event": "parser_result",
        "job_id": "33333333-3333-3333-3333-333333333333",
        "observed_at": "2026-06-29T12:00:00+00:00",
        "confidence": "medium",
        "warnings": ["parser_stage:tutu"],
    }
