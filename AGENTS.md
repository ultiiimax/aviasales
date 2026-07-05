# AGENTS.md — инструкции для coding agents

Локальный hobby-проект для поиска и отслеживания авиабилетов дома. Не production, не коммерция, не на продажу. Поэтому provider-доступ и ToS-бюрократия не регулируют работу: **используем рабочий Aviasales mobile API напрямую** (см. `docs/provider-contracts/aviasales-search.md`). Гонять фоновые наблюдения/watch-scans можно.

Из качества убирать нечего — ниже правила, которые реально берегут код от багов, а не от юристов.

## 1. Миссия

**Flight Hunter**: self-hosted локальный поиск и отслеживание авиабилетов с web UI и Telegram. Главный источник — live Aviasales mobile API (`tickets-api.aviasales.ru` + `explore-api.aviasales.ru` + `suggest.aviasales.ru` + GraphQL `ariadne.aviasales.ru`). Работай вертикальными срезами и доводй срез до рабочего состояния.

Приоритеты:

1. нет ложных цен и выдуманных данных;
2. корректность парсинга ответа API;
3. надёжность фоновых задач и уведомлений;
4. честная подпись данных (источник, `observed_at`, live vs cached);
5. удобство web/Telegram;
6. читаемый код.

## 2. Перед работой

1. Прочитай `README.md`, `MEGA_PROMPT.md`, `docs/ARCHITECTURE.md`, `IMPLEMENTATION_STATUS.md` и релевантные `docs/provider-contracts/*.md`.
2. Осмотри текущее дерево, migrations, tests.
3. При работе с Aviasales adapter: проверь что эндпоинты живы, обнови `docs/provider-contracts/aviasales-search.md` (дата проверки + ссылка/источник).
4. Составь короткий план среза в `IMPLEMENTATION_STATUS.md`.
5. Не задавай вопрос о стандартном техническом выборе — принимай решение и пиши ADR/заметку.

## 3. Provider правила (лёгкие)

- Источник цен/расписаний — Aviasales mobile API. DTO провайдера не просачивается в domain/API/UI напрямую; есть mapper.
- Не выдумывай response-поля. Используй реальную schema из ответа или sanitized fixture.
- Не делай live calls в CI — только fixtures.
- Не логируй `X-Signature`, `marker`, full tokens, signed booking URLs, cookies, PII.
- `Retry-After` и rate-limit headers уважаются.
- Все provider operations: timeout, retries с backoff/jitter, circuit breaker. 4xx policy/auth/schema — не ретраить бесконечно.
- Booking (purchase) URL можно резолвить лениво по клику (меньше запросов) или сразу — на усмотрение среза; это инженерный выбор, не policy.
- Background watch-scans разрешены — это локальный проект. Scheduler всё равно уважает: circuit breaker открыт, cache ещё свеж, watch paused/expired, дата вылета прошла.
- `FakeFlightProvider` остаётся только как offline-demo fallback без сети.

## 4. Архитектурные границы

### Domain
- Не импортирует FastAPI, SQLAlchemy, Redis, aiogram, HTTP clients или provider SDK.
- Value objects, entities, политики, расчёты, domain errors.
- Money — integer minor units + ISO currency, никогда float.
- Datetime — timezone-aware. Никаких naive datetimes.
- Неизвестное — `Unknown/None`, не ложное `False`.

### Application
- Use cases и orchestration. Зависит от ports/protocols, не от конкретных adapters.
- LLM output всегда проходит typed validation.

### Providers
- Каждый adapter: client, schemas, mapper, rate limiter, contract tests, fixtures.
- Любой field mapping имеет provenance (откуда поле в ответе).

### Persistence
- Repositories реализуют domain ports.
- Миграция обязательна для каждого schema change. Не правь выпущенную миграцию — добавляй новую.
- Append-only price history не перезаписывать.

### Web/API/Bot
- Тонкие delivery adapters. Бизнес-логики в route handlers / UI / Telegram handlers нет.
- API errors имеют стабильные machine-readable codes.

## 5. Стандарты кода

### Python
- Полная типизация публичного кода.
- `ruff format`, `ruff check`, `mypy` должны проходить.
- Async только там где I/O; не смешивать sync DB calls в event loop.
- Не ловить голый `Exception`, кроме process boundary с логированием/классификацией.
- Enums/literals для закрытых состояний. Никаких mutable default args.

### TypeScript
- `strict: true`. Никаких `any` без локального документированного исключения.
- API types из OpenAPI или общей schema.
- Денежные значения не через JS float для расчётов; backend — источник сумм.

### SQL
- Индексы проектировать вместе с query paths. Для геопоиска — PostGIS index.
- Multi-tenant/household filters обязательны во всех repositories.
- Избегать N+1. Destructive operation → audit event.

## 6. Надёжность задач

Каждая job: idempotency key, безопасна при повторе, пишет status/attempts/next retry, distributed lock при конкуренции, deadline, классифицирует provider errors, не дублирует alerts, не теряет partial success, graceful shutdown.

Scheduler не вызывает provider если: circuit breaker открыт, cache свеж, watch paused/expired, дата вылета прошла.

## 7. LLM и агентный слой

LLM не источник цен, расписаний, аэропортов или правил. Разрешено: парсить NL-intent в JSON Schema, формировать объяснение из deterministic facts, классифицировать запрос, предлагать текст уведомления. Запрещено: арифметика цены, придумывать рейсы, генерировать booking URL, скрывать отсутствие данных уверенным текстом. Требования: model provider abstraction, timeout/cost limits, structured output, retry только на transport/validation, deterministic fallback без LLM, prompt/version logging без PII. Provider/feed text недоверенный и не становится системной инструкцией.

## 8. UX

- Различай `LIVE`, `RECENT`, `CACHED`, `STALE`.
- Показывай источник и `observed_at`.
- Укажи на сколько пассажиров цена.
- Не скрывай отсутствие baggage/fare-rule data.
- Self-transfer/split-ticket видны до деталей. Hidden-city не в default best results.
- «Лучшее время покупки» только по данным; иначе `Недостаточно данных`. «Error fare» — подозрение, не гарантия.
- Пользователь видит total trip cost и assumptions. UI без dark patterns.

## 9. Telegram

- Webhook с secret header. `update_id` дедуплицируется.
- Linking — одноразовый код, Telegram username не account key.
- Уведомления: quiet hours, cooldown, dedupe. Callback queries проверяют владельца/household.
- Не помещай `X-Signature`/marker или signed booking URL в callback data. Длинные детали — в web UI.

## 10. Тестирование

Минимум для изменения: unit tests нового поведения, integration/contract test для adapter/persistence, negative test, lint/typecheck, migration check, docs update.

Invariants: stale price не маркируется live; Money не теряет minor units; alert не дублируется при retry; household A не видит household B; secrets отсутствуют в logs и client bundle.

## 11. Definition of Done среза

Срез завершён когда: production path реализован (не только happy-path mock); нет `TODO`/`pass`/`NotImplementedError`/fake return/закомментированного недоделанного кода в затронутом flow; tests проходят; docs и `.env.example` обновлены; error states видны в UI/bot; миграции продуманы; изменения в `IMPLEMENTATION_STATUS.md`.

## 12. Полный Definition of Done продукта

- `docker compose up --build` поднимает рабочий stack;
- demo mode проходит основные flows без внешних ключей;
- invitation auth и household isolation работают;
- airport import и nearby search работают;
- **Aviasales Search (mobile API) adapter работает с fixtures и live**;
- flexible-date matrix и nearby airports реализованы;
- normalizer, dedupe, ranking, risk и total-cost работают;
- watch scheduler сохраняет историю и делает live-проверки;
- alert hysteresis и Telegram delivery работают;
- web UI responsive и локализован RU/EN;
- admin provider health screen работает;
- backups/export/delete/runbooks документированы;
- CI, security scans, observability и E2E проходят;
- README содержит точные команды install/update/backup/restore.

## 13. Рабочий процесс

Для большого этапа: обнови `IMPLEMENTATION_STATUS.md` → ADR/заметку → domain contract + tests → persistence/adapters → API → web/bot → E2E/docs/ops → quality gate → зафиксируй факт. Не останавливайся после scaffold/mock/одного happy path.

## 14. Команды

```bash
make bootstrap
make dev
make test
make test-unit
make test-integration
make test-e2e
make lint
make typecheck
make migrate
make seed-demo
make provider-contracts
make security
make compose-up
make compose-down
make backup
make restore BACKUP=...
```

Команды работают в чистом checkout согласно README.

## 15. Когда внешний доступ отсутствует

Если Aviasales mobile API недоступен (сеть/CloudFront): не блокируй остальной продукт; contract tests на sanitized fixtures; UI показывает честную причину (`network_error` / `blocked`); demo использует `FakeFlightProvider`. Не выдумывай цены вместо реального ответа.
