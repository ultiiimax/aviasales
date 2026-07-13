import pytest


@pytest.fixture(autouse=True)
def enable_legacy_headers_for_non_auth_api_unit_tests(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("AUTH_ALLOW_LEGACY_HEADERS", "true")
