from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Self

_ISO_CURRENCY_RE = re.compile(r"^[A-Z]{3}$")
MAX_MONEY_MINOR_UNITS = 2_147_483_647


@dataclass(frozen=True, slots=True)
class Money:
    """Money value object stored in integer minor units."""

    minor_units: int
    currency: str

    def __post_init__(self) -> None:
        if type(self.minor_units) is not int:
            raise TypeError("minor_units must be an int, never float or bool")
        if not -MAX_MONEY_MINOR_UNITS <= self.minor_units <= MAX_MONEY_MINOR_UNITS:
            raise ValueError("minor_units is outside the supported persistence range")
        if not isinstance(self.currency, str):
            raise TypeError("currency must be a string")

        normalized_currency = self.currency.upper()
        if not _ISO_CURRENCY_RE.fullmatch(normalized_currency):
            raise ValueError("currency must be an ISO 4217 alpha-3 code")

        object.__setattr__(self, "currency", normalized_currency)

    def __add__(self, other: Self) -> Self:
        self._require_same_currency(other)
        return type(self)(self.minor_units + other.minor_units, self.currency)

    def __sub__(self, other: Self) -> Self:
        self._require_same_currency(other)
        return type(self)(self.minor_units - other.minor_units, self.currency)

    def __str__(self) -> str:
        sign = "-" if self.minor_units < 0 else ""
        units, cents = divmod(abs(self.minor_units), 100)
        return f"{sign}{units}.{cents:02d} {self.currency}"

    def _require_same_currency(self, other: Self) -> None:
        if self.currency != other.currency:
            raise ValueError("currency mismatch")
