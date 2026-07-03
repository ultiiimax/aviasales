from __future__ import annotations

from dataclasses import dataclass
from ipaddress import IPv4Address, IPv6Address, ip_address
from urllib.parse import urlparse


class DealUrlPolicyError(ValueError):
    """Raised when a deal-discovery URL is unsafe to fetch."""


@dataclass(frozen=True, slots=True)
class DealUrlPolicy:
    allow_non_default_ports: bool = False
    allowed_hosts: tuple[str, ...] = ()

    def validate_public_http_url(self, url: str) -> str:
        parsed = urlparse(url)
        if parsed.scheme not in {"http", "https"}:
            raise DealUrlPolicyError("deal_url_invalid_scheme")
        if parsed.username is not None or parsed.password is not None:
            raise DealUrlPolicyError("deal_url_credentials_not_allowed")
        hostname = parsed.hostname
        if hostname is None or not hostname.strip():
            raise DealUrlPolicyError("deal_url_missing_host")
        host = _normalized_host(hostname)
        if _is_blocked_hostname(host):
            raise DealUrlPolicyError("deal_url_blocked_host")
        if _is_blocked_ip_literal(host):
            raise DealUrlPolicyError("deal_url_blocked_ip")
        if self.allowed_hosts and not _host_matches_allowed_patterns(host, self.allowed_hosts):
            raise DealUrlPolicyError("deal_url_host_not_allowed")
        if not self.allow_non_default_ports and parsed.port is not None:
            allowed_port = 443 if parsed.scheme == "https" else 80
            if parsed.port != allowed_port:
                raise DealUrlPolicyError("deal_url_non_default_port")
        return url.strip()


def _normalized_host(hostname: str) -> str:
    host = hostname.strip().lower().rstrip(".")
    if "%" in host:
        raise DealUrlPolicyError("deal_url_blocked_host")
    try:
        return host.encode("idna").decode("ascii")
    except UnicodeError as exc:
        raise DealUrlPolicyError("deal_url_blocked_host") from exc


def _is_blocked_hostname(host: str) -> bool:
    if host in {
        "localhost",
        "host.docker.internal",
        "metadata.google.internal",
    }:
        return True
    return host.endswith((".localhost", ".local", ".internal"))


def _host_matches_allowed_patterns(host: str, patterns: tuple[str, ...]) -> bool:
    for raw_pattern in patterns:
        pattern = _normalized_allowed_host_pattern(raw_pattern)
        if pattern.startswith("*."):
            suffix = pattern[2:]
            if host.endswith(f".{suffix}"):
                return True
            continue
        if host == pattern:
            return True
    return False


def _normalized_allowed_host_pattern(raw_pattern: str) -> str:
    pattern = raw_pattern.strip().lower().rstrip(".")
    if not pattern:
        raise DealUrlPolicyError("deal_url_invalid_allowed_host")
    wildcard = pattern.startswith("*.")
    host = pattern[2:] if wildcard else pattern
    if "/" in host or ":" in host or "@" in host:
        raise DealUrlPolicyError("deal_url_invalid_allowed_host")
    normalized = _normalized_host(host)
    if _is_blocked_hostname(normalized) or _is_blocked_ip_literal(normalized):
        raise DealUrlPolicyError("deal_url_invalid_allowed_host")
    return f"*.{normalized}" if wildcard else normalized


def _is_blocked_ip_literal(host: str) -> bool:
    aliased = _legacy_ipv4_alias(host)
    if aliased is not None:
        return True
    try:
        parsed = ip_address(host.strip("[]"))
    except ValueError:
        return False
    return _is_blocked_ip(parsed)


def _is_blocked_ip(parsed: IPv4Address | IPv6Address) -> bool:
    return (
        parsed.is_loopback
        or parsed.is_private
        or parsed.is_link_local
        or parsed.is_multicast
        or parsed.is_reserved
        or parsed.is_unspecified
    )


def _legacy_ipv4_alias(host: str) -> IPv4Address | None:
    if ":" in host:
        return None
    if _is_canonical_ipv4_literal(host):
        return None
    parts = host.split(".")
    if len(parts) > 4:
        return None
    values = [_legacy_ipv4_part(part) for part in parts]
    if any(value is None for value in values):
        return None
    parsed = [value for value in values if value is not None]
    try:
        if len(parsed) == 1:
            return IPv4Address(parsed[0])
        if len(parsed) == 2 and parsed[0] <= 0xFF and parsed[1] <= 0xFFFFFF:
            return IPv4Address((parsed[0] << 24) | parsed[1])
        if len(parsed) == 3 and parsed[0] <= 0xFF and parsed[1] <= 0xFF and parsed[2] <= 0xFFFF:
            return IPv4Address((parsed[0] << 24) | (parsed[1] << 16) | parsed[2])
        if len(parsed) == 4 and all(value <= 0xFF for value in parsed):
            return IPv4Address((parsed[0] << 24) | (parsed[1] << 16) | (parsed[2] << 8) | parsed[3])
    except ValueError:
        return None
    return None


def _legacy_ipv4_part(value: str) -> int | None:
    if not value:
        return None
    lowered = value.lower()
    try:
        if lowered.startswith("0x"):
            return int(lowered, 16)
        if len(lowered) > 1 and lowered.startswith("0"):
            return int(lowered, 8)
        return int(lowered, 10)
    except ValueError:
        return None


def _is_canonical_ipv4_literal(host: str) -> bool:
    parts = host.split(".")
    if len(parts) != 4:
        return False
    for part in parts:
        if not part.isdecimal():
            return False
        if len(part) > 1 and part.startswith("0"):
            return False
        value = int(part, 10)
        if value > 255:
            return False
    return True
