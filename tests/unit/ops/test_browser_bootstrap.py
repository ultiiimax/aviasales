from __future__ import annotations

from subprocess import CompletedProcess

from flight_hunter.ops.browser_bootstrap import browser_bootstrap


class RecordingRunner:
    def __init__(self, return_codes: list[int]) -> None:
        self._return_codes = list(return_codes)
        self.calls: list[tuple[tuple[str, ...], bool]] = []

    def __call__(
        self,
        command: tuple[str, ...],
        *,
        check: bool,
    ) -> CompletedProcess[str]:
        self.calls.append((command, check))
        return CompletedProcess(command, self._return_codes.pop(0))


def test_browser_bootstrap_uses_exact_argv_without_shell() -> None:
    runner = RecordingRunner([0, 0])

    result = browser_bootstrap(run=runner)

    assert result == 0
    assert runner.calls == [
        (("uv", "sync", "--group", "dev", "--group", "scraping"), False),
        (("uv", "run", "playwright", "install", "chromium"), False),
    ]


def test_browser_bootstrap_stops_after_failed_command() -> None:
    runner = RecordingRunner([23])

    result = browser_bootstrap(run=runner)

    assert result == 23
    assert runner.calls == [
        (("uv", "sync", "--group", "dev", "--group", "scraping"), False),
    ]
