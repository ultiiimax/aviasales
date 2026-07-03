# ADR 0116: Privacy export API

Date: 2026-06-29

## Status

Accepted for the current implementation slice.

## Context

The architecture lists `POST /api/v1/privacy/export`, and the product rules require secrets and raw
provider payloads to stay out of exports. The existing data model already keeps household-scoped
watches and audit rows plus user-scoped manual confirmations, browser observations and deal
candidates. Reusing UI readers directly would hide archived/deleted watches and expired-but-retained
personal observations, while raw table dumps would expose internal fields such as `raw_ref`,
idempotency keys or queue payload JSON.

## Decision

Add a bounded JSON export endpoint:

- `POST /api/v1/privacy/export` requires the same bearer or legacy household headers as the rest of
  the authenticated API.
- The endpoint returns retained watches for the authenticated household, including archived/deleted
  watch metadata.
- It returns personal manual confirmations, browser-observed offers and deal candidates only for
  the authenticated user inside that household.
- Audit events are household-scoped and returned newest first.
- Each collection is capped at 500 rows. The endpoint fetches one extra row and reports
  `truncated` per collection.
- The response declares omitted sensitive/internal fields: provider secrets, raw payloads,
  `raw_ref`, idempotency keys, session tokens, Telegram payload JSON and worker queue payloads.
- The export action itself writes an append-only `privacy.exported` audit event after the export
  snapshot is assembled, so the response does not include its own audit row.

No migration is required because this slice adds read models over existing tables.

## Consequences

Positive:

- Users can obtain a privacy-safe archive without database access.
- Soft-deleted watch records remain visible in the export while normal watch APIs still hide them.
- Browser/deal/manual personal data does not leak across users sharing a household.
- Export generation is auditable without storing the generated export payload.

Tradeoffs:

- This is an immediate JSON export, not an object-storage backed asynchronous export bundle.
- Account deletion/erasure remains a separate destructive privacy slice.
- Collection pagination for very large exports is deferred; truncation is explicit.

## Verification

- `uv run pytest tests/unit/api/test_privacy_export_api.py tests/unit/persistence/test_household_watch_repository.py tests/unit/persistence/test_manual_price_confirmation_repository.py tests/unit/persistence/test_deal_candidate_repository.py tests/unit/persistence/test_browser_observed_offer_repository.py -q`
  -> 18 passed.
