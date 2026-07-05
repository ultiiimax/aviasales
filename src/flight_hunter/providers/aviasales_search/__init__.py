"""Aviasales Search (mobile API) live adapter.

Live flight search via ``tickets-api.aviasales.ru`` mobile endpoints. DTO parsed
from raw provider chunks stays inside this package; :mod:`mapper` maps to domain
``FlightOffer``. See ``docs/provider-contracts/aviasales-search.md``.
"""
