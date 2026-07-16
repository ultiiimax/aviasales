from __future__ import annotations

import base64
import hmac
import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from typing import Any
from uuid import UUID


class BookingActionTokenError(ValueError):
    """Raised when a booking action token is expired, malformed or tampered."""


@dataclass(frozen=True, slots=True)
class BookingActionPayload:
    provider_id: str
    ref: str
    expires_at: datetime


@dataclass(frozen=True, slots=True)
class AgentBookingActionPayload:
    descriptor_id: UUID
    expires_at: datetime


def sign_booking_action_token(
    *,
    secret_key: str,
    provider_id: str,
    ref: str,
    now: datetime | None = None,
    ttl_seconds: int = 900,
) -> str:
    if not secret_key:
        raise ValueError("secret_key is required")
    issued_at = now or datetime.now(UTC)
    if issued_at.tzinfo is None or issued_at.utcoffset() is None:
        raise ValueError("now must be timezone-aware")
    expires_at = issued_at + timedelta(seconds=max(1, ttl_seconds))
    payload = {
        "provider_id": provider_id,
        "ref": ref,
        "exp": int(expires_at.timestamp()),
    }
    payload_bytes = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    encoded_payload = _b64encode(payload_bytes)
    signature = _signature(encoded_payload, secret_key)
    return f"{encoded_payload}.{signature}"


def verify_booking_action_token(
    token: str,
    *,
    secret_key: str,
    now: datetime | None = None,
) -> BookingActionPayload:
    if not secret_key:
        raise ValueError("secret_key is required")
    checked_at = now or datetime.now(UTC)
    if checked_at.tzinfo is None or checked_at.utcoffset() is None:
        raise ValueError("now must be timezone-aware")
    try:
        encoded_payload, signature = token.split(".", 1)
    except ValueError as exc:
        raise BookingActionTokenError("booking_action_token_malformed") from exc
    expected = _signature(encoded_payload, secret_key)
    if not hmac.compare_digest(signature, expected):
        raise BookingActionTokenError("booking_action_token_tampered")
    try:
        raw_payload = json.loads(_b64decode(encoded_payload))
    except (ValueError, json.JSONDecodeError) as exc:
        raise BookingActionTokenError("booking_action_token_malformed") from exc
    if not isinstance(raw_payload, dict):
        raise BookingActionTokenError("booking_action_token_malformed")
    provider_id = raw_payload.get("provider_id")
    ref = raw_payload.get("ref")
    exp = raw_payload.get("exp")
    if not isinstance(provider_id, str) or not provider_id:
        raise BookingActionTokenError("booking_action_token_malformed")
    if not isinstance(ref, str) or not ref:
        raise BookingActionTokenError("booking_action_token_malformed")
    if not isinstance(exp, int):
        raise BookingActionTokenError("booking_action_token_malformed")
    expires_at = datetime.fromtimestamp(exp, tz=UTC)
    if checked_at >= expires_at:
        raise BookingActionTokenError("booking_action_token_expired")
    return BookingActionPayload(provider_id=provider_id, ref=ref, expires_at=expires_at)


def sign_agent_booking_action_token(
    *,
    secret_key: str,
    descriptor_id: UUID,
    now: datetime | None = None,
    ttl_seconds: int = 900,
) -> str:
    if not secret_key:
        raise ValueError("secret_key is required")
    if not isinstance(descriptor_id, UUID):
        raise TypeError("descriptor_id must be UUID")
    issued_at = now or datetime.now(UTC)
    if issued_at.tzinfo is None or issued_at.utcoffset() is None:
        raise ValueError("now must be timezone-aware")
    expires_at = issued_at + timedelta(seconds=max(1, ttl_seconds))
    encoded_payload = _b64encode(
        json.dumps(
            {
                "descriptor_id": str(descriptor_id),
                "exp": int(expires_at.timestamp()),
                "version": "agent-booking-v1",
            },
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    )
    return f"{encoded_payload}.{_signature(encoded_payload, secret_key)}"


def verify_agent_booking_action_token(
    token: str,
    *,
    secret_key: str,
    now: datetime | None = None,
) -> AgentBookingActionPayload:
    if not secret_key:
        raise ValueError("secret_key is required")
    checked_at = now or datetime.now(UTC)
    if checked_at.tzinfo is None or checked_at.utcoffset() is None:
        raise ValueError("now must be timezone-aware")
    try:
        encoded_payload, signature = token.split(".", 1)
    except ValueError as exc:
        raise BookingActionTokenError("agent_booking_token_malformed") from exc
    if not hmac.compare_digest(
        signature,
        _signature(encoded_payload, secret_key),
    ):
        raise BookingActionTokenError("agent_booking_token_tampered")
    try:
        payload = json.loads(_b64decode(encoded_payload))
    except (ValueError, json.JSONDecodeError) as exc:
        raise BookingActionTokenError("agent_booking_token_malformed") from exc
    if (
        not isinstance(payload, dict)
        or payload.get("version") != "agent-booking-v1"
        or not isinstance(payload.get("descriptor_id"), str)
        or not isinstance(payload.get("exp"), int)
    ):
        raise BookingActionTokenError("agent_booking_token_malformed")
    try:
        descriptor_id = UUID(payload["descriptor_id"])
    except ValueError as exc:
        raise BookingActionTokenError("agent_booking_token_malformed") from exc
    expires_at = datetime.fromtimestamp(payload["exp"], tz=UTC)
    if checked_at >= expires_at:
        raise BookingActionTokenError("agent_booking_token_expired")
    return AgentBookingActionPayload(
        descriptor_id=descriptor_id,
        expires_at=expires_at,
    )


def decode_booking_ref(ref: str) -> dict[str, Any]:
    try:
        payload = json.loads(ref)
    except json.JSONDecodeError as exc:
        raise BookingActionTokenError("booking_action_ref_malformed") from exc
    if not isinstance(payload, dict):
        raise BookingActionTokenError("booking_action_ref_malformed")
    return payload


def _signature(encoded_payload: str, secret_key: str) -> str:
    digest = hmac.new(
        secret_key.encode("utf-8"),
        encoded_payload.encode("ascii"),
        sha256,
    ).digest()
    return _b64encode(digest)


def _b64encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def _b64decode(value: str) -> str:
    padding = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode(value + padding).decode("utf-8")
