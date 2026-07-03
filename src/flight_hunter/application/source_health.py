from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

from flight_hunter.application.source_contracts import SourceContractCatalog, SourceReadiness
from flight_hunter.persistence.repositories import (
    SourceHealthEventRecord,
    SourceHealthEventRepository,
)


@dataclass(frozen=True, slots=True)
class SourceHealthEventView:
    id: UUID
    source_id: str
    event_type: str
    status: str
    message: str
    observed_at: datetime
    cooldown_until: datetime | None


@dataclass(frozen=True, slots=True)
class SourceHealthItem:
    source_id: str
    display_name: str
    contract_known: bool
    stage: str | None
    enabled: bool
    data_kind: str | None
    merge_scope: str | None
    background_requests_allowed: bool | None
    user_action_required: bool | None
    blocked_reasons: tuple[str, ...]
    current_status: str
    latest_event: SourceHealthEventView | None


@dataclass(frozen=True, slots=True)
class SourceHealthSnapshot:
    checked_at: datetime
    sources: tuple[SourceHealthItem, ...]


class SourceHealthService:
    def __init__(
        self,
        *,
        contracts: SourceContractCatalog,
        events: SourceHealthEventRepository,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._contracts = contracts
        self._events = events
        self._clock = clock or (lambda: datetime.now(UTC))

    async def snapshot(self, *, event_limit: int = 100) -> SourceHealthSnapshot:
        readiness = self._contracts.readiness()
        events = await self._events.list_recent(limit=event_limit)
        latest_events = _latest_by_source(events)
        readiness_by_source = {source.source_id: source for source in readiness}
        source_ids = sorted(set(readiness_by_source) | set(latest_events))
        return SourceHealthSnapshot(
            checked_at=self._clock(),
            sources=tuple(
                _health_item(
                    source_id=source_id,
                    readiness=readiness_by_source.get(source_id),
                    latest_event=latest_events.get(source_id),
                )
                for source_id in source_ids
            ),
        )


def _latest_by_source(
    events: tuple[SourceHealthEventRecord, ...],
) -> dict[str, SourceHealthEventView]:
    latest: dict[str, SourceHealthEventView] = {}
    for event in events:
        if event.source_id in latest:
            continue
        latest[event.source_id] = SourceHealthEventView(
            id=event.id,
            source_id=event.source_id,
            event_type=event.event_type,
            status=event.status,
            message=event.message,
            observed_at=event.observed_at,
            cooldown_until=event.cooldown_until,
        )
    return latest


def _health_item(
    *,
    source_id: str,
    readiness: SourceReadiness | None,
    latest_event: SourceHealthEventView | None,
) -> SourceHealthItem:
    if readiness is None:
        return SourceHealthItem(
            source_id=source_id,
            display_name=source_id,
            contract_known=False,
            stage=None,
            enabled=False,
            data_kind=None,
            merge_scope=None,
            background_requests_allowed=None,
            user_action_required=None,
            blocked_reasons=(),
            current_status=latest_event.status if latest_event is not None else "event_only",
            latest_event=latest_event,
        )
    return SourceHealthItem(
        source_id=readiness.source_id,
        display_name=readiness.display_name,
        contract_known=True,
        stage=readiness.stage.value,
        enabled=readiness.enabled,
        data_kind=readiness.data_kind,
        merge_scope=readiness.merge_scope,
        background_requests_allowed=readiness.background_requests_allowed,
        user_action_required=readiness.user_action_required,
        blocked_reasons=readiness.blocked_reasons,
        current_status=_current_status(readiness=readiness, latest_event=latest_event),
        latest_event=latest_event,
    )


def _current_status(
    *,
    readiness: SourceReadiness,
    latest_event: SourceHealthEventView | None,
) -> str:
    if latest_event is not None:
        return latest_event.status
    if readiness.blocked_reasons:
        return "blocked"
    return "no_events"
