"""Aviasales Search (mobile API) live adapter.

Live flight search via ``tickets-api.aviasales.ru`` mobile endpoints. DTO parsed
from raw provider chunks stays inside this package; :mod:`mapper` maps the
compatibility flow to domain ``FlightOffer`` and the resumable agent flow to
``ConfirmedOfferEvidence`` / ``DiscoverySignal``. See
``docs/provider-contracts/aviasales-search.md``.
"""
