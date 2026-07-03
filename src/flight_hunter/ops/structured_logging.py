from __future__ import annotations

import json
import logging
from collections.abc import Mapping, Sequence
from datetime import date, datetime
from enum import Enum
from uuid import UUID

from flight_hunter.ops.application_metrics import record_observability_metric

LOGGER_NAME = "flight_hunter.observability"

_LOGGER = logging.getLogger(LOGGER_NAME)


def log_event(event: str, **fields: object) -> None:
    record_observability_metric(event, fields)
    payload: dict[str, object] = {"event": event}
    for key, value in fields.items():
        if value is None:
            continue
        payload[key] = _json_safe(value)
    _LOGGER.info(
        json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
    )


def _json_safe(value: object) -> object:
    if isinstance(value, str | int | float | bool):
        return value
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, datetime | date):
        return value.isoformat()
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, Mapping):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, Sequence) and not isinstance(value, bytes | bytearray | str):
        return [_json_safe(item) for item in value]
    return str(value)
