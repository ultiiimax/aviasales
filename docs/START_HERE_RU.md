# START HERE RU

Коротко и по делу.

## Что это

Flight Hunter - локальный self-hosted поиск и наблюдение за авиабилетами.

Главный источник цен сейчас - Aviasales mobile API:

- live search: `tickets-api.aviasales.ru`;
- suggest: `suggest.aviasales.ru`;
- hot offers/calendar: `explore-api.aviasales.ru`;
- typed GraphQL blocks: `ariadne.aviasales.ru`.

Без внешних ключей проект всё равно работает в demo/offline режиме через `FakeFlightProvider`.

## Быстрый запуск

```powershell
make bootstrap
uv run alembic upgrade head
uv run uvicorn flight_hunter.api.app:app --reload --host 127.0.0.1 --port 8000
```

Открыть:

```text
http://127.0.0.1:8000/
```

## Включить Aviasales mobile API

В `.env`:

```env
APP_SECRET_KEY=replace-with-strong-random-secret
AVIASALES_SEARCH_ENABLED=true
AVIASALES_SEARCH_SIGNATURE=replace-with-provider-signature
AVIASALES_SEARCH_MARKER=mobile_app.replace-with-md5-of-android-id
AVIASALES_SEARCH_INTERNAL_RPM=20
```

Проверка источника:

```powershell
uv run flight-hunter-source-smoke --source aviasales_search
```

Smoke печатает только summary: source/status/code/counts. Секреты, marker, raw payload и ссылки покупки не печатает.

## Что смотреть

- `GET /` - web UI.
- `POST /api/v1/searches` - live offers.
- `POST /api/v1/booking-actions/resolve` - получить purchase URL только по short-lived token.
- `GET /api/v1/aviasales/suggest`
- `GET /api/v1/aviasales/hot-offers`
- `GET /api/v1/aviasales/calendar`
- `GET /api/v1/aviasales/graphql/main-page-blocks`
- `GET /api/v1/source-contracts`
- `GET /api/v1/admin/providers/health`

## Worker

Один проход:

```powershell
uv run flight-hunter-worker --fixture-html tests/fixtures/browser/tutu/search_result_source_specific.html
```

Лупы по ролям:

```powershell
uv run flight-hunter-worker --role watch --loop
uv run flight-hunter-worker --role telegram --loop
uv run flight-hunter-worker --role maintenance --loop
```

## Telegram

Нужен только Telegram bot token:

```env
TELEGRAM_ENABLED=true
TELEGRAM_BOT_TOKEN=...
TELEGRAM_WEBHOOK_SECRET=replace-me
```

## Качество

```powershell
uv run pytest tests/unit --disable-warnings -q
uv run pytest tests/integration -q --disable-warnings
uv run ruff format --check .
uv run ruff check .
uv run mypy
uv run alembic upgrade head
uv run flight-hunter-security-scan
```
