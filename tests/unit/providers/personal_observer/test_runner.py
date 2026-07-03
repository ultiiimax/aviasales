from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from pathlib import Path

import pytest

from flight_hunter.browser.html_extractor import DomSnapshot
from flight_hunter.domain.money import Money
from flight_hunter.domain.observation import ObservationStatus, OperatorCheckpointDecision
from flight_hunter.domain.offers import SearchIntent
from flight_hunter.domain.search_results import Confidence
from flight_hunter.providers.personal_observer.runner import (
    PersonalObserverConfig,
    PersonalObserverError,
    PersonalObserverErrorCode,
    PersonalObserverRunner,
)

NOW = datetime(2026, 6, 29, 15, 0, tzinfo=UTC)
FIXTURE = Path("tests/fixtures/browser/tutu/search_result_sanitized.html")
SOURCE_SPECIFIC_FIXTURE = Path("tests/fixtures/browser/tutu/search_result_source_specific.html")
SOURCE_CHALLENGE_FIXTURE = Path(
    "tests/fixtures/browser/tutu/search_result_source_specific_challenge.html"
)


def test_runner_observes_fixture_without_live_browser_enabled(tmp_path: Path, monkeypatch) -> None:
    events: list[dict[str, object]] = []
    monkeypatch.setattr(
        "flight_hunter.providers.personal_observer.runner.log_event",
        lambda event, **fields: events.append({"event": event, **fields}),
    )
    runner = PersonalObserverRunner(
        config=_config(tmp_path, enabled=False),
        clock=lambda: NOW,
    )

    result = runner.observe(
        source_id="tutu",
        intent=_intent(),
        user_action=True,
        fixture_html_path=SOURCE_SPECIFIC_FIXTURE,
    )

    assert result.source_id == "tutu"
    assert result.extraction.confidence == Confidence.MEDIUM
    assert result.extraction.offers[0].total_price == Money(1_842_000, "RUB")
    assert result.extraction.offers[0].observed_at == NOW
    payload = events[0]
    assert payload["source"] == "tutu"
    assert payload["offers"] == 1
    assert payload["confidence"] == "medium"
    assert payload["warnings"] == ("parser_stage:tutu",)
    log_text = str(payload)
    assert "https://www.tutu.ru" not in log_text
    assert "<html" not in log_text.lower()


def test_runner_selects_source_specific_tutu_parser(tmp_path: Path) -> None:
    runner = PersonalObserverRunner(
        config=_config(tmp_path, enabled=False),
        clock=lambda: NOW,
    )

    result = runner.observe(
        source_id="tutu",
        intent=_intent(),
        user_action=True,
        fixture_html_path=SOURCE_SPECIFIC_FIXTURE,
    )

    assert result.extraction.offers[0].provider_offer_id == "tutu-realistic-1"
    assert result.extraction.offers[0].parser_version.startswith("tutu:")


def test_runner_falls_back_to_generic_parser_after_source_specific_drift(tmp_path: Path) -> None:
    runner = PersonalObserverRunner(
        config=_config(tmp_path, enabled=False, scrapling_enabled=False),
        clock=lambda: NOW,
    )

    result = runner.observe(
        source_id="tutu",
        intent=_intent(),
        user_action=True,
        fixture_html_path=FIXTURE,
    )

    assert result.extraction.offers[0].provider_offer_id == "tutu-card-1"
    assert result.extraction.offers[0].parser_version.startswith("generic_ru_html_fixture:")
    assert "tutu:selector_drift" in result.extraction.warnings
    assert "parser_stage:generic_html" in result.extraction.warnings


def test_runner_reports_source_challenge_as_typed_error(tmp_path: Path) -> None:
    runner = PersonalObserverRunner(
        config=_config(tmp_path, enabled=False, scrapling_enabled=False),
        clock=lambda: NOW,
    )

    with pytest.raises(PersonalObserverError) as exc:
        runner.observe(
            source_id="tutu",
            intent=_intent(),
            user_action=True,
            fixture_html_path=SOURCE_CHALLENGE_FIXTURE,
        )

    assert exc.value.code == PersonalObserverErrorCode.SOURCE_CHALLENGE


def test_runner_rejects_live_browser_when_observer_disabled(tmp_path: Path) -> None:
    runner = PersonalObserverRunner(
        config=_config(tmp_path, enabled=False),
        clock=lambda: NOW,
    )

    with pytest.raises(PersonalObserverError) as exc:
        runner.observe(
            source_id="tutu",
            intent=_intent(),
            user_action=True,
            fixture_html_path=None,
        )

    assert exc.value.code == PersonalObserverErrorCode.OBSERVER_DISABLED


def test_runner_rejects_sources_without_browser_observation_permission(tmp_path: Path) -> None:
    runner = PersonalObserverRunner(config=_config(tmp_path), clock=lambda: NOW)

    with pytest.raises(PersonalObserverError) as exc:
        runner.observe(
            source_id="aviasales_clickout",
            intent=_intent(),
            user_action=True,
            fixture_html_path=FIXTURE,
        )

    assert exc.value.code == PersonalObserverErrorCode.SOURCE_NOT_OBSERVABLE


def test_runner_rejects_hosts_outside_allowlist(tmp_path: Path) -> None:
    runner = PersonalObserverRunner(
        config=_config(tmp_path, allowed_hosts=("travel.yandex.ru",)),
        clock=lambda: NOW,
    )

    with pytest.raises(PersonalObserverError) as exc:
        runner.observe(
            source_id="tutu",
            intent=_intent(),
            user_action=True,
            fixture_html_path=FIXTURE,
        )

    assert exc.value.code == PersonalObserverErrorCode.HOST_NOT_ALLOWED


def test_runner_allows_configured_host_with_port(tmp_path: Path) -> None:
    runner = PersonalObserverRunner(
        config=_config(tmp_path, allowed_hosts=("www.tutu.ru",)),
        clock=lambda: NOW,
    )

    runner._validate_allowed_host("https://www.tutu.ru:443/avia/")


def test_runner_applies_playwright_runtime_wait_controls(tmp_path: Path) -> None:
    page = FakePage(
        html=SOURCE_SPECIFIC_FIXTURE.read_text(encoding="utf-8"),
        final_url="https://www.tutu.ru/avia/",
        title="Tutu fixture",
    )
    context = FakeContext(page)
    runtime = FakePlaywrightRuntime(context)
    phases: list[ObservationStatus] = []
    runner = PersonalObserverRunner(
        config=_config(
            tmp_path,
            navigation_timeout_ms=12_345,
            ready_selector="[data-flight-card]",
            ready_timeout_ms=2_500,
            wait_for_network_idle=True,
            manual_checkpoint_seconds=3,
        ),
        clock=lambda: NOW,
        playwright_context_factory=lambda: FakePlaywrightContextManager(runtime),
    )

    result = runner.observe(
        source_id="tutu",
        intent=_intent(),
        user_action=True,
        fixture_html_path=None,
        progress_callback=phases.append,
    )

    assert result.extraction.offers[0].provider_offer_id == "tutu-realistic-1"
    assert phases == [
        ObservationStatus.OPENING_BROWSER,
        ObservationStatus.WAITING_FOR_USER,
        ObservationStatus.CAPTURING_DOM,
        ObservationStatus.PARSING,
    ]
    assert context.closed is True
    assert runtime.chromium.launch_kwargs is not None
    assert runtime.chromium.launch_kwargs["user_data_dir"].endswith("profiles\\tutu") or (
        runtime.chromium.launch_kwargs["user_data_dir"].endswith("profiles/tutu")
    )
    assert runtime.chromium.launch_kwargs["headless"] is False
    assert page.calls[:5] == [
        ("goto", "https://www.tutu.ru/", 12_345),
        ("wait_for_timeout", 3000),
        ("wait_for_load_state", "networkidle", 2_500),
        ("wait_for_selector", "[data-flight-card]", 2_500),
        ("wait_for_timeout", 1500),
    ]


def test_runner_rejects_active_profile_lock_without_launching_browser(tmp_path: Path) -> None:
    page = FakePage(
        html=SOURCE_SPECIFIC_FIXTURE.read_text(encoding="utf-8"),
        final_url="https://www.tutu.ru/avia/",
        title="Tutu fixture",
    )
    context = FakeContext(page)
    runtime = FakePlaywrightRuntime(context)
    profile_dir = tmp_path / "profiles" / "tutu"
    profile_dir.mkdir(parents=True)
    lock_path = profile_dir / ".flight_hunter_profile.lock"
    lock_path.write_text('{"pid": 12345}', encoding="utf-8")
    runner = PersonalObserverRunner(
        config=_config(tmp_path, profile_lock_stale_seconds=3600),
        clock=lambda: NOW,
        playwright_context_factory=lambda: FakePlaywrightContextManager(runtime),
    )

    with pytest.raises(PersonalObserverError) as exc:
        runner.observe(
            source_id="tutu",
            intent=_intent(),
            user_action=True,
            fixture_html_path=None,
        )

    assert exc.value.code == PersonalObserverErrorCode.PROFILE_LOCKED
    assert runtime.chromium.launch_kwargs is None
    assert lock_path.exists()
    assert context.closed is False


def test_runner_replaces_stale_profile_lock_and_releases_after_success(tmp_path: Path) -> None:
    page = FakePage(
        html=SOURCE_SPECIFIC_FIXTURE.read_text(encoding="utf-8"),
        final_url="https://www.tutu.ru/avia/",
        title="Tutu fixture",
    )
    profile_dir = tmp_path / "profiles" / "tutu"
    profile_dir.mkdir(parents=True)
    lock_path = profile_dir / ".flight_hunter_profile.lock"
    lock_path.write_text('{"pid": 12345}', encoding="utf-8")
    stale_time = 1_600_000_000
    os.utime(lock_path, (stale_time, stale_time))
    runner = PersonalObserverRunner(
        config=_config(tmp_path, profile_lock_stale_seconds=1),
        clock=lambda: NOW,
        playwright_context_factory=lambda: FakePlaywrightContextManager(
            FakePlaywrightRuntime(FakeContext(page))
        ),
    )

    result = runner.observe(
        source_id="tutu",
        intent=_intent(),
        user_action=True,
        fixture_html_path=None,
    )

    assert result.extraction.offers[0].provider_offer_id == "tutu-realistic-1"
    assert not lock_path.exists()


def test_runner_saves_only_sanitized_dom_fixture_artifact(tmp_path: Path) -> None:
    html = (
        SOURCE_SPECIFIC_FIXTURE.read_text(encoding="utf-8")
        + """
        <script>window.sessionToken = "secret-session-token";</script>
        <form action="https://www.tutu.ru/pay?token=secret">
          <input name="csrf_token" value="secret-csrf">
        </form>
        """
    )
    page = FakePage(
        html=html,
        final_url="https://www.tutu.ru/avia/",
        title="Tutu fixture",
    )
    runner = PersonalObserverRunner(
        config=_config(tmp_path, save_dom_fixtures=True),
        clock=lambda: NOW,
        playwright_context_factory=lambda: FakePlaywrightContextManager(
            FakePlaywrightRuntime(FakeContext(page))
        ),
    )

    result = runner.observe(
        source_id="tutu",
        intent=_intent(),
        user_action=True,
        fixture_html_path=None,
    )

    assert result.extraction.offers[0].provider_offer_id == "tutu-realistic-1"
    artifacts = tuple((tmp_path / "artifacts" / "tutu").glob("*.html"))
    assert len(artifacts) == 1
    saved = artifacts[0].read_text(encoding="utf-8")
    assert "<script" not in saved
    assert "secret-session-token" not in saved
    assert "secret-csrf" not in saved
    assert "token=secret" not in saved
    assert "tutu-realistic-1" in saved


def test_runner_writes_redacted_runtime_manifest_for_diagnostic_artifacts(
    tmp_path: Path,
) -> None:
    html = (
        SOURCE_SPECIFIC_FIXTURE.read_text(encoding="utf-8")
        + """
        <a href="https://www.tutu.ru/pay?session=secret-session-token">pay</a>
        <input name="auth_token" value="secret-auth-token">
        """
    )
    page = FakePage(
        html=html,
        final_url="https://www.tutu.ru/avia/results?session=secret-session-token#checkout",
        title="Tutu secret title",
    )
    runner = PersonalObserverRunner(
        config=_config(
            tmp_path,
            save_dom_fixtures=True,
            save_screenshots=True,
            save_runtime_manifests=True,
        ),
        clock=lambda: NOW,
        playwright_context_factory=lambda: FakePlaywrightContextManager(
            FakePlaywrightRuntime(FakeContext(page))
        ),
    )

    result = runner.observe(
        source_id="tutu",
        intent=_intent(),
        user_action=True,
        fixture_html_path=None,
    )

    manifests = tuple((tmp_path / "artifacts" / "tutu").glob("*.json"))
    assert len(manifests) == 1
    payload = json.loads(manifests[0].read_text(encoding="utf-8"))
    assert payload["source_id"] == "tutu"
    assert payload["final_url_redacted"] == "https://www.tutu.ru/avia/results"
    assert payload["final_url_query_or_fragment_redacted"] is True
    assert payload["html_sha256"] == result.snapshot.html_hash
    assert payload["visible_text_sha256"] == result.snapshot.visible_text_hash
    assert payload["raw_html_stored"] is False
    assert payload["sanitized_dom_path"].endswith(".html")
    assert payload["screenshot_path"].endswith(".png")
    assert "title" not in payload

    manifest_text = manifests[0].read_text(encoding="utf-8")
    assert "secret-session-token" not in manifest_text
    assert "secret-auth-token" not in manifest_text
    assert "Tutu secret title" not in manifest_text
    assert ("screenshot", payload["screenshot_path"], True) in page.calls


def test_runner_skips_manual_checkpoint_in_headless_mode(tmp_path: Path) -> None:
    page = FakePage(
        html=SOURCE_SPECIFIC_FIXTURE.read_text(encoding="utf-8"),
        final_url="https://www.tutu.ru/avia/",
        title="Tutu fixture",
    )
    runtime = FakePlaywrightRuntime(FakeContext(page))
    runner = PersonalObserverRunner(
        config=_config(
            tmp_path,
            headless=True,
            manual_checkpoint_seconds=3,
        ),
        clock=lambda: NOW,
        playwright_context_factory=lambda: FakePlaywrightContextManager(runtime),
    )

    runner.observe(
        source_id="tutu",
        intent=_intent(),
        user_action=True,
        fixture_html_path=None,
    )

    assert ("wait_for_timeout", 3000) not in page.calls


def test_runner_manual_checkpoint_can_resume_from_operator_signal(tmp_path: Path) -> None:
    page = FakePage(
        html=SOURCE_SPECIFIC_FIXTURE.read_text(encoding="utf-8"),
        final_url="https://www.tutu.ru/avia/",
        title="Tutu fixture",
    )
    runtime = FakePlaywrightRuntime(FakeContext(page))
    decisions = iter((OperatorCheckpointDecision.WAITING, OperatorCheckpointDecision.RESUME))
    runner = PersonalObserverRunner(
        config=_config(tmp_path, manual_checkpoint_seconds=5),
        clock=lambda: NOW,
        playwright_context_factory=lambda: FakePlaywrightContextManager(runtime),
    )

    result = runner.observe(
        source_id="tutu",
        intent=_intent(),
        user_action=True,
        fixture_html_path=None,
        checkpoint_callback=lambda: next(decisions),
    )

    assert result.extraction.offers[0].provider_offer_id == "tutu-realistic-1"
    assert ("wait_for_timeout", 5000) not in page.calls
    assert page.calls[:3] == [
        ("goto", "https://www.tutu.ru/", 45_000),
        ("wait_for_timeout", 1000),
        ("wait_for_timeout", 1500),
    ]


def test_runner_manual_checkpoint_abort_closes_context(tmp_path: Path) -> None:
    page = FakePage(
        html=SOURCE_SPECIFIC_FIXTURE.read_text(encoding="utf-8"),
        final_url="https://www.tutu.ru/avia/",
        title="Tutu fixture",
    )
    context = FakeContext(page)
    runner = PersonalObserverRunner(
        config=_config(tmp_path, manual_checkpoint_seconds=5),
        clock=lambda: NOW,
        playwright_context_factory=lambda: FakePlaywrightContextManager(
            FakePlaywrightRuntime(context)
        ),
    )

    with pytest.raises(PersonalObserverError) as exc:
        runner.observe(
            source_id="tutu",
            intent=_intent(),
            user_action=True,
            fixture_html_path=None,
            checkpoint_callback=lambda: OperatorCheckpointDecision.ABORT,
        )

    assert exc.value.code == PersonalObserverErrorCode.OPERATOR_ABORTED
    assert context.closed is True


def test_runner_passes_explicit_crawl4ai_markdown_provider(tmp_path: Path) -> None:
    no_offer_fixture = tmp_path / "no-offers.html"
    no_offer_fixture.write_text(
        "<html><body>No structured cards here.</body></html>",
        encoding="utf-8",
    )
    seen_snapshots: list[str] = []

    def markdown_provider(snapshot: DomSnapshot) -> str:
        seen_snapshots.append(snapshot.__class__.__name__)
        return "Manual diagnostic markdown saw MOW IST around 24 500 RUB."

    runner = PersonalObserverRunner(
        config=_config(tmp_path, enabled=False, crawl4ai_diagnostics_enabled=True),
        clock=lambda: NOW,
        crawl4ai_markdown_provider=markdown_provider,
    )

    with pytest.raises(PersonalObserverError) as exc:
        runner.observe(
            source_id="tutu",
            intent=_intent(),
            user_action=True,
            fixture_html_path=no_offer_fixture,
        )

    assert exc.value.code == PersonalObserverErrorCode.SELECTOR_DRIFT
    assert seen_snapshots == ["DomSnapshot"]


def _intent() -> SearchIntent:
    return SearchIntent(
        origin="MOW",
        destination="IST",
        departure_date="2026-09-10",
        return_date="2026-09-20",
        passengers=1,
        currency="RUB",
    )


def _config(
    tmp_path: Path,
    *,
    enabled: bool = True,
    headless: bool = False,
    allowed_hosts: tuple[str, ...] = ("www.tutu.ru", "tutu.ru", "avia.tutu.ru"),
    navigation_timeout_ms: int = 45_000,
    ready_selector: str | None = None,
    ready_timeout_ms: int = 15_000,
    wait_for_network_idle: bool = False,
    manual_checkpoint_seconds: int = 0,
    profile_lock_timeout_seconds: int = 0,
    profile_lock_stale_seconds: int = 3_600,
    scrapling_enabled: bool = True,
    crawl4ai_diagnostics_enabled: bool = False,
    save_dom_fixtures: bool = False,
    save_screenshots: bool = False,
    save_runtime_manifests: bool = False,
) -> PersonalObserverConfig:
    return PersonalObserverConfig(
        enabled=enabled,
        headless=headless,
        profile_root=tmp_path / "profiles",
        artifact_root=tmp_path / "artifacts",
        save_dom_fixtures=save_dom_fixtures,
        save_screenshots=save_screenshots,
        navigation_timeout_ms=navigation_timeout_ms,
        ready_selector=ready_selector,
        ready_timeout_ms=ready_timeout_ms,
        wait_for_network_idle=wait_for_network_idle,
        manual_checkpoint_seconds=manual_checkpoint_seconds,
        allowed_hosts=allowed_hosts,
        profile_lock_timeout_seconds=profile_lock_timeout_seconds,
        profile_lock_stale_seconds=profile_lock_stale_seconds,
        scrapling_enabled=scrapling_enabled,
        crawl4ai_diagnostics_enabled=crawl4ai_diagnostics_enabled,
        save_runtime_manifests=save_runtime_manifests,
    )


class FakePage:
    def __init__(self, *, html: str, final_url: str, title: str) -> None:
        self._html = html
        self._title = title
        self._url = final_url
        self.calls: list[tuple[object, ...]] = []

    @property
    def url(self) -> str:
        return self._url

    def goto(self, url: str, *, wait_until: str, timeout: int) -> None:
        self.calls.append(("goto", url, timeout))
        assert wait_until == "domcontentloaded"

    def wait_for_load_state(self, state: str, *, timeout: int) -> None:
        self.calls.append(("wait_for_load_state", state, timeout))

    def wait_for_selector(self, selector: str, *, timeout: int) -> None:
        self.calls.append(("wait_for_selector", selector, timeout))

    def wait_for_timeout(self, timeout: float) -> None:
        self.calls.append(("wait_for_timeout", int(timeout)))

    def content(self) -> str:
        return self._html

    def title(self) -> str:
        return self._title

    def screenshot(self, *, path: str, full_page: bool) -> None:
        self.calls.append(("screenshot", path, full_page))


class FakeContext:
    def __init__(self, page: FakePage) -> None:
        self._page = page
        self.closed = False

    def new_page(self) -> FakePage:
        return self._page

    def close(self) -> None:
        self.closed = True


class FakeChromium:
    def __init__(self, context: FakeContext) -> None:
        self._context = context
        self.launch_kwargs: dict[str, object] | None = None

    def launch_persistent_context(
        self,
        *,
        user_data_dir: str,
        headless: bool,
        accept_downloads: bool,
    ) -> FakeContext:
        self.launch_kwargs = {
            "user_data_dir": user_data_dir,
            "headless": headless,
            "accept_downloads": accept_downloads,
        }
        return self._context


class FakePlaywrightRuntime:
    def __init__(self, context: FakeContext) -> None:
        self.chromium = FakeChromium(context)


class FakePlaywrightContextManager:
    def __init__(self, runtime: FakePlaywrightRuntime) -> None:
        self._runtime = runtime

    def __enter__(self) -> FakePlaywrightRuntime:
        return self._runtime

    def __exit__(self, *args: object) -> None:
        return None
