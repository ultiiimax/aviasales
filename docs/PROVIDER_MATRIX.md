# Provider Matrix

| Source | Status | Data kind | Credentials | Background scans | Merge | Notes |
|---|---|---|---|---:|---:|---|
| `fake` | implemented | demo cached fixtures | none | yes | yes | Offline fallback for local demo mode. |
| `aviasales_search` | implemented | live | `AVIASALES_SEARCH_SIGNATURE`, `AVIASALES_SEARCH_MARKER` | yes | yes | Primary source. Aviasales mobile API direct search, gates/prices, lazy purchase links, suggest, hot offers, calendar, typed GraphQL blocks. |
| `searxng` | implemented | deal URL discovery | self-hosted optional | no | candidate only | Manual deal discovery metadata, not priced offers. |
| `crawl4ai` | implemented | markdown diagnostics | self-hosted optional | no | candidate only | Fetches allowed public pages after URL policy. |
| `deal_discovery` | implemented | deal candidates | SearXNG + Crawl4AI flags | no | candidate only | Persists manual-verification candidates only. |
| `skyscanner_indicative` | contract only | indicative | none | no | no | Not active. |
| `skyscanner_live` | contract only | live | none | no | no | Not active. |
| `duffel` | contract only | bookable | none | no | no | Not active. |

## Primary Path

Use `aviasales_search` for real fare search.

Required env:

```env
AVIASALES_SEARCH_ENABLED=true
AVIASALES_SEARCH_SIGNATURE=...
AVIASALES_SEARCH_MARKER=...
AVIASALES_SEARCH_INTERNAL_RPM=20
APP_SECRET_KEY=...
```

Contracts:

- `docs/provider-contracts/aviasales-search.md`
- `src/flight_hunter/providers/aviasales_search/`

Rules:

- Live offers carry source and `observed_at`.
- Raw provider refs stay server-side.
- Purchase URL is resolved only through `POST /api/v1/booking-actions/resolve`.
- No live calls in CI; tests use fixtures/fake transports.
