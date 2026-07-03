# ADR 0065: Household admin audit surface

Date: 2026-06-29

## Status

Accepted for the current implementation slice.

## Context

Watch lifecycle actions and Telegram watch callbacks already write append-only `audit_events`
rows scoped by `household_id`. Operators could verify those rows only through tests or direct
database inspection, so the product had persistence without a safe delivery surface.

## Decision

Add a read-only household admin audit surface:

- `GET /api/v1/admin/audit-events` requires the same bearer or legacy household headers used by
  watch endpoints.
- The endpoint reads `AuditEventRepository.list_events(household_id)` and never accepts a
  household id from query/body parameters.
- Responses include event id, actor user id, action, entity type/id, summary and creation time.
- Results are returned newest first with a bounded `limit` query parameter.
- The web workbench renders an Audit panel and refreshes it after watch lifecycle mutations.

No migration is required for this slice because `audit_events` already exists from
`0015_watch_lifecycle_audit`.

## Consequences

Positive:

- Household users can inspect lifecycle actions without direct database access.
- The API preserves household isolation by construction: auth context chooses the household.
- Refreshing the panel is read-only and does not trigger provider, browser or worker activity.

Tradeoffs:

- This is still a compact local workbench panel, not a full RBAC admin console with filtering or
  export.
- The endpoint currently exposes internal UUIDs to authenticated household users for traceability.

## Verification

- `uv run pytest tests/unit/api/test_admin_audit_api.py tests/unit/api/test_web_ui.py tests/unit/api/test_watch_api.py --quiet`
  -> 10 passed.
- Extracted inline script from `render_index_html()` and parsed it with Node
  `new Function(script)` -> `script syntax ok`.
