from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from json import JSONDecodeError
from typing import Any, Protocol
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from uuid import NAMESPACE_URL, UUID, uuid4, uuid5

from flight_hunter.deals.crawl4ai_client import Crawl4AiClientError
from flight_hunter.deals.searxng_client import SearxngClientError
from flight_hunter.deals.url_policy import DealUrlPolicyError
from flight_hunter.domain.offers import SearchIntent, TripType
from flight_hunter.domain.search_results import DealCandidate
from flight_hunter.persistence.repositories import (
    DealCandidateRepository,
    DealDiscoveryJobRecord,
    DealDiscoveryJobRepository,
    NewDealCandidate,
    NewSourceHealthEvent,
    SourceHealthEventRepository,
)


class DealDiscoveryRunner(Protocol):
    async def discover(
        self, intent: SearchIntent, *, limit: int = 5
    ) -> tuple[DealCandidate, ...]: ...


@dataclass(frozen=True, slots=True)
class DealDiscoveryJobRunSummary:
    jobs_processed: int = 0
    jobs_succeeded: int = 0
    jobs_retry_scheduled: int = 0
    jobs_failed: int = 0
    candidates_saved: int = 0
    health_events_recorded: int = 0

    def merge(self, other: DealDiscoveryJobRunSummary) -> DealDiscoveryJobRunSummary:
        return DealDiscoveryJobRunSummary(
            jobs_processed=self.jobs_processed + other.jobs_processed,
            jobs_succeeded=self.jobs_succeeded + other.jobs_succeeded,
            jobs_retry_scheduled=self.jobs_retry_scheduled + other.jobs_retry_scheduled,
            jobs_failed=self.jobs_failed + other.jobs_failed,
            candidates_saved=self.candidates_saved + other.candidates_saved,
            health_events_recorded=self.health_events_recorded + other.health_events_recorded,
        )


class DealDiscoveryJobService:
    def __init__(
        self,
        *,
        jobs: DealDiscoveryJobRepository,
        candidates: DealCandidateRepository,
        source_health_events: SourceHealthEventRepository,
        discovery: DealDiscoveryRunner | None,
        clock: Callable[[], datetime] | None = None,
        id_factory: Callable[[], UUID] = uuid4,
        candidate_ttl: timedelta = timedelta(hours=6),
    ) -> None:
        self._jobs = jobs
        self._candidates = candidates
        self._source_health_events = source_health_events
        self._discovery = discovery
        self._clock = clock or (lambda: datetime.now(UTC))
        self._id_factory = id_factory
        self._candidate_ttl = candidate_ttl

    async def run_once(
        self,
        *,
        limit: int,
        retry_delay: timedelta,
        worker_id: str,
    ) -> DealDiscoveryJobRunSummary:
        now = self._clock()
        claimed_jobs = await self._jobs.claim_queued(
            now=now,
            limit=limit,
            worker_id=worker_id,
        )
        summary = DealDiscoveryJobRunSummary(jobs_processed=len(claimed_jobs))
        for job in claimed_jobs:
            summary = summary.merge(
                await self.run_job(
                    job,
                    retry_delay=retry_delay,
                )
            )
        return summary

    async def run_job(
        self,
        job: DealDiscoveryJobRecord,
        *,
        retry_delay: timedelta,
    ) -> DealDiscoveryJobRunSummary:
        started_at = self._clock()
        if job.deadline_at <= started_at:
            await self._fail(
                job,
                code="deadline_exceeded",
                message="deal discovery job deadline elapsed before execution",
                observed_at=started_at,
            )
            return DealDiscoveryJobRunSummary(jobs_failed=1, health_events_recorded=1)

        if self._discovery is None:
            await self._fail(
                job,
                code="deal_discovery_disabled",
                message="deal discovery requires enabled SearXNG and Crawl4AI settings",
                observed_at=started_at,
            )
            return DealDiscoveryJobRunSummary(jobs_failed=1, health_events_recorded=1)

        try:
            intent = _search_intent_from_json(job.search_intent_json)
        except (JSONDecodeError, TypeError, ValueError, KeyError) as exc:
            await self._fail(
                job,
                code="invalid_search_intent",
                message=_safe_error_message(exc, context="deal discovery search intent"),
                observed_at=started_at,
            )
            return DealDiscoveryJobRunSummary(jobs_failed=1, health_events_recorded=1)

        try:
            discovered = await self._discovery.discover(intent, limit=job.limit)
        except DealUrlPolicyError as exc:
            await self._fail(
                job,
                code="deal_discovery_url_rejected",
                message=_safe_error_message(exc, context="deal discovery URL policy"),
                observed_at=self._clock(),
            )
            return DealDiscoveryJobRunSummary(jobs_failed=1, health_events_recorded=1)
        except (Crawl4AiClientError, SearxngClientError) as exc:
            return await self._retry_or_fail(
                job,
                retry_delay=retry_delay,
                code="deal_discovery_source_failed",
                message=_safe_error_message(exc, context="deal discovery source"),
            )
        except Exception as exc:
            return await self._retry_or_fail(
                job,
                retry_delay=retry_delay,
                code="deal_discovery_source_failed",
                message=_safe_error_message(exc, context="deal discovery source"),
            )

        finished_at = self._clock()
        expires_at = finished_at + self._candidate_ttl
        saved = 0
        for candidate in discovered:
            candidate_with_expiry = replace(candidate, expires_at=expires_at)
            inserted = await self._candidates.add_candidate_once(
                NewDealCandidate(
                    id=_candidate_id(job, candidate_with_expiry),
                    household_id=job.household_id,
                    user_id=job.user_id,
                    search_id=job.search_id,
                    candidate=candidate_with_expiry,
                    expires_at=expires_at,
                )
            )
            if inserted:
                saved += 1
        await self._jobs.mark_succeeded(
            job_id=job.id,
            completed_at=finished_at,
            result_count=len(discovered),
        )
        await self._record_health_event(
            status="ok",
            message=f"deal discovery job succeeded; candidates={len(discovered)} saved={saved}",
            observed_at=finished_at,
        )
        return DealDiscoveryJobRunSummary(
            jobs_succeeded=1,
            candidates_saved=saved,
            health_events_recorded=1,
        )

    async def _retry_or_fail(
        self,
        job: DealDiscoveryJobRecord,
        *,
        retry_delay: timedelta,
        code: str,
        message: str,
    ) -> DealDiscoveryJobRunSummary:
        observed_at = self._clock()
        retry_at = observed_at + retry_delay
        if job.attempts < job.max_attempts and retry_at < job.deadline_at:
            await self._jobs.mark_retry_scheduled(
                job_id=job.id,
                retry_at=retry_at,
                error_code=code,
                error_message=message,
            )
            await self._record_health_event(
                status="retry_scheduled",
                message=f"deal discovery job retry scheduled; code={code}",
                observed_at=observed_at,
                cooldown_until=retry_at,
            )
            return DealDiscoveryJobRunSummary(
                jobs_retry_scheduled=1,
                health_events_recorded=1,
            )
        await self._fail(job, code=code, message=message, observed_at=observed_at)
        return DealDiscoveryJobRunSummary(jobs_failed=1, health_events_recorded=1)

    async def _fail(
        self,
        job: DealDiscoveryJobRecord,
        *,
        code: str,
        message: str,
        observed_at: datetime,
    ) -> None:
        await self._jobs.mark_failed(
            job_id=job.id,
            completed_at=observed_at,
            error_code=code,
            error_message=message,
        )
        await self._record_health_event(
            status="failed",
            message=f"deal discovery job failed; code={code}",
            observed_at=observed_at,
        )

    async def _record_health_event(
        self,
        *,
        status: str,
        message: str,
        observed_at: datetime,
        cooldown_until: datetime | None = None,
    ) -> None:
        await self._source_health_events.add_event(
            NewSourceHealthEvent(
                id=self._id_factory(),
                source_id="deal_discovery",
                event_type="deal_discovery_job",
                status=status,
                message=message,
                observed_at=observed_at,
                cooldown_until=cooldown_until,
            )
        )


def _search_intent_from_json(raw: str) -> SearchIntent:
    payload: Any = json.loads(raw)
    if not isinstance(payload, dict):
        raise ValueError("search intent payload must be an object")
    return SearchIntent(
        origin=_required_str(payload, "origin"),
        destination=_required_str(payload, "destination"),
        departure_date=_required_str(payload, "departure_date"),
        return_date=_optional_str(payload, "return_date"),
        passengers=_required_int(payload, "passengers"),
        currency=_required_str(payload, "currency"),
        adults=_optional_int(payload, "adults"),
        children=_int_or_default(payload, "children", 0),
        infants=_int_or_default(payload, "infants", 0),
        trip_type=_optional_trip_type(payload, "trip_type"),
    )


def _required_str(payload: dict[str, Any], field_name: str) -> str:
    value = payload[field_name]
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must be a non-empty string")
    return value.strip()


def _optional_str(payload: dict[str, Any], field_name: str) -> str | None:
    value = payload.get(field_name)
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError(f"{field_name} must be a string")
    value = value.strip()
    return value or None


def _required_int(payload: dict[str, Any], field_name: str) -> int:
    value = payload[field_name]
    if type(value) is not int:
        raise ValueError(f"{field_name} must be an integer")
    return value


def _optional_int(payload: dict[str, Any], field_name: str) -> int | None:
    value = payload.get(field_name)
    if value is None:
        return None
    if type(value) is not int:
        raise ValueError(f"{field_name} must be an integer")
    return value


def _int_or_default(payload: dict[str, Any], field_name: str, default: int) -> int:
    value = payload.get(field_name, default)
    if type(value) is not int:
        raise ValueError(f"{field_name} must be an integer")
    return value


def _optional_trip_type(payload: dict[str, Any], field_name: str) -> TripType | str | None:
    value = payload.get(field_name)
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError(f"{field_name} must be a string")
    return value


def _candidate_id(job: DealDiscoveryJobRecord, candidate: DealCandidate) -> UUID:
    raw = "|".join(
        (
            "flight-hunter:deal-discovery-candidate",
            str(job.id),
            candidate.source_id,
            _canonical_url_key(candidate.url),
            candidate.title,
        )
    )
    return uuid5(NAMESPACE_URL, raw)


def _canonical_url_key(url: str) -> str:
    parsed = urlsplit(url)
    query = urlencode(
        sorted(
            (key, value)
            for key, value in parse_qsl(parsed.query, keep_blank_values=True)
            if not _is_tracking_query_param(key)
        )
    )
    path = parsed.path.rstrip("/") or "/"
    return urlunsplit((parsed.scheme.lower(), parsed.netloc.lower(), path, query, ""))


def _is_tracking_query_param(key: str) -> bool:
    normalized = key.lower()
    return normalized.startswith("utm_") or normalized in {"gclid", "fbclid", "yclid"}


def _safe_error_message(exc: Exception, *, context: str) -> str:
    return f"{exc.__class__.__name__} during {context}"
