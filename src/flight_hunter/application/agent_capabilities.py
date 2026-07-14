from __future__ import annotations

from flight_hunter.domain.agent_search import (
    CapabilityState,
    ProviderCapabilitySnapshot,
    ProviderHttpCostModel,
)


class ProviderCapabilityRegistry:
    def __init__(self, *, requests_per_minute: int = 20) -> None:
        if type(requests_per_minute) is not int or requests_per_minute <= 0:
            raise ValueError("requests_per_minute must be a positive integer")
        self._requests_per_minute = requests_per_minute

    def snapshot(self) -> ProviderCapabilitySnapshot:
        return ProviderCapabilitySnapshot(
            provider_id="aviasales_search",
            version="mobile-contract-2026-07-13",
            one_way=CapabilityState.SUPPORTED,
            round_trip=CapabilityState.SUPPORTED,
            native_open_jaw=CapabilityState.UNKNOWN,
            native_multi_city=CapabilityState.UNKNOWN,
            explicit_connection_protection=CapabilityState.UNKNOWN,
            airport_location_semantics=CapabilityState.SUPPORTED,
            city_location_semantics=CapabilityState.UNKNOWN,
            cost_model=ProviderHttpCostModel(
                version="aviasales-v1",
                start_attempts=3,
                poll_rounds=8,
                attempts_per_poll=3,
                requests_per_minute=self._requests_per_minute,
            ),
        )
