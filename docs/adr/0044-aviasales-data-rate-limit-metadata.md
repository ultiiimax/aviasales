# ADR 0044: Aviasales Data Rate-Limit Metadata

Date: 2026-06-29

## Status

Accepted for sanitized provider quota visibility.

## Context

The monster plan requires Flight Hunter to respect provider rate limits and specifically mentions
Travelpayouts `X-Rate-Limit-*` headers. The adapter already handled HTTP 429 and `Retry-After`, but
operator smoke checks did not surface the quota counters that are safe to show.

Official Travelpayouts references were rechecked on 2026-06-29:

- https://support.travelpayouts.com/hc/en-us/articles/203956163-Aviasales-Data-API
- https://support.travelpayouts.com/hc/en-us/articles/4402565416594-API-rate-limits

## Decision

1. Parse `X-Rate-Limit`, `X-Rate-Limit-Remaining` and `X-Rate-Limit-Reset` as optional
   non-negative integers.
2. Attach this metadata to `AviasalesDataResponse`.
3. Attach the same metadata to `AviasalesDataRateLimited` exceptions when a 429 response carries
   headers.
4. Include only sanitized integer counters in `travelpayouts-smoke` and
   `flight-hunter-source-smoke` output.
5. Keep raw headers, tokens, URLs and provider payloads out of logs and smoke summaries.

## Consequences

- Local operators can see quota pressure without exposing secrets.
- Future worker/source-health logic can make better decisions from response metadata.
- This does not replace Flight Hunter's lower internal RPM guard; it complements it with provider
  feedback.

## Verification

- `tests/unit/providers/aviasales_data/test_client.py`
- `tests/unit/providers/aviasales_data/test_smoke.py`
- `tests/unit/ops/test_source_smoke.py`
