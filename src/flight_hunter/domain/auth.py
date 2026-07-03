from __future__ import annotations

import hashlib
import hmac
import secrets
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from uuid import UUID

from flight_hunter.domain.policy import require_aware_datetime


class HouseholdRole(StrEnum):
    OWNER = "owner"
    ADMIN = "admin"
    MEMBER = "member"
    VIEWER = "viewer"


@dataclass(frozen=True, slots=True)
class AuthSession:
    id: UUID
    household_id: UUID
    user_id: UUID
    role: HouseholdRole | str
    created_at: datetime
    expires_at: datetime

    def __post_init__(self) -> None:
        require_aware_datetime(self.created_at, "created_at")
        require_aware_datetime(self.expires_at, "expires_at")
        object.__setattr__(self, "role", HouseholdRole(self.role))


def new_secret_token() -> str:
    return secrets.token_urlsafe(32)


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def token_hash_matches(token: str, expected_hash: str) -> bool:
    return hmac.compare_digest(token_hash(token), expected_hash)
