from __future__ import annotations

import re
from dataclasses import dataclass, replace
from datetime import date, timedelta
from typing import Literal

from flight_hunter.domain.agent_evidence import (
    ConfirmationState,
    DiscoverySignal,
    DiscoverySource,
)
from flight_hunter.domain.offers import Freshness

_IATA_RE = re.compile(r"^[A-Z]{3}$")
_CURRENCY_RE = re.compile(r"^[A-Z]{3}$")


@dataclass(frozen=True, slots=True)
class DateMatrixRequest:
    departure_date: date
    return_date: date | None
    flexibility_days: int
    min_stay_days: int | None
    max_stay_days: int | None


@dataclass(frozen=True, slots=True)
class DateMatrixDiscoveryContext:
    origin: str
    destination: str
    currency: str
    passengers: int
    one_way: bool

    def __post_init__(self) -> None:
        if not isinstance(self.origin, str) or not isinstance(self.destination, str):
            raise TypeError("discovery route must contain strings")
        origin = self.origin.upper()
        destination = self.destination.upper()
        if not _IATA_RE.fullmatch(origin) or not _IATA_RE.fullmatch(destination):
            raise ValueError("discovery route must contain ASCII IATA codes")
        if not isinstance(self.currency, str):
            raise TypeError("discovery currency must be a string")
        currency = self.currency.upper()
        if not _CURRENCY_RE.fullmatch(currency):
            raise ValueError("discovery currency must be an ASCII ISO code")
        if type(self.passengers) is not int or self.passengers < 1:
            raise ValueError("discovery passengers must be a positive integer")
        if type(self.one_way) is not bool:
            raise TypeError("discovery one_way must be a boolean")
        object.__setattr__(self, "origin", origin)
        object.__setattr__(self, "destination", destination)
        object.__setattr__(self, "currency", currency)


@dataclass(frozen=True, slots=True)
class DateMatrixCell:
    departure_date: date
    return_date: date | None
    stay_days: int | None
    discovery_signal: DiscoverySignal | None = None
    freshness: Freshness | None = None

    def __post_init__(self) -> None:
        if self.discovery_signal is not None and not isinstance(
            self.discovery_signal, DiscoverySignal
        ):
            raise TypeError("discovery_signal must be DiscoverySignal")
        if (self.discovery_signal is None) != (self.freshness is None):
            raise ValueError("discovery_signal and freshness must be set together")
        if self.discovery_signal is not None and (
            self.discovery_signal.departure_date != self.departure_date
            or self.discovery_signal.return_date != self.return_date
        ):
            raise ValueError("matrix cell and discovery signal dates must match")
        if self.freshness is not None:
            object.__setattr__(self, "freshness", Freshness(self.freshness))

    @property
    def evidence_kind(self) -> Literal["discovery_signal"] | None:
        return "discovery_signal" if self.discovery_signal is not None else None

    @property
    def confirmation_state(self) -> ConfirmationState | None:
        return (
            self.discovery_signal.confirmation_state if self.discovery_signal is not None else None
        )

    @property
    def requires_live_confirmation(self) -> bool | None:
        return True if self.discovery_signal is not None else None


@dataclass(frozen=True, slots=True)
class DateMatrix:
    cells: tuple[DateMatrixCell, ...]
    provider_calls_required: int
    priced: bool


class DateMatrixPlanner:
    def __init__(self, *, max_flexibility_days: int = 7) -> None:
        self._max_flexibility_days = max_flexibility_days

    def plan(self, request: DateMatrixRequest) -> DateMatrix:
        self._validate(request)
        departure_dates = self._expanded_dates(request.departure_date, request.flexibility_days)
        return_dates = (
            self._expanded_dates(request.return_date, request.flexibility_days)
            if request.return_date is not None
            else (None,)
        )

        cells: list[DateMatrixCell] = []
        for departure_date in departure_dates:
            for return_date in return_dates:
                stay_days = (return_date - departure_date).days if return_date is not None else None
                if stay_days is not None and stay_days < 0:
                    continue
                if not self._stay_length_allowed(request, stay_days):
                    continue
                cells.append(
                    DateMatrixCell(
                        departure_date=departure_date,
                        return_date=return_date,
                        stay_days=stay_days,
                    )
                )

        return DateMatrix(cells=tuple(cells), provider_calls_required=0, priced=False)

    def overlay_discovery(
        self,
        matrix: DateMatrix,
        *,
        signals: tuple[DiscoverySignal, ...],
        context: DateMatrixDiscoveryContext,
        freshness: Freshness,
    ) -> DateMatrix:
        if not isinstance(matrix, DateMatrix):
            raise TypeError("matrix must be DateMatrix")
        if not isinstance(context, DateMatrixDiscoveryContext):
            raise TypeError("context must be DateMatrixDiscoveryContext")
        normalized_signals = tuple(signals)
        if not all(isinstance(signal, DiscoverySignal) for signal in normalized_signals):
            raise TypeError("signals must contain DiscoverySignal values")
        normalized_freshness = Freshness(freshness)
        cell_keys = {(cell.departure_date, cell.return_date) for cell in matrix.cells}
        indexed: dict[tuple[date, date | None], DiscoverySignal] = {}
        for signal in normalized_signals:
            key = (signal.departure_date, signal.return_date)
            _require_discovery_matches_context(
                signal,
                context=context,
                cell_keys=cell_keys,
            )
            existing = indexed.get(key)
            if existing is None:
                indexed[key] = signal
                continue
            if existing.observed_amount.currency != signal.observed_amount.currency:
                raise ValueError("calendar signals for one cell must use one currency")
            if signal.observed_amount.minor_units < existing.observed_amount.minor_units:
                indexed[key] = signal

        cells = tuple(
            replace(
                cell,
                discovery_signal=cell_signal,
                freshness=normalized_freshness,
            )
            if (cell_signal := indexed.get((cell.departure_date, cell.return_date))) is not None
            else cell
            for cell in matrix.cells
        )
        return DateMatrix(
            cells=cells,
            provider_calls_required=matrix.provider_calls_required,
            priced=any(cell.discovery_signal is not None for cell in cells),
        )

    def _validate(self, request: DateMatrixRequest) -> None:
        if request.flexibility_days < 0:
            raise ValueError("flexibility_days cannot be negative")
        if request.flexibility_days > self._max_flexibility_days:
            raise ValueError("flexibility_days exceeds maximum")
        if request.min_stay_days is not None and request.min_stay_days < 0:
            raise ValueError("min_stay_days cannot be negative")
        if request.max_stay_days is not None and request.max_stay_days < 0:
            raise ValueError("max_stay_days cannot be negative")
        if (
            request.min_stay_days is not None
            and request.max_stay_days is not None
            and request.min_stay_days > request.max_stay_days
        ):
            raise ValueError("min_stay_days cannot exceed max_stay_days")

    @staticmethod
    def _expanded_dates(center: date, flexibility_days: int) -> tuple[date, ...]:
        return tuple(
            center + timedelta(days=offset)
            for offset in range(-flexibility_days, flexibility_days + 1)
        )

    @staticmethod
    def _stay_length_allowed(request: DateMatrixRequest, stay_days: int | None) -> bool:
        if stay_days is None:
            return True
        if request.min_stay_days is not None and stay_days < request.min_stay_days:
            return False
        return not (request.max_stay_days is not None and stay_days > request.max_stay_days)


def _require_discovery_matches_context(
    signal: DiscoverySignal,
    *,
    context: DateMatrixDiscoveryContext,
    cell_keys: set[tuple[date, date | None]],
) -> None:
    if (
        signal.source_kind is not DiscoverySource.CALENDAR
        or signal.origin != context.origin
        or signal.destination != context.destination
        or signal.observed_amount.currency != context.currency
        or signal.passengers != context.passengers
        or (signal.return_date is None) is not context.one_way
        or (signal.departure_date, signal.return_date) not in cell_keys
    ):
        raise ValueError("discovery signal does not match matrix context")
