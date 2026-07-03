from __future__ import annotations

import pytest

from flight_hunter.deals.url_policy import DealUrlPolicy, DealUrlPolicyError


def test_deal_url_policy_accepts_public_http_urls() -> None:
    policy = DealUrlPolicy()

    assert policy.validate_public_http_url("https://example.com/deal") == "https://example.com/deal"
    assert policy.validate_public_http_url("http://example.com/path") == "http://example.com/path"
    assert policy.validate_public_http_url("https://93.184.216.34/deal") == (
        "https://93.184.216.34/deal"
    )


def test_deal_url_policy_honors_optional_host_allowlist() -> None:
    policy = DealUrlPolicy(allowed_hosts=("example.com", "*.deals.example"))

    assert policy.validate_public_http_url("https://example.com/deal") == "https://example.com/deal"
    assert policy.validate_public_http_url("https://hot.deals.example/deal") == (
        "https://hot.deals.example/deal"
    )

    with pytest.raises(DealUrlPolicyError, match="deal_url_host_not_allowed"):
        policy.validate_public_http_url("https://other.example/deal")


@pytest.mark.parametrize(
    "url",
    [
        "file:///etc/passwd",
        "ftp://example.com/deal",
        "http://localhost/deal",
        "http://127.0.0.1/deal",
        "http://10.0.0.1/deal",
        "http://169.254.169.254/latest/meta-data",
        "http://[::ffff:127.0.0.1]/deal",
        "http://[fe80::1%25eth0]/deal",
        "http://2130706433/deal",
        "http://0x7f000001/deal",
        "http://0177.0.0.1/deal",
        "http://127.1/deal",
        "http://metadata.google.internal/computeMetadata/v1",
        "http://example.local/deal",
        "https://user:pass@example.com/deal",
        "https://example.com:8443/deal",
    ],
)
def test_deal_url_policy_rejects_ssrf_shapes(url: str) -> None:
    with pytest.raises(DealUrlPolicyError):
        DealUrlPolicy().validate_public_http_url(url)


@pytest.mark.parametrize(
    "allowed_host",
    [
        "http://example.com",
        "localhost",
        "127.0.0.1",
        "0x7f000001",
        "example.com/path",
    ],
)
def test_deal_url_policy_rejects_invalid_allowed_host_patterns(allowed_host: str) -> None:
    with pytest.raises(DealUrlPolicyError, match="deal_url_invalid_allowed_host"):
        DealUrlPolicy(allowed_hosts=(allowed_host,)).validate_public_http_url(
            "https://example.com/deal"
        )
