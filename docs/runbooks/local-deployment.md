# Local Deployment Runbook — v1.0.0

Дата: 2026-07-15. Поддерживаемая схема: один компьютер, loopback HTTP,
FastAPI + основной worker + agent-worker + SQLite. Публичная публикация не
поддерживается.

## 1. Первый прямой запуск

```powershell
uv sync --frozen --group dev
uv run flight-hunter-init-local
uv run alembic upgrade head
uv run uvicorn flight_hunter.api.app:app --host 127.0.0.1 --port 8000
```

Во втором PowerShell:

```powershell
uv run flight-hunter-worker --loop --roles browser,watch,deal,telegram,maintenance --idle-sleep-seconds 10
```

В третьем PowerShell для одобренных agent runs:

```powershell
uv run flight-hunter-worker --loop --roles agent --idle-sleep-seconds 10
```

Для live agent execution в `.env` обязательны валидные
`AVIASALES_SEARCH_SIGNATURE` и `AVIASALES_SEARCH_MARKER`. Cadence и recovery
задают `AGENT_POLL_INTERVAL_SECONDS`, `AGENT_OPERATION_LEASE_SECONDS`,
`AGENT_PROVIDER_CIRCUIT_FAILURE_THRESHOLD` и
`AGENT_PROVIDER_CIRCUIT_COOLDOWN_SECONDS`. При disabled/missing/invalid
credentials agent-worker делает terminal typed failure до HTTP.

Создание первого владельца описано в `README.md`. После приёма invitation
очисти `AUTH_BOOTSTRAP_TOKEN` в `.env`, если новые bootstrap invitations не
нужны, и перезапусти все три процесса.

## 2. Проверка состояния

```powershell
Invoke-RestMethod http://127.0.0.1:8000/healthz
Invoke-RestMethod http://127.0.0.1:8000/readyz
uv run flight-hunter-worker-healthcheck --role flight_hunter_worker --max-age-seconds 120
uv run flight-hunter-worker-healthcheck --role agent --max-age-seconds 120
```

Ожидается `status=ok/ready` и worker code `ok`. `readyz` non-200 означает, что
БД недоступна или не на текущем migration head.

## 3. Остановка

Для прямого запуска нажми `Ctrl+C` сначала в worker, затем в API. Дождись
завершения процессов перед restore или заменой кода.

Для Compose:

```powershell
docker compose stop agent-worker worker api
```

## 4. Docker Compose

Требуется запущенный Docker Desktop Linux engine.

```powershell
uv run flight-hunter-init-local
docker compose config --quiet
docker compose up --build -d
docker compose ps
Invoke-RestMethod http://127.0.0.1:8000/readyz
```

Логи и остановка:

```powershell
docker compose logs --tail 200 api worker agent-worker
docker compose down
```

Не используй `docker compose down --volumes`, кроме намеренного полного
удаления базы и backups в named volume.

## 5. Browser runtime

```powershell
uv run flight-hunter-browser-bootstrap
uv run flight-hunter-browser-smoke
uv run pytest tests/e2e -q -m browser_e2e --strict-markers
```

Установка Chromium нужна только E2E и personal observer. Она не нужна API,
Aviasales adapter или worker без browser jobs.

## 6. Обновление прямого запуска

Сделай backup до получения нового кода:

```powershell
uv run flight-hunter-backup --database .\flight_hunter_dev.db --backup-dir .\backups
uv run flight-hunter-backup-verify .\backups\flight_hunter_YYYYMMDDTHHMMSSZ.db
```

Останови API/оба worker-процесса, запомни текущий commit и обнови код:

```powershell
git rev-parse HEAD
git pull --ff-only
uv sync --frozen --group dev
uv run alembic upgrade head
uv run flight-hunter-release-check --include-browser
```

После зелёного gate запусти API/worker и проверь health/readiness.

## 7. Обновление Compose

Сначала создай backup внутри volume:

```powershell
docker compose exec api uv run flight-hunter-backup --database /data/flight_hunter.db --backup-dir /data/backups
docker compose exec api uv run flight-hunter-backup-verify /data/backups/flight_hunter_YYYYMMDDTHHMMSSZ.db
```

Скопируй `.db` и `.manifest.json` на host, затем обнови:

```powershell
docker compose cp api:/data/backups/flight_hunter_YYYYMMDDTHHMMSSZ.db .\backups\
docker compose cp api:/data/backups/flight_hunter_YYYYMMDDTHHMMSSZ.db.manifest.json .\backups\
git pull --ff-only
docker compose config --quiet
docker compose up --build -d
docker compose ps
Invoke-RestMethod http://127.0.0.1:8000/readyz
```

## 8. Rollback

Миграции назад автоматически не откатываются. Rollback кода делай вместе с
проверенным pre-update backup.

Прямой запуск:

```powershell
git switch --detach <previous-known-good-commit>
uv sync --frozen --group dev
uv run flight-hunter-backup-verify .\backups\flight_hunter_YYYYMMDDTHHMMSSZ.db
uv run flight-hunter-restore .\backups\flight_hunter_YYYYMMDDTHHMMSSZ.db --database .\flight_hunter_dev.db
uv run alembic upgrade head
```

Compose: останови сервисы и восстанови backup из named volume:

```powershell
docker compose stop agent-worker worker api
git switch --detach <previous-known-good-commit>
docker compose run --rm --no-deps api uv run flight-hunter-backup-verify /data/backups/flight_hunter_YYYYMMDDTHHMMSSZ.db
docker compose run --rm --no-deps api uv run flight-hunter-restore /data/backups/flight_hunter_YYYYMMDDTHHMMSSZ.db --database /data/flight_hunter.db
docker compose up --build -d
```

После rollback повтори health/readiness и основные search/watch flows.
