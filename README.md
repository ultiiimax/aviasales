# Flight Hunter 1.0.0

Локальный поиск и отслеживание авиабилетов с web UI, фоновым worker и
Telegram-доставкой. Основной live-источник — Aviasales mobile API. Без внешних
ключей приложение работает в честном offline demo через `FakeFlightProvider`.

Релиз рассчитан на один компьютер и слушает только
`http://127.0.0.1:8000`. Публичный сервер, reverse proxy и публикация в интернет
в v1.0.0 не поддерживаются.

## Что входит в v1

- поиск, нормализация, дедупликация, ranking, risk и total cost;
- live Aviasales search, suggest, hot offers, calendar и GraphQL blocks;
- lazy resolve ссылки покупки только по короткоживущему booking token;
- invitation/session auth и household isolation;
- watches, append-only история цен, hysteresis и durable worker jobs;
- Telegram webhook/outbox, quiet hours, cooldown и dedupe;
- SQLite/Alembic, backup/verify/restore, health/readiness endpoints;
- русский responsive web UI и локальные Playwright E2E.

## Требования

- Windows 10/11 или Linux;
- Python 3.13;
- [uv](https://docs.astral.sh/uv/);
- Git;
- опционально Docker Desktop с запущенным Linux engine;
- опционально Chromium для browser E2E/personal observer.

## Рекомендуемый локальный запуск

Из корня репозитория:

```powershell
uv sync --frozen --group dev
uv run flight-hunter-init-local
uv run alembic upgrade head
```

Initializer создаёт `.env`, генерирует `APP_SECRET_KEY` и
`AUTH_BOOTSTRAP_TOKEN`, выбирает локальную SQLite и оставляет внешние провайдеры
выключенными. Существующий `.env` он не перезаписывает без `--force`.

Запусти API:

```powershell
uv run uvicorn flight_hunter.api.app:app --host 127.0.0.1 --port 8000
```

Во втором PowerShell запусти worker:

```powershell
uv run flight-hunter-worker --loop --idle-sleep-seconds 10
```

Открой `http://127.0.0.1:8000`. Проверки процесса:

```powershell
Invoke-RestMethod http://127.0.0.1:8000/healthz
Invoke-RestMethod http://127.0.0.1:8000/readyz
uv run flight-hunter-worker-healthcheck --role flight_hunter_worker
```

### Первый владелец

Сначала создай одноразовое owner invitation. Команда читает bootstrap token из
локального `.env`, но не печатает его:

```powershell
$bootstrapToken = (Select-String -Path .env -Pattern '^AUTH_BOOTSTRAP_TOKEN=(.+)$').Matches[0].Groups[1].Value
$headers = @{ 'X-Flight-Hunter-Bootstrap-Token' = $bootstrapToken }
$body = @{ household_name = 'Моя семья'; recipient_label = 'owner' } | ConvertTo-Json
$invitation = Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8000/api/v1/auth/bootstrap-invitation -Headers $headers -ContentType 'application/json' -Body $body
$invitation.invitation_code
```

В web UI введи полученный код и имя. После входа session token хранится в
локальном browser storage. В релизе обязательно:

```env
AUTH_ALLOW_LEGACY_HEADERS=false
```

После создания владельца можно очистить `AUTH_BOOTSTRAP_TOKEN` в `.env` и
перезапустить API/worker. Это выключит выпуск новых bootstrap invitations.

## Demo без внешней сети

Стандартный `.env`, созданный initializer-ом, уже настроен на demo:

```env
AVIASALES_SEARCH_ENABLED=false
TELEGRAM_ENABLED=false
PERSONAL_OBSERVER_ENABLED=false
```

Поиск возвращает только детерминированные demo-предложения и явно подписывает
их источником. Demo-данные никогда не маркируются как live Aviasales.

## Live Aviasales

Полученные из локально исследованного mobile-клиента значения добавь только в
`.env`:

```env
AVIASALES_SEARCH_ENABLED=true
AVIASALES_SEARCH_SIGNATURE=<local-mobile-signature>
AVIASALES_SEARCH_MARKER=mobile_app.<32-lowercase-hex>
AVIASALES_SEARCH_INTERNAL_RPM=20
```

Не коммить и не вставляй эти значения в issue, лог или клиентский bundle.
Сначала выполни безопасные smoke checks:

```powershell
uv run flight-hunter-source-smoke --source aviasales_search
uv run flight-hunter-source-smoke --source aviasales_search --exact-search --origin MOW --destination LED --departure-offset-days 30
```

Вывод содержит только status/code/count/source/freshness: без цен, offer IDs,
provider refs, сырых ответов и booking URL. `blocked`, `rate_limited`,
`auth_failed` и `unavailable` остаются честными кодами ошибок.

Контракт: `docs/provider-contracts/aviasales-search.md`.

## Docker Compose

Нужен запущенный Docker Desktop Linux engine. Сначала создай `.env`, затем
подними API и worker:

```powershell
uv run flight-hunter-init-local
docker compose config --quiet
docker compose up --build
```

Compose применяет миграции только в API, ждёт `/readyz` перед запуском worker,
использует общий named volume и публикует только `127.0.0.1:8000`.

Статус и остановка:

```powershell
docker compose ps
docker compose logs --tail 100 api worker
docker compose down
```

`docker compose down` сохраняет named volume. Не добавляй `--volumes`, если не
хочешь удалить локальную базу и backups внутри volume.

## Browser runtime и E2E

Chromium не входит в минимальный runtime. Установка выполняется явно:

```powershell
uv run flight-hunter-browser-bootstrap
uv run flight-hunter-browser-smoke
uv run pytest tests/e2e -q -m browser_e2e --strict-markers
```

Если runtime отсутствует, browser job завершается кодом
`browser_runtime_unavailable`; это не маскируется под ошибку источника.

## Проверка релиза

Credential-free gate:

```powershell
uv run flight-hunter-release-check
```

Полная локальная проверка с Chromium:

```powershell
uv run flight-hunter-release-check --include-browser
```

Docker build включается отдельно и требует работающий engine:

```powershell
uv run flight-hunter-release-check --include-docker-build
```

Результаты release-check — JSONL с отдельным status/code каждого этапа. Live
Aviasales smoke в credential-free gate не входит.

## Backup, restore и update

Прямой локальный backup:

```powershell
uv run flight-hunter-backup --database .\flight_hunter_dev.db --backup-dir .\backups
uv run flight-hunter-backup-verify .\backups\flight_hunter_YYYYMMDDTHHMMSSZ.db
```

Restore делай при остановленных API и worker:

```powershell
uv run flight-hunter-restore .\backups\flight_hunter_YYYYMMDDTHHMMSSZ.db --database .\flight_hunter_dev.db
uv run alembic upgrade head
```

Перед update всегда делай и проверяй backup. Полные direct/Docker команды,
rollback и restore drill:

- `docs/runbooks/local-deployment.md`;
- `docs/runbooks/backup-restore.md`.

## Основные endpoints

- `POST /api/v1/searches` — агрегированный поиск;
- `POST /api/v1/booking-actions/resolve` — lazy purchase URL;
- `GET /api/v1/aviasales/suggest`;
- `GET /api/v1/aviasales/hot-offers`;
- `GET /api/v1/aviasales/calendar`;
- `GET /api/v1/aviasales/graphql/main-page-blocks`;
- `POST /api/v1/searches/date-matrix`;
- `GET /healthz`, `GET /readyz`;
- `GET /api/v1/providers`, `GET /api/v1/source-contracts`.

Search responses показывают источник, `observed_at`, freshness и число
пассажиров. Raw provider refs и purchase URLs не выдаются в поиске, логах или
Telegram callback data.

## Документация

- `CHANGELOG.md` — состав релиза;
- `SECURITY.md` — граница безопасности;
- `docs/ARCHITECTURE.md` — реализованная и целевая архитектура;
- `docs/provider-contracts/aviasales-search.md` — mobile API contract;
- `IMPLEMENTATION_STATUS.md` — свежие результаты проверок.
