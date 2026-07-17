# Changelog

Все заметные изменения Flight Hunter фиксируются здесь.

## [Unreleased] - 2026-07-17

### Добавлено

- Безопасный импорт локального Aviasales API kit без выполнения его Python-кода
  и без вывода credentials.
- Немедленный durable search из полного сообщения агенту, replay-safe
  idempotency и отдельное явное создание слежения за ценой.
- Ограниченный read-only Codex CLI overlay для неполных intent-полей; цены,
  рейсы и booking-ссылки по-прежнему берутся только из provider facts.
- Явный выбор локально доступной модели Codex с 15-секундным deterministic
  fallback, завершением Windows process tree и bounded cleanup временных данных.

### Изменено

- Главный экран сведён к одному понятному действию «Найти варианты»; внутренний
  план и ручное управление перенесены в свёрнутые детали.
- Результаты показываются едиными карточками с человеческими названиями и
  флагами мест, авиакомпаниями, багажом, защитой пересадки, источником и
  несколькими ranking-бейджами без дублирования маршрута.

### Проверка

- Sanitized Aviasales exact-search smoke: 50 schema-valid `live` items.
- 101 focused tests, один Chromium E2E, targeted Ruff/mypy и desktop/mobile
  browser QA; API и оба worker-процесса здоровы после перезапуска.

## [1.0.0] - 2026-07-13

### Добавлено

- Локальный FastAPI/web runtime и durable multi-lane worker на SQLite/Alembic.
- Invitation/session auth, household isolation и безопасный local initializer.
- Live Aviasales mobile API adapter: search, suggest, hot offers, calendar,
  GraphQL blocks и lazy purchase URL.
- Нормализация, дедупликация, ranking/risk/total cost, watches, история цен и
  Telegram outbox.
- Browser bootstrap, Chromium smoke и семь локальных browser E2E сценариев.
- Backup/verify/restore, readiness, worker healthcheck, security scan и единый
  JSONL release gate.
- Linux/Windows/browser/image CI и hardened loopback Docker Compose.

### Исправлено

- Удалена зависимость worker-тестов от текущего времени.
- Централизованы SQLite WAL, foreign keys и busy timeout.
- Ошибки Aviasales получили стабильные коды, bounded retries и честный partial
  success без выдуманных live-данных.
- Восстановлена кодировка русского web UI и архитектурной документации.
- Compose worker healthcheck проверяет фактическую durable heartbeat role.

### Безопасность

- Packaged runtime отключает legacy identity headers и требует
  `APP_SECRET_KEY`.
- API публикуется только на `127.0.0.1:8000`; container работает не от root.
- Signature/marker, provider refs и purchase URLs исключены из smoke output,
  логов и client bundle.

### Проверка

- Credential-free test/lint/type/migration/security/Compose/health gates.
- Browser acceptance после явной установки Chromium.
- Sanitized live Aviasales exact-date smoke 2026-07-13.
- Docker image build выполняется CI; локальный build требует доступный Docker
  Desktop Linux engine.
