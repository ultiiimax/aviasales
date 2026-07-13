from __future__ import annotations

from flight_hunter.application.agent_capabilities import ProviderCapabilityRegistry
from flight_hunter.domain.agent_search import CapabilityState


def test_aviasales_capability_snapshot_is_versioned_and_tri_state() -> None:
    snapshot = ProviderCapabilityRegistry().snapshot()

    assert snapshot.provider_id == "aviasales_search"
    assert snapshot.version == "mobile-contract-2026-07-13"
    assert snapshot.one_way is CapabilityState.SUPPORTED
    assert snapshot.round_trip is CapabilityState.SUPPORTED
    assert snapshot.native_open_jaw is CapabilityState.UNKNOWN
    assert snapshot.native_multi_city is CapabilityState.UNKNOWN
    assert snapshot.explicit_connection_protection is CapabilityState.UNKNOWN
    assert snapshot.airport_location_semantics is CapabilityState.SUPPORTED
    assert snapshot.city_location_semantics is CapabilityState.UNKNOWN
    assert snapshot.cost_model.version == "aviasales-v1"
