from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from flight_hunter.ops.browser_smoke import format_browser_smoke_result, run_browser_smoke

NOW = datetime(2026, 6, 29, 23, 0, tzinfo=UTC)


def test_browser_smoke_runs_persistent_chromium_check(tmp_path: Path) -> None:
    context = FakeContext(FakePage(text="ready"))
    runtime = FakeRuntime(context)

    result = run_browser_smoke(
        playwright_context_factory=lambda: FakeContextManager(runtime),
        profile_root=tmp_path,
        clock=lambda: NOW,
    )

    rendered = format_browser_smoke_result(result)

    assert result.ok is True
    assert result.code == "ok"
    assert result.checked_at == NOW
    assert context.closed is True
    assert runtime.chromium.launch_kwargs is not None
    assert runtime.chromium.launch_kwargs["headless"] is True
    assert runtime.chromium.launch_kwargs["accept_downloads"] is False
    assert str(runtime.chromium.launch_kwargs["user_data_dir"]).endswith("browser-smoke-profile")
    assert "secret" not in rendered.lower()


def test_browser_smoke_reports_unexpected_local_dom(tmp_path: Path) -> None:
    context = FakeContext(FakePage(text="not-ready"))
    runtime = FakeRuntime(context)

    result = run_browser_smoke(
        playwright_context_factory=lambda: FakeContextManager(runtime),
        profile_root=tmp_path,
        clock=lambda: NOW,
    )

    assert result.ok is False
    assert result.code == "browser_smoke_unexpected_dom"
    assert context.closed is True


def test_browser_smoke_classifies_runtime_failures(tmp_path: Path) -> None:
    result = run_browser_smoke(
        playwright_context_factory=lambda: FailingContextManager(),
        profile_root=tmp_path,
        clock=lambda: NOW,
    )

    assert result.ok is False
    assert result.code == "browser_smoke_failed"
    assert result.message == "RuntimeError"


class FakeLocator:
    def __init__(self, text: str) -> None:
        self._text = text

    def inner_text(self) -> str:
        return self._text


class FakePage:
    def __init__(self, *, text: str) -> None:
        self._text = text
        self.set_content_calls: list[tuple[str, object]] = []

    def set_content(self, html: str, **kwargs: object) -> None:
        self.set_content_calls.append((html, kwargs))

    def locator(self, selector: str) -> FakeLocator:
        assert selector == "#flight-hunter-browser-smoke"
        return FakeLocator(self._text)


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


class FakeRuntime:
    def __init__(self, context: FakeContext) -> None:
        self.chromium = FakeChromium(context)


class FakeContextManager:
    def __init__(self, runtime: FakeRuntime) -> None:
        self._runtime = runtime

    def __enter__(self) -> FakeRuntime:
        return self._runtime

    def __exit__(self, *args: object) -> None:
        return None


class FailingContextManager:
    def __enter__(self) -> FakeRuntime:
        raise RuntimeError("browser boom")

    def __exit__(self, *args: object) -> None:
        return None
