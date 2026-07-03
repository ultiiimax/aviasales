from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

_REDACTED = "<redacted>"
_SENSITIVE_QUERY_KEYS = {
    "access_token",
    "apikey",
    "api_key",
    "auth",
    "authorization",
    "code",
    "key",
    "password",
    "secret",
    "session",
    "session_id",
    "sessionid",
    "sig",
    "signature",
    "signed",
    "token",
}


@dataclass(frozen=True, slots=True)
class RedactedUrlResult:
    ok: bool
    redacted_url: str
    redacted_keys: tuple[str, ...]
    credentials_redacted: bool
    fragment_redacted: bool


def redact_url(url: str) -> RedactedUrlResult:
    parsed = urlsplit(url.strip())
    netloc = parsed.netloc
    credentials_redacted = False
    if parsed.hostname is not None:
        credentials_redacted = parsed.username is not None or parsed.password is not None
        host = parsed.hostname
        if ":" in host and not host.startswith("["):
            host = f"[{host}]"
        netloc = host
        if parsed.port is not None:
            netloc = f"{netloc}:{parsed.port}"

    redacted_keys: list[str] = []
    query_pairs: list[tuple[str, str]] = []
    for key, value in parse_qsl(parsed.query, keep_blank_values=True):
        if _is_sensitive_query_key(key):
            query_pairs.append((key, _REDACTED))
            redacted_keys.append(key)
        else:
            query_pairs.append((key, value))

    fragment_redacted = bool(parsed.fragment)
    redacted_url = urlunsplit(
        (
            parsed.scheme,
            netloc,
            parsed.path,
            urlencode(query_pairs, doseq=True),
            "",
        )
    )
    return RedactedUrlResult(
        ok=True,
        redacted_url=redacted_url,
        redacted_keys=tuple(redacted_keys),
        credentials_redacted=credentials_redacted,
        fragment_redacted=fragment_redacted,
    )


def main() -> int:
    parser = argparse.ArgumentParser(
        prog="flight-hunter-redact-url",
        description="Redact credentials and token-like URL query parameters.",
    )
    parser.add_argument("--url", required=True)
    args = parser.parse_args()

    result = redact_url(args.url)
    print(
        json.dumps(
            {
                "ok": result.ok,
                "redacted_url": result.redacted_url,
                "redacted_keys": list(result.redacted_keys),
                "credentials_redacted": result.credentials_redacted,
                "fragment_redacted": result.fragment_redacted,
            },
            ensure_ascii=False,
        )
    )
    return 0


def _is_sensitive_query_key(key: str) -> bool:
    normalized = key.strip().lower().replace("-", "_")
    return normalized in _SENSITIVE_QUERY_KEYS
