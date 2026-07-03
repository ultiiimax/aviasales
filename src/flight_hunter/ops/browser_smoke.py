from __future__ import annotations

import argparse
import json
from collections.abc import Callable
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from types import TracebackType
from typing import Any, Protocol, cast


@dataclass(frozen=True, slots=True)
class BrowserSmokeResult:
    ok: bool
    code: str
    checked_at: datetime
    browser: str = "chromium"
    message: str | None = None


class _Locator(Protocol):
    def inner_text(self) -> str: ...


class _Page(Protocol):
    def set_content(self, html: str, **kwargs: Any) -> object: ...
    def locator(self, selector: str) -> _Locator: ...


class _Context(Protocol):
    def new_page(self) -> _Page: ...
    def close(self) -> object: ...


class _Chromium(Protocol):
    def launch_persistent_context(
        self,
        *,
        user_data_dir: str,
        headless: bool,
        accept_downloads: bool,
    ) -> _Context: ...


class _Runtime(Protocol):
    chromium: _Chromium


class _ContextManager(Protocol):
    def __enter__(self) -> _Runtime: ...

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> bool | None: ...


def run_browser_smoke(
    *,
    playwright_context_factory: Callable[[], _ContextManager] | None = None,
    profile_root: Path | None = None,
    clock: Callable[[], datetime] | None = None,
) -> BrowserSmokeResult:
    now = clock or (lambda: datetime.now(UTC))
    context_factory: Callable[[], _ContextManager]
    browser_error_types: tuple[type[BaseException], ...]
    try:
        if playwright_context_factory is None:
            from playwright.sync_api import Error as PlaywrightError
            from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
            from playwright.sync_api import sync_playwright

            context_factory = cast(Callable[[], _ContextManager], sync_playwright)
            browser_error_types = (PlaywrightError, PlaywrightTimeoutError)
        else:
            context_factory = playwright_context_factory
            browser_error_types = ()
    except ImportError:
        return BrowserSmokeResult(
            ok=False,
            code="playwright_unavailable",
            checked_at=now(),
            message="sync the scraping dependency group and install chromium",
        )

    try:
        observed_text = _run_browser_check(
            context_factory=context_factory,
            profile_root=profile_root,
        )
    except browser_error_types as exc:
        return BrowserSmokeResult(
            ok=False,
            code="browser_runtime_unavailable",
            checked_at=now(),
            message=exc.__class__.__name__,
        )
    except Exception as exc:  # process boundary: classify local runtime failures.
        return BrowserSmokeResult(
            ok=False,
            code="browser_smoke_failed",
            checked_at=now(),
            message=exc.__class__.__name__,
        )

    if observed_text != "ready":
        return BrowserSmokeResult(
            ok=False,
            code="browser_smoke_unexpected_dom",
            checked_at=now(),
            message="expected ready marker was not visible",
        )
    return BrowserSmokeResult(ok=True, code="ok", checked_at=now())


def format_browser_smoke_result(result: BrowserSmokeResult) -> str:
    payload = asdict(result)
    payload["checked_at"] = result.checked_at.isoformat()
    ordered_payload = {
        "ok": payload["ok"],
        "code": payload["code"],
        "checked_at": payload["checked_at"],
        "browser": payload["browser"],
        "message": payload["message"],
    }
    return json.dumps(ordered_payload, ensure_ascii=False, indent=2)


def _run_browser_check(
    *,
    context_factory: Callable[[], _ContextManager],
    profile_root: Path | None,
) -> str:
    if profile_root is not None:
        profile_root.mkdir(parents=True, exist_ok=True)
        return _run_browser_check_with_profile(
            context_factory=context_factory,
            profile_dir=profile_root / "browser-smoke-profile",
        )
    with TemporaryDirectory(prefix="flight-hunter-browser-smoke-") as temp_dir:
        return _run_browser_check_with_profile(
            context_factory=context_factory,
            profile_dir=Path(temp_dir) / "profile",
        )


def _run_browser_check_with_profile(
    *,
    context_factory: Callable[[], _ContextManager],
    profile_dir: Path,
) -> str:
    profile_dir.mkdir(parents=True, exist_ok=True)
    with context_factory() as runtime:
        context = runtime.chromium.launch_persistent_context(
            user_data_dir=str(profile_dir),
            headless=True,
            accept_downloads=False,
        )
        try:
            page = context.new_page()
            page.set_content(
                "<!doctype html><title>Flight Hunter smoke</title>"
                '<div id="flight-hunter-browser-smoke">ready</div>',
                wait_until="domcontentloaded",
            )
            return page.locator("#flight-hunter-browser-smoke").inner_text()
        finally:
            context.close()


def main() -> int:
    parser = argparse.ArgumentParser(
        prog="flight-hunter-browser-smoke",
        description="Run a local Playwright Chromium smoke check without live websites.",
    )
    parser.add_argument("--profile-root", type=Path, default=None)
    args = parser.parse_args()
    result = run_browser_smoke(profile_root=args.profile_root)
    print(format_browser_smoke_result(result))
    return 0 if result.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
