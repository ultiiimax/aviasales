from __future__ import annotations

import hashlib
import json
import os
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from types import TracebackType
from typing import Any, Protocol, cast
from urllib.parse import urlparse, urlsplit, urlunsplit

from flight_hunter.browser.html_extractor import (
    BrowserExtractionResult,
    BrowserOfferParserPipeline,
    DomSnapshot,
    sanitize_dom_html_for_fixture,
)
from flight_hunter.config import AppSettings
from flight_hunter.domain.observation import ObservationStatus, OperatorCheckpointDecision
from flight_hunter.domain.offers import SearchIntent
from flight_hunter.ops.structured_logging import log_event
from flight_hunter.providers.ru_clickout import RuClickoutLinkBuilder, default_ru_aggregator_specs
from flight_hunter.providers.ru_clickout.source_specs import RuAggregatorSpec


class PersonalObserverErrorCode(StrEnum):
    OBSERVER_DISABLED = "observer_disabled"
    SOURCE_NOT_FOUND = "source_not_found"
    SOURCE_NOT_OBSERVABLE = "source_not_observable"
    HOST_NOT_ALLOWED = "host_not_allowed"
    PLAYWRIGHT_UNAVAILABLE = "playwright_unavailable"
    NAVIGATION_FAILED = "navigation_failed"
    SOURCE_CHALLENGE = "source_challenge"
    SELECTOR_DRIFT = "selector_drift"
    PARSER_NO_OFFERS = "parser_no_offers"
    OPERATOR_ABORTED = "operator_aborted"
    PROFILE_LOCKED = "profile_locked"


class PersonalObserverError(RuntimeError):
    def __init__(self, code: PersonalObserverErrorCode, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True, slots=True)
class PersonalObserverConfig:
    enabled: bool
    headless: bool
    profile_root: Path
    artifact_root: Path
    save_dom_fixtures: bool
    save_screenshots: bool
    navigation_timeout_ms: int
    ready_selector: str | None
    ready_timeout_ms: int
    wait_for_network_idle: bool
    manual_checkpoint_seconds: int
    allowed_hosts: tuple[str, ...]
    profile_lock_timeout_seconds: int = 0
    profile_lock_stale_seconds: int = 3_600
    scrapling_enabled: bool = True
    crawl4ai_diagnostics_enabled: bool = False
    require_user_action: bool = True
    save_runtime_manifests: bool = False

    @classmethod
    def from_settings(cls, settings: AppSettings) -> PersonalObserverConfig:
        return cls(
            enabled=settings.personal_observer_enabled,
            headless=settings.personal_observer_headless,
            profile_root=Path(settings.personal_observer_profile_root),
            artifact_root=Path(settings.personal_observer_artifact_root),
            save_dom_fixtures=settings.personal_observer_save_dom_fixtures,
            save_screenshots=settings.personal_observer_save_screenshots,
            save_runtime_manifests=settings.personal_observer_save_runtime_manifests,
            navigation_timeout_ms=settings.personal_observer_navigation_timeout_ms,
            ready_selector=settings.personal_observer_ready_selector,
            ready_timeout_ms=settings.personal_observer_ready_timeout_ms,
            wait_for_network_idle=settings.personal_observer_wait_for_network_idle,
            manual_checkpoint_seconds=settings.personal_observer_manual_checkpoint_seconds,
            allowed_hosts=settings.personal_observer_allowed_hosts,
            profile_lock_timeout_seconds=settings.personal_observer_profile_lock_timeout_seconds,
            profile_lock_stale_seconds=settings.personal_observer_profile_lock_stale_seconds,
            scrapling_enabled=settings.scrapling_enabled,
            crawl4ai_diagnostics_enabled=settings.crawl4ai_enabled,
            require_user_action=settings.personal_observer_require_user_action,
        )


@dataclass(frozen=True, slots=True)
class PersonalObserverResult:
    source_id: str
    final_url: str
    snapshot: DomSnapshot
    extraction: BrowserExtractionResult


class _PlaywrightPage(Protocol):
    @property
    def url(self) -> str: ...

    def goto(self, url: str, **kwargs: Any) -> object: ...
    def wait_for_load_state(self, state: str, **kwargs: Any) -> object: ...
    def wait_for_selector(self, selector: str, **kwargs: Any) -> object: ...
    def wait_for_timeout(self, timeout: float) -> object: ...
    def content(self) -> str: ...
    def title(self) -> str: ...
    def screenshot(self, *, path: str, full_page: bool) -> object: ...


class _PlaywrightContext(Protocol):
    def new_page(self) -> _PlaywrightPage: ...
    def close(self) -> object: ...


class _PlaywrightChromium(Protocol):
    def launch_persistent_context(
        self,
        *,
        user_data_dir: str,
        headless: bool,
        accept_downloads: bool,
    ) -> _PlaywrightContext: ...


class _PlaywrightRuntime(Protocol):
    chromium: _PlaywrightChromium


class _PlaywrightContextManager(Protocol):
    def __enter__(self) -> _PlaywrightRuntime: ...

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> bool | None: ...


class PersonalObserverRunner:
    def __init__(
        self,
        *,
        config: PersonalObserverConfig,
        specs: Sequence[RuAggregatorSpec] | None = None,
        clock: Callable[[], datetime] | None = None,
        playwright_context_factory: Callable[[], _PlaywrightContextManager] | None = None,
        crawl4ai_markdown_provider: Callable[[DomSnapshot], str | None] | None = None,
    ) -> None:
        self._config = config
        self._specs = tuple(specs or default_ru_aggregator_specs())
        self._spec_by_id = {spec.source_id: spec for spec in self._specs}
        self._clock = clock or (lambda: datetime.now(UTC))
        self._link_builder = RuClickoutLinkBuilder(self._specs)
        self._playwright_context_factory = playwright_context_factory
        self._crawl4ai_markdown_provider = crawl4ai_markdown_provider

    def observe(
        self,
        *,
        source_id: str,
        intent: SearchIntent,
        user_action: bool,
        fixture_html_path: Path | None = None,
        crawl4ai_markdown_fixture_path: Path | None = None,
        progress_callback: Callable[[ObservationStatus], None] | None = None,
        checkpoint_callback: Callable[[], OperatorCheckpointDecision] | None = None,
    ) -> PersonalObserverResult:
        spec = self._spec_by_id.get(source_id)
        if spec is None:
            raise PersonalObserverError(
                PersonalObserverErrorCode.SOURCE_NOT_FOUND,
                "source not found",
            )
        if not spec.browser_observation_allowed:
            raise PersonalObserverError(
                PersonalObserverErrorCode.SOURCE_NOT_OBSERVABLE,
                "source does not allow browser observation",
            )
        link = self._link_builder.build(spec, intent)
        self._validate_allowed_host(link.url)

        if fixture_html_path is not None:
            html = fixture_html_path.read_text(encoding="utf-8")
            snapshot = DomSnapshot.from_html(
                source_id=source_id,
                final_url=link.url,
                html=html,
                captured_at=self._clock(),
                title=f"fixture:{fixture_html_path.name}",
            )
        else:
            self._validate_live_run_allowed(user_action=user_action)
            snapshot = self._capture_with_playwright(
                source_id=source_id,
                url=link.url,
                progress_callback=progress_callback,
                checkpoint_callback=checkpoint_callback,
            )

        _report_runtime_status(progress_callback, ObservationStatus.PARSING)
        extractor = BrowserOfferParserPipeline(
            source_names={spec.source_id: spec.display_name},
            scrapling_enabled=self._config.scrapling_enabled,
            crawl4ai_diagnostics_enabled=self._config.crawl4ai_diagnostics_enabled,
            crawl4ai_markdown_provider=self._crawl4ai_markdown_provider_for(
                crawl4ai_markdown_fixture_path
            ),
        )
        extraction = extractor.extract(snapshot, intent)
        log_event(
            "parser_result",
            source=source_id,
            offers=len(extraction.offers),
            confidence=extraction.confidence,
            warnings=extraction.warnings,
        )
        if not extraction.offers:
            if "source_challenge" in _unprefixed_warnings(extraction.warnings):
                raise PersonalObserverError(
                    PersonalObserverErrorCode.SOURCE_CHALLENGE,
                    "source presented a challenge page",
                )
            if "selector_drift" in _unprefixed_warnings(extraction.warnings):
                raise PersonalObserverError(
                    PersonalObserverErrorCode.SELECTOR_DRIFT,
                    "parser selectors did not match the page",
                )
            raise PersonalObserverError(
                PersonalObserverErrorCode.PARSER_NO_OFFERS,
                "parser did not extract any offers",
            )
        return PersonalObserverResult(
            source_id=source_id,
            final_url=snapshot.final_url,
            snapshot=snapshot,
            extraction=extraction,
        )

    def _crawl4ai_markdown_provider_for(
        self,
        fixture_path: Path | None,
    ) -> Callable[[DomSnapshot], str | None] | None:
        if fixture_path is None:
            return self._crawl4ai_markdown_provider

        def read_fixture(_snapshot: DomSnapshot) -> str:
            return fixture_path.read_text(encoding="utf-8")

        return read_fixture

    def _validate_live_run_allowed(self, *, user_action: bool) -> None:
        if not self._config.enabled:
            raise PersonalObserverError(
                PersonalObserverErrorCode.OBSERVER_DISABLED,
                "personal observer is disabled",
            )
        if self._config.require_user_action and not user_action:
            raise PersonalObserverError(
                PersonalObserverErrorCode.OBSERVER_DISABLED,
                "personal observer requires explicit user action",
            )

    def _validate_allowed_host(self, url: str) -> None:
        host = (urlparse(url).hostname or "").lower()
        if host not in self._config.allowed_hosts:
            raise PersonalObserverError(
                PersonalObserverErrorCode.HOST_NOT_ALLOWED,
                f"host is not allowed: {host}",
            )

    def _capture_with_playwright(
        self,
        *,
        source_id: str,
        url: str,
        progress_callback: Callable[[ObservationStatus], None] | None,
        checkpoint_callback: Callable[[], OperatorCheckpointDecision] | None,
    ) -> DomSnapshot:
        playwright_context_factory: Callable[[], _PlaywrightContextManager]
        playwright_error_types: tuple[type[BaseException], ...]
        try:
            if self._playwright_context_factory is None:
                from playwright.sync_api import Error as PlaywrightError
                from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
                from playwright.sync_api import sync_playwright

                playwright_context_factory = cast(
                    Callable[[], _PlaywrightContextManager],
                    sync_playwright,
                )
                playwright_error_types = (
                    PlaywrightError,
                    PlaywrightTimeoutError,
                )
            else:
                playwright_context_factory = self._playwright_context_factory
                playwright_error_types = ()
        except ImportError as exc:
            raise PersonalObserverError(
                PersonalObserverErrorCode.PLAYWRIGHT_UNAVAILABLE,
                "playwright is not installed; sync the scraping dependency group",
            ) from exc

        profile_dir = self._config.profile_root / _safe_component(source_id)
        profile_dir.mkdir(parents=True, exist_ok=True)
        artifact_dir = self._config.artifact_root / _safe_component(source_id)
        artifact_name = ""
        try:
            with _ProfileLock(
                lock_path=profile_dir / ".flight_hunter_profile.lock",
                timeout_seconds=self._config.profile_lock_timeout_seconds,
                stale_seconds=self._config.profile_lock_stale_seconds,
            ):
                _report_runtime_status(progress_callback, ObservationStatus.OPENING_BROWSER)
                with playwright_context_factory() as playwright:
                    context = playwright.chromium.launch_persistent_context(
                        user_data_dir=str(profile_dir),
                        headless=self._config.headless,
                        accept_downloads=False,
                    )
                    try:
                        page = context.new_page()
                        page.goto(
                            url,
                            wait_until="domcontentloaded",
                            timeout=self._config.navigation_timeout_ms,
                        )
                        self._wait_for_operator_checkpoint(
                            page,
                            progress_callback=progress_callback,
                            checkpoint_callback=checkpoint_callback,
                        )
                        _report_runtime_status(progress_callback, ObservationStatus.CAPTURING_DOM)
                        self._wait_for_runtime_readiness(page)
                        page.wait_for_timeout(1500)
                        final_url = page.url
                        self._validate_allowed_host(final_url)
                        html = page.content()
                        title = page.title()
                        captured_at = self._clock()
                        artifact_name = _timestamp(captured_at)
                        screenshot_path = None
                        if self._config.save_screenshots:
                            artifact_dir.mkdir(parents=True, exist_ok=True)
                            screenshot_path = str(artifact_dir / f"{artifact_name}.png")
                            page.screenshot(path=screenshot_path, full_page=True)
                    finally:
                        context.close()
        except _ProfileLockError as exc:
            raise PersonalObserverError(
                PersonalObserverErrorCode.PROFILE_LOCKED,
                "browser profile is already locked by another worker",
            ) from exc
        except playwright_error_types as exc:
            raise PersonalObserverError(
                PersonalObserverErrorCode.NAVIGATION_FAILED,
                "browser navigation failed",
            ) from exc

        sanitized_dom_path = None
        if self._config.save_dom_fixtures:
            artifact_dir.mkdir(parents=True, exist_ok=True)
            fixture_path = artifact_dir / f"{artifact_name}.html"
            fixture_path.write_text(sanitize_dom_html_for_fixture(html), encoding="utf-8")
            sanitized_dom_path = str(fixture_path)

        snapshot = DomSnapshot.from_html(
            source_id=source_id,
            final_url=final_url,
            title=title,
            html=html,
            captured_at=captured_at,
            screenshot_path=screenshot_path,
        )
        if self._should_write_runtime_manifest():
            _write_runtime_manifest(
                artifact_dir=artifact_dir,
                artifact_name=artifact_name,
                snapshot=snapshot,
                sanitized_dom_path=sanitized_dom_path,
            )
        return snapshot

    def _should_write_runtime_manifest(self) -> bool:
        return (
            self._config.save_runtime_manifests
            or self._config.save_dom_fixtures
            or self._config.save_screenshots
        )

    def _wait_for_operator_checkpoint(
        self,
        page: _PlaywrightPage,
        *,
        progress_callback: Callable[[ObservationStatus], None] | None,
        checkpoint_callback: Callable[[], OperatorCheckpointDecision] | None,
    ) -> None:
        checkpoint_ms = self._config.manual_checkpoint_seconds * 1000
        if checkpoint_ms <= 0 or self._config.headless:
            return
        _report_runtime_status(progress_callback, ObservationStatus.WAITING_FOR_USER)
        if checkpoint_callback is None:
            page.wait_for_timeout(checkpoint_ms)
            return
        remaining_ms = checkpoint_ms
        poll_ms = min(1000, checkpoint_ms)
        while remaining_ms > 0:
            decision = checkpoint_callback()
            if decision == OperatorCheckpointDecision.RESUME:
                return
            if decision == OperatorCheckpointDecision.ABORT:
                raise PersonalObserverError(
                    PersonalObserverErrorCode.OPERATOR_ABORTED,
                    "operator aborted the browser checkpoint",
                )
            page.wait_for_timeout(poll_ms)
            remaining_ms -= poll_ms
        if checkpoint_callback() == OperatorCheckpointDecision.ABORT:
            raise PersonalObserverError(
                PersonalObserverErrorCode.OPERATOR_ABORTED,
                "operator aborted the browser checkpoint",
            )

    def _wait_for_runtime_readiness(self, page: _PlaywrightPage) -> None:
        if self._config.wait_for_network_idle:
            page.wait_for_load_state(
                "networkidle",
                timeout=self._config.ready_timeout_ms,
            )
        if self._config.ready_selector is not None:
            page.wait_for_selector(
                self._config.ready_selector,
                timeout=self._config.ready_timeout_ms,
            )


def _timestamp(value: datetime) -> str:
    return value.strftime("%Y%m%dT%H%M%SZ")


def _report_runtime_status(
    progress_callback: Callable[[ObservationStatus], None] | None,
    status: ObservationStatus,
) -> None:
    if progress_callback is not None:
        progress_callback(status)


def _safe_component(value: str) -> str:
    cleaned = "".join(
        character if character.isalnum() or character in {"-", "_"} else "_" for character in value
    )
    return cleaned.strip("._") or "source"


class _ProfileLockError(RuntimeError):
    """Raised when a browser profile lock cannot be acquired."""


class _ProfileLock:
    def __init__(self, *, lock_path: Path, timeout_seconds: int, stale_seconds: int) -> None:
        self._lock_path = lock_path
        self._timeout_seconds = max(0, timeout_seconds)
        self._stale_seconds = max(0, stale_seconds)
        self._fd: int | None = None

    def __enter__(self) -> _ProfileLock:
        self._acquire()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> bool | None:
        self._release()
        return None

    def _acquire(self) -> None:
        self._lock_path.parent.mkdir(parents=True, exist_ok=True)
        deadline = time.monotonic() + self._timeout_seconds
        while True:
            try:
                self._fd = os.open(
                    str(self._lock_path),
                    os.O_CREAT | os.O_EXCL | os.O_WRONLY,
                    0o600,
                )
                payload = json.dumps(
                    {
                        "pid": os.getpid(),
                        "acquired_at": datetime.now(UTC).isoformat(),
                    },
                    sort_keys=True,
                )
                os.write(self._fd, payload.encode("utf-8"))
                return
            except FileExistsError as exc:
                if self._remove_stale_lock():
                    continue
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise _ProfileLockError("browser profile lock is held") from exc
                time.sleep(min(0.25, remaining))
            except OSError as exc:
                raise _ProfileLockError("browser profile lock cannot be acquired") from exc

    def _remove_stale_lock(self) -> bool:
        if self._stale_seconds <= 0:
            return False
        try:
            age_seconds = time.time() - self._lock_path.stat().st_mtime
        except FileNotFoundError:
            return True
        if age_seconds < self._stale_seconds:
            return False
        try:
            self._lock_path.unlink()
            return True
        except FileNotFoundError:
            return True
        except OSError:
            return False

    def _release(self) -> None:
        if self._fd is None:
            return
        os.close(self._fd)
        self._fd = None
        try:
            self._lock_path.unlink()
        except FileNotFoundError:
            return


def _write_runtime_manifest(
    *,
    artifact_dir: Path,
    artifact_name: str,
    snapshot: DomSnapshot,
    sanitized_dom_path: str | None,
) -> None:
    artifact_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "manifest_version": "personal_observer_runtime_manifest:2026-06-29",
        "source_id": snapshot.source_id,
        "captured_at": snapshot.captured_at.isoformat(),
        "final_url_redacted": _redact_url(snapshot.final_url),
        "final_url_query_or_fragment_redacted": _url_has_query_or_fragment(snapshot.final_url),
        "title_sha256": _sha256_text(snapshot.title) if snapshot.title else None,
        "html_sha256": snapshot.html_hash,
        "visible_text_sha256": snapshot.visible_text_hash,
        "sanitized_dom_path": sanitized_dom_path,
        "screenshot_path": snapshot.screenshot_path,
        "raw_html_stored": False,
    }
    (artifact_dir / f"{artifact_name}.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )


def _redact_url(url: str) -> str:
    parsed = urlsplit(url)
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, "", ""))


def _url_has_query_or_fragment(url: str) -> bool:
    parsed = urlsplit(url)
    return bool(parsed.query or parsed.fragment)


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _unprefixed_warnings(warnings: Sequence[str]) -> tuple[str, ...]:
    return tuple(warning.rsplit(":", 1)[-1] for warning in warnings)
