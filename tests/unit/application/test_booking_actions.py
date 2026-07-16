from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest

from flight_hunter.application.booking_actions import (
    BookingActionTokenError,
    decode_booking_ref,
    sign_agent_booking_action_token,
    sign_booking_action_token,
    verify_agent_booking_action_token,
    verify_booking_action_token,
)

NOW = datetime(2026, 7, 4, 12, 0, tzinfo=UTC)


def test_booking_token_round_trips_signed_ref_without_raw_url_resolution() -> None:
    ref = (
        '{"provider_id":"aviasales_search","proposal_id":"p1",'
        '"results_url":"host","search_id":"s1"}'
    )

    token = sign_booking_action_token(
        secret_key="test-secret",
        provider_id="aviasales_search",
        ref=ref,
        now=NOW,
        ttl_seconds=60,
    )
    payload = verify_booking_action_token(token, secret_key="test-secret", now=NOW)

    assert payload.provider_id == "aviasales_search"
    assert payload.ref == ref
    assert payload.expires_at == NOW + timedelta(seconds=60)
    assert decode_booking_ref(payload.ref)["proposal_id"] == "p1"


def test_booking_token_rejects_tampering() -> None:
    token = sign_booking_action_token(
        secret_key="test-secret",
        provider_id="aviasales_search",
        ref='{"provider_id":"aviasales_search"}',
        now=NOW,
    )

    with pytest.raises(BookingActionTokenError, match="tampered"):
        verify_booking_action_token(token + "x", secret_key="test-secret", now=NOW)


def test_booking_token_rejects_expired_token() -> None:
    token = sign_booking_action_token(
        secret_key="test-secret",
        provider_id="aviasales_search",
        ref='{"provider_id":"aviasales_search"}',
        now=NOW,
        ttl_seconds=1,
    )

    with pytest.raises(BookingActionTokenError, match="expired"):
        verify_booking_action_token(
            token,
            secret_key="test-secret",
            now=NOW + timedelta(seconds=2),
        )


def test_agent_booking_token_contains_only_an_opaque_descriptor_identity() -> None:
    descriptor_id = UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa")

    token = sign_agent_booking_action_token(
        secret_key="test-secret",
        descriptor_id=descriptor_id,
        now=NOW,
        ttl_seconds=60,
    )
    payload = verify_agent_booking_action_token(
        token,
        secret_key="test-secret",
        now=NOW,
    )

    assert payload.descriptor_id == descriptor_id
    assert "proposal_id" not in token
    assert "results_url" not in token
    assert "provider_ref" not in token
