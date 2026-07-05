# Flight Hunter вЂ” С†РµР»РµРІР°СЏ Р°СЂС…РёС‚РµРєС‚СѓСЂР°

## 1. РђСЂС…РёС‚РµРєС‚СѓСЂРЅР°СЏ РїРѕР·РёС†РёСЏ

Flight Hunter вЂ” self-hosted, invitation-only РїСЂРёР»РѕР¶РµРЅРёРµ РґР»СЏ СЃРµРјСЊРё Рё РґСЂСѓР·РµР№. РћРЅРѕ РЅРµ РїСЂРѕРґР°С‘С‚ Р±РёР»РµС‚С‹ Рё РЅРµ РїСЂРёС‚РІРѕСЂСЏРµС‚СЃСЏ РµРґРёРЅСЃС‚РІРµРЅРЅС‹Рј РёСЃС‚РѕС‡РЅРёРєРѕРј РёСЃС‚РёРЅС‹. Р•РіРѕ Р·Р°РґР°С‡Р°:

- СЃРѕР±СЂР°С‚СЊ СЂР°Р·СЂРµС€С‘РЅРЅС‹Рµ РґР°РЅРЅС‹Рµ РёР· РЅРµСЃРєРѕР»СЊРєРёС… РёСЃС‚РѕС‡РЅРёРєРѕРІ;
- РЅРѕСЂРјР°Р»РёР·РѕРІР°С‚СЊ РїСЂРµРґР»РѕР¶РµРЅРёСЏ;
- РЅР°Р№С‚Рё РґРµС€С‘РІС‹Рµ РґР°С‚С‹, СЃРѕСЃРµРґРЅРёРµ Р°СЌСЂРѕРїРѕСЂС‚С‹ Рё СЂР°Р·СѓРјРЅС‹Рµ РєРѕРјР±РёРЅР°С†РёРё;
- СЃРѕС…СЂР°РЅСЏС‚СЊ РёСЃС‚РѕСЂРёСЋ РЅР°Р±Р»СЋРґРµРЅРёР№;
- РѕС†РµРЅРёРІР°С‚СЊ С†РµРЅСѓ, РґР»РёС‚РµР»СЊРЅРѕСЃС‚СЊ Рё СЂРёСЃРє;
- Р·Р°РїСѓСЃРєР°С‚СЊ live refresh С‚РѕР»СЊРєРѕ С‚Р°Рј, РіРґРµ СЌС‚Рѕ СЂР°Р·СЂРµС€РµРЅРѕ;
- РѕС‚РїСЂР°РІР»СЏС‚СЊ РїРѕР»РµР·РЅС‹Рµ, РЅРµ СЃРїР°РјСЏС‰РёРµ СѓРІРµРґРѕРјР»РµРЅРёСЏ РІ Telegram;
- РѕР±СЉСЏСЃРЅСЏС‚СЊ РїРѕР»СЊР·РѕРІР°С‚РµР»СЋ, РїРѕС‡РµРјСѓ РІР°СЂРёР°РЅС‚ СЃС‡РёС‚Р°РµС‚СЃСЏ РІС‹РіРѕРґРЅС‹Рј.

РђСЂС…РёС‚РµРєС‚СѓСЂР° вЂ” **РјРѕРґСѓР»СЊРЅС‹Р№ РјРѕРЅРѕР»РёС‚ СЃ РѕС‚РґРµР»СЊРЅС‹РјРё РїСЂРѕС†РµСЃСЃР°РјРё**, Р° РЅРµ РЅР°Р±РѕСЂ РјРёРєСЂРѕСЃРµСЂРІРёСЃРѕРІ. РћРґРёРЅ СЂРµРїРѕР·РёС‚РѕСЂРёР№, РѕРґРЅР° РґРѕРјРµРЅРЅР°СЏ РјРѕРґРµР»СЊ, РѕС‚РґРµР»СЊРЅС‹Рµ runtime-РїСЂРѕС†РµСЃСЃС‹:

- `web` вЂ” Next.js UI/PWA;
- `api` вЂ” FastAPI REST/SSE;
- `worker` вЂ” С„РѕРЅРѕРІС‹Рµ Р·Р°РґР°С‡Рё Рё scheduler;
- `bot` вЂ” Telegram webhook processor;
- `postgres` вЂ” PostgreSQL + PostGIS;
- `redis` вЂ” РѕС‡РµСЂРµРґСЊ, РєСЌС€ Рё distributed locks;
- `object-storage` вЂ” РѕРїС†РёРѕРЅР°Р»СЊРЅРѕ S3/MinIO РґР»СЏ exports/fixtures;
- `reverse-proxy` вЂ” Caddy/Traefik;
- observability stack вЂ” РІРєР»СЋС‡Р°РµРјС‹Р№ profile.

Р›РѕРіРёС‡РµСЃРєРёР№ Р°РіРµРЅС‚РЅС‹Р№ СЃР»РѕР№ РЅРµ РґРѕР»Р¶РµРЅ РїСЂРµРІСЂР°С‰Р°С‚СЊ СЃРёСЃС‚РµРјСѓ РІ РЅРµРґРµС‚РµСЂРјРёРЅРёСЂРѕРІР°РЅРЅС‹Р№ В«СЂРѕР№В». LLM РёСЃРїРѕР»СЊР·СѓРµС‚СЃСЏ РґР»СЏ РїРѕРЅРёРјР°РЅРёСЏ РµСЃС‚РµСЃС‚РІРµРЅРЅРѕРіРѕ СЏР·С‹РєР° Рё РѕР±СЉСЏСЃРЅРµРЅРёР№, Р° РїРѕРёСЃРє, РѕРіСЂР°РЅРёС‡РµРЅРёСЏ, РґРµРЅРµР¶РЅС‹Рµ СЂР°СЃС‡С‘С‚С‹, РјР°СЂС€СЂСѓС‚РёР·Р°С†РёСЏ Рё alerts РІС‹РїРѕР»РЅСЏСЋС‚СЃСЏ РґРµС‚РµСЂРјРёРЅРёСЂРѕРІР°РЅРЅС‹Рј РєРѕРґРѕРј.

---

## 2. Р РµРєРѕРјРµРЅРґСѓРµРјС‹Р№ СЃС‚РµРє

РџРµСЂРµРґ РЅР°С‡Р°Р»РѕРј СЂРµР°Р»РёР·Р°С†РёРё coding agent РїСЂРѕРІРµСЂСЏРµС‚ Р°РєС‚СѓР°Р»СЊРЅС‹Рµ stable/LTS РІРµСЂСЃРёРё Рё С„РёРєСЃРёСЂСѓРµС‚ РёС… РІ ADR Рё lock-С„Р°Р№Р»Р°С…. Р‘Р°Р·РѕРІС‹Р№ РІС‹Р±РѕСЂ:

### Backend

- Python 3.13+;
- FastAPI;
- Pydantic v2;
- SQLAlchemy 2 async;
- Alembic;
- PostgreSQL + PostGIS;
- Redis;
- Dramatiq РёР»Рё Celery РґР»СЏ РѕС‡РµСЂРµРґРµР№; РІС‹Р±СЂР°С‚СЊ РѕРґРёРЅ РїРѕСЃР»Рµ РєРѕСЂРѕС‚РєРѕРіРѕ ADR;
- APScheduler С‚РѕР»СЊРєРѕ РєР°Рє trigger producer, РЅРµ РєР°Рє РµРґРёРЅСЃС‚РІРµРЅРЅС‹Р№ durable scheduler;
- HTTPX;
- Tenacity РёР»Рё СЃРѕР±СЃС‚РІРµРЅРЅС‹Р№ retry policy;
- structlog;
- OpenTelemetry;
- Prometheus client;
- aiogram 3 РґР»СЏ Telegram;
- pytest, Hypothesis, respx, testcontainers.

### Frontend

- Next.js App Router;
- TypeScript strict;
- React;
- Tailwind CSS;
- shadcn/ui РёР»Рё Radix primitives;
- TanStack Query;
- TanStack Table;
- React Hook Form + Zod;
- ECharts/Recharts РґР»СЏ РёСЃС‚РѕСЂРёРё С†РµРЅ Рё РјР°С‚СЂРёС†;
- MapLibre РґР»СЏ РєР°СЂС‚С‹ Р°СЌСЂРѕРїРѕСЂС‚РѕРІ, РµСЃР»Рё РєР°СЂС‚Р° РІРєР»СЋС‡РµРЅР°;
- Playwright РґР»СЏ E2E СЃРѕР±СЃС‚РІРµРЅРЅРѕРіРѕ РїСЂРёР»РѕР¶РµРЅРёСЏ;
- Vitest + Testing Library.

### Р РµРїРѕР·РёС‚РѕСЂРёР№ Рё СЌРєСЃРїР»СѓР°С‚Р°С†РёСЏ

- pnpm workspace РёР»Рё Turborepo;
- uv РґР»СЏ Python dependencies;
- Docker Compose РґР»СЏ self-host;
- GitHub Actions;
- pre-commit;
- Ruff, mypy/pyright, ESLint, Prettier;
- Renovate/Dependabot;
- Caddy РґР»СЏ TLS Рё reverse proxy;
- Sentry-compatible error sink вЂ” РѕРїС†РёРѕРЅР°Р»СЊРЅРѕ;
- Grafana/Prometheus/Loki вЂ” production profile.

РќРµ РІРІРѕРґРёС‚СЊ Kubernetes РєР°Рє РѕР±СЏР·Р°С‚РµР»СЊРЅРѕРµ СѓСЃР»РѕРІРёРµ. Helm/Terraform РјРѕР¶РЅРѕ РґРѕР±Р°РІРёС‚СЊ РєР°Рє РґРѕРїРѕР»РЅРёС‚РµР»СЊРЅС‹Р№ deployment target РїРѕСЃР»Рµ РїРѕР»РЅРѕСЃС‚СЊСЋ СЂР°Р±РѕС‡РµРіРѕ Docker Compose.

---

## 3. РЎС‚СЂСѓРєС‚СѓСЂР° РјРѕРЅРѕСЂРµРїРѕР·РёС‚РѕСЂРёСЏ

```text
flight-hunter/
в”њв”Ђ AGENTS.md
в”њв”Ђ README.md
в”њв”Ђ Makefile
в”њв”Ђ compose.yaml
в”њв”Ђ compose.observability.yaml
в”њв”Ђ .env.example
в”њв”Ђ .github/
в”‚  в””в”Ђ workflows/
в”њв”Ђ apps/
в”‚  в”њв”Ђ web/
в”‚  в”њв”Ђ api/
в”‚  в”њв”Ђ worker/
в”‚  в””в”Ђ bot/
в”њв”Ђ packages/
в”‚  в”њв”Ђ domain/                 # С‡РёСЃС‚Р°СЏ РґРѕРјРµРЅРЅР°СЏ Р»РѕРіРёРєР°
в”‚  в”њв”Ђ application/            # use cases / orchestration
в”‚  в”њв”Ђ persistence/            # SQLAlchemy, migrations, repositories
в”‚  в”њв”Ђ providers/              # Р°РґР°РїС‚РµСЂС‹ Р°РІРёР°РґР°РЅРЅС‹С…
в”‚  в”‚  в”њв”Ђ aviasales_search/
в”‚  в”‚  в”њв”Ђ skyscanner_indicative/
в”‚  в”‚  в”њв”Ђ skyscanner_live/
в”‚  в”‚  в”њв”Ђ duffel/
в”‚  в”‚  в”њв”Ђ deal_feed/
в”‚  в”‚  в”њв”Ђ manual/
в”‚  в”‚  в””в”Ђ fake/
в”‚  в”њв”Ђ geo/                    # Р°СЌСЂРѕРїРѕСЂС‚С‹, PostGIS, nearby
в”‚  в”њв”Ђ money/                  # FX, minor units, fees
в”‚  в”њв”Ђ ranking/
в”‚  в”њв”Ђ itinerary_engine/
в”‚  в”њв”Ђ price_intelligence/
в”‚  в”њв”Ђ notifications/
в”‚  в”њв”Ђ policy/
в”‚  в”њв”Ђ llm/
в”‚  в””в”Ђ contracts/              # JSON schemas / generated clients
в”њв”Ђ docs/
в”‚  в”њв”Ђ adr/
в”‚  в”њв”Ђ api/
в”‚  в”њв”Ђ runbooks/
в”‚  в”њв”Ђ provider-contracts/
в”‚  в”њв”Ђ privacy/
в”‚  в””в”Ђ threat-model.md
в”њв”Ђ fixtures/
в”‚  в”њв”Ђ providers/
в”‚  в””в”Ђ demo/
в””в”Ђ scripts/
```

Python-РїР°РєРµС‚С‹ РјРѕРіСѓС‚ Р±С‹С‚СЊ СЂР°Р·РјРµС‰РµРЅС‹ РІ `src/flight_hunter/...`; РІР°Р¶РЅР° РіСЂР°РЅРёС†Р° РјРѕРґСѓР»РµР№, Р° РЅРµ Р±СѓРєРІР°Р»СЊРЅР°СЏ СЃС‚СЂСѓРєС‚СѓСЂР°.

---

## 4. РљР»СЋС‡РµРІРѕР№ СЃР»РѕР№: Provider Policy Engine

### 4.1. РџРѕС‡РµРјСѓ РѕРЅ РѕР±СЏР·Р°С‚РµР»РµРЅ

РћРґРёРЅР°РєРѕРІС‹Р№ HTTP client РґР»СЏ СЂР°Р·РЅС‹С… РїРѕСЃС‚Р°РІС‰РёРєРѕРІ РЅРµРґРѕСЃС‚Р°С‚РѕС‡РµРЅ. РџСЂР°РІРёР»Р° Aviasales Search, Skyscanner Live Рё Duffel СЂР°Р·Р»РёС‡Р°СЋС‚СЃСЏ. РћРіСЂР°РЅРёС‡РµРЅРёСЏ РґРѕР»Р¶РЅС‹ РїСЂРµРґРѕС‚РІСЂР°С‰Р°С‚СЊСЃСЏ РєРѕРґРѕРј.

### 4.2. РњРѕРґРµР»СЊ РїРѕР»РёС‚РёРєРё

```python
class ProviderPolicy:
    provider_id: str
    policy_version: str
    terms_url: str
    terms_verified_at: datetime

    enabled: bool
    credentials_present: bool
    access_approved: bool

    data_kind: Literal["cached", "indicative", "live", "bookable", "feed"]
    background_requests_allowed: bool
    user_action_required: bool
    merge_with_other_sources_allowed: bool
    persist_raw_results_allowed: bool
    persist_normalized_results_allowed: bool
    booking_link_requires_click: bool
    preload_booking_links_allowed: bool
    server_side_only: bool
    real_user_ip_required: bool

    max_requests_per_minute: int | None
    max_requests_per_hour_per_user_ip: int | None
    cache_ttl_seconds: int
    result_ttl_seconds: int | None
    max_concurrent_requests: int

    supports_flexible_dates: bool
    supports_nearby_airports: bool
    supports_multi_city: bool
    supports_one_way: bool
    supports_round_trip: bool
    supports_baggage: bool
    supports_fare_rules: bool

    notes: str
```

### 4.3. UserActionGrant

Р”Р»СЏ user-initiated API РєР°Р¶РґС‹Р№ Р·Р°РїСѓСЃРє С‚СЂРµР±СѓРµС‚ grant:

```python
class UserActionGrant:
    id: UUID
    user_id: UUID
    provider_id: str
    action_type: str
    request_fingerprint: str
    issued_at: datetime
    expires_at: datetime
    source: Literal["web_click", "telegram_callback", "api_request"]
    consumed_at: datetime | None
```

Grant:

- СЃРѕР·РґР°С‘С‚СЃСЏ С‚РѕР»СЊРєРѕ РїСЂРё СЂРµР°Р»СЊРЅРѕРј РґРµР№СЃС‚РІРёРё РїРѕР»СЊР·РѕРІР°С‚РµР»СЏ;
- РѕРґРЅРѕСЂР°Р·РѕРІС‹Р№;
- СЃРІСЏР·Р°РЅ СЃ РєРѕРЅРєСЂРµС‚РЅС‹РјРё РїР°СЂР°РјРµС‚СЂР°РјРё РїРѕРёСЃРєР°;
- РёРјРµРµС‚ РєРѕСЂРѕС‚РєРёР№ TTL;
- РїСЂРѕРІРµСЂСЏРµС‚СЃСЏ policy guard РґРѕ РІС‹Р·РѕРІР° РїСЂРѕРІР°Р№РґРµСЂР°;
- РЅРµ РјРѕР¶РµС‚ СЃРѕР·РґР°РІР°С‚СЊСЃСЏ worker-РѕРј.

### 4.4. РР·РѕР»СЏС†РёСЏ СЂРµР·СѓР»СЊС‚Р°С‚РѕРІ

`SearchRun` РёРјРµРµС‚ `merge_scope`:

- `MERGEABLE` вЂ” СЂР°Р·СЂРµС€РµРЅРѕ РЅРѕСЂРјР°Р»РёР·РѕРІР°С‚СЊ Рё СЃСЂР°РІРЅРёРІР°С‚СЊ СЃ РґСЂСѓРіРёРјРё РёСЃС‚РѕС‡РЅРёРєР°РјРё;
- `PROVIDER_ISOLATED` вЂ” РѕС‚РґРµР»СЊРЅР°СЏ РІС‹РґР°С‡Р°, РЅРµ РїРѕРїР°РґР°РµС‚ РІ РѕР±С‰РёР№ ranker;
- `PRIVATE_TRANSIENT` вЂ” С…СЂР°РЅРёС‚СЃСЏ С‚РѕР»СЊРєРѕ СЃ РјРёРЅРёРјР°Р»СЊРЅС‹Рј TTL.

Aviasales Search РІСЃРµРіРґР° `PROVIDER_ISOLATED`.

---

## 5. РљР°РЅРѕРЅРёС‡РµСЃРєР°СЏ РјРѕРґРµР»СЊ Р°РІРёР°РїСЂРµРґР»РѕР¶РµРЅРёСЏ

### 5.1. Р”РµРЅСЊРіРё

- С…СЂР°РЅРёС‚СЊ СЃСѓРјРјСѓ РІ integer minor units;
- С…СЂР°РЅРёС‚СЊ ISO 4217 currency;
- РѕС‚РґРµР»СЊРЅРѕ `provider_amount`, `normalized_amount`, `fx_rate`, `fx_observed_at`;
- total price РІСЃРµРіРґР° РѕС‚РЅРѕСЃРёС‚СЃСЏ Рє СЏРІРЅРѕ СѓРєР°Р·Р°РЅРЅРѕРјСѓ РЅР°Р±РѕСЂСѓ РїР°СЃСЃР°Р¶РёСЂРѕРІ;
- РєРѕРјРёСЃСЃРёРё РєР°СЂС‚С‹/FX РјРѕРґРµР»РёСЂСѓСЋС‚СЃСЏ РѕС‚РґРµР»СЊРЅРѕ Рё РЅРµ СЃРјРµС€РёРІР°СЋС‚СЃСЏ СЃ provider fare Р±РµР· label.

### 5.2. Р’СЂРµРјРµРЅР°

- РІСЃРµ timestamps РІ Р‘Р” вЂ” timezone-aware UTC;
- РґР»СЏ СЃРµРіРјРµРЅС‚Р° С…СЂР°РЅРёС‚СЊ local datetime Рё IANA timezone origin/destination;
- РґР»РёС‚РµР»СЊРЅРѕСЃС‚СЊ РІС‹С‡РёСЃР»СЏС‚СЊ РїРѕ UTC, Р° РїРѕРєР°Р·С‹РІР°С‚СЊ Р»РѕРєР°Р»СЊРЅРѕРµ РІСЂРµРјСЏ;
- DST РїРѕРєСЂС‹С‚СЊ С‚РµСЃС‚Р°РјРё.

### 5.3. РћСЃРЅРѕРІРЅС‹Рµ СЃСѓС‰РЅРѕСЃС‚Рё

#### User / Household

- `users`;
- `households`;
- `household_memberships` СЃ СЂРѕР»СЏРјРё owner/admin/member/viewer;
- invitation-only registration;
- per-user locale, timezone, base currency, Telegram preferences.

#### Airport

- IATA/ICAO/local code;
- name, municipality, country, region;
- point geography;
- timezone;
- commercial relevance;
- active/closed/type;
- metro group;
- source and source timestamp;
- admin overrides.

#### SearchIntent

- typed normalized user request;
- one-way/round-trip/multi-city;
- origin and destination sets;
- exact or flexible dates;
- trip length range;
- passengers;
- cabin;
- baggage;
- nearby radius;
- max stops;
- overnight/self-transfer/airport-change preferences;
- budget;
- weights;
- provider selection.

#### SearchRun / ProviderRun

- request fingerprint;
- actor/user action grant;
- execution mode;
- provider policy snapshot;
- status and timings;
- quota cost;
- errors classified as transient/permanent/policy;
- raw payload reference only if storage allowed.

#### Offer

- provider offer id;
- source and observed time;
- expiry;
- total money;
- passengers;
- fare products;
- baggage;
- agent/seller;
- itinerary references;
- booking action descriptor, not necessarily a pre-generated URL;
- freshness.

#### Itinerary / Slice / Segment

- itinerary type: single-ticket, split-ticket, self-transfer, hidden-city research;
- slices;
- segments;
- marketing and operating carrier;
- flight number;
- aircraft when available;
- origin/destination;
- departure/arrival;
- layover;
- terminal;
- PNR grouping;
- airport-change flag;
- overnight flag;
- protected connection flag;
- visa/entry unknown flag.

#### PriceSnapshot

- canonical offer fingerprint;
- source;
- observed amount;
- freshness;
- availability confidence;
- normalized money;
- query context;
- immutable append-only record.

#### Watch

- owner/household;
- search intent;
- schedule policy;
- alert rules;
- enabled/paused;
- allowed providers;
- last successful run;
- next eligible run;
- quiet hours;
- Telegram destinations.

#### Alert / NotificationDelivery

- reason code;
- baseline and current value;
- score and explanation inputs;
- dedupe key;
- cooldown/hysteresis state;
- rendered message version;
- delivery attempts;
- Telegram message id;
- click tracking where permitted.

---

## 6. РџРѕРёСЃРєРѕРІС‹Р№ РєРѕРЅРІРµР№РµСЂ

```mermaid
flowchart LR
  U[Web / Telegram user action] --> P[Intent parser]
  P --> V[Validation and policy planning]
  V --> D[Date and airport expansion]
  D --> Q[Provider task planner]
  Q --> G{Policy guard}
  G -->|allowed| A[Provider adapters]
  G -->|blocked| X[Explain restriction]
  A --> N[Normalize]
  N --> C[Compose itineraries]
  C --> R[Risk and total-cost model]
  R --> K[Rank / Pareto frontier]
  K --> S[Persist snapshots]
  S --> UI[Web results / Telegram summary]
```

### 6.1. Intent parser

LLM РґРѕРїСѓСЃРєР°РµС‚СЃСЏ РґР»СЏ С„СЂР°Р· РІРёРґР°:

- В«РёР· Р’Р°СЂС€Р°РІС‹ РІ РЇРїРѕРЅРёСЋ РЅР° 10вЂ“14 РґРЅРµР№ РІ РѕРєС‚СЏР±СЂРµ, РјРѕР¶РЅРѕ РёР· Р‘РµСЂР»РёРЅР°, Р±Р°РіР°Р¶ РѕРґРёРЅВ»;
- В«Р»РѕРІРё РґРѕ 1800 PLN, РјР°РєСЃРёРјСѓРј РѕРґРЅР° РїРµСЂРµСЃР°РґРєР°В».

РќРѕ LLM РІРѕР·РІСЂР°С‰Р°РµС‚ С‚РѕР»СЊРєРѕ `SearchIntentDraft` РїРѕ JSON Schema. Р—Р°С‚РµРј deterministic validator:

- СЂР°Р·СЂРµС€Р°РµС‚ РЅРµРѕРґРЅРѕР·РЅР°С‡РЅС‹Рµ РіРѕСЂРѕРґР°;
- РїСЂРѕРІРµСЂСЏРµС‚ РґР°С‚С‹;
- РЅРѕСЂРјР°Р»РёР·СѓРµС‚ РІР°Р»СЋС‚Сѓ;
- Р·Р°РїСЂР°С€РёРІР°РµС‚ РЅРµРґРѕСЃС‚Р°СЋС‰РёРµ РґР°РЅРЅС‹Рµ С‡РµСЂРµР· UI/bot;
- РЅРµ РІС‹РґСѓРјС‹РІР°РµС‚ Р°СЌСЂРѕРїРѕСЂС‚С‹, С†РµРЅС‹ РёР»Рё СЂРµР№СЃС‹.

Р‘РµР· LLM РІСЃРµ С„СѓРЅРєС†РёРё РґРѕСЃС‚СѓРїРЅС‹ С‡РµСЂРµР· РѕР±С‹С‡РЅСѓСЋ С„РѕСЂРјСѓ.

### 6.2. Expansion planner

#### Flexible dates

Р”Р»СЏ В±3 РґРЅРµР№ round trip С‚РµРѕСЂРµС‚РёС‡РµСЃРєРё 49 РєРѕРјР±РёРЅР°С†РёР№. РќРµР»СЊР·СЏ СЃР»РµРїРѕ РґРµР»Р°С‚СЊ 49 live-Р·Р°РїСЂРѕСЃРѕРІ. РђР»РіРѕСЂРёС‚Рј:

1. РџРѕР»СѓС‡РёС‚СЊ cached/indicative matrix РѕРґРЅРёРј РёР»Рё РјРёРЅРёРјР°Р»СЊРЅС‹Рј С‡РёСЃР»РѕРј Р·Р°РїСЂРѕСЃРѕРІ.
2. РћС‚С„РёР»СЊС‚СЂРѕРІР°С‚СЊ РЅРµРІРѕР·РјРѕР¶РЅС‹Рµ stay lengths.
3. РћС†РµРЅРёС‚СЊ top candidates РїРѕ С†РµРЅРµ Рё РїРѕР»СЊР·РѕРІР°С‚РµР»СЊСЃРєРёРј РѕРіСЂР°РЅРёС‡РµРЅРёСЏРј.
4. РџРѕРєР°Р·Р°С‚СЊ heatmap.
5. Live refresh РІС‹РїРѕР»РЅСЏС‚СЊ С‚РѕР»СЊРєРѕ РґР»СЏ РІС‹Р±СЂР°РЅРЅРѕР№ РїРѕР»СЊР·РѕРІР°С‚РµР»РµРј РєРѕРјР±РёРЅР°С†РёРё РёР»Рё top-N, РµСЃР»Рё РґРѕРіРѕРІРѕСЂ РїСЂСЏРјРѕ СЂР°Р·СЂРµС€Р°РµС‚.

#### Nearby airports

1. Resolve origin/destination to coordinates/metro groups.
2. PostGIS `ST_DWithin` РґР»СЏ СЂР°РґРёСѓСЃР°, РїРѕ СѓРјРѕР»С‡Р°РЅРёСЋ РґРѕ 150 РєРј.
3. РћС‚С„РёР»СЊС‚СЂРѕРІР°С‚СЊ Р°СЌСЂРѕРїРѕСЂС‚С‹ Р±РµР· IATA, Р·Р°РєСЂС‹С‚С‹Рµ Рё РєРѕРјРјРµСЂС‡РµСЃРєРё РЅРµСЂРµР»РµРІР°РЅС‚РЅС‹Рµ.
4. Р Р°СЃСЃС‡РёС‚Р°С‚СЊ great-circle distance.
5. Р”РѕР±Р°РІРёС‚СЊ РїСЂРёР±Р»РёР·РёС‚РµР»СЊРЅС‹Рµ ground time/cost СЃ confidence label.
6. РќРµ СЃС‡РёС‚Р°С‚СЊ РґР°Р»С‘РєРёР№ Р°СЌСЂРѕРїРѕСЂС‚ РІС‹РіРѕРґРЅС‹Рј, РµСЃР»Рё РЅР°Р·РµРјРЅС‹Р№ С‚СЂР°РЅСЃС„РµСЂ СЃСЉРµРґР°РµС‚ СЌРєРѕРЅРѕРјРёСЋ.

#### Candidate budget

Planner РїРѕР»СѓС‡Р°РµС‚ request budget:

- max provider calls;
- max date combinations;
- max airport pairs;
- max total execution time;
- max monetary API cost, РµСЃР»Рё РїСЂРѕРІР°Р№РґРµСЂ С‚Р°СЂРёС„РёС†РёСЂСѓРµС‚СЃСЏ.

РСЃРїРѕР»СЊР·РѕРІР°С‚СЊ beam search: СЃРЅР°С‡Р°Р»Р° РґРµС€С‘РІС‹Рµ/РІРµСЂРѕСЏС‚РЅС‹Рµ РєРѕРјР±РёРЅР°С†РёРё, Р·Р°С‚РµРј СЂР°СЃС€РёСЂРµРЅРёРµ РїСЂРё РЅР°Р»РёС‡РёРё Р±СЋРґР¶РµС‚Р°.

### 6.3. Provider task planner

РќР° РєР°Р¶РґС‹Р№ candidate С„РѕСЂРјРёСЂСѓРµС‚ Р·Р°РґР°С‡Сѓ СЃ:

- provider;
- query parameters;
- execution mode;
- `UserActionGrant`, РµСЃР»Рё С‚СЂРµР±СѓРµС‚СЃСЏ;
- quota reservation;
- idempotency key;
- deadline;
- result merge scope.

### 6.4. РќРѕСЂРјР°Р»РёР·Р°С†РёСЏ

РљР°Р¶РґС‹Р№ adapter РІРѕР·РІСЂР°С‰Р°РµС‚ provider-specific DTO. Mapper СЃРѕР·РґР°С‘С‚ canonical `OfferCandidate` Рё СЃРѕС…СЂР°РЅСЏРµС‚:

- provenance РєР°Р¶РґРѕРіРѕ РїРѕР»СЏ;
- РЅРµРёР·РІРµСЃС‚РЅС‹Рµ Р·РЅР°С‡РµРЅРёСЏ РєР°Рє `unknown`, РЅРµ `false`;
- raw field bag С‚РѕР»СЊРєРѕ РµСЃР»Рё policy СЂР°Р·СЂРµС€Р°РµС‚;
- parsing warnings.

### 6.5. Р”РµРґСѓРїР»РёРєР°С†РёСЏ

Canonical fingerprint СЃС‚СЂРѕРёС‚СЃСЏ РёР·:

- ordered segments;
- operating carrier + flight number;
- local departure date/time;
- airports;
- cabin;
- fare family;
- baggage;
- seller/agent;
- passenger mix.

Р”РІР° РїСЂРµРґР»РѕР¶РµРЅРёСЏ СЃ РѕРґРёРЅР°РєРѕРІС‹Рј itinerary, РЅРѕ СЂР°Р·РЅС‹РјРё РїСЂРѕРґР°РІС†Р°РјРё РёР»Рё СѓСЃР»РѕРІРёСЏРјРё, РЅРµ С‚РµСЂСЏСЋС‚СЃСЏ: UI РіСЂСѓРїРїРёСЂСѓРµС‚ РёС…, РЅРѕ С…СЂР°РЅРёС‚ РѕС‚РґРµР»СЊРЅС‹Рµ offers.

---

## 7. Itinerary Engine

### 7.1. Р’РёРґС‹ РјР°СЂС€СЂСѓС‚РѕРІ

- РїСЂСЏРјРѕР№;
- РѕР±С‹С‡РЅР°СЏ РїРµСЂРµСЃР°РґРєР° РЅР° РѕРґРЅРѕРј Р±РёР»РµС‚Рµ;
- multi-city/open jaw;
- РєРѕРјР±РёРЅР°С†РёСЏ one-way Р±РёР»РµС‚РѕРІ;
- split ticket;
- self-transfer;
- positioning flight;
- airport change;
- hidden-city research вЂ” РѕС‚РґРµР»СЊРЅС‹Р№ experimental СЂРµР¶РёРј.

### 7.2. Р“СЂР°С„РѕРІР°СЏ РјРѕРґРµР»СЊ

- vertex: `(airport, timestamp window, state)`;
- edge: flight offer slice РёР»Рё ground transfer;
- edge attributes: price, duration, provider, PNR, baggage, expiry, risk;
- path constraints: minimum connection, maximum total duration, max stops, airport-change policy, overnight policy, visa/entry unknown, terminal transition.

РСЃРїРѕР»СЊР·РѕРІР°С‚СЊ constrained k-shortest paths РёР»Рё beam search, Р° РЅРµ РїРѕР»РЅС‹Р№ РїРµСЂРµР±РѕСЂ.

### 7.3. Minimum connection

Р•СЃР»Рё provider РЅРµ РґР°С‘С‚ Р·Р°С‰РёС‰С‘РЅРЅРѕСЃС‚СЊ/Minimum Connection Time:

- РЅРµ СѓС‚РІРµСЂР¶РґР°С‚СЊ, С‡С‚Рѕ РїРµСЂРµСЃР°РґРєР° РіР°СЂР°РЅС‚РёСЂРѕРІР°РЅР°;
- РёСЃРїРѕР»СЊР·РѕРІР°С‚СЊ РєРѕРЅСЃРµСЂРІР°С‚РёРІРЅС‹Рµ configurable defaults;
- РґР»СЏ self-transfer РґРѕР±Р°РІР»СЏС‚СЊ buffer РїРѕ С‚РёРїСѓ Р°СЌСЂРѕРїРѕСЂС‚Р°, domestic/international, terminal/airport change Рё baggage;
- РІС‹СЃРѕРєРёР№ СЂРёСЃРє РёСЃРєР»СЋС‡Р°С‚СЊ РёР· default results.

### 7.4. Split tickets

Split-ticket candidate РґРѕР»Р¶РµРЅ СЃРѕРґРµСЂР¶Р°С‚СЊ:

- РѕС‚РґРµР»СЊРЅС‹Рµ PNR/Р·Р°РєР°Р·С‹;
- РѕР±С‰РёР№ total price;
- baggage recheck requirement;
- connection buffer;
- missed-connection risk;
- immigration/visa uncertainty;
- РѕС‚РґРµР»СЊРЅС‹Рµ РїСЂР°РІРёР»Р° РёР·РјРµРЅРµРЅРёСЏ/РІРѕР·РІСЂР°С‚Р°;
- СЏРІРЅРѕРµ СЃСЂР°РІРЅРµРЅРёРµ СЃ Р»СѓС‡С€РёРј single-ticket РІР°СЂРёР°РЅС‚РѕРј.

РџРѕРєР°Р·С‹РІР°С‚СЊ С‚РѕР»СЊРєРѕ РµСЃР»Рё СЌРєРѕРЅРѕРјРёСЏ РїСЂРµРІС‹С€Р°РµС‚ configurable minimum РїРѕСЃР»Рµ РЅР°Р·РµРјРЅС‹С… СЂР°СЃС…РѕРґРѕРІ Рё risk penalty.

### 7.5. Hidden-city research

Feature flag РІС‹РєР»СЋС‡РµРЅ РїРѕ СѓРјРѕР»С‡Р°РЅРёСЋ. Р РµР¶РёРј:

- РЅРµ РІРєР»СЋС‡Р°РµС‚СЃСЏ РІ РѕР±С‰РёР№ В«Р›СѓС‡С€РёР№В» СЂРµР№С‚РёРЅРі;
- С‚СЂРµР±СѓРµС‚ СЏРІРЅРѕРіРѕ РїРѕРґС‚РІРµСЂР¶РґРµРЅРёСЏ РїСЂРµРґСѓРїСЂРµР¶РґРµРЅРёСЏ;
- РЅРµ Р°РІС‚РѕРјР°С‚РёР·РёСЂСѓРµС‚ РїРѕРєСѓРїРєСѓ;
- РЅРµ РїСЂРµРґР»Р°РіР°РµС‚ checked baggage;
- РїРѕРєР°Р·С‹РІР°РµС‚ СЂРёСЃРє Р°РЅРЅСѓР»РёСЂРѕРІР°РЅРёСЏ РїРѕСЃР»РµРґСѓСЋС‰РёС… СЃРµРіРјРµРЅС‚РѕРІ, РїСЂРѕР±Р»РµРј СЃ РѕР±СЂР°С‚РЅС‹Рј Р±РёР»РµС‚РѕРј, rerouting Рё РїРѕСЃР»РµРґСЃС‚РІРёР№ РїРѕ РїСЂР°РІРёР»Р°Рј Р°РІРёР°РєРѕРјРїР°РЅРёРё;
- С…СЂР°РЅРёС‚ СЃРѕР±С‹С‚РёРµ acknowledgement;
- РЅР°Р·С‹РІР°РµС‚СЃСЏ В«РёСЃСЃР»РµРґРѕРІР°С‚РµР»СЊСЃРєРёР№ РІР°СЂРёР°РЅС‚В», Р° РЅРµ В«Р»Р°Р№С„С…Р°Рє Р±РµР· СЂРёСЃРєР°В».

---

## 8. Ranking Рё РѕР±СЉСЏСЃРЅРёРјРѕСЃС‚СЊ

### 8.1. Pareto frontier

РЎРЅР°С‡Р°Р»Р° РёСЃРєР»СЋС‡РёС‚СЊ dominated РІР°СЂРёР°РЅС‚С‹ РїРѕ:

- total trip cost;
- total duration;
- number of stops;
- risk;
- freshness;
- baggage fit.

Р—Р°С‚РµРј weighted score РїРѕ РїСЂРѕС„РёР»СЋ РїРѕР»СЊР·РѕРІР°С‚РµР»СЏ.

### 8.2. РљРѕРјРїРѕРЅРµРЅС‚С‹ score

```text
value_score =
  w_price * normalized_price
+ w_duration * normalized_duration
+ w_stops * stop_penalty
+ w_risk * risk_penalty
+ w_airport * ground_transfer_penalty
+ w_baggage * baggage_penalty
+ w_freshness * freshness_penalty
+ w_schedule * departure_time_penalty
```

РќРµ РёСЃРїРѕР»СЊР·РѕРІР°С‚СЊ В«РјР°РіРёС‡РµСЃРєРёРµВ» РІРµСЃР° Р±РµР· РѕС‚РѕР±СЂР°Р¶РµРЅРёСЏ. РџРѕР»СЊР·РѕРІР°С‚РµР»СЊ РјРѕР¶РµС‚ РІС‹Р±СЂР°С‚СЊ preset:

- РЎР°РјС‹Р№ РґРµС€С‘РІС‹Р№;
- Р›СѓС‡С€РёР№ Р±Р°Р»Р°РЅСЃ;
- РЎР°РјС‹Р№ Р±С‹СЃС‚СЂС‹Р№;
- РњРёРЅРёРјСѓРј СЂРёСЃРєР°;
- РЎ Р±Р°РіР°Р¶РѕРј;
- РЎРµРјРµР№РЅС‹Р№.

### 8.2.1. Implemented offer risk contract

Current priced offers expose a deterministic `risk` object from
`flight_hunter.itinerary_engine.risk`:

- `level`: `low`, `medium` or `high`;
- `flags`: `cached_price`, `stale_price`, `requires_live_confirmation`, `baggage_unknown`,
  `provider_single_adult_ticket` or `unknown_freshness`;
- `explanations`: deterministic text derived from domain fields, never provider free text.

This contract covers existing direct priced offers only. It does not create split-ticket,
self-transfer or hidden-city candidates. Future itinerary composition can add more flags while
keeping the same API shape.

### 8.3. Total trip cost

РџРѕРјРёРјРѕ fare:

- baggage fees, РµСЃР»Рё РёР·РІРµСЃС‚РЅС‹;
- seat/ancillary вЂ” РѕС‚РґРµР»СЊРЅРѕ Рё С‚РѕР»СЊРєРѕ РµСЃР»Рё РёР·РІРµСЃС‚РЅС‹;
- card FX/foreign transaction fee РїРѕ РїРѕР»СЊР·РѕРІР°С‚РµР»СЊСЃРєРѕР№ РЅР°СЃС‚СЂРѕР№РєРµ;
- estimated ground transfer;
- overnight hotel estimate вЂ” optional Рё РїРѕРјРµС‡РµРЅ РєР°Рє estimate;
- positioning flight;
- self-transfer contingency.

РќРµ РґРѕР±Р°РІР»СЏС‚СЊ РЅРµРёР·РІРµСЃС‚РЅС‹Рµ СЂР°СЃС…РѕРґС‹ РєР°Рє С‚РѕС‡РЅС‹Рµ С‡РёСЃР»Р°. РСЃРїРѕР»СЊР·РѕРІР°С‚СЊ ranges/confidence.

### 8.4. Explainability

Р”Р»СЏ РєР°Р¶РґРѕРіРѕ СЂРµР·СѓР»СЊС‚Р°С‚Р° deterministic explanation facts:

- В«РЅР° 18% РґРµС€РµРІР»Рµ РјРµРґРёР°РЅС‹ РІР°С€РёС… 42 РЅР°Р±Р»СЋРґРµРЅРёР№В»;
- В«РЅР° 320 PLN РґРµС€РµРІР»Рµ Р»СѓС‡С€РµРіРѕ single-ticket, РЅРѕ РґРІР° PNRВ»;
- В«Р°СЌСЂРѕРїРѕСЂС‚ РІ 112 РєРј; РѕС†РµРЅРєР° С‚СЂР°РЅСЃС„РµСЂР° 2 С‡ 10 РјРёРЅВ»;
- В«С†РµРЅР° cached, РЅР°Р±Р»СЋРґР°Р»Р°СЃСЊ 5 С‡Р°СЃРѕРІ РЅР°Р·Р°РґВ»;
- В«С‚Р°СЂРёС„ Р±РµР· Р·Р°СЂРµРіРёСЃС‚СЂРёСЂРѕРІР°РЅРЅРѕРіРѕ Р±Р°РіР°Р¶Р°В».

LLM РјРѕР¶РµС‚ РїСЂРµРІСЂР°С‚РёС‚СЊ facts РІ С‡РёС‚Р°РµРјС‹Р№ С‚РµРєСЃС‚, РЅРѕ РЅРµ РґРѕР±Р°РІР»СЏРµС‚ РЅРѕРІС‹Рµ СѓС‚РІРµСЂР¶РґРµРЅРёСЏ.

---

## 9. Price Intelligence

### 9.1. РСЃС‚РѕСЂРёСЏ

РЎРѕС…СЂР°РЅСЏС‚СЊ append-only snapshots. РќРµ РїРµСЂРµР·Р°РїРёСЃС‹РІР°С‚СЊ РїСЂРѕС€Р»С‹Рµ С†РµРЅС‹. Р”Р»СЏ РѕРґРёРЅР°РєРѕРІРѕРіРѕ РЅР°Р±Р»СЋРґРµРЅРёСЏ РґРѕРїСѓСЃРєР°РµС‚СЃСЏ compaction СЃ count, РЅРѕ РёСЃС…РѕРґРЅР°СЏ РІСЂРµРјРµРЅРЅР°СЏ РїРѕСЃР»РµРґРѕРІР°С‚РµР»СЊРЅРѕСЃС‚СЊ РґРѕР»Р¶РЅР° РІРѕСЃСЃС‚Р°РЅР°РІР»РёРІР°С‚СЊСЃСЏ.

### 9.2. Buy-now score

РќРµ СЃСѓС‰РµСЃС‚РІСѓРµС‚ hardcoded В«СЃР°РјРѕРіРѕ РґРµС€С‘РІРѕРіРѕ РІС‚РѕСЂРЅРёРєР° РІ 02:00В». РћС†РµРЅРєР° СЃС‚СЂРѕРёС‚СЃСЏ РїРѕ РґР°РЅРЅС‹Рј РєРѕРЅРєСЂРµС‚РЅРѕРіРѕ watch:

- percentile С‚РµРєСѓС‰РµР№ С†РµРЅС‹;
- robust z-score РѕС‚РЅРѕСЃРёС‚РµР»СЊРЅРѕ РјРµРґРёР°РЅС‹/MAD;
- recent slope;
- volatility;
- days to departure;
- С‡РёСЃР»Рѕ РЅР°Р±Р»СЋРґРµРЅРёР№;
- freshness;
- cross-source confirmation;
- seat/fare expiry, РµСЃР»Рё РёР·РІРµСЃС‚РЅРѕ.

РџСЂРё РЅРµРґРѕСЃС‚Р°С‚РєРµ РґР°РЅРЅС‹С… РїРѕРєР°Р·С‹РІР°С‚СЊ `INSUFFICIENT_DATA`, Р° РЅРµ СѓРІРµСЂРµРЅРЅС‹Р№ СЃРѕРІРµС‚.

### 9.3. Suspected error fare

Anomaly detector:

```text
anomaly_score =
  route_price_ratio_score
+ historical_robust_z_score
+ cross_market_gap_score
+ cross_provider_confirmation_score
- stale_data_penalty
- impossible_itinerary_penalty
- missing_fees_penalty
```

РўСЂРµР±РѕРІР°РЅРёСЏ:

- СЃСЂР°РІРЅРёРІР°С‚СЊ РѕРґРёРЅР°РєРѕРІС‹Р№ passenger mix/cabin/baggage;
- РёСЃРєР»СЋС‡Р°С‚СЊ РѕС€РёР±РѕС‡РЅСѓСЋ РІР°Р»СЋС‚Сѓ Рё one-way/round-trip mismatch;
- РїСЂРѕРІРµСЂСЏС‚СЊ, С‡С‚Рѕ itinerary РІР°Р»РёРґРµРЅ;
- РїРѕ РІРѕР·РјРѕР¶РЅРѕСЃС‚Рё РґРµР»Р°С‚СЊ СЂР°Р·СЂРµС€С‘РЅРЅС‹Р№ refresh;
- label: В«РїРѕРґРѕР·СЂРµРЅРёРµ РЅР° Р°РЅРѕРјР°Р»СЊРЅРѕ РЅРёР·РєСѓСЋ С†РµРЅСѓВ»;
- РЅРёРєРѕРіРґР° РЅРµ РѕР±РµС‰Р°С‚СЊ, С‡С‚Рѕ Р±РёР»РµС‚ Р±СѓРґРµС‚ РІС‹РїРёСЃР°РЅ;
- СѓРІРµРґРѕРјР»РµРЅРёРµ РґРѕР»Р¶РЅРѕ СЃРѕРІРµС‚РѕРІР°С‚СЊ РїСЂРѕРІРµСЂРёС‚СЊ СѓСЃР»РѕРІРёСЏ Рё РЅРµ СЃС‚СЂРѕРёС‚СЊ РЅРµРІРѕР·РІСЂР°С‚РЅС‹Рµ РїР»Р°РЅС‹ РґРѕ ticketing confirmation.

### 9.4. Р“РѕСЂСЏС‰РёРµ РЅР°РїСЂР°РІР»РµРЅРёСЏ

`DealScanner` СЂР°Р±РѕС‚Р°РµС‚ С‚РѕР»СЊРєРѕ РЅР° РёСЃС‚РѕС‡РЅРёРєР°С…, СЂР°Р·СЂРµС€Р°СЋС‰РёС… background discovery. РћРЅ РЅРµ РїРµСЂРµР±РёСЂР°РµС‚ РІРµСЃСЊ РјРёСЂ live-Р·Р°РїСЂРѕСЃР°РјРё. РЎС‚СЂР°С‚РµРіРёСЏ:

1. РџРѕР»СЊР·РѕРІР°С‚РµР»СЊ Р·Р°РґР°С‘С‚ origin set, СЂРµРіРёРѕРЅС‹, РїРµСЂРёРѕРґ, РґР»РёС‚РµР»СЊРЅРѕСЃС‚СЊ, Р±СЋРґР¶РµС‚.
2. РџРѕР»СѓС‡РёС‚СЊ popular/alternative directions Рё cached/indicative matrix.
3. РЎС„РѕСЂРјРёСЂРѕРІР°С‚СЊ РѕРіСЂР°РЅРёС‡РµРЅРЅС‹Р№ candidate set.
4. РЎСЂР°РІРЅРёС‚СЊ СЃ СЃРѕР±СЃС‚РІРµРЅРЅРѕР№ РёСЃС‚РѕСЂРёРµР№.
5. РћС‚РїСЂР°РІРёС‚СЊ alert РїСЂРё РїСЂРµРІС‹С€РµРЅРёРё deal threshold.
6. РџСЂРµРґР»РѕР¶РёС‚СЊ РєРЅРѕРїРєСѓ В«РџСЂРѕРІРµСЂРёС‚СЊ liveВ», РєРѕС‚РѕСЂР°СЏ СЃРѕР·РґР°С‘С‚ UserActionGrant.

---

## 10. Watch Scheduler

### 10.1. РџСЂРёРЅС†РёРїС‹

- provider policy РІС‹С€Рµ РїРѕР»СЊР·РѕРІР°С‚РµР»СЊСЃРєРѕРіРѕ Р¶РµР»Р°РЅРёСЏ;
- adaptive interval;
- quota-aware;
- jitter;
- exponential backoff;
- circuit breaker;
- distributed lock;
- idempotency;
- dead-letter queue;
- quiet hours РѕС‚РЅРѕСЃСЏС‚СЃСЏ Рє РґРѕСЃС‚Р°РІРєРµ, Р° РЅРµ РѕР±СЏР·Р°С‚РµР»СЊРЅРѕ Рє СЃР±РѕСЂСѓ;
- РЅРµ РІС‹РїРѕР»РЅСЏС‚СЊ Р±РµСЃСЃРјС‹СЃР»РµРЅРЅС‹Рµ Р·Р°РїСЂРѕСЃС‹ РїРѕСЃР»Рµ РІС‹Р»РµС‚Р°/РёСЃС‚РµС‡РµРЅРёСЏ watch.

### 10.2. РџСЂРёРјРµСЂ Р±Р°Р·РѕРІРѕР№ С‡Р°СЃС‚РѕС‚С‹

РўРѕР»СЊРєРѕ РґР»СЏ РёСЃС‚РѕС‡РЅРёРєРѕРІ, СЂР°Р·СЂРµС€Р°СЋС‰РёС… background:

- >120 РґРЅРµР№: СЂР°Р· РІ 24 С‡Р°СЃР°;
- 61вЂ“120 РґРЅРµР№: СЂР°Р· РІ 12 С‡Р°СЃРѕРІ;
- 15вЂ“60 РґРЅРµР№: СЂР°Р· РІ 6 С‡Р°СЃРѕРІ;
- 3вЂ“14 РґРЅРµР№: СЂР°Р· РІ 2 С‡Р°СЃР°;
- <72 С‡Р°СЃРѕРІ: СЂР°Р· РІ 1 С‡Р°СЃ С‚РѕР»СЊРєРѕ РµСЃР»Рё provider policy Рё quota СЌС‚Рѕ РґРѕРїСѓСЃРєР°СЋС‚;
- cached API РІСЃС‘ СЂР°РІРЅРѕ РЅРµ РѕРїСЂР°С€РёРІР°С‚СЊ С‡Р°С‰Рµ, С‡РµРј РѕР±РЅРѕРІР»СЏРµС‚СЃСЏ РїРѕР»РµР·РЅР°СЏ РёРЅС„РѕСЂРјР°С†РёСЏ.

Р­С‚Рѕ defaults, Р° РЅРµ РѕР±РµС‰Р°РЅРёРµ. Scheduler СѓС‡РёС‚С‹РІР°РµС‚ `cache_ttl`, `last_modified`, quota Рё РѕС‚СЃСѓС‚СЃС‚РІРёРµ РёР·РјРµРЅРµРЅРёР№.

### 10.3. Alert hysteresis

РќРѕРІС‹Р№ alert С‚РѕР»СЊРєРѕ РµСЃР»Рё:

- С†РµРЅР° РЅРёР¶Рµ absolute threshold; РёР»Рё
- РїР°РґРµРЅРёРµ Р±РѕР»СЊС€Рµ X%; РёР»Рё
- РЅРѕРІС‹Р№ historical low; РёР»Рё
- deal score РїРµСЂРµСЃС‘Рє threshold;
- Рё РёР·РјРµРЅРµРЅРёРµ РјР°С‚РµСЂРёР°Р»СЊРЅРѕ РѕС‚РЅРѕСЃРёС‚РµР»СЊРЅРѕ РїРѕСЃР»РµРґРЅРµРіРѕ РѕС‚РїСЂР°РІР»РµРЅРЅРѕРіРѕ;
- Рё cooldown РёСЃС‚С‘Рє, РєСЂРѕРјРµ РЅРѕРІРѕРіРѕ СЃРёР»СЊРЅРѕРіРѕ СЂРµРєРѕСЂРґР°.

Р”РµРґСѓРїР»РёРєР°С†РёСЏ РїРѕ `(watch, canonical itinerary group, reason bucket, price bucket)`.

---

## 11. Telegram

### 11.1. Production mode

- webhook С‡РµСЂРµР· HTTPS;
- РїСЂРѕРІРµСЂРєР° `X-Telegram-Bot-Api-Secret-Token`;
- idempotency РїРѕ `update_id`;
- long polling С‚РѕР»СЊРєРѕ РґР»СЏ local development;
- token С‚РѕР»СЊРєРѕ РІ secret store/env;
- bot РЅРµ РґРѕРІРµСЂСЏРµС‚ Telegram username РєР°Рє РёРґРµРЅС‚РёС„РёРєР°С‚РѕСЂСѓ Р°РєРєР°СѓРЅС‚Р°.

### 11.2. Linking

1. РђРІС‚РѕСЂРёР·РѕРІР°РЅРЅС‹Р№ web-РїРѕР»СЊР·РѕРІР°С‚РµР»СЊ РіРµРЅРµСЂРёСЂСѓРµС‚ РѕРґРЅРѕСЂР°Р·РѕРІС‹Р№ link code.
2. РќР°Р¶РёРјР°РµС‚ deep link `/start <code>`.
3. Backend СЃРІСЏР·С‹РІР°РµС‚ Telegram user id СЃ account.
4. Code РѕРґРЅРѕСЂР°Р·РѕРІС‹Р№ Рё РєРѕСЂРѕС‚РєРѕР¶РёРІСѓС‰РёР№.
5. Р’ РЅР°СЃС‚СЂРѕР№РєР°С… РјРѕР¶РЅРѕ РѕС‚РѕР·РІР°С‚СЊ СЃРІСЏР·СЊ.

### 11.3. РљРѕРјР°РЅРґС‹

- `/start`;
- `/search` вЂ” guided flow;
- `/watch` вЂ” СЃРѕР·РґР°С‚СЊ РѕС‚СЃР»РµР¶РёРІР°РЅРёРµ;
- `/watches`;
- `/pause` Рё `/resume`;
- `/deals`;
- `/settings`;
- `/link`;
- `/help`.

РћСЃРЅРѕРІРЅРѕР№ UX вЂ” inline keyboards Рё Web App/deep links, Р° РЅРµ РґР»РёРЅРЅС‹Рµ РєРѕРјР°РЅРґС‹.

### 11.4. РЈРІРµРґРѕРјР»РµРЅРёРµ

Р”РѕР»Р¶РЅРѕ РїРѕРјРµС‰Р°С‚СЊ РіР»Р°РІРЅРѕРµ РІ РїРµСЂРІС‹Р№ СЌРєСЂР°РЅ:

```text
рџ”Ґ РќРѕРІС‹Р№ РјРёРЅРёРјСѓРј: WAW в†’ NRT
2 184 PLN Р·Р° 2 РїР°СЃСЃР°Р¶РёСЂРѕРІ В· в€’17% РѕС‚ РјРµРґРёР°РЅС‹
12вЂ“25 РѕРєС‚СЏР±СЂСЏ В· 1 РїРµСЂРµСЃР°РґРєР° В· 16С‡ 40Рј
РСЃС‚РѕС‡РЅРёРє: cached, РЅР°Р±Р»СЋРґР°Р»РѕСЃСЊ 18 РјРёРЅСѓС‚ РЅР°Р·Р°Рґ
Р‘Р°РіР°Р¶: СЂСѓС‡РЅР°СЏ РєР»Р°РґСЊ; checked bag РЅРµРёР·РІРµСЃС‚РµРЅ

[РћС‚РєСЂС‹С‚СЊ СЃСЂР°РІРЅРµРЅРёРµ] [РџСЂРѕРІРµСЂРёС‚СЊ live] [РќРµ СѓРІРµРґРѕРјР»СЏС‚СЊ 24С‡]
```

РќРµ РѕС‚РїСЂР°РІР»СЏС‚СЊ booking link Р·Р°СЂР°РЅРµРµ, РµСЃР»Рё РїРѕР»РёС‚РёРєР° РїСЂРѕРІР°Р№РґРµСЂР° С‚СЂРµР±СѓРµС‚ РіРµРЅРµСЂР°С†РёСЋ РїРѕСЃР»Рµ РєР»РёРєР°.

---

## 12. Web UI

### 12.1. РћСЃРЅРѕРІРЅС‹Рµ СЌРєСЂР°РЅС‹

1. **Dashboard**
   - Р°РєС‚РёРІРЅС‹Рµ watches;
   - Р»СѓС‡С€РёРµ РёР·РјРµРЅРµРЅРёСЏ;
   - provider health;
   - РЅРѕРІС‹Рµ deals;
   - Р±Р»РёР¶Р°Р№С€РёРµ РїРѕРµР·РґРєРё.

2. **Search**
   - structured form + natural-language input;
   - airport/city autosuggest;
   - date flexibility;
   - trip length;
   - passengers/baggage/cabin;
   - nearby radius;
   - risk preferences;
   - provider selection with policy explanations.

3. **Results**
   - progress via SSE;
   - tabs best/cheapest/fastest/lowest risk;
   - separate provider-isolated workspace;
   - date heatmap;
   - grouped sellers;
   - full segment details;
   - freshness/provenance labels;
   - compare drawer;
   - create watch.

4. **Watch detail**
   - price history;
   - alert timeline;
   - best current options;
   - scheduler status;
   - thresholds;
   - pause/resume/archive.

5. **Deals**
   - anomaly/deal feed;
   - filters by origin, region, dates, budget;
   - confidence and caveats.

6. **Settings**
   - user profile;
   - currency/timezone/locale;
   - Telegram;
   - quiet hours;
   - card FX fee;
   - risk presets.

7. **Admin**
   - invitations;
   - providers and policy status;
   - credentials presence, never plaintext;
   - quotas and circuit breakers;
   - job health;
   - data imports;
   - audit log;
   - backup status.

### 12.2. UX С‚СЂРµР±РѕРІР°РЅРёСЏ

- responsive PWA;
- WCAG AA baseline;
- keyboard navigation;
- dark/light mode;
- RU and EN from day one, locale architecture РіРѕС‚РѕРІР° Рє PL;
- skeleton/progress without fake results;
- errors explain provider failure and next action;
- cached/live distinction visible, not hidden in tooltip;
- no dark patterns around booking buttons.

---

## 13. API surface

РџСЂРёРјРµСЂРЅС‹Рµ endpoints:

```text
POST   /api/v1/auth/invitations
POST   /api/v1/telegram/link-codes
POST   /api/v1/searches
GET    /api/v1/searches/{id}
GET    /api/v1/searches/{id}/events          # SSE
POST   /api/v1/searches/{id}/live-refresh    # user action grant
POST   /api/v1/offers/{id}/booking-action    # click-gated
GET    /api/v1/airports/autocomplete
GET    /api/v1/airports/nearby
POST   /api/v1/watches
GET    /api/v1/watches
GET    /api/v1/watches/{id}
PATCH  /api/v1/watches/{id}
POST   /api/v1/watches/{id}/pause
POST   /api/v1/watches/{id}/resume
GET    /api/v1/watches/{id}/history
GET    /api/v1/deals
GET    /api/v1/providers
GET    /api/v1/admin/providers/health
POST   /api/v1/admin/imports/airports
POST   /api/v1/privacy/export
DELETE /api/v1/account
```

Р’СЃРµ mutating endpoints РїРѕРґРґРµСЂР¶РёРІР°СЋС‚ idempotency key, РіРґРµ СЌС‚Рѕ СЂР°Р·СѓРјРЅРѕ. OpenAPI РіРµРЅРµСЂРёСЂСѓРµС‚ frontend client.

---

## 14. Р‘РµР·РѕРїР°СЃРЅРѕСЃС‚СЊ Рё РїСЂРёРІР°С‚РЅРѕСЃС‚СЊ

- invitation-only;
- Argon2id РґР»СЏ РїР°СЂРѕР»РµР№, РµСЃР»Рё password auth РІРєР»СЋС‡С‘РЅ;
- РїСЂРµРґРїРѕС‡С‚РёС‚РµР»СЊРЅРѕ OIDC/passkeys/magic link;
- secure, HTTP-only, SameSite cookies;
- CSRF protection;
- RBAC РЅР° household/admin boundaries;
- provider secrets Р·Р°С€РёС„СЂРѕРІР°РЅС‹ at rest РёР»Рё РїРµСЂРµРґР°СЋС‚СЃСЏ С‡РµСЂРµР· secret manager;
- secrets РЅРёРєРѕРіРґР° РЅРµ РїРѕРїР°РґР°СЋС‚ РІ frontend, logs, fixtures, exports;
- outbound host allowlist РґР»СЏ provider adapters;
- Р·Р°С‰РёС‚Р° РѕС‚ SSRF;
- timeout/size limits РґР»СЏ HTTP;
- signed webhook secrets;
- audit log РґР»СЏ admin/provider changes;
- rate limits РЅР° auth/search/Telegram actions;
- dependency and secret scanning;
- encrypted backups;
- data export/delete;
- configurable retention РґР»СЏ raw provider payloads;
- threat model РІ СЂРµРїРѕР·РёС‚РѕСЂРёРё.

---

## 15. Observability

### РњРµС‚СЂРёРєРё

- search latency per provider;
- provider error rate;
- 429 rate;
- quota remaining;
- cache hit ratio;
- scheduler lag;
- watch success age;
- offers normalized/rejected;
- alert count/dedupe count;
- Telegram delivery failures;
- SSE active sessions;
- DB pool saturation.
- `/api/v1/metrics` exposes process-local Prometheus text for provider calls, browser observation
  starts, parser offer counts, search duration and sent alerts; labels stay low-cardinality and do
  not include ids, tokens, URLs or message text.

### Р›РѕРіРё

- JSON structured;
- correlation id, search run id, provider run id;
- current safe application events: `search_started`, `provider_call`,
  `browser_observation_started`, `parser_result`, `alert_sent`;
- event fields stay low-cardinality and safe: ids, source/provider names, endpoint names, counts,
  confidence/warning codes, delivery reason and durations;
- no raw token, PII, full booking URL or card data;
- policy denial logged as event, not exception noise.

### Tracing

HTTP request в†’ planner в†’ provider calls в†’ normalization в†’ ranking в†’ notification.

### Runbooks

- provider returns 429;
- provider schema changed;
- Telegram webhook broken;
- scheduler backlog;
- airport import failed;
- database restore;
- secret rotation.

---

## 16. Testing

### Unit

- money conversions/minor units;
- date expansion;
- nearby airport selection;
- itinerary graph constraints;
- risk score;
- ranking;
- anomaly detection;
- policy guard;
- alert hysteresis;
- timezone/DST.

### Property-based

- no itinerary arrives before it departs in UTC;
- no connection violates configured buffer;
- rank score finite for incomplete data;
- currency round-trip error bounded;
- dedupe stable under provider ordering;
- policy guard never permits background call when disallowed.

### Provider contract

- recorded/sanitized fixtures;
- schema validation;
- unknown fields tolerated;
- required field disappearance fails clearly;
- 429/retry-after;
- timeout/partial results;
- expired offers;
- no live calls in CI.

### Integration

- PostgreSQL/PostGIS + Redis via testcontainers;
- migrations up/down or forward-only verification;
- worker idempotency;
- Telegram webhook secret;
- SSE event order;
- provider policy snapshots.

### E2E

- invite в†’ sign in;
- create search;
- view matrix;
- create watch;
- fake provider price drop;
- Telegram fake sink receives one alert;
- pause/resume;
- booking click gate;
- admin disables provider;
- RU/EN and mobile viewport.

### Coverage gates

- domain/policy/ranking/itinerary modules: в‰Ґ85%;
- backend total: в‰Ґ75%;
- frontend critical flows covered; numeric coverage secondary to meaningful assertions.

---

## 17. Deployment

`docker compose up --build` РґРѕР»Р¶РµРЅ Р·Р°РїСѓСЃРєР°С‚СЊ:

- web;
- api;
- worker;
- bot (disabled gracefully without token or fake mode);
- postgres/postgis;
- redis;
- reverse proxy;
- optional fake provider/demo seeder.

Production checklist:

- TLS;
- strong secrets;
- external volumes;
- scheduled backups and restore drill;
- health/readiness endpoints;
- migrations as explicit release step;
- image pinning by digest or immutable tag;
- non-root containers;
- resource limits;
- restart policies;
- log rotation;
- alerting.

---

## 18. РђСЂС…РёС‚РµРєС‚СѓСЂРЅС‹Рµ Р·Р°РїСЂРµС‚С‹

- РќРµ СЃРІСЏР·С‹РІР°С‚СЊ РґРѕРјРµРЅ СЃ РєРѕРЅРєСЂРµС‚РЅС‹Рј provider response.
- РќРµ РІС‹Р·С‹РІР°С‚СЊ live API РёР· frontend.
- РќРµ С…СЂР°РЅРёС‚СЊ РґРµРЅСЊРіРё РєР°Рє float.
- РќРµ СЃСЂР°РІРЅРёРІР°С‚СЊ С†РµРЅС‹ Р±РµР· passenger/cabin/baggage normalization.
- РќРµ Р·Р°РїСѓСЃРєР°С‚СЊ 49 live-РїРѕРёСЃРєРѕРІ РґР»СЏ В±3 РґРЅРµР№ Р°РІС‚РѕРјР°С‚РёС‡РµСЃРєРё.
- РќРµ РѕР±СЉРµРґРёРЅСЏС‚СЊ provider-isolated results.
- РќРµ СЃРѕР·РґР°РІР°С‚СЊ booking link РґРѕ РїРѕР»СЊР·РѕРІР°С‚РµР»СЊСЃРєРѕРіРѕ РєР»РёРєР°, РµСЃР»Рё Р·Р°РїСЂРµС‰РµРЅРѕ.
- РќРµ РІС‹РґР°РІР°С‚СЊ cached С†РµРЅСѓ Р·Р° live.
- РќРµ РёСЃРїРѕР»СЊР·РѕРІР°С‚СЊ LLM РґР»СЏ Р°СЂРёС„РјРµС‚РёРєРё, РјР°СЂС€СЂСѓС‚РёР·Р°С†РёРё РёР»Рё policy decisions.
- РќРµ РґРµР»Р°С‚СЊ scraping fallback В«РЅР° РІСЃСЏРєРёР№ СЃР»СѓС‡Р°Р№В».
- РќРµ РѕР±С…РѕРґРёС‚СЊ CAPTCHA/Р°РЅС‚РёР±РѕС‚/РіРµРѕРіСЂР°С„РёС‡РµСЃРєРёРµ РѕРіСЂР°РЅРёС‡РµРЅРёСЏ.
- РќРµ РѕС‚РїСЂР°РІР»СЏС‚СЊ РїРѕРІС‚РѕСЂСЏСЋС‰РёРµСЃСЏ Telegram alerts Р±РµР· material change.
- РќРµ РѕСЃС‚Р°РІР»СЏС‚СЊ TODO, fake implementation РёР»Рё РјРѕРє РІ production path.
