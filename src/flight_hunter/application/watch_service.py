from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from flight_hunter.persistence.repositories import (
    AuditEventRepository,
    HouseholdWatchRepository,
    NewAuditEvent,
    NewWatch,
    WatchMutationResult,
    WatchRecord,
)


@dataclass(frozen=True, slots=True)
class CreateWatchCommand:
    household_id: UUID
    owner_user_id: UUID
    origin: str
    destination: str
    departure_date: str
    return_date: str | None
    passengers: int = 1
    currency: str = "RUB"
    scan_interval_seconds: int = 21_600
    allowed_provider_ids: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class UpdateWatchCommand:
    household_id: UUID
    watch_id: UUID
    actor_user_id: UUID
    expected_version: int
    updates: Mapping[str, object]


@dataclass(frozen=True, slots=True)
class WatchLifecycleCommand:
    household_id: UUID
    watch_id: UUID
    actor_user_id: UUID
    expected_version: int


class WatchService:
    def __init__(
        self,
        repository: HouseholdWatchRepository,
        *,
        audit_repository: AuditEventRepository | None = None,
        clock: Callable[[], datetime] | None = None,
        id_factory: Callable[[], UUID] = uuid4,
    ) -> None:
        self._repository = repository
        self._audit_repository = audit_repository
        self._clock = clock or (lambda: datetime.now(UTC))
        self._id_factory = id_factory

    async def create_watch(self, command: CreateWatchCommand) -> WatchRecord:
        now = self._clock()
        watch = NewWatch(
            id=self._id_factory(),
            household_id=command.household_id,
            owner_user_id=command.owner_user_id,
            origin=command.origin,
            destination=command.destination,
            departure_date=command.departure_date,
            return_date=command.return_date,
            passengers=command.passengers,
            currency=command.currency,
            created_at=now,
            updated_at=now,
            scan_interval_seconds=command.scan_interval_seconds,
            allowed_provider_ids=command.allowed_provider_ids,
        )
        await self._repository.add_watch(watch)
        created = await self._repository.get_watch(command.household_id, watch.id)
        if created is None:
            raise RuntimeError("created watch was not found")
        await self._record_audit(
            household_id=command.household_id,
            actor_user_id=command.owner_user_id,
            action="watch.created",
            entity_id=watch.id,
            summary="watch created",
            created_at=now,
        )
        return created

    async def list_watches(self, household_id: UUID) -> tuple[WatchRecord, ...]:
        return await self._repository.list_watches(household_id)

    async def get_watch(self, household_id: UUID, watch_id: UUID) -> WatchRecord | None:
        return await self._repository.get_watch(household_id, watch_id)

    async def pause_watch(
        self,
        *,
        household_id: UUID,
        watch_id: UUID,
        actor_user_id: UUID | None = None,
        paused_until: datetime | None = None,
    ) -> WatchRecord | None:
        until = paused_until or (self._clock() + timedelta(hours=24))
        updated_at = self._clock()
        watch = await self._repository.pause_watch(
            household_id=household_id,
            watch_id=watch_id,
            paused_until=until,
            updated_at=updated_at,
        )
        if watch is not None:
            await self._record_audit(
                household_id=household_id,
                actor_user_id=actor_user_id,
                action="watch.paused",
                entity_id=watch_id,
                summary="watch paused",
                created_at=updated_at,
            )
        return watch

    async def update_watch(self, command: UpdateWatchCommand) -> WatchMutationResult:
        updated_at = self._clock()
        result = await self._repository.update_watch(
            household_id=command.household_id,
            watch_id=command.watch_id,
            expected_version=command.expected_version,
            updated_at=updated_at,
            updates=self._normalized_updates(command.updates),
        )
        if result.status == "updated" and command.updates:
            await self._record_audit(
                household_id=command.household_id,
                actor_user_id=command.actor_user_id,
                action="watch.updated",
                entity_id=command.watch_id,
                summary="watch updated",
                created_at=updated_at,
            )
        return result

    async def archive_watch(self, command: WatchLifecycleCommand) -> WatchMutationResult:
        archived_at = self._clock()
        result = await self._repository.archive_watch(
            household_id=command.household_id,
            watch_id=command.watch_id,
            expected_version=command.expected_version,
            archived_at=archived_at,
            archived_by_user_id=command.actor_user_id,
        )
        if result.status == "archived":
            await self._record_audit(
                household_id=command.household_id,
                actor_user_id=command.actor_user_id,
                action="watch.archived",
                entity_id=command.watch_id,
                summary="watch archived",
                created_at=archived_at,
            )
        return result

    async def delete_watch(self, command: WatchLifecycleCommand) -> WatchMutationResult:
        deleted_at = self._clock()
        result = await self._repository.delete_watch(
            household_id=command.household_id,
            watch_id=command.watch_id,
            expected_version=command.expected_version,
            deleted_at=deleted_at,
            deleted_by_user_id=command.actor_user_id,
        )
        if result.status == "deleted":
            await self._record_audit(
                household_id=command.household_id,
                actor_user_id=command.actor_user_id,
                action="watch.deleted",
                entity_id=command.watch_id,
                summary="watch deleted",
                created_at=deleted_at,
            )
        return result

    async def resume_watch(
        self,
        *,
        household_id: UUID,
        watch_id: UUID,
        actor_user_id: UUID | None = None,
    ) -> WatchRecord | None:
        resumed_at = self._clock()
        watch = await self._repository.resume_watch(
            household_id=household_id,
            watch_id=watch_id,
            resumed_at=resumed_at,
        )
        if watch is not None:
            await self._record_audit(
                household_id=household_id,
                actor_user_id=actor_user_id,
                action="watch.resumed",
                entity_id=watch_id,
                summary="watch resumed",
                created_at=resumed_at,
            )
        return watch

    async def _record_audit(
        self,
        *,
        household_id: UUID,
        actor_user_id: UUID | None,
        action: str,
        entity_id: UUID,
        summary: str,
        created_at: datetime,
    ) -> None:
        if self._audit_repository is None:
            return
        await self._audit_repository.add_event(
            NewAuditEvent(
                id=self._id_factory(),
                household_id=household_id,
                actor_user_id=actor_user_id,
                action=action,
                entity_type="watch",
                entity_id=entity_id,
                summary=summary,
                created_at=created_at,
            )
        )

    @staticmethod
    def _normalized_updates(updates: Mapping[str, object]) -> dict[str, object]:
        normalized: dict[str, object] = {}
        for key, value in updates.items():
            if key in {"origin", "destination", "currency"} and isinstance(value, str):
                normalized[key] = value.upper()
            elif key == "allowed_provider_ids" and isinstance(value, list):
                normalized[key] = tuple(str(item) for item in value)
            else:
                normalized[key] = value
        return normalized
