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
- Loopback-only автоматический owner-профиль на обычной bearer-сессии без кода
  приглашения; повторные подключения сохраняют durable plan/run pointers.

### Изменено

- Главный экран сведён к одному понятному действию «Найти варианты»; внутренний
  план и ручное управление перенесены в свёрнутые детали.
- Результаты показываются едиными карточками с человеческими названиями и
  флагами мест, авиакомпаниями, багажом, защитой пересадки, источником и
  несколькими ranking-бейджами без дублирования маршрута.
- Из личного web UI удалены поля кода/имени и кнопки входа/выхода. Профиль
  подключается при загрузке, а первый запрос агенту продолжается тем же кликом.
- Детерминированный parser понимает русские диапазоны дат с годом и пассажирами,
  например `из Санкт-Петербурга во Францию с 10 по 17 сентября 2026 года`.
- Aviasales poll корректно принимает HTTP 304 без нового тела, а явно помеченная
  provider-ом смена аэропорта больше не ломает выдачу и показывается как риск с
  неизвестной стоимостью наземного переезда. Заголовок такого round-trip
  сохраняет отдельные направления туда и обратно вместо ложного маршрута
  `origin → origin`.
- Aviasales poll больше не отбрасывается, если upstream оставил
  `last_update_timestamp=0`: билет сохраняется, а пустой ответ повторяется только
  в пределах poll-бюджета; откат cursor по-прежнему считается ошибкой схемы.
- Валидные provider-альтернативы с разными аэропортами вылета/возврата больше не
  ломают весь chunk: неподдерживаемая строка пропускается, request-bound билеты
  сохраняются. Формат багажа совместим с durable JSON-защитой.
- Большая агентная выдача рисует первые 20 карточек и раскрывается порциями, а не
  блокирует браузер сотнями DOM-элементов.

### Проверка

- Sanitized Aviasales exact-search smoke: 50 one-way `live` items; отдельная
  round-trip проверка вернула 48 валидных предложений.
- Живой агентный поиск Санкт-Петербург → Франция на 10–17 сентября 2026 года
  сохранил 672 подтверждённых варианта за 20 логических операций и 53 HTTP
  попытки. Статус честно `partial`: один аэропорт отклонён provider-ом, для двух
  аэропортов не получено подтверждённых билетов; schema-failure нет.
- 101 focused tests базового среза, 30 финальных focused regressions, отдельные
  проверки проекции маршрута, один Chromium E2E, targeted Ruff/mypy и
  desktop/mobile browser QA. API и оба worker-процесса здоровы после
  перезапуска; выдача раскрывается 20 → 40 из 672 без ошибок консоли.

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
