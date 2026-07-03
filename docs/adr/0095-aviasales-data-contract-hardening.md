# ADR 0095: Aviasales Data contract hardening

Date: 2026-06-29

## Status

Accepted.

## Context

The Aviasales / Travelpayouts Data API adapter supports the main cached radar endpoints needed by
Flight Hunter. A contract audit found a few low-risk hardening gaps: some official matrix examples
use integer-valued float prices, empty return-date fields could leak as empty strings, and the
provider contract notes did not explicitly inventory implemented/superseded/deprecated endpoints.

## Decision

Normalize provider price fields through a single parser:

- `int` values are accepted;
- integer-valued `float` values such as `26000.0` are accepted and normalized to `int`;
- fractional floats fail closed as schema errors.

Normalize optional return-date fields through a shared helper so empty strings become `None`.

Document the endpoint inventory in `docs/provider-contracts/aviasales-data.md`, including v3/v2
implemented endpoints, superseded legacy endpoints and deprecated/do-not-implement endpoints.

## Consequences

- Current official nearest-places/matrix-style payloads are accepted without weakening schema
  validation.
- Fractional provider prices still fail closed; Flight Hunter does not silently round prices.
- No live Search API, booking-link preload or legacy endpoint calls are introduced.

## Verification

- Client tests cover integer-valued float prices, fractional float rejection and empty return-date
  normalization.
- Provider contract docs record the endpoint inventory and parsing policy.
