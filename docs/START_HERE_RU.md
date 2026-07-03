# Flight Hunter: старт без техномагии

Эта страница для нормального человеческого запуска. Без “подними кластер”, “сконфигурируй всё на свете” и прочего тумана.

## Коротко

Сейчас можно запустить demo API без ключей и аккаунтов.

Для этого нужен только `uv`, менеджер Python-проектов.

## Что установить

### 1. uv

Официальная установка для Windows:

```powershell
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
```

Проверить:

```powershell
uv --version
```

Источник: https://docs.astral.sh/uv/

### 2. Python отдельно ставить обычно не надо

`uv` сам скачает подходящий Python для проекта.

Если хотите поставить руками: https://www.python.org/downloads/

## Как запустить то, что уже есть

Откройте PowerShell в папке проекта:

```powershell
cd "C:\Users\kiwun\Документы\CHEAP AIR FLY"
```

Установите зависимости:

```powershell
uv sync --group dev
```

Если хотите попробовать локальный Personal Browser Observer, установите опциональные browser/crawler
зависимости и Chromium для Playwright:

```powershell
uv sync --group dev --group scraping --group crawler
uv run playwright install chromium
```

Если хотите создать локальную demo-базу:

```powershell
uv run alembic upgrade head
```

Backup локальной demo-базы:

```powershell
uv run flight-hunter-backup
```

Verify backup manifest:

```powershell
uv run flight-hunter-backup-verify .\backups\ИМЯ_BACKUP.db
```

Restore из backup-файла:

```powershell
uv run flight-hunter-restore .\backups\ИМЯ_BACKUP.db
```

Посмотреть, сколько истекших live-check записей будет очищено:

```powershell
uv run flight-hunter-cleanup-live-observations --dry-run
```

Если у вас есть локальный OurAirports `airports.csv`, импортируйте справочник:

```powershell
uv run flight-hunter-import-airports --airports-csv .\data\airports.csv
```

Файл берётся локально. Команда не скачивает данные сама, не требует API key и пишет
только справочник аэропортов/статус импорта.

Запустите demo API:

```powershell
uv run uvicorn flight_hunter.api.app:app --reload --host 127.0.0.1 --port 8000
```

Откройте в браузере:

- http://127.0.0.1:8000/
- http://127.0.0.1:8000/healthz
- http://127.0.0.1:8000/docs

`/` — экран с чатом агента, формой поиска, источниками и результатами.

`/docs` — техническая страница, где можно нажимать API руками.

## Что попробовать в `/docs`

### Проверить, что сервер жив

Откройте `GET /healthz`.

Ожидаемый смысл ответа: `status: ok`.

### Посмотреть источники

Откройте `GET /api/v1/providers`.

Вы увидите:

- `fake` включён;
- реальные источники выключены;
- рядом показано, почему они выключены.

Это нормально. Без ключей проект всё равно работает в demo mode.

Чтобы увидеть не только runtime-статус, но и карту готовности интеграций,
откройте `GET /api/v1/source-contracts`. Там видно, какие источники уже
`implemented`, какие являются `policy_skeleton`, а какие пока `contract_only`.

### Сделать demo-поиск

Откройте `POST /api/v1/searches` и вставьте:

```json
{
  "origin": "WAW",
  "destination": "BCN",
  "departure_date": "2026-10-12",
  "return_date": "2026-10-19",
  "passengers": 2,
  "currency": "PLN"
}
```

Важно: это demo-результат от `FakeFlightProvider`. Он нужен, чтобы проверить логику приложения без внешних ключей. Он не выдаётся за реальную цену.

### Проверить соседние аэропорты

Откройте:

```text
GET /api/v1/airports/nearby?iata_code=WAW&radius_km=150
```

Проект покажет расстояния, но не будет говорить “вы сэкономите”. Расстояние — это только факт, не обещание цены.

### Попробовать чат агента

Откройте `/` и напишите:

```text
из Варшавы в Барселону 2026-10-12 2026-10-19 следи
```

Агент покажет варианты аэропортов, безопасные действия, даты +/- 3 дня и создаст
watch только потому, что в фразе явно есть просьба следить. Live-проверка всё равно
остаётся отдельной кнопкой.

## Что мне нужно от вас

### Сейчас, чтобы продолжать разработку

Ничего обязательного.

Я могу продолжать строить demo mode, базу, web UI, Telegram-заглушку, scheduler и тесты без ваших внешних ключей.

### Когда захотите реальные cached-цены Aviasales Data API

Нужны:

- аккаунт Travelpayouts;
- API token;
- marker, если хотите affiliate/click-out сценарии позже.

Где взять token:

1. Зайдите в Travelpayouts.
2. Откройте профиль.
3. Откройте вкладку API token.

Официальная инструкция: https://support.travelpayouts.com/hc/en-us/articles/13024069738386-Where-to-find-API-token

Потом вы дадите значения для:

```env
TRAVELPAYOUTS_API_TOKEN=...
TRAVELPAYOUTS_MARKER=...
AVIASALES_DATA_ENABLED=true
```

Не присылайте ключи в чат, если не уверены. Лучше вставлять их локально в `.env`.

Локально это выглядит так:

```powershell
Copy-Item .env.example .env
notepad .env
```

В `.env` поменяйте только эти строки:

```env
AVIASALES_DATA_ENABLED=true
TRAVELPAYOUTS_API_TOKEN=ВАШ_TOKEN
```

`TRAVELPAYOUTS_MARKER` можно оставить пустым на текущем этапе.

После этого перезапустите demo API. В `GET /api/v1/providers` источник `aviasales_data` должен стать включённым.

Если token уже отправлялся в чат или чужой сервис, лучше потом перевыпустить его в Travelpayouts.

Проверить token одним безопасным cached-запросом:

```powershell
uv run travelpayouts-smoke
```

Команда не печатает token, booking links или raw payload. Она показывает только `ok`, код результата, количество найденных cached-записей и время ответа.

Общий smoke для optional sources:

```powershell
uv run flight-hunter-source-smoke --source aviasales_data
uv run flight-hunter-source-smoke --source searxng
uv run flight-hunter-source-smoke --source crawl4ai --url https://example.com/
```

`searxng` и `crawl4ai` без включённых env flags вернут disabled-состояние, а не fake success.

### Когда захотите Telegram-бота

Нужны:

- Telegram bot token;
- имя бота;
- позже — публичный HTTPS URL для webhook, если это production.

Где взять bot token:

1. В Telegram откройте `@BotFather`.
2. Напишите `/newbot`.
3. Следуйте шагам.
4. Сохраните token.

Официальная инструкция Telegram: https://core.telegram.org/bots/tutorial

Потом значения пойдут в:

```env
TELEGRAM_ENABLED=true
TELEGRAM_BOT_TOKEN=...
TELEGRAM_WEBHOOK_URL=...
TELEGRAM_WEBHOOK_SECRET=...
```

Для локальной разработки можно оставить Telegram выключенным.

### Когда дойдём до self-hosted production

Понадобятся:

- домен, например `flights.example.com`;
- VPS или домашний сервер;
- email владельца для первого admin-аккаунта;
- сильные секреты для приложения;
- решение, нужны ли Telegram alerts сразу.

Секрет можно сгенерировать так:

```powershell
uv run python -c "import secrets; print(secrets.token_urlsafe(48))"
```

## Что можно не трогать

Пока не нужны:

- Skyscanner;
- Duffel;
- Aviasales Search API;
- OpenAI/LLM key;
- scraping;
- proxies;
- Kubernetes.

Aviasales Search API отдельно ограничен: он требует подтверждённый доступ и не подходит для фонового сбора. Поэтому он выключен по умолчанию.

## Agent mode без магии

Сейчас агентный режим работает как typed chat-orchestrator и набор понятных
пресетов, а не как бот, который сам парсит сайты:

- чатовый turn endpoint понимает простые фразы с городами/датами;
- города резолвятся в варианты аэропортов, неоднозначность не угадывается;
- watch создаётся только по явной просьбе “следи/мониторь/уведомляй”;
- когда покупать;
- даты вылета +/- 3 дня;
- аэропорты рядом в радиусе 150 км;
- hidden-city только как отдельный рискованный режим;
- split ticket с предупреждением про самостоятельную пересадку;
- error fare источники после актуальной проверки;
- страна сайта авиакомпании и валюта оплаты.

Попробовать можно в `/docs`:

- `POST /api/v1/agent/chat/turn`;
- `GET /api/v1/airports/search?q=Варшава`;
- `GET /api/v1/agent/presets`;
- `POST /api/v1/agent/plan`.

Для этого не нужен OpenAI key, Codex OAuth или MCP server. По умолчанию стоит
`AGENT_PROVIDER=deterministic_presets`, `AGENT_CODEX_CLI_ENABLED=false` и
`AGENT_OPENAI_ENABLED=false`.

Если нужен OpenAI-backed агент для разбора естественного языка, включайте его отдельно:

- `OPENAI_API_KEY=...`;
- `AGENT_OPENAI_ENABLED=true`;
- `AGENT_OPENAI_MODEL=gpt-5.5`;
- понимание, что OpenAI output проходит typed validation и не может быть источником цен,
  расписаний, provider policy или live-проверок.

Если нужен локальный агент через Codex CLI, включайте его отдельно:

- установленный Codex CLI;
- исправный `~/.codex/config.toml` (`service_tier` должен быть `fast` или `flex`);
- `AGENT_CODEX_CLI_ENABLED=true`;
- понимание, что Codex output проходит typed validation и не может быть источником цен.

Live-цены агент сам не собирает. Он может предложить кнопку "обновить live", но
такая проверка идет не чаще одного раза в 10 минут:

```env
LIVE_REFRESH_MIN_GAP_SECONDS=600
```

## Откуда брать live-цены

Нормальный путь: официальные API и партнерские доступы.

- Travelpayouts/Aviasales Data API - cached цены, не live.
- Aviasales Search API - live, но только после подтвержденного доступа и действия пользователя.
- Skyscanner Live, Duffel, Amadeus/NDC - только после официального доступа и проверки правил.

Парсить страницы агрегаторов или авиакомпаний можно только если это явно разрешено
их правилами. В проекте не используются CAPTCHA bypass, stealth, fingerprint
spoofing, rotating proxies, чужие cookies или обход геолокации.

## Текущая модель для RUB и покупки снаружи

Покупки внутри приложения не будет. Flight Hunter ищет и объясняет цены, а покупать
пользователь идет наружу:

- Aviasales / Travelpayouts Data API - cached цена внутри приложения;
- Aviasales, Яндекс Путешествия, Туту, OneTwoTrip - click-out на внешний поиск;
- Аэрофлот, Победа, S7 и другие перевозчики - click-out на официальный сайт;
- финальная цена всегда подтверждается снаружи перед покупкой.

В API это видно здесь:

```text
GET /api/v1/price-sources
GET /api/v1/source-contracts
```

Scraping observer можно будет включать только точечно:

```env
PERSONAL_OBSERVER_ENABLED=false
PERSONAL_OBSERVER_REQUIRE_USER_ACTION=true
PERSONAL_OBSERVER_AUTO_RUN=false
PERSONAL_OBSERVER_MIN_GAP_SECONDS=60
```

Deal discovery is also user-triggered and disabled unless SearXNG/Crawl4AI are configured. Its
results are stored as manual-verification hints scoped by household/user/search and expire by TTL:

```env
CRAWL4AI_ENABLED=false
SEARXNG_ENABLED=false
SEARXNG_BASE_URL=http://127.0.0.1:8080
DEAL_CANDIDATE_TTL_SECONDS=86400
DEAL_DISCOVERY_JOB_DEADLINE_SECONDS=600
```

Локальный SearXNG можно поднять отдельным compose profile:

```powershell
docker compose --profile deal-discovery up --build
```

Сейчас его безопаснее пробовать на sanitized fixture без сети:

```powershell
uv run flight-hunter-observe --source tutu --origin MOW --destination IST --depart 2026-09-10 --return-date 2026-09-20 --fixture-html tests/fixtures/browser/tutu/search_result_source_specific.html
```

Если web/API уже поставил personal observation job в очередь, отдельный worker CLI выполняет его
так:

```powershell
uv run flight-hunter-run-personal-observation --job-id JOB_UUID --fixture-html tests/fixtures/browser/tutu/search_result_source_specific.html
```

Для локального polling loop используйте общий worker. Он забирает только уже queued user-action
jobs, включая durable deal-discovery jobs и personal browser jobs, соблюдает attempts/next retry
и не создаёт browser/provider вызовы сам:

```powershell
uv run flight-hunter-worker --loop --idle-sleep-seconds 5 --fixture-html tests/fixtures/browser/tutu/search_result_source_specific.html
```

For production supervision, split worker lanes into separate processes while keeping the same
DB-backed claims and policy gates:

```powershell
uv run flight-hunter-worker --role browser --loop --fixture-html tests/fixtures/browser/tutu/search_result_source_specific.html
uv run flight-hunter-worker --role watch --loop
uv run flight-hunter-worker --role deal --loop
uv run flight-hunter-worker --role telegram --loop
uv run flight-hunter-worker --role maintenance --loop
```

Admin health shows `current_job_kind`/`current_job_id`, so active and stale work are visible
without parsing worker logs.

Даже если live-режим включить, он не будет делать CAPTCHA solving, stealth,
fingerprint spoofing, proxy rotation, использовать чужие cookies или закрытые
страницы. Такие цены будут называться `browser_observed`, а не гарантированной
доступностью билета, и живут коротко.

## Простая карта проекта

```text
src/flight_hunter/api            HTTP endpoints
src/flight_hunter/application    сценарии приложения
src/flight_hunter/domain         чистые правила и объекты
src/flight_hunter/geo            аэропорты и расстояния
src/flight_hunter/policy         правила provider calls
src/flight_hunter/providers      источники данных
src/flight_hunter/notifications  alert logic
tests/unit                       проверки
docs/adr                         решения по архитектуре
```

## Если что-то сломалось

### `uv` не найден

Закройте и заново откройте PowerShell. Потом:

```powershell
uv --version
```

### Порт 8000 занят

Запустите на другом порту:

```powershell
uv run uvicorn flight_hunter.api.app:app --reload --host 127.0.0.1 --port 8001
```

Откройте http://127.0.0.1:8001/docs

### Не хочется разбираться с API

Откройте http://127.0.0.1:8000/ — там уже есть простая форма поиска, список источников и результаты.
