from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from uuid import UUID

from flight_hunter.domain.money import Money
from flight_hunter.domain.policy import require_aware_datetime
from flight_hunter.domain.search_results import ResultKind


class ManualConfirmationStatus(StrEnum):
    CONFIRMED = "confirmed"
    SOLD_OUT = "sold_out"
    PRICE_CHANGED = "price_changed"
    BOUGHT = "bought"
    WRONG_ROUTE = "wrong_route"


@dataclass(frozen=True, slots=True)
class ManualPriceConfirmation:
    id: UUID
    household_id: UUID
    user_id: UUID
    target_kind: ResultKind | str
    target_id: str
    source_id: str
    status: ManualConfirmationStatus | str
    confirmed_at: datetime
    confirmed_price: Money | None = None
    note: str | None = None

    def __post_init__(self) -> None:
        target_kind = ResultKind(self.target_kind)
        status = ManualConfirmationStatus(self.status)
        if not self.target_id.strip():
            raise ValueError("target_id is required")
        if len(self.target_id) > 160:
            raise ValueError("target_id is too long")
        if not self.source_id.strip():
            raise ValueError("source_id is required")
        if len(self.source_id) > 80:
            raise ValueError("source_id is too long")
        if self.note is not None and len(self.note) > 500:
            raise ValueError("note is too long")
        require_aware_datetime(self.confirmed_at, "confirmed_at")
        object.__setattr__(self, "target_kind", target_kind)
        object.__setattr__(self, "target_id", self.target_id.strip())
        object.__setattr__(self, "source_id", self.source_id.strip())
        object.__setattr__(self, "status", status)
