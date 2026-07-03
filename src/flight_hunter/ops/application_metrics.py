from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from threading import RLock


@dataclass(slots=True)
class _MetricState:
    counters: dict[tuple[str, tuple[tuple[str, str], ...]], float] = field(default_factory=dict)
    search_duration_count: int = 0
    search_duration_sum_seconds: float = 0.0


_STATE = _MetricState()
_LOCK = RLock()


def reset_application_metrics() -> None:
    with _LOCK:
        _STATE.counters.clear()
        _STATE.search_duration_count = 0
        _STATE.search_duration_sum_seconds = 0.0


def record_observability_metric(event: str, fields: Mapping[str, object]) -> None:
    with _LOCK:
        if event == "provider_call":
            _record_provider_call(fields)
        elif event == "browser_observation_started":
            _increment(
                "flight_hunter_browser_observation_jobs_total",
                {"source": _label_field(fields, "source")},
            )
        elif event == "parser_result":
            _increment(
                "flight_hunter_parser_offers_extracted_total",
                {
                    "source": _label_field(fields, "source"),
                    "confidence": _label_field(fields, "confidence"),
                },
                amount=_numeric_field(fields, "offers", default=0),
            )
        elif event == "search_started":
            duration_ms = _numeric_field(fields, "duration_ms", default=0)
            _STATE.search_duration_count += 1
            _STATE.search_duration_sum_seconds += duration_ms / 1000
        elif event == "alert_sent":
            _increment(
                "flight_hunter_alerts_sent_total",
                {"reason": _label_field(fields, "reason")},
            )


def render_application_metrics() -> str:
    with _LOCK:
        counters = dict(_STATE.counters)
        search_duration_count = _STATE.search_duration_count
        search_duration_sum_seconds = _STATE.search_duration_sum_seconds

    lines = [
        "# HELP flight_hunter_provider_requests_total "
        "Provider API calls by safe endpoint and status.",
        "# TYPE flight_hunter_provider_requests_total counter",
    ]
    lines.extend(_counter_lines("flight_hunter_provider_requests_total", counters))
    lines.extend(
        [
            "# HELP flight_hunter_provider_errors_total "
            "Provider API calls that ended in HTTP or transport errors.",
            "# TYPE flight_hunter_provider_errors_total counter",
        ]
    )
    lines.extend(_counter_lines("flight_hunter_provider_errors_total", counters))
    lines.extend(
        [
            "# HELP flight_hunter_browser_observation_jobs_total "
            "User-action browser observation jobs started.",
            "# TYPE flight_hunter_browser_observation_jobs_total counter",
        ]
    )
    lines.extend(_counter_lines("flight_hunter_browser_observation_jobs_total", counters))
    lines.extend(
        [
            "# HELP flight_hunter_parser_offers_extracted_total "
            "Browser parser offers extracted from sanitized DOM snapshots.",
            "# TYPE flight_hunter_parser_offers_extracted_total counter",
        ]
    )
    lines.extend(_counter_lines("flight_hunter_parser_offers_extracted_total", counters))
    lines.extend(
        [
            "# HELP flight_hunter_search_duration_seconds Search request duration summary.",
            "# TYPE flight_hunter_search_duration_seconds summary",
            f"flight_hunter_search_duration_seconds_count {_metric_number(search_duration_count)}",
            "flight_hunter_search_duration_seconds_sum "
            f"{_metric_number(search_duration_sum_seconds)}",
            "# HELP flight_hunter_alerts_sent_total "
            "Alerts successfully sent through delivery transports.",
            "# TYPE flight_hunter_alerts_sent_total counter",
        ]
    )
    lines.extend(_counter_lines("flight_hunter_alerts_sent_total", counters))
    return "\n".join(lines) + "\n"


def _record_provider_call(fields: Mapping[str, object]) -> None:
    provider = _label_field(fields, "provider")
    endpoint = _label_field(fields, "endpoint")
    status_code = fields.get("status_code")
    status = str(status_code) if isinstance(status_code, int) else "transport_error"
    _increment(
        "flight_hunter_provider_requests_total",
        {"provider": provider, "endpoint": endpoint, "status": status},
    )
    error_class = _optional_label_field(fields, "error_class")
    if error_class is not None:
        error = error_class
    elif isinstance(status_code, int) and status_code >= 400:
        error = f"http_{status_code}"
    else:
        error = None
    if error is not None:
        _increment(
            "flight_hunter_provider_errors_total",
            {"provider": provider, "endpoint": endpoint, "error": error},
        )


def _increment(name: str, labels: Mapping[str, str], *, amount: float = 1.0) -> None:
    key = (name, tuple(sorted(labels.items())))
    _STATE.counters[key] = _STATE.counters.get(key, 0.0) + amount


def _counter_lines(
    name: str,
    counters: Mapping[tuple[str, tuple[tuple[str, str], ...]], float],
) -> list[str]:
    lines: list[str] = []
    for (metric_name, labels), value in sorted(counters.items()):
        if metric_name != name:
            continue
        lines.append(f"{metric_name}{_metric_labels(dict(labels))} {_metric_number(value)}")
    return lines


def _label_field(fields: Mapping[str, object], key: str) -> str:
    value = fields.get(key)
    if value is None:
        return "unknown"
    text = str(value).strip()
    return text if text else "unknown"


def _optional_label_field(fields: Mapping[str, object], key: str) -> str | None:
    value = fields.get(key)
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _numeric_field(fields: Mapping[str, object], key: str, *, default: float) -> float:
    value = fields.get(key)
    if isinstance(value, bool):
        return default
    if isinstance(value, int | float):
        return float(value)
    return default


def _metric_labels(labels: Mapping[str, str]) -> str:
    if not labels:
        return ""
    return "{" + ",".join(f'{key}="{_escape_label(value)}"' for key, value in labels.items()) + "}"


def _escape_label(value: str) -> str:
    return value.replace("\\", "\\\\").replace("\n", "\\n").replace('"', '\\"')


def _metric_number(value: float | int | bool) -> str:
    if isinstance(value, bool):
        return "1" if value else "0"
    if isinstance(value, int):
        return str(value)
    if value.is_integer():
        return str(int(value))
    return f"{value:.6g}"
