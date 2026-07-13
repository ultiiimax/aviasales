# Security Policy

## Поддерживаемая версия

Исправления безопасности делаются для локального релиза `1.0.x`. Старые
коммиты и долгосрочная target-архитектура из `docs/ARCHITECTURE.md` не считаются
поддерживаемым deployment.

## Граница безопасности v1

Flight Hunter 1.0.0 поддерживает только один доверенный компьютер:

- API и web UI слушают `127.0.0.1:8000`;
- TLS, публичный reverse proxy, multi-host и internet-facing deployment не
  поддерживаются;
- `AUTH_ALLOW_LEGACY_HEADERS=false` обязателен;
- доступ выдаётся через одноразовое invitation и bearer session;
- SQLite и backups находятся на локальном диске или в локальном Docker volume.

Публикация порта на `0.0.0.0`, проброс через туннель/proxy или совместное
использование недоверенными пользователями выходит за поддерживаемую модель.

## Секреты

Не коммить и не передавать в логи:

- `APP_SECRET_KEY`, `AUTH_BOOTSTRAP_TOKEN`, session tokens;
- `AVIASALES_SEARCH_SIGNATURE`, `AVIASALES_SEARCH_MARKER`;
- Telegram/OpenAI/provider tokens, cookies;
- signed booking URLs и полные provider refs.

`.env` создаётся `uv run flight-hunter-init-local`, исключён из Git и должен
быть доступен только локальному пользователю. Если секрет попал наружу, замени
его, отзови связанные sessions и проверь историю Git/логов.

## Сообщение об уязвимости

Не публикуй рабочий exploit, секреты или пользовательские данные в открытом
issue. Если репозиторий размещён на GitHub, используй private security advisory;
иначе передай владельцу проекта минимальный воспроизводимый пример по частному
каналу. Укажи версию/commit, влияние и шаги воспроизведения с вычищенными
данными.

## Проверка перед использованием

```powershell
uv run flight-hunter-security-scan
uv run flight-hunter-release-check --include-browser
```

Для Docker дополнительно нужен успешный `docker compose build`. Live provider
smoke выполняется отдельно и никогда не должен печатать credential values.
