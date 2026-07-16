from __future__ import annotations

import pytest

from flight_hunter.domain.money import MAX_MONEY_MINOR_UNITS, Money


def test_money_keeps_integer_minor_units_and_normalizes_currency() -> None:
    money = Money(minor_units=12345, currency="pln")

    assert money.minor_units == 12345
    assert money.currency == "PLN"
    assert str(money) == "123.45 PLN"


def test_money_rejects_float_minor_units() -> None:
    with pytest.raises(TypeError, match="minor_units"):
        Money(minor_units=12.34, currency="PLN")  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "minor_units",
    (MAX_MONEY_MINOR_UNITS + 1, -MAX_MONEY_MINOR_UNITS - 1),
)
def test_money_rejects_values_outside_persistence_range(minor_units: int) -> None:
    with pytest.raises(ValueError, match="range"):
        Money(minor_units=minor_units, currency="PLN")


def test_money_addition_requires_matching_currency() -> None:
    assert Money(100, "PLN") + Money(250, "PLN") == Money(350, "PLN")

    with pytest.raises(ValueError, match="currency"):
        Money(100, "PLN") + Money(100, "EUR")
