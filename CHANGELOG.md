# Changelog

Все заметные изменения Flight Hunter фиксируются здесь.

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
