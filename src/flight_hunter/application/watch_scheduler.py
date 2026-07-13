from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime
from uuid import UUID

from flight_hunter.domain.policy import ExecutionContext, ProviderOperation, ProviderPolicy
from flight_hunter.policy.guard import ProviderPolicyGuard


@dataclass(frozen=True, slots=True)
class WatchScheduleState:
    watch_id: UUID
    enabled: bool
    paused_until: datetime | None
    departure_date: date
    next_eligible_at: datetime
    cache_fresh_until: datetime | None
    allowed_provider_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ProviderRuntimeState:
    policy: ProviderPolicy
    circuit_open: bool = False
    quota_reserved: bool = True


@dataclass(frozen=True, slots=True)
class WatchSchedulerDecision:
    watch_id: UUID
    eligible: bool
    provider_ids: tuple[str, ...]
    blocked_reasons: tuple[str, ...]
    provider_denials: dict[str, str]


class SchedulerProviderRegistry:
    def __init__(self) -> None:
        self._providers: list[ProviderRuntimeState] = []
        self._denials: dict[str, str] = {}

    @property
    def providers(self) -> tuple[ProviderRuntimeState, ...]:
        return tuple(self._providers)

    @property
    def denials(self) -> dict[str, str]:
        return dict(self._denials)

    def register(self, provider: ProviderRuntimeState) -> bool:
        denial = _scheduler_registration_denial(provider.policy)
        provider_id = provider.policy.provider_id
        if denial is not None:
            self._denials[provider_id] = denial
            return False
        self._providers.append(provider)
        return True


class WatchSchedulerPlanner:
    def __init__(self, *, clock: Callable[[], datetime] | None = None) -> None:
        self._clock = clock or (lambda: datetime.now(UTC))
        self._guard = ProviderPolicyGuard(clock=self._clock)

    def decide(
        self,
        watch: WatchScheduleState,
        *,
        providers: tuple[ProviderRuntimeState, ...],
    ) -> WatchSchedulerDecision:
        now = self._clock()
        blocked_reasons = self._watch_blocked_reasons(watch, now)
        if blocked_reasons:
            return WatchSchedulerDecision(
                watch_id=watch.watch_id,
                eligible=False,
                provider_ids=(),
                blocked_reasons=blocked_reasons,
                provider_denials={},
            )

        provider_ids: list[str] = []
        provider_denials: dict[str, str] = {}
        allowed_provider_ids = set(watch.allowed_provider_ids)
        for provider in providers:
            provider_id = provider.policy.provider_id
            if allowed_provider_ids and provider_id not in allowed_provider_ids:
                provider_denials[provider_id] = "provider_not_allowed_by_watch"
                continue
            if provider.circuit_open:
                provider_denials[provider_id] = "circuit_open"
                continue
            if not provider.quota_reserved:
                provider_denials[provider_id] = "quota_unavailable"
                continue

            decision = self._guard.authorize(
                provider.policy,
                operation=ProviderOperation.SEARCH,
                context=ExecutionContext.SCHEDULER,
                request_fingerprint=f"watch:{watch.watch_id}",
            )
            if not decision.allowed:
                provider_denials[provider_id] = decision.code.value
                continue
            provider_ids.append(provider_id)

        return WatchSchedulerDecision(
            watch_id=watch.watch_id,
            eligible=bool(provider_ids),
            provider_ids=tuple(provider_ids),
            blocked_reasons=(),
            provider_denials=provider_denials,
        )

    @staticmethod
    def _watch_blocked_reasons(
        watch: WatchScheduleState,
        now: datetime,
    ) -> tuple[str, ...]:
        if not watch.enabled:
            return ("watch_disabled",)
        if watch.paused_until is not None and now < watch.paused_until:
            return ("watch_paused",)
        if watch.departure_date < now.date():
            return ("departure_passed",)
        if now < watch.next_eligible_at:
            return ("watch_not_due",)
        if watch.cache_fresh_until is not None and now < watch.cache_fresh_until:
            return ("cache_fresh",)
        return ()


def _scheduler_registration_denial(policy: ProviderPolicy) -> str | None:
    if policy.user_action_required:
        return "user_action_required"
    if not policy.background_requests_allowed:
        return "background_not_allowed"
    return None
