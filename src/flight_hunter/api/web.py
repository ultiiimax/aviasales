# ruff: noqa: E501, RUF001

from __future__ import annotations


def render_index_html() -> str:
    return """<!doctype html>
<html lang="ru">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Flight Hunter</title>
  <meta name="theme-color" content="#126d7a">
  <link rel="manifest" href="/manifest.webmanifest">
  <meta name="description" content="Flight Hunter: семейный поиск авиабилетов с честной свежестью цен.">
  <link rel="icon" href='data:image/svg+xml,
    <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64">
      <rect width="64" height="64" rx="12" fill="%2314242c"/>
      <path d="M13 34h31M32 16l15 18-15 14" fill="none" stroke="%23ffffff"
        stroke-width="6" stroke-linecap="round" stroke-linejoin="round"/>
    </svg>'>
  <style>
    :root {
      color-scheme: light;
      --bg: #edf1f4;
      --ink: #131a22;
      --muted: #66717c;
      --surface: #ffffff;
      --surface-soft: #f4f7f9;
      --line: #d7dee5;
      --accent: #126d7a;
      --accent-strong: #0b5660;
      --accent-soft: #e1f2f4;
      --warning: #9a5b16;
      --warning-soft: #f7ead5;
      --danger: #a33a2a;
      --danger-soft: #f7deda;
      --ok: #247044;
      --ok-soft: #ddefe4;
      --shadow: 0 18px 44px rgba(25, 40, 54, 0.10);
      font-family:
        Aptos, "Segoe UI Variable", "Segoe UI", ui-sans-serif, system-ui, sans-serif;
    }

    * { box-sizing: border-box; }

    html { scroll-behavior: smooth; }

    body {
      margin: 0;
      min-height: 100dvh;
      background:
        linear-gradient(90deg, rgba(18, 109, 122, 0.08) 1px, transparent 1px),
        linear-gradient(180deg, #f8fafb 0%, var(--bg) 52%, #e8edf1 100%);
      background-size: 44px 44px, auto;
      color: var(--ink);
    }

    button,
    input,
    textarea {
      font: inherit;
    }

    button {
      border: 0;
      cursor: pointer;
      transition: transform 160ms ease, background 160ms ease, border-color 160ms ease;
    }

    button:active { transform: translateY(1px) scale(0.99); }
    button:disabled { cursor: wait; opacity: 0.68; }

    button:focus-visible,
    input:focus-visible,
    textarea:focus-visible {
      outline: 3px solid rgba(15, 118, 110, 0.18);
      outline-offset: 2px;
    }

    .shell {
      width: min(1240px, calc(100vw - 28px));
      margin: 0 auto;
      padding: 18px 0 44px;
    }

    .topbar {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 16px;
      margin-bottom: 16px;
    }

    .brand {
      display: flex;
      align-items: center;
      gap: 12px;
      min-width: 0;
    }

    .mark {
      width: 38px;
      height: 38px;
      border-radius: 8px;
      display: grid;
      place-items: center;
      background: #14242c;
      color: white;
      box-shadow: 0 12px 28px rgba(20, 36, 44, 0.18);
    }

    .brand-title {
      display: grid;
      gap: 1px;
    }

    .brand-title strong {
      font-size: 20px;
      line-height: 1;
      letter-spacing: 0;
    }

    .brand-title span,
    .status-line,
    .fineprint {
      color: var(--muted);
      font-size: 13px;
      line-height: 1.35;
    }

    .status-line {
      font-variant-numeric: tabular-nums;
      text-align: right;
    }

    .workbench {
      display: grid;
      grid-template-columns: minmax(0, 1.08fr) minmax(340px, 0.92fr);
      gap: 16px;
      align-items: start;
      margin-bottom: 16px;
    }

    .auth-panel {
      margin-bottom: 16px;
    }

    .auth-form {
      display: grid;
      grid-template-columns: minmax(220px, 1fr) minmax(180px, 0.7fr) auto auto;
      gap: 10px;
      align-items: end;
      padding: 14px 16px;
    }

    .auth-state {
      grid-column: 1 / -1;
      min-height: 18px;
      color: var(--muted);
      font-size: 12px;
      line-height: 1.45;
    }

    .agent-cockpit {
      grid-template-columns: minmax(0, 1fr) minmax(360px, 0.42fr);
    }

    .panel {
      background: rgba(255, 255, 255, 0.96);
      border: 1px solid var(--line);
      border-radius: 8px;
      box-shadow: var(--shadow);
      overflow: hidden;
    }

    .panel-header {
      display: flex;
      align-items: flex-start;
      justify-content: space-between;
      gap: 12px;
      padding: 16px;
      border-bottom: 1px solid var(--line);
      background: rgba(255, 255, 255, 0.78);
    }

    .panel-title {
      margin: 0;
      font-size: 18px;
      line-height: 1.15;
      letter-spacing: 0;
    }

    .panel-kicker {
      margin-top: 5px;
      color: var(--muted);
      font-size: 13px;
      line-height: 1.4;
      max-width: 58ch;
    }

    .search-form {
      display: grid;
      grid-template-columns: repeat(6, minmax(0, 1fr));
      gap: 12px;
      padding: 16px;
    }

    label {
      display: grid;
      gap: 6px;
      color: #4f5c63;
      font-size: 12px;
      font-weight: 720;
    }

    label.wide { grid-column: span 2; }

    input,
    textarea {
      width: 100%;
      border: 1px solid var(--line);
      border-radius: 8px;
      background: #ffffff;
      color: var(--ink);
    }

    input {
      height: 45px;
      padding: 0 12px;
      font-size: 15px;
      font-weight: 650;
      letter-spacing: 0;
    }

    textarea {
      min-height: 86px;
      padding: 11px 12px;
      resize: vertical;
      line-height: 1.45;
    }

    .form-actions {
      grid-column: 1 / -1;
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 12px;
      flex-wrap: wrap;
      padding-top: 2px;
    }

    .primary,
    .secondary,
    .chip {
      min-height: 40px;
      border-radius: 8px;
      padding: 0 14px;
      font-weight: 760;
    }

    .primary {
      background: var(--accent);
      color: white;
    }

    .primary:hover { background: var(--accent-strong); }

    .secondary,
    .chip {
      border: 1px solid var(--line);
      background: #ffffff;
      color: var(--ink);
    }

    .secondary:hover,
    .chip:hover {
      border-color: #98bbb5;
      background: var(--accent-soft);
    }

    .assistant-body {
      padding: 14px;
      display: grid;
      gap: 12px;
    }

    .runtime-strip {
      display: grid;
      grid-template-columns: repeat(4, minmax(0, 1fr));
      gap: 8px;
    }

    .runtime-node {
      min-height: 54px;
      border: 1px solid var(--line);
      border-radius: 8px;
      background: var(--surface-soft);
      padding: 9px 10px;
      display: grid;
      gap: 3px;
    }

    .runtime-node span {
      color: var(--muted);
      font-size: 11px;
      line-height: 1.2;
      font-weight: 760;
      text-transform: uppercase;
    }

    .runtime-node strong {
      font-size: 13px;
      line-height: 1.25;
      overflow-wrap: anywhere;
    }

    .quick-actions {
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
    }

    .agent-sidecars {
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: 10px;
    }

    .agent-plan-card {
      display: grid;
      gap: 12px;
      padding: 14px;
      border: 1px solid var(--line);
      border-radius: 16px;
      background: rgba(244, 248, 249, 0.92);
    }

    .agent-plan-card[hidden],
    .agent-plan-region[hidden] {
      display: none;
    }

    .agent-plan-grid {
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 8px 14px;
      margin: 0;
    }

    .agent-plan-grid div {
      min-width: 0;
    }

    .agent-plan-grid dt {
      color: var(--muted);
      font-size: 11px;
      text-transform: uppercase;
      letter-spacing: 0.06em;
    }

    .agent-plan-grid dd {
      margin: 3px 0 0;
      overflow-wrap: anywhere;
      font-size: 13px;
    }

    .choice-list,
    .action-list {
      display: grid;
      gap: 8px;
    }

    .action-card,
    .choice-card {
      border: 1px solid var(--line);
      border-radius: 8px;
      background: #ffffff;
      padding: 10px 11px;
      font-size: 13px;
      line-height: 1.4;
    }

    .choice-card {
      text-align: left;
      cursor: pointer;
    }

    .action-card strong,
    .choice-card strong {
      display: block;
      margin-bottom: 4px;
      color: var(--ink);
      font-size: 13px;
      line-height: 1.25;
    }

    .action-card strong,
    .choice-card strong {
      display: block;
      margin-bottom: 4px;
      font-size: 13px;
    }

    .chat-log {
      min-height: 172px;
      max-height: 312px;
      overflow: auto;
      display: grid;
      align-content: start;
      gap: 9px;
      padding: 10px;
      border: 1px solid var(--line);
      border-radius: 8px;
      background:
        linear-gradient(180deg, rgba(244, 247, 249, 0.82), rgba(255, 255, 255, 0.92));
    }

    .message {
      max-width: 88%;
      border-radius: 8px;
      padding: 10px 11px;
      line-height: 1.45;
      font-size: 14px;
      white-space: pre-wrap;
    }

    .message.bot {
      justify-self: start;
      background: #ffffff;
      border: 1px solid var(--line);
    }

    .message.user {
      justify-self: end;
      background: #183239;
      color: white;
    }

    .assistant-input {
      display: grid;
      gap: 9px;
    }

    .lower-grid {
      display: grid;
      grid-template-columns: 330px minmax(0, 1fr);
      gap: 16px;
      align-items: start;
    }

    .provider-list,
    .result-list,
    .denial-list {
      display: grid;
    }

    .provider-row,
    .result-row,
    .denial-row {
      padding: 14px 16px;
      border-bottom: 1px solid var(--line);
    }

    .provider-row:last-child,
    .result-row:last-child,
    .denial-row:last-child {
      border-bottom: 0;
    }

    .row-main {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 12px;
      margin-bottom: 7px;
    }

    .provider-name,
    .route {
      font-weight: 780;
      font-size: 14px;
    }

    .small {
      color: var(--muted);
      font-size: 12px;
      line-height: 1.45;
    }

    .badge {
      display: inline-flex;
      align-items: center;
      min-height: 24px;
      border-radius: 8px;
      padding: 0 8px;
      font-size: 12px;
      font-weight: 760;
      white-space: nowrap;
    }

    .badge.ok { color: var(--ok); background: var(--ok-soft); }
    .badge.warn { color: var(--warning); background: var(--warning-soft); }
    .badge.high { color: var(--danger); background: var(--danger-soft); }
    .badge.off { color: #516169; background: var(--surface-soft); }

    .result-row {
      display: grid;
      grid-template-columns: minmax(190px, 1fr) 160px minmax(220px, 0.9fr);
      gap: 14px;
      align-items: center;
    }

    .price {
      font-size: 21px;
      font-weight: 820;
      text-align: right;
      font-variant-numeric: tabular-nums;
      white-space: nowrap;
    }

    .caveats {
      display: flex;
      gap: 7px;
      flex-wrap: wrap;
      justify-content: flex-end;
      margin-bottom: 8px;
    }

    .result-actions,
    .confirmation-actions {
      display: flex;
      flex-wrap: wrap;
      gap: 7px;
      justify-content: flex-end;
    }

    .confirmation-actions {
      margin-top: 8px;
    }

    .confirmation-actions .chip {
      min-height: 32px;
      padding: 0 9px;
      font-size: 12px;
    }

    .confirmation-status {
      color: var(--muted);
      font-size: 12px;
      line-height: 1.45;
      margin-top: 7px;
      min-height: 18px;
      text-align: right;
    }

    .side-stack,
    .admin-health-list,
    .watch-list,
    .watch-history,
    .watch-toolbar {
      display: grid;
    }

    .side-stack {
      gap: 16px;
    }

    .watch-toolbar {
      grid-template-columns: 1fr 1fr;
      gap: 8px;
      padding: 12px 16px;
      border-bottom: 1px solid var(--line);
      background: var(--surface-soft);
    }

    .watch-actions {
      display: flex;
      flex-wrap: wrap;
      gap: 7px;
      margin-top: 9px;
    }

    .watch-actions .chip {
      min-height: 32px;
      padding: 0 9px;
      font-size: 12px;
    }

    .empty-state,
    .error-state {
      padding: 28px 16px;
      color: var(--muted);
      font-size: 14px;
      line-height: 1.45;
    }

    .error-state { color: var(--danger); }

    @media (max-width: 980px) {
      .workbench,
      .lower-grid,
      .result-row {
        grid-template-columns: 1fr;
      }

      .search-form {
        grid-template-columns: repeat(2, minmax(0, 1fr));
      }

      .auth-form {
        grid-template-columns: 1fr 1fr;
      }

      label.wide { grid-column: span 1; }

      .price,
      .caveats,
      .result-actions,
      .confirmation-actions,
      .confirmation-status {
        text-align: left;
        justify-content: flex-start;
      }

      .status-line {
        text-align: left;
      }
    }

    @media (max-width: 560px) {
      .shell {
        width: min(100vw - 18px, 1240px);
        padding-top: 10px;
      }

      .topbar {
        align-items: flex-start;
        flex-direction: column;
      }

      .search-form {
        grid-template-columns: 1fr;
        gap: 10px;
      }

      .auth-form {
        grid-template-columns: 1fr;
      }

      .form-actions {
        align-items: stretch;
      }

      .primary,
      .secondary {
        width: 100%;
      }

      .watch-toolbar {
        grid-template-columns: 1fr;
      }

      .confirmation-actions .chip {
        width: auto;
      }

      .message {
        max-width: 96%;
      }

      .agent-sidecars {
        grid-template-columns: 1fr;
      }
    }
  </style>
</head>
<body>
  <main class="shell">
    <header class="topbar">
      <div class="brand">
        <span class="mark" aria-hidden="true">
          <svg width="21" height="21" viewBox="0 0 24 24" fill="none">
            <path d="M4 12h15M12 5l7 7-7 7" stroke="currentColor" stroke-width="2.2"
              stroke-linecap="round" stroke-linejoin="round"/>
          </svg>
        </span>
        <div class="brand-title">
          <strong>Flight Hunter</strong>
          <span>семейный поиск билетов без выдуманных цен</span>
        </div>
      </div>
      <div class="status-line" id="status-line">локальный режим · данные помечаются по свежести</div>
    </header>

    <section class="panel auth-panel" aria-labelledby="auth-heading">
      <div class="panel-header">
        <div>
          <h2 class="panel-title" id="auth-heading">Session</h2>
          <div class="panel-kicker">Invitation-only access for household data.</div>
        </div>
      </div>
      <form class="auth-form" id="auth-form">
        <label>Invitation code
          <input name="invitation_code" autocomplete="one-time-code">
        </label>
        <label>Name
          <input name="display_name" autocomplete="name">
        </label>
        <button class="primary" type="submit" id="auth-submit-button">Accept</button>
        <button class="secondary" type="button" id="auth-signout-button">Sign out</button>
        <div class="auth-state" id="auth-state" aria-live="polite"></div>
      </form>
    </section>

    <section class="workbench agent-cockpit" aria-label="Agent cockpit">
      <aside class="panel" aria-labelledby="assistant-heading">
        <div class="panel-header">
          <div>
            <h1 class="panel-title" id="assistant-heading">Agent cockpit</h1>
            <div class="panel-kicker">Human-in-the-loop агент понимает маршрут словами, строит typed tool plan и запускает только policy-разрешенные действия.</div>
          </div>
          <span class="badge ok" id="agent-mode">harness</span>
        </div>
        <div class="assistant-body">
          <div class="quick-actions" id="preset-list" aria-label="Сценарии ИИ">
            <button class="chip" type="button" data-preset="flexible_dates">Даты ±3 дня</button>
            <button class="chip" type="button" data-preset="nearby_airports">Аэропорты рядом</button>
            <button class="chip" type="button" data-preset="buy_timing">Когда покупать</button>
          </div>
          <div class="runtime-strip" id="runtime-strip" aria-label="Agent runtime">
            <div class="runtime-node">
              <span>Runtime</span>
              <strong id="agent-runtime">deterministic_harness</strong>
            </div>
            <div class="runtime-node">
              <span>Loop</span>
              <strong id="agent-loop">policy_validated_tool_plan</strong>
            </div>
            <div class="runtime-node">
              <span>Live</span>
              <strong id="agent-live-policy">user action only</strong>
            </div>
            <div class="runtime-node">
              <span>Cloudflare</span>
              <strong id="agent-edge-ready">portable boundary</strong>
            </div>
          </div>
          <div class="chat-log" id="chat-log" aria-live="polite">
            <div class="message bot">Напиши: “Хочу из СПб улететь в Шанхай в октябре”. Агент разберёт intent, покажет аэропорты, попросит дату вместо угадывания и не сделает live-вызов без твоего клика.</div>
          </div>
          <div class="agent-sidecars" id="decision-rail">
            <div>
              <div class="fineprint">Варианты аэропортов</div>
              <div class="choice-list" id="airport-choice-list"></div>
            </div>
            <div>
              <div class="fineprint">Действия агента</div>
              <div class="action-list" id="agent-action-list"></div>
            </div>
          </div>
          <section class="agent-plan-card" id="agent-plan-card" aria-labelledby="agent-plan-heading" hidden>
            <div>
              <h3 id="agent-plan-heading">План поиска</h3>
              <div id="agent-plan-status" role="status" aria-live="polite">План не создан</div>
            </div>
            <dl class="agent-plan-grid">
              <div><dt>Ревизия</dt><dd id="agent-plan-revision">Неизвестно</dd></div>
              <div><dt>Замороженная область</dt><dd id="agent-plan-scope">Неизвестно</dd></div>
              <div><dt>Даты</dt><dd id="agent-plan-date-mode">Неизвестно</dd></div>
              <div><dt>Пассажиры</dt><dd id="agent-plan-passengers">Неизвестно</dd></div>
              <div><dt>Покрытие</dt><dd id="agent-plan-coverage">Неизвестно</dd></div>
              <div><dt>Стратегии</dt><dd id="agent-plan-strategies">Неизвестно</dd></div>
              <div><dt>Hidden-city</dt><dd id="agent-plan-hidden-city">Неизвестно</dd></div>
              <div><dt>Оценка</dt><dd id="agent-plan-estimate">Неизвестно</dd></div>
              <div><dt>Лимит провайдера</dt><dd id="agent-plan-rpm">Неизвестно</dd></div>
              <div><dt>Дедлайн</dt><dd id="agent-plan-deadline">Неизвестно</dd></div>
              <div><dt>Источник</dt><dd id="agent-plan-source">Неизвестно</dd></div>
              <div><dt>Истекает</dt><dd id="agent-plan-expiry">Неизвестно</dd></div>
            </dl>
            <div class="quick-actions" aria-label="Действия с планом">
              <button class="secondary" type="button" id="agent-plan-edit">Изменить план</button>
              <button class="secondary" type="button" id="agent-plan-full">Проверить всю область</button>
              <button class="primary" type="button" id="agent-plan-execute" disabled>Запустить поиск</button>
            </div>
            <div class="agent-plan-region" id="agent-run-progress" role="status" aria-live="polite">Запуск ещё не создан.</div>
            <button class="secondary" type="button" id="agent-run-cancel" disabled>Отменить запуск</button>
            <section class="agent-plan-region" id="agent-risky-results" aria-labelledby="agent-risky-results-heading" hidden>
              <h4 id="agent-risky-results-heading">Рискованные варианты</h4>
              <div id="agent-risky-results-list">Нет подтверждённых рискованных вариантов.</div>
            </section>
            <div class="agent-plan-region" id="agent-partial-errors" role="alert" hidden></div>
          </section>
          <form class="assistant-input" id="assistant-form">
            <textarea name="agent_prompt" placeholder="Например: из Варшавы в Барселону 2026-10-12 2026-10-19 следи"></textarea>
            <button class="primary" type="submit">Спросить агента</button>
          </form>
        </div>
      </aside>

      <section class="panel" aria-labelledby="search-heading">
        <div class="panel-header">
          <div>
            <h2 class="panel-title" id="search-heading">Маршрут</h2>
            <div class="panel-kicker">Сначала показываем cached-варианты. Live-проверка запускается отдельной кнопкой.</div>
          </div>
        </div>
        <form class="search-form" id="search-form">
          <label>Откуда
            <input name="origin" value="WAW" maxlength="3" autocomplete="off" required>
          </label>
          <label>Куда
            <input name="destination" value="BCN" maxlength="3" autocomplete="off" required>
          </label>
          <label>Вылет
            <input name="departure_date" type="date" value="2026-10-12" required>
          </label>
          <label>Обратно
            <input name="return_date" type="date" value="2026-10-19">
          </label>
          <label>Взрослые
            <input name="adults" type="number" min="1" value="2" required>
          </label>
          <label>Дети
            <input name="children" type="number" min="0" value="0" required>
          </label>
          <label>Младенцы
            <input name="infants" type="number" min="0" value="0" required>
          </label>
          <label>Валюта
            <input name="currency" value="RUB" maxlength="3" autocomplete="off" required>
          </label>
          <div class="form-actions">
            <span class="fineprint" id="passenger-total">2 пассажира · туда-обратно</span>
            <div class="quick-actions" aria-label="Ручные проверки">
              <button class="secondary" type="button" id="personal-observe-button">Считать из браузера</button>
              <button class="secondary" type="button" id="deal-discovery-button">Найти акции</button>
              <button class="primary" type="submit" id="submit-button">Найти билеты</button>
            </div>
          </div>
        </form>
      </section>
    </section>

    <section class="lower-grid">
      <div class="side-stack">
        <aside class="panel" aria-labelledby="providers-heading">
          <div class="panel-header">
            <div>
              <h2 class="panel-title" id="providers-heading">Источники</h2>
              <div class="panel-kicker">Что сейчас можно использовать.</div>
            </div>
          </div>
          <div class="provider-list" id="providers-list">
            <div class="empty-state">Загружаю источники...</div>
          </div>
        </aside>

        <section class="panel" aria-labelledby="watches-heading">
          <div class="panel-header">
            <div>
              <h2 class="panel-title" id="watches-heading">Отслеживания</h2>
              <div class="panel-kicker">Слежение работает по расписанию и не запускает браузер без клика.</div>
            </div>
          </div>
          <div class="watch-toolbar">
            <button class="secondary" type="button" id="create-watch-button">Следить за маршрутом</button>
            <button class="secondary" type="button" id="refresh-watches-button">Обновить watches</button>
          </div>
          <div class="watch-list" id="watch-list">
            <div class="empty-state">Загружаю watches...</div>
          </div>
          <div class="watch-history" id="watch-history-list"></div>
        </section>

        <section class="panel" aria-labelledby="admin-health-heading">
          <div class="panel-header">
            <div>
              <h2 class="panel-title" id="admin-health-heading">Health</h2>
              <div class="panel-kicker">Read-only provider/source status; no live checks on refresh.</div>
            </div>
            <button class="secondary" type="button" id="refresh-admin-health-button">Обновить</button>
          </div>
          <div class="admin-health-list" id="admin-health-list">
            <div class="empty-state">Загружаю health...</div>
          </div>
        </section>

        <section class="panel" aria-labelledby="audit-heading">
          <div class="panel-header">
            <div>
              <h2 class="panel-title" id="audit-heading">Audit</h2>
              <div class="panel-kicker">Household-scoped lifecycle log; read-only.</div>
            </div>
            <button class="secondary" type="button" id="refresh-audit-button">РћР±РЅРѕРІРёС‚СЊ</button>
          </div>
          <div class="admin-health-list" id="audit-list">
            <div class="empty-state">Р—Р°РіСЂСѓР¶Р°СЋ audit...</div>
          </div>
        </section>
      </div>

      <section class="panel" aria-labelledby="results-heading">
        <div class="panel-header">
          <div>
            <h2 class="panel-title" id="results-heading">Результаты</h2>
            <div class="panel-kicker">Цены из кэша, ссылки для проверки и свежие наблюдения из браузера показываются отдельно.</div>
          </div>
          <span class="small" id="results-count">0 вариантов</span>
        </div>
        <div class="result-list" id="results-list">
          <div class="empty-state">Заполни маршрут и нажми “Найти билеты”.</div>
        </div>
        <div class="denial-list" id="confirmation-list"></div>
        <div class="denial-list" id="live-list"></div>
        <div class="denial-list" id="denials-list"></div>
      </section>
    </section>
  </main>

  <script>
    const providersList = document.querySelector("#providers-list");
    const resultsList = document.querySelector("#results-list");
    const confirmationList = document.querySelector("#confirmation-list");
    const liveList = document.querySelector("#live-list");
    const denialsList = document.querySelector("#denials-list");
    const resultsCount = document.querySelector("#results-count");
    const statusLine = document.querySelector("#status-line");
    const submitButton = document.querySelector("#submit-button");
    const personalObserveButton = document.querySelector("#personal-observe-button");
    const dealDiscoveryButton = document.querySelector("#deal-discovery-button");
    const createWatchButton = document.querySelector("#create-watch-button");
    const refreshWatchesButton = document.querySelector("#refresh-watches-button");
    const watchList = document.querySelector("#watch-list");
    const watchHistoryList = document.querySelector("#watch-history-list");
    const refreshAdminHealthButton = document.querySelector("#refresh-admin-health-button");
    const adminHealthList = document.querySelector("#admin-health-list");
    const refreshAuditButton = document.querySelector("#refresh-audit-button");
    const auditList = document.querySelector("#audit-list");
    const passengerTotal = document.querySelector("#passenger-total");
    const chatLog = document.querySelector("#chat-log");
    const presetList = document.querySelector("#preset-list");
    const agentMode = document.querySelector("#agent-mode");
    const agentRuntime = document.querySelector("#agent-runtime");
    const agentLoop = document.querySelector("#agent-loop");
    const agentLivePolicy = document.querySelector("#agent-live-policy");
    const agentEdgeReady = document.querySelector("#agent-edge-ready");
    const airportChoiceList = document.querySelector("#airport-choice-list");
    const agentActionList = document.querySelector("#agent-action-list");
    const authForm = document.querySelector("#auth-form");
    const authState = document.querySelector("#auth-state");
    const authSubmitButton = document.querySelector("#auth-submit-button");
    const authSignoutButton = document.querySelector("#auth-signout-button");
    let browserSources = [];
    let agentPresets = [];
    let lastSearchPayload = null;
    let lastSearchId = null;
    let lastExternalLinks = [];
    let watchRecords = [];
    let currentAgentPlan = null;
    let currentAgentRun = null;
    let lastAgentPrompt = "";
    let agentEditMode = false;
    const sessionTokenKey = "flight_hunter_session_token";
    const agentPlanStorageKey = "flight_hunter_agent_plan_id_v1";

    const manualConfirmationActions = [
      {status: "confirmed", label: "Совпала"},
      {status: "price_changed", label: "Изменилась"},
      {status: "sold_out", label: "Нет мест"},
      {status: "bought", label: "Купил"},
      {status: "wrong_route", label: "Маршрут не тот"}
    ];

    const reasonLabels = {
      cached_price: "cached",
      cached_price_range: "price range",
      cached_month_matrix: "month matrix",
      cached_nearest_places_matrix: "nearby cached",
      cached_popular_directions: "popular directions",
      cached_special_offers: "special offers",
      recent_price: "recent",
      live_price: "live",
      stale_price: "stale",
      provider_single_adult_ticket: "single adult ticket",
      unknown_freshness: "freshness unknown",
      requires_live_confirmation: "проверить перед покупкой",
      baggage_unknown: "багаж неизвестен",
      provider_disabled: "выключен",
      credentials_missing: "нужен ключ",
      access_not_approved: "доступ не подтвержден",
      background_not_allowed: "фон запрещен"
    };

    const providerLabels = {
      fake: "Демо-источник",
      aviasales_search: "Aviasales mobile API",
      aviasales_search: "Aviasales Search",
      skyscanner_indicative: "Skyscanner Indicative",
      skyscanner_live: "Skyscanner Live",
      duffel: "Duffel"
    };

    function sessionToken() {
      return window.localStorage.getItem(sessionTokenKey);
    }

    function authHeaders(extra = {}) {
      const token = sessionToken();
      if (token) {
        return {
          "Authorization": `Bearer ${token}`,
          ...extra
        };
      }
      return extra;
    }

    function storeSession(session) {
      window.localStorage.setItem(sessionTokenKey, session.session_token);
      authState.textContent = `Session: ${session.role} · ${session.household_id.slice(0, 8)}`;
      authSignoutButton.disabled = false;
    }

    function clearSession() {
      window.localStorage.removeItem(sessionTokenKey);
      authState.textContent = "Session: не выполнен вход";
      authSignoutButton.disabled = true;
    }

    function renderSignedOutState() {
      watchList.innerHTML = '<div class="empty-state">Войдите, чтобы видеть отслеживания.</div>';
      auditList.innerHTML = '<div class="empty-state">Войдите, чтобы видеть аудит.</div>';
      renderSignedOutConfirmationState();
    }

    function renderSignedOutConfirmationState() {
      confirmationList.innerHTML = '<div class="empty-state">Войдите, чтобы видеть подтверждения.</div>';
    }

    async function loadSessionBoundData() {
      if (!sessionToken()) {
        renderSignedOutState();
        return;
      }
      await Promise.all([
        loadManualConfirmations(),
        loadWatches(),
        loadAuditEvents(),
        reloadAgentPlan()
      ]);
    }

    async function refreshSessionState() {
      const token = sessionToken();
      if (!token) {
        clearSession();
        return;
      }
      try {
        const response = await fetch("/api/v1/auth/me", {
          headers: {"Authorization": `Bearer ${token}`}
        });
        if (!response.ok) throw new Error(await codedMessage(response));
        const session = await response.json();
        authState.textContent = `Session: ${session.role} · ${session.household_id.slice(0, 8)}`;
        authSignoutButton.disabled = false;
      } catch (error) {
        clearSession();
        statusLine.textContent = "session expired";
      }
    }

    async function acceptInvitation(event) {
      event.preventDefault();
      const form = new FormData(authForm);
      const invitationCode = text(form.get("invitation_code"));
      const displayName = text(form.get("display_name"));
      if (!invitationCode || !displayName) {
        authState.textContent = "Session: invitation code and name required";
        return;
      }
      authSubmitButton.disabled = true;
      try {
        const response = await fetch("/api/v1/auth/accept-invitation", {
          method: "POST",
          headers: {"Content-Type": "application/json"},
          body: JSON.stringify({
            invitation_code: invitationCode,
            display_name: displayName
          })
        });
        if (!response.ok) throw new Error(await codedMessage(response));
        storeSession(await response.json());
        authForm.reset();
        statusLine.textContent = "session active";
        await loadSessionBoundData();
      } catch (error) {
        authState.textContent = `Session: ${error.message}`;
      } finally {
        authSubmitButton.disabled = false;
      }
    }

    function text(value) {
      return String(value ?? "").trim();
    }

    function numberValue(form, name, fallback) {
      const parsed = Number(form.get(name));
      return Number.isFinite(parsed) ? parsed : fallback;
    }

    function providerLabel(providerId) {
      return providerLabels[providerId] || providerId;
    }

    function reasonLabel(reason) {
      return reasonLabels[reason] || reason;
    }

    function priceBasisLabel(offer) {
      const basis = offer.price_basis || "total_for_passengers";
      if (basis === "total_for_passengers") return "";
      if (basis === "provider_single_adult_ticket") return " · single adult ticket";
      return ` · ${basis}`;
    }

    function riskTone(level) {
      if (level === "low") return "ok";
      if (level === "high") return "high";
      return "warn";
    }

    function riskLevelLabel(offer) {
      const risk = offer.risk || {};
      return `risk: ${risk.level || "unknown"}`;
    }

    function riskBadges(offer) {
      const risk = offer.risk || {};
      const level = risk.level || "unknown";
      const flags = risk.flags || [];
      const badges = [`<span class="badge ${riskTone(level)}">${riskLevelLabel(offer)}</span>`];
      flags.forEach((flag) => {
        badges.push(`<span class="badge warn">${reasonLabel(flag)}</span>`);
      });
      return badges.join("");
    }

    function riskExplanationText(offer) {
      const risk = offer.risk || {};
      return (risk.explanations || []).join(" ");
    }

    function badgeClass(provider) {
      if (provider.blocked_reasons.length > 0) return "warn";
      if (!provider.enabled) return "off";
      return "ok";
    }

    function providerState(provider) {
      if (provider.blocked_reasons.includes("credentials_missing")) return "Не подключен";
      if (provider.blocked_reasons.includes("access_not_approved")) return "Нет доступа";
      if (!provider.enabled) return "выключен";
      if (provider.blocked_reasons.length > 0) return "ограничен";
      return "готов";
    }

    function providerHelp(provider) {
      if (provider.blocked_reasons.length === 0) {
        return `${provider.data_kind} · можно использовать сейчас`;
      }
      const notes = [];
      if (provider.blocked_reasons.includes("credentials_missing")) {
        notes.push("нужен API key в .env");
      }
      if (provider.blocked_reasons.includes("access_not_approved")) {
        notes.push("доступ у провайдера не подтвержден");
      }
      if (
        provider.blocked_reasons.includes("provider_disabled")
        && !provider.blocked_reasons.includes("credentials_missing")
      ) {
        notes.push("выключен feature flag");
      }
      return `${notes.join("; ")}. Это не ошибка поиска, просто реальные источники пока не настроены.`;
    }

    function optionCountLabel(count) {
      if (count % 10 === 1 && count % 100 !== 11) return `${count} вариант`;
      if ([2, 3, 4].includes(count % 10) && ![12, 13, 14].includes(count % 100)) {
        return `${count} варианта`;
      }
      return `${count} вариантов`;
    }

    function formatMinorAmount(minorUnits, currency) {
      const value = Number(minorUnits);
      if (!Number.isSafeInteger(value)) return `${minorUnits} ${currency}`;
      const sign = value < 0 ? "-" : "";
      const absolute = Math.abs(value);
      const major = Math.trunc(absolute / 100);
      const minor = String(absolute % 100).padStart(2, "0");
      return `${sign}${major}.${minor} ${currency}`;
    }

    function formatIsoMinute(value) {
      if (!value) return "нет срока";
      const parsed = new Date(value);
      if (Number.isNaN(parsed.getTime())) return value;
      return parsed.toLocaleString("ru-RU", {
        dateStyle: "short",
        timeStyle: "short",
      });
    }

    function dealCandidateExpiryLabel(candidate) {
      if (!candidate.expires_at) return "срок не указан";
      const expired = Date.parse(candidate.expires_at) <= Date.now();
      return `${expired ? "stale" : "candidate"} · до ${formatIsoMinute(candidate.expires_at)}`;
    }

    function buildSearchPayload() {
      const form = new FormData(document.querySelector("#search-form"));
      const adults = Math.max(1, numberValue(form, "adults", 1));
      const children = Math.max(0, numberValue(form, "children", 0));
      const infants = Math.max(0, numberValue(form, "infants", 0));
      const returnDate = text(form.get("return_date")) || null;
      return {
        origin: text(form.get("origin")).toUpperCase(),
        destination: text(form.get("destination")).toUpperCase(),
        departure_date: text(form.get("departure_date")),
        return_date: returnDate,
        passengers: adults + children + infants,
        adults,
        children,
        infants,
        trip_type: returnDate ? "round_trip" : "one_way",
        currency: text(form.get("currency")).toUpperCase()
      };
    }

    function updatePassengerSummary() {
      const payload = buildSearchPayload();
      const trip = payload.return_date ? "туда-обратно" : "в одну сторону";
      passengerTotal.textContent = `${payload.passengers} пасс. · ${trip}`;
    }

    function currentSlots() {
      const payload = buildSearchPayload();
      return {
        origin: payload.origin,
        destination: payload.destination,
        departure_date: payload.departure_date,
        return_date: payload.return_date,
        adults: payload.adults,
        children: payload.children,
        infants: payload.infants,
        currency: payload.currency,
        flight: `${payload.origin}-${payload.destination} ${payload.departure_date}`,
        region: payload.destination || payload.origin
      };
    }

    function setSearchField(name, value) {
      document.querySelector(`[name="${name}"]`).value = value || "";
    }

    function syncExtractedRoute(body) {
      const extracted = body.extracted || {};
      const missing = body.missing_slots || [];
      const airportOptions = body.airport_options || {};
      if (extracted.origin) {
        setSearchField("origin", extracted.origin);
      } else if (airportOptions.origin && airportOptions.origin.length) {
        setSearchField("origin", "");
      }
      if (extracted.destination) {
        setSearchField("destination", extracted.destination);
      } else if (airportOptions.destination && airportOptions.destination.length) {
        setSearchField("destination", "");
      }
      if (extracted.departure_date) {
        setSearchField("departure_date", extracted.departure_date);
      } else if (missing.includes("departure_date")) {
        setSearchField("departure_date", "");
      }
      if (extracted.return_date) {
        setSearchField("return_date", extracted.return_date);
      } else if (missing.includes("departure_date")) {
        setSearchField("return_date", "");
      }
      updatePassengerSummary();
    }

    function addMessage(kind, message) {
      const node = document.createElement("div");
      node.className = `message ${kind}`;
      node.textContent = message;
      chatLog.append(node);
      chatLog.scrollTop = chatLog.scrollHeight;
    }

    function renderAgentRuntime(runtime) {
      const details = runtime || {};
      agentRuntime.textContent = details.model
        ? `${details.backend || "deterministic_harness"} · ${details.model}`
        : details.backend || "deterministic_harness";
      agentLoop.textContent = details.agentic_loop || "policy_validated_tool_plan";
      agentLivePolicy.textContent = details.live_calls_allowed
        ? "enabled by user grant"
        : "user action only";
      agentEdgeReady.textContent = details.cloudflare_ready
        ? "portable boundary"
        : "local only";
      agentMode.textContent = details.backend === "openai_responses" ? "agent" : "harness";
    }

    function renderProviders(providers) {
      providersList.replaceChildren();
      providers.forEach((provider) => {
        const row = document.createElement("div");
        row.className = "provider-row";
        row.innerHTML = `
          <div class="row-main">
            <div class="provider-name"></div>
            <span class="badge ${badgeClass(provider)}">${providerState(provider)}</span>
          </div>
          <div class="small"></div>
        `;
        row.querySelector(".provider-name").textContent = providerLabel(provider.provider_id);
        row.querySelector(".small").textContent = providerHelp(provider);
        providersList.append(row);
      });
    }

    function healthBadge(status, blockedReasons = []) {
      if (
        blockedReasons.length > 0
        || ["critical", "failed", "blocked", "retry_scheduled", "stale", "backlog", "deadline_risk"].includes(status)
      ) {
        return {label: status || "blocked", tone: "warn"};
      }
      if (status === "warning") {
        return {label: status, tone: "warn"};
      }
      if (status === "drained") {
        return {label: status, tone: "warn"};
      }
      if (["ok", "healthy", "ready", "running", "idle"].includes(status)) {
        return {label: status, tone: "ok"};
      }
      if (status === "disabled" || status === "no_events" || status === "stopped") {
        return {label: status, tone: "off"};
      }
      return {label: status || "unknown", tone: "off"};
    }

    function renderAdminHealth(providerBody, sourceBody, workerBody) {
      adminHealthList.replaceChildren();
      appendSectionHeader(
        adminHealthList,
        "Provider health",
        `Checked ${providerBody.checked_at || "unknown"}. Values are readiness flags, not live probes.`
      );
      (providerBody.providers || []).forEach((provider) => {
        const status = provider.enabled ? "ready" : "disabled";
        const badge = healthBadge(status, provider.blocked_reasons || []);
        const row = document.createElement("div");
        row.className = "provider-row";
        row.innerHTML = `
          <div class="row-main">
            <div class="provider-name"></div>
            <span class="badge ${badge.tone}"></span>
          </div>
          <div class="small"></div>
        `;
        row.querySelector(".provider-name").textContent = providerLabel(provider.provider_id);
        row.querySelector(".badge").textContent = badge.label;
        const credentials = provider.credentials_present ? "credentials present" : "credentials missing";
        const reasons = (provider.blocked_reasons || []).join(", ") || "no blockers";
        row.querySelector(".small").textContent =
          `${provider.data_kind} · ${credentials} · access=${provider.access_approved} · ${reasons}`;
        adminHealthList.append(row);
      });

      appendSectionHeader(
        adminHealthList,
        "Source health",
        `Checked ${sourceBody.checked_at || "unknown"}. Latest events are append-only diagnostics.`
      );
      (sourceBody.sources || []).forEach((source) => {
        const badge = healthBadge(source.current_status, source.blocked_reasons || []);
        const row = document.createElement("div");
        row.className = "provider-row";
        row.innerHTML = `
          <div class="row-main">
            <div class="provider-name"></div>
            <span class="badge ${badge.tone}"></span>
          </div>
          <div class="small"></div>
        `;
        row.querySelector(".provider-name").textContent = source.display_name || source.source_id;
        row.querySelector(".badge").textContent = badge.label;
        const latest = source.latest_event
          ? `${source.latest_event.event_type}: ${source.latest_event.message}`
          : "no recent event";
        const blockers = (source.blocked_reasons || []).join(", ") || "no blockers";
        row.querySelector(".small").textContent =
          `${source.stage || "event-only"} · enabled=${source.enabled} · ${blockers} · ${latest}`;
        adminHealthList.append(row);
      });

      appendSectionHeader(
        adminHealthList,
        "Worker health",
        `Checked ${workerBody.checked_at || "unknown"}. Heartbeats are durable DB state, not log scraping.`
      );
      const control = workerBody.control || {drain_requested: false};
      const controlStatus = control.drain_requested ? "drained" : "ready";
      const controlBadge = healthBadge(controlStatus);
      const controlRow = document.createElement("div");
      controlRow.className = "provider-row";
      controlRow.innerHTML = `
        <div class="row-main">
          <div class="provider-name">Worker claims</div>
          <span class="badge ${controlBadge.tone}"></span>
        </div>
        <div class="small"></div>
      `;
      controlRow.querySelector(".badge").textContent = controlBadge.label;
      controlRow.querySelector(".small").textContent = control.drain_requested
        ? `new claims paused | reason=${control.reason || "operator"} | since=${control.requested_at || "unknown"}`
        : `new claims enabled | updated=${control.updated_at || control.cleared_at || "default"}`;
      const pauseClaimsButton = document.createElement("button");
      pauseClaimsButton.className = "secondary";
      pauseClaimsButton.type = "button";
      pauseClaimsButton.textContent = "Pause claims";
      pauseClaimsButton.disabled = Boolean(control.drain_requested);
      pauseClaimsButton.addEventListener("click", () => setWorkerDrain(true));
      const resumeClaimsButton = document.createElement("button");
      resumeClaimsButton.className = "secondary";
      resumeClaimsButton.type = "button";
      resumeClaimsButton.textContent = "Resume claims";
      resumeClaimsButton.disabled = !control.drain_requested;
      resumeClaimsButton.addEventListener("click", () => setWorkerDrain(false));
      controlRow.append(pauseClaimsButton, document.createTextNode(" "), resumeClaimsButton);
      adminHealthList.append(controlRow);
      const alerts = workerBody.alerts || [];
      if (alerts.length > 0) {
        appendSectionHeader(
          adminHealthList,
          "Worker alerts",
          "Derived from heartbeat and queue snapshots for external supervisor alerting."
        );
      }
      alerts.forEach((alert) => {
        const badge = healthBadge(alert.severity);
        const row = document.createElement("div");
        row.className = "provider-row";
        row.innerHTML = `
          <div class="row-main">
            <div class="provider-name"></div>
            <span class="badge ${badge.tone}"></span>
          </div>
          <div class="small"></div>
        `;
        row.querySelector(".provider-name").textContent =
          `${alert.subject_kind}:${alert.subject_id}`;
        row.querySelector(".badge").textContent = badge.label;
        row.querySelector(".small").textContent = `${alert.code} | ${alert.message}`;
        adminHealthList.append(row);
      });
      const queues = workerBody.queues || [];
      const staleQueues = queues.filter((queue) => (queue.stale_count || 0) > 0);
      if (staleQueues.length > 0) {
        appendSectionHeader(
          adminHealthList,
          "Stale lock monitor",
          "Queued work stuck behind stale worker leases, grouped by lane."
        );
      }
      staleQueues.forEach((queue) => {
        const row = document.createElement("div");
        row.className = "provider-row";
        row.innerHTML = `
          <div class="row-main">
            <div class="provider-name"></div>
            <span class="badge bad">critical</span>
          </div>
          <div class="small"></div>
        `;
        row.querySelector(".provider-name").textContent = `${queue.lane} stale locks`;
        row.querySelector(".small").textContent =
          `stale=${queue.stale_count ?? 0}`
          + ` | oldest_locked_age=${queue.oldest_locked_age_seconds ?? "n/a"}s`;
        adminHealthList.append(row);
      });
      if (queues.length > 0) {
        appendSectionHeader(
          adminHealthList,
          "Worker queues",
          "Backlog and stale/deadline indicators are read-only database aggregates."
        );
      }
      queues.forEach((queue) => {
        const badge = healthBadge(queue.warning_level);
        const row = document.createElement("div");
        row.className = "provider-row";
        row.innerHTML = `
          <div class="row-main">
            <div class="provider-name"></div>
            <span class="badge ${badge.tone}"></span>
          </div>
          <div class="small"></div>
        `;
        row.querySelector(".provider-name").textContent = `${queue.lane} queue`;
        row.querySelector(".badge").textContent = badge.label;
        const statuses = Object.entries(queue.status_counts || {})
          .map(([status, count]) => `${status}=${count}`)
          .join(", ") || "empty";
        const queuedAge = queue.oldest_queued_age_seconds ?? "n/a";
        const lockedAge = queue.oldest_locked_age_seconds ?? "n/a";
        row.querySelector(".small").textContent =
          `due=${queue.due_count ?? 0} | delayed=${queue.delayed_count ?? 0}`
          + ` | stale=${queue.stale_count ?? 0} | expired=${queue.expired_count ?? 0}`
          + ` | oldest_queued_age=${queuedAge}s | oldest_locked_age=${lockedAge}s`
          + ` | statuses: ${statuses}`;
        adminHealthList.append(row);
      });
      const workers = workerBody.workers || [];
      if (workers.length === 0) {
        const row = document.createElement("div");
        row.className = "denial-row small";
        row.textContent = "No worker heartbeat has been recorded yet.";
        adminHealthList.append(row);
      }
      workers.forEach((worker) => {
        const badge = healthBadge(worker.effective_status);
        const row = document.createElement("div");
        row.className = "provider-row";
        row.innerHTML = `
          <div class="row-main">
            <div class="provider-name"></div>
            <span class="badge ${badge.tone}"></span>
          </div>
          <div class="small"></div>
        `;
        row.querySelector(".provider-name").textContent = worker.worker_id;
        row.querySelector(".badge").textContent = badge.label;
        const summary = worker.last_summary || {};
        const job = worker.current_job_kind
          ? ` | job=${worker.current_job_kind}${worker.current_job_id ? "/" + worker.current_job_id : ""}`
          : "";
        row.querySelector(".small").textContent =
          `${worker.role} | phase=${worker.current_phase}${job} | last_seen=${worker.last_seen_at}`
          + ` | browser=${summary.browser_jobs_seen ?? 0}/${summary.browser_jobs_succeeded ?? 0}`
          + ` | watch=${summary.watch_jobs_processed ?? 0}/${summary.watch_jobs_succeeded ?? 0}`
          + ` | deal=${summary.deal_jobs_processed ?? 0}/${summary.deal_jobs_succeeded ?? 0}`
          + ` | telegram=${summary.telegram_notifications_seen ?? 0}/${summary.telegram_notifications_sent ?? 0}`
          + ` | maintenance=${summary.live_cleanup_observations_deleted ?? 0}/${summary.deal_candidates_deleted ?? 0}`;
        adminHealthList.append(row);
      });
    }

    async function setWorkerDrain(drainRequested) {
      refreshAdminHealthButton.disabled = true;
      try {
        const response = await fetch("/api/v1/admin/workers/control", {
          method: "PATCH",
          headers: authHeaders({"Content-Type": "application/json"}),
          body: JSON.stringify({
            drain_requested: drainRequested,
            reason: drainRequested ? "web health panel" : null
          })
        });
        if (!response.ok) throw new Error(await codedMessage(response));
        await loadAdminHealth();
        await loadAuditEvents();
      } catch (error) {
        const row = document.createElement("div");
        row.className = "denial-row small";
        row.textContent = `Worker control: ${error.message}`;
        adminHealthList.prepend(row);
      } finally {
        refreshAdminHealthButton.disabled = false;
      }
    }

    async function loadAdminHealth() {
      refreshAdminHealthButton.disabled = true;
      try {
        const [providersResponse, sourcesResponse, workersResponse] = await Promise.all([
          fetch("/api/v1/admin/providers/health"),
          fetch("/api/v1/admin/sources/health"),
          fetch("/api/v1/admin/workers/health")
        ]);
        if (!providersResponse.ok) throw new Error(await codedMessage(providersResponse));
        if (!sourcesResponse.ok) throw new Error(await codedMessage(sourcesResponse));
        if (!workersResponse.ok) throw new Error(await codedMessage(workersResponse));
        renderAdminHealth(
          await providersResponse.json(),
          await sourcesResponse.json(),
          await workersResponse.json()
        );
      } catch (error) {
        adminHealthList.replaceChildren();
        const row = document.createElement("div");
        row.className = "denial-row small";
        row.textContent = `Health: ${error.message}`;
        adminHealthList.append(row);
      } finally {
        refreshAdminHealthButton.disabled = false;
      }
    }

    function auditTone(event) {
      if (event.action.endsWith(".deleted")) return "off";
      if (event.action.endsWith(".archived") || event.action.endsWith(".paused")) return "warn";
      return "ok";
    }

    function auditMeta(event) {
      const actor = event.actor_user_id ? `actor ${event.actor_user_id.slice(0, 8)}` : "system";
      const target = event.entity_id
        ? `${event.entity_type} ${event.entity_id.slice(0, 8)}`
        : event.entity_type;
      return `${event.created_at} - ${actor} - ${target}`;
    }

    function renderAuditEvents(events) {
      auditList.replaceChildren();
      appendSectionHeader(
        auditList,
        "Audit",
        "Household-scoped lifecycle events; newest first."
      );
      if (!events || events.length === 0) {
        const empty = document.createElement("div");
        empty.className = "empty-state";
        empty.textContent = "Audit СЃРѕР±С‹С‚РёР№ РїРѕРєР° РЅРµС‚.";
        auditList.append(empty);
        return;
      }
      events.forEach((event) => {
        const row = document.createElement("div");
        row.className = "provider-row";
        row.innerHTML = `
          <div class="row-main">
            <div class="provider-name"></div>
            <span class="badge ${auditTone(event)}"></span>
          </div>
          <div class="small"></div>
        `;
        row.querySelector(".provider-name").textContent = event.summary;
        row.querySelector(".badge").textContent = event.action;
        row.querySelector(".small").textContent = auditMeta(event);
        auditList.append(row);
      });
    }

    async function loadAuditEvents() {
      refreshAuditButton.disabled = true;
      try {
        const response = await fetch("/api/v1/admin/audit-events", {headers: authHeaders()});
        if (!response.ok) throw new Error(await codedMessage(response));
        const body = await response.json();
        renderAuditEvents(body.audit_events || []);
      } catch (error) {
        auditList.replaceChildren();
        const row = document.createElement("div");
        row.className = "denial-row small";
        row.textContent = `Audit: ${error.message}`;
        auditList.append(row);
      } finally {
        refreshAuditButton.disabled = false;
      }
    }

    function watchStatus(watch) {
      if (!watch.enabled) return {label: "выключен", tone: "off"};
      if (watch.paused_until) return {label: "пауза", tone: "warn"};
      if (watch.last_scan_status === "failed") return {label: "ошибка", tone: "warn"};
      return {label: "активен", tone: "ok"};
    }

    function watchMeta(watch) {
      const trip = watch.return_date ? `${watch.departure_date} — ${watch.return_date}` : watch.departure_date;
      const scan = watch.last_scanned_at
        ? `последний scan ${watch.last_scanned_at}`
        : "scan ещё не запускался";
      const paused = watch.paused_until ? ` · пауза до ${watch.paused_until}` : "";
      return `${trip} · ${watch.passengers} пасс. · ${watch.currency} · v${watch.version} · ${scan}${paused}`;
    }

    function renderWatches(watches) {
      watchRecords = watches || [];
      watchList.replaceChildren();
      if (watchRecords.length === 0) {
        const empty = document.createElement("div");
        empty.className = "empty-state";
        empty.textContent = "Активных watches пока нет.";
        watchList.append(empty);
        return;
      }
      watchRecords.forEach((watch) => {
        const state = watchStatus(watch);
        const row = document.createElement("div");
        row.className = "provider-row";
        row.innerHTML = `
          <div class="row-main">
            <div class="provider-name"></div>
            <span class="badge ${state.tone}"></span>
          </div>
          <div class="small"></div>
          <div class="watch-actions"></div>
        `;
        row.querySelector(".provider-name").textContent = `${watch.origin} → ${watch.destination}`;
        row.querySelector(".badge").textContent = state.label;
        row.querySelector(".small").textContent = watchMeta(watch);
        const actions = row.querySelector(".watch-actions");
        const pauseButton = document.createElement("button");
        pauseButton.className = "chip";
        pauseButton.type = "button";
        pauseButton.textContent = watch.paused_until ? "Возобновить" : "Пауза";
        pauseButton.addEventListener("click", () =>
          watch.paused_until ? resumeWatch(watch) : pauseWatch(watch)
        );
        const historyButton = document.createElement("button");
        historyButton.className = "chip";
        historyButton.type = "button";
        historyButton.textContent = "История";
        historyButton.addEventListener("click", () => loadWatchHistory(watch));
        const archiveButton = document.createElement("button");
        archiveButton.className = "chip";
        archiveButton.type = "button";
        archiveButton.textContent = "Архив";
        archiveButton.addEventListener("click", () => archiveWatch(watch));
        const deleteButton = document.createElement("button");
        deleteButton.className = "chip";
        deleteButton.type = "button";
        deleteButton.textContent = "Удалить";
        deleteButton.addEventListener("click", () => deleteWatch(watch));
        actions.append(pauseButton, historyButton, archiveButton, deleteButton);
        watchList.append(row);
      });
    }

    function renderWatchHistory(watch, snapshots) {
      watchHistoryList.replaceChildren();
      appendSectionHeader(
        watchHistoryList,
        "История watch",
        `${watch.origin} → ${watch.destination}. Snapshots не являются live-гарантией.`
      );
      if (!snapshots || snapshots.length === 0) {
        const empty = document.createElement("div");
        empty.className = "empty-state";
        empty.textContent = "История цен пока пустая.";
        watchHistoryList.append(empty);
        return;
      }
      snapshots.forEach((snapshot) => {
        const row = document.createElement("div");
        row.className = "denial-row small";
        const confirmation = snapshot.requires_live_confirmation
          ? "нужна внешняя проверка"
          : "подтверждение источника";
        row.textContent =
          `${providerLabel(snapshot.provider_id)} · ${formatMinorAmount(snapshot.amount_minor, snapshot.currency)}`
          + ` · ${snapshot.freshness} · ${snapshot.observed_at} · ${confirmation}`;
        watchHistoryList.append(row);
      });
    }

    async function loadWatches() {
      try {
        const response = await fetch("/api/v1/watches", {headers: authHeaders()});
        if (!response.ok) throw new Error(await codedMessage(response));
        const body = await response.json();
        renderWatches(body.watches || []);
      } catch (error) {
        watchList.replaceChildren();
        const row = document.createElement("div");
        row.className = "denial-row small";
        row.textContent = `Watches: ${error.message}`;
        watchList.append(row);
      }
    }

    async function createWatchFromSearch() {
      const payload = buildSearchPayload();
      createWatchButton.disabled = true;
      statusLine.textContent = "creating watch...";
      try {
        const response = await fetch("/api/v1/watches", {
          method: "POST",
          headers: authHeaders({"Content-Type": "application/json"}),
          body: JSON.stringify({
            origin: payload.origin,
            destination: payload.destination,
            departure_date: payload.departure_date,
            return_date: payload.return_date,
            passengers: payload.passengers,
            currency: payload.currency,
            allowed_provider_ids: []
          })
        });
        if (!response.ok) throw new Error(await codedMessage(response));
        const watch = await response.json();
        statusLine.textContent = `watch created v${watch.version}`;
        await loadWatches();
        await loadAuditEvents();
        await loadWatchHistory(watch);
      } catch (error) {
        statusLine.textContent = "watch create error";
        watchHistoryList.replaceChildren();
        const row = document.createElement("div");
        row.className = "denial-row small";
        row.textContent = `Watch: ${error.message}`;
        watchHistoryList.append(row);
      } finally {
        createWatchButton.disabled = false;
      }
    }

    async function pauseWatch(watch) {
      await mutateWatch(watch, `/api/v1/watches/${watch.id}/pause`, "POST", {}, "watch paused");
    }

    async function resumeWatch(watch) {
      await mutateWatch(watch, `/api/v1/watches/${watch.id}/resume`, "POST", null, "watch resumed");
    }

    async function archiveWatch(watch) {
      await mutateWatch(
        watch,
        `/api/v1/watches/${watch.id}/archive`,
        "POST",
        {expected_version: watch.version},
        "watch archived"
      );
      watchHistoryList.replaceChildren();
    }

    async function deleteWatch(watch) {
      if (!window.confirm("Удалить watch из активного списка?")) return;
      await mutateWatch(
        watch,
        `/api/v1/watches/${watch.id}`,
        "DELETE",
        {expected_version: watch.version},
        "watch deleted"
      );
      watchHistoryList.replaceChildren();
    }

    async function mutateWatch(watch, url, method, body, okStatus) {
      statusLine.textContent = "watch action...";
      try {
        const options = {
          method,
          headers: authHeaders({"Content-Type": "application/json"})
        };
        if (body !== null) {
          options.body = JSON.stringify(body);
        }
        const response = await fetch(url, options);
        if (!response.ok) throw new Error(await codedMessage(response));
        statusLine.textContent = okStatus;
        await loadWatches();
        await loadAuditEvents();
        if (method !== "DELETE") {
          const latest = watchRecords.find((item) => item.id === watch.id);
          if (latest) await loadWatchHistory(latest);
        }
      } catch (error) {
        statusLine.textContent = "watch action error";
        watchHistoryList.replaceChildren();
        const row = document.createElement("div");
        row.className = "denial-row small";
        row.textContent = `Watch: ${error.message}`;
        watchHistoryList.append(row);
      }
    }

    async function loadWatchHistory(watch) {
      statusLine.textContent = "watch history...";
      try {
        const response = await fetch(`/api/v1/watches/${watch.id}/history`, {
          headers: authHeaders()
        });
        if (!response.ok) throw new Error(await codedMessage(response));
        const body = await response.json();
        renderWatchHistory(watch, body.snapshots || []);
        statusLine.textContent = "watch history ready";
      } catch (error) {
        watchHistoryList.replaceChildren();
        const row = document.createElement("div");
        row.className = "denial-row small";
        row.textContent = `Watch history: ${error.message}`;
        watchHistoryList.append(row);
        statusLine.textContent = "watch history error";
      }
    }

    function appendSectionHeader(container, title, subtitle) {
      const node = document.createElement("div");
      node.className = "denial-row";
      const strong = document.createElement("strong");
      strong.textContent = title;
      const meta = document.createElement("div");
      meta.className = "small";
      meta.textContent = subtitle;
      node.append(strong, document.createTextNode("\\n"), meta);
      container.append(node);
    }

    function compactTargetId(...parts) {
      const raw = parts
        .map((part) => text(part))
        .filter(Boolean)
        .join(":")
        .replace(/\\s+/g, " ");
      if (!raw) return "unknown";
      return raw.length <= 160 ? raw : `${raw.slice(0, 157)}...`;
    }

    function pricedOfferTarget(offer) {
      return {
        kind: "priced_offer",
        targetId: compactTargetId(offer.provider_id, offer.provider_offer_id),
        sourceId: offer.provider_id,
        price: offer.total_price || null
      };
    }

    function externalLinkTarget(link) {
      return {
        kind: link.kind || "external_search_link",
        targetId: compactTargetId(
          link.source_id,
          `${link.origin}-${link.destination}`,
          link.departure_date,
          link.return_date || "oneway",
          link.passengers
        ),
        sourceId: link.source_id,
        price: null
      };
    }

    function browserObservationTarget(offer) {
      return {
        kind: "browser_observation",
        targetId: compactTargetId(offer.observation_id),
        sourceId: offer.source_id,
        price: offer.total_price || null
      };
    }

    function dealCandidateTarget(candidate) {
      return {
        kind: "deal_candidate",
        targetId: compactTargetId(candidate.source_id, candidate.discovered_at, candidate.title),
        sourceId: candidate.source_id,
        price: candidate.extracted_price || null
      };
    }

    function manualConfirmationStatusLabel(status) {
      const labels = {
        confirmed: "цена совпала",
        price_changed: "цена изменилась",
        sold_out: "нет мест",
        bought: "куплено",
        wrong_route: "маршрут не тот"
      };
      return labels[status] || status;
    }

    function appendManualConfirmationActions(container, target) {
      const actions = document.createElement("div");
      actions.className = "confirmation-actions";
      const status = document.createElement("div");
      status.className = "confirmation-status";
      status.textContent = "Ручная проверка";
      manualConfirmationActions.forEach((item) => {
        const button = document.createElement("button");
        button.className = "chip";
        button.type = "button";
        button.textContent = item.label;
        button.addEventListener("click", () => recordManualConfirmation(target, item.status, status));
        actions.append(button);
      });
      container.append(actions, status);
    }

    async function recordManualConfirmation(target, status, statusNode) {
      const body = {
        target_kind: target.kind,
        target_id: target.targetId,
        source_id: target.sourceId,
        status,
        note: "web manual confirmation"
      };
      if ((status === "confirmed" || status === "bought") && target.price) {
        body.amount_minor = target.price.minor_units;
        body.currency = target.price.currency;
      }
      statusNode.textContent = "сохраняю...";
      try {
        const response = await fetch("/api/v1/manual-price-confirmations", {
          method: "POST",
          headers: authHeaders({"Content-Type": "application/json"}),
          body: JSON.stringify(body)
        });
        if (!response.ok) throw new Error(await codedMessage(response));
        const saved = await response.json();
        statusNode.textContent = `Сохранено: ${manualConfirmationStatusLabel(saved.status)}`;
        await loadManualConfirmations();
        statusLine.textContent = "manual confirmation saved";
      } catch (error) {
        statusNode.textContent = `Не сохранено: ${error.message}`;
        statusLine.textContent = "manual confirmation error";
      }
    }

    function renderManualConfirmations(confirmations) {
      confirmationList.replaceChildren();
      if (!confirmations || confirmations.length === 0) return;
      appendSectionHeader(
        confirmationList,
        "Ручные подтверждения",
        "Личная история проверок. Она не переписывает provider facts."
      );
      confirmations.forEach((confirmation) => {
        const row = document.createElement("div");
        row.className = "denial-row small";
        const price = confirmation.confirmed_price
          ? ` · ${confirmation.confirmed_price.formatted}`
          : "";
        row.textContent =
          `${manualConfirmationStatusLabel(confirmation.status)} · ${confirmation.source_id}`
          + ` · ${confirmation.target_kind}${price} · ${confirmation.confirmed_at}`;
        confirmationList.append(row);
      });
    }

    async function loadManualConfirmations() {
      try {
        const params = new URLSearchParams({limit: "8"});
        const response = await fetch(`/api/v1/manual-price-confirmations?${params.toString()}`, {
          headers: authHeaders()
        });
        if (!response.ok) throw new Error(await codedMessage(response));
        const body = await response.json();
        renderManualConfirmations(body.confirmations || []);
      } catch (error) {
        confirmationList.replaceChildren();
        const row = document.createElement("div");
        row.className = "denial-row small";
        row.textContent = `Ручные подтверждения: ${error.message}`;
        confirmationList.append(row);
      }
    }

    function renderResults(body) {
      const offers = body.priced_offers || body.offers || [];
      const externalLinks = body.external_links || [];
      const observedOffers = body.browser_observed_offers || [];
      const dealCandidates = body.deal_candidates || [];
      const freshnessSummary = body.freshness_summary || {};
      lastSearchId = body.search_id || null;
      lastExternalLinks = externalLinks;
      resultsList.replaceChildren();
      confirmationList.replaceChildren();
      liveList.replaceChildren();
      denialsList.replaceChildren();
      resultsCount.textContent = optionCountLabel(
        offers.length + externalLinks.length + observedOffers.length
      );

      appendSectionHeader(
        resultsList,
        "Цены из кэша",
        freshnessSummary.needs_external_confirmation
          ? "Нужна внешняя проверка перед покупкой."
          : "Свежесть подтверждена источником."
      );

      if (offers.length === 0) {
        const empty = document.createElement("div");
        empty.className = "empty-state";
        empty.textContent = "Недостаточно данных: нет вариантов по текущему запросу.";
        resultsList.append(empty);
      }

      offers.forEach((offer) => {
        const row = document.createElement("div");
        row.className = "result-row";
        const caveats = (offer.ranking_reasons || []).map((reason) => {
          const label = reasonLabel(reason);
          const tone = reason === "cached_price" || reason === "recent_price" ? "ok" : "warn";
          return `<span class="badge ${tone}">${label}</span>`;
        }).join("") + riskBadges(offer);
        row.innerHTML = `
          <div>
            <div class="route"></div>
            <div class="small"></div>
          </div>
          <div class="price"></div>
          <div>
            <div class="caveats">${caveats}</div>
            <div class="risk-detail small"></div>
            <div class="result-actions">
              <button class="secondary live-check-button" type="button">Проверить live</button>
            </div>
          </div>
        `;
        row.querySelector(".route").textContent = `${offer.origin} → ${offer.destination}`;
        row.querySelector(".small").textContent =
          `${offer.departure_date}${offer.return_date ? " — " + offer.return_date : ""}`
          + ` · ${offer.passengers} пасс. · ${providerLabel(offer.provider_id)}`
          + `${priceBasisLabel(offer)} · ${offer.freshness}`;
        row.querySelector(".price").textContent = offer.total_price.formatted;
        row.querySelector(".risk-detail").textContent = riskExplanationText(offer);
        row.querySelector(".live-check-button").addEventListener("click", () => runLiveCheck());
        appendManualConfirmationActions(row.querySelector(".result-actions"), pricedOfferTarget(offer));
        resultsList.append(row);
      });

      appendSectionHeader(
        resultsList,
        "Ссылки для проверки",
        "Это внешние сайты, не найденные цены. Откройте и проверьте маршрут вручную."
      );
      if (externalLinks.length === 0) {
        const empty = document.createElement("div");
        empty.className = "empty-state";
        empty.textContent = "Пока нет внешних ссылок для проверки.";
        resultsList.append(empty);
      }
      externalLinks.forEach((link) => {
        const row = document.createElement("div");
        row.className = "result-row";
        row.innerHTML = `
          <div>
            <div class="route"></div>
            <div class="small"></div>
          </div>
          <div class="price">Цена неизвестна</div>
          <div>
            <div class="caveats"><span class="badge warn">external check</span></div>
            <div class="result-actions">
              <a class="secondary" target="_blank" rel="noopener noreferrer">Открыть на сайте</a>
            </div>
          </div>
        `;
        row.querySelector(".route").textContent =
          `${link.source_name}: ${link.origin} -> ${link.destination}`;
        row.querySelector(".small").textContent =
          `${link.departure_date}${link.return_date ? " — " + link.return_date : ""}`
          + ` · ${link.passengers} пасс. · ${link.notes_ru || "Проверить на внешнем сайте."}`;
        row.querySelector("a").href = link.url;
        appendManualConfirmationActions(row.querySelector(".result-actions"), externalLinkTarget(link));
        resultsList.append(row);
      });

      appendSectionHeader(
        liveList,
        "Свежие наблюдения из браузера",
        "Personal Browser Observer запускается только после явного действия пользователя."
      );
      if (observedOffers.length === 0) {
        const empty = document.createElement("div");
        empty.className = "empty-state";
        empty.textContent = "Пока нет browser observation по этому запросу.";
        liveList.append(empty);
      }
      observedOffers.forEach((offer) => {
        const row = document.createElement("div");
        row.className = "denial-row";
        const details = document.createElement("div");
        details.className = "small";
        details.textContent =
          `${offer.source_name}: ${offer.total_price ? offer.total_price.formatted : "цена не найдена"}`
          + ` · confidence=${offer.confidence} · ${offer.parser_warnings.join(", ") || "без предупреждений"}`;
        row.append(details);
        appendManualConfirmationActions(row, browserObservationTarget(offer));
        liveList.append(row);
      });

      if (dealCandidates.length > 0) {
        renderDealCandidates(dealCandidates);
      }

      Object.entries(body.denied_providers || {}).forEach(([providerId, denial]) => {
        const row = document.createElement("div");
        row.className = "denial-row small";
        row.textContent = `${providerLabel(providerId)}: ${reasonLabel(denial.code)}`;
        denialsList.append(row);
      });
      if (sessionToken()) {
        loadManualConfirmations();
      } else {
        renderSignedOutConfirmationState();
      }
    }

    function renderLiveObservation(observation) {
      liveList.replaceChildren();
      const row = document.createElement("div");
      row.className = "denial-row small";
      const offer = (observation.offers || [])[0];
      if (!offer) {
        row.textContent = `Live: ${observation.status}`;
        liveList.append(row);
        return;
      }
      row.textContent =
        `Live observed · ${offer.total_price.formatted} · ${offer.origin} → ${offer.destination}`
        + ` · наблюдалось ${observation.observed_at}`;
      liveList.append(row);
    }

    function renderPersonalObservationJob(job) {
      liveList.replaceChildren();
      appendSectionHeader(
        liveList,
        "Personal Browser Observer",
        "Job обрабатывается worker CLI; ручной checkpoint можно продолжить или отменить."
      );
      const row = document.createElement("div");
      row.className = "denial-row small";
      const command = `uv run flight-hunter-run-personal-observation --job-id ${job.job_id}`;
      const waiting = job.status === "waiting_for_user";
      const flags = [
        job.waiting_since ? `ждёт с ${job.waiting_since}` : null,
        job.operator_resume_requested_at ? "resume requested" : null,
        job.operator_abort_requested_at ? "abort requested" : null,
      ].filter(Boolean).join(" · ");
      row.textContent = `Job ${job.job_id} · ${job.status}${flags ? ` · ${flags}` : ""}. Команда: ${command}`;
      const controls = document.createElement("div");
      controls.className = "quick-actions";
      const refresh = document.createElement("button");
      refresh.className = "secondary";
      refresh.type = "button";
      refresh.textContent = "Обновить";
      refresh.addEventListener("click", () => refreshPersonalObservation(job.job_id));
      const resume = document.createElement("button");
      resume.className = "secondary";
      resume.type = "button";
      resume.textContent = "Продолжить";
      resume.disabled = !waiting || Boolean(job.operator_resume_requested_at || job.operator_abort_requested_at);
      resume.addEventListener("click", () => controlPersonalObservation(job.job_id, "resume"));
      const abort = document.createElement("button");
      abort.className = "secondary";
      abort.type = "button";
      abort.textContent = "Отменить";
      abort.disabled = !waiting || Boolean(job.operator_resume_requested_at || job.operator_abort_requested_at);
      abort.addEventListener("click", () => controlPersonalObservation(job.job_id, "abort"));
      controls.append(refresh, resume, abort);
      liveList.append(row);
      liveList.append(controls);
      if (job.operator_instruction) {
        const hint = document.createElement("div");
        hint.className = "denial-row small";
        hint.textContent = job.operator_instruction;
        liveList.append(hint);
      }
    }

    function renderDealCandidates(candidates) {
      appendSectionHeader(
        denialsList,
        "Сделки/форумы",
        "Кандидаты требуют ручной проверки и не считаются источником истины цены."
      );
      candidates.forEach((candidate) => {
        const row = document.createElement("div");
        row.className = "denial-row";
        const details = document.createElement("div");
        details.className = "small";
        details.textContent = `${candidate.title}: ${candidate.summary_ru}`;
        const expiry = document.createElement("div");
        expiry.className = "small";
        expiry.textContent = dealCandidateExpiryLabel(candidate);
        row.append(details);
        row.append(expiry);
        appendManualConfirmationActions(row, dealCandidateTarget(candidate));
        denialsList.append(row);
      });
    }

    function choosePersonalObservationSource() {
      const supported = ["tutu", "yandex_travel", "onetwotrip"];
      const link = lastExternalLinks.find((item) => supported.includes(item.source_id));
      return link ? link.source_id : "tutu";
    }

    function enabledBrowserSource() {
      return browserSources.find((source) =>
        source.enabled && source.permission_status === "active"
      );
    }

    async function loadProviders() {
      const response = await fetch("/api/v1/providers");
      const body = await response.json();
      renderProviders(body.providers || []);
    }

    async function loadBrowserSources() {
      const response = await fetch("/api/v1/browser-sources");
      const body = await response.json();
      browserSources = body.sources || [];
    }

    async function loadAgentPresets() {
      const response = await fetch("/api/v1/agent/presets");
      const body = await response.json();
      agentPresets = body.presets || [];
      if (!body.mode || !body.mode.enabled) {
        agentMode.textContent = "harness";
      }
      presetList.replaceChildren();
      agentPresets.slice(0, 5).forEach((preset) => {
        const button = document.createElement("button");
        button.className = "chip";
        button.type = "button";
        button.textContent = preset.title_ru;
        button.addEventListener("click", () => requestAgentPlan(preset.id, preset.title_ru));
        presetList.append(button);
      });
    }

    function choosePreset(prompt) {
      const raw = prompt.toLowerCase();
      if (raw.includes("аэроп")) return "nearby_airports";
      if (raw.includes("когда") || raw.includes("покуп")) return "buy_timing";
      if (raw.includes("стык") || raw.includes("разб")) return "split_ticket";
      if (raw.includes("скры") || raw.includes("hidden")) return "hidden_city";
      if (raw.includes("валют") || raw.includes("страна")) return "geo_currency";
      if (raw.includes("ошиб") || raw.includes("error")) return "error_fare_sources";
      return "flexible_dates";
    }

    function freshIdempotencyKey() {
      if (window.crypto && typeof window.crypto.randomUUID === "function") {
        return `web-${window.crypto.randomUUID()}`;
      }
      if (window.crypto && typeof window.crypto.getRandomValues === "function") {
        const words = new Uint32Array(4);
        window.crypto.getRandomValues(words);
        return `web-${Array.from(words, (word) => word.toString(16).padStart(8, "0")).join("")}`;
      }
      throw new Error("secure_idempotency_key_unavailable");
    }

    function agentPlanUrl(planId) {
      return `/api/v1/agent/search-plans/${encodeURIComponent(planId)}`;
    }

    function agentPlanStateLabel(state) {
      const labels = {
        draft: "Черновик — нужны уточнения",
        awaiting_approval: "Ждёт явного запуска",
        consumed: "Быстрый план уже запущен",
        expired: "План истёк",
        superseded: "Есть более новая ревизия"
      };
      return labels[state] || state || "Неизвестно";
    }

    function agentScopeLabel(scope) {
      if (!scope || scope.length === 0) return "Неизвестно";
      return scope.map((leg, index) => {
        const requestedOrigin = [leg.origin_kind, leg.origin_value].filter(Boolean).join(": ");
        const requestedDestination = [leg.destination_kind, leg.destination_value]
          .filter(Boolean).join(": ");
        const origin = leg.frozen && leg.origin_airports.length
          ? leg.origin_airports.join(", ")
          : requestedOrigin || "не задано";
        const destination = leg.anywhere
          ? "куда угодно"
          : leg.frozen && leg.destination_airports.length
            ? leg.destination_airports.join(", ")
            : requestedDestination || "не задано";
        const nearby = leg.nearby_radius_km > 0 ? ` · радиус ${leg.nearby_radius_km} км` : "";
        const freeze = leg.frozen ? "заморожено" : "ещё не заморожено";
        return `${index + 1}. ${origin} → ${destination}${nearby} · ${freeze}`;
      }).join("; ");
    }

    function agentDateLabel(plan) {
      const summary = plan.summary || {};
      const legs = summary.scope || [];
      const ranges = legs.map((leg) => {
        if (!leg.date_start) return null;
        const end = leg.date_end && leg.date_end !== leg.date_start ? ` — ${leg.date_end}` : "";
        const flex = leg.flex_days > 0 ? ` · ±${leg.flex_days} дн.` : "";
        return `${leg.date_start}${end}${flex}`;
      }).filter(Boolean);
      return `${summary.date_mode || "Неизвестно"}${ranges.length ? ` · ${ranges.join("; ")}` : ""}`;
    }

    function agentEstimateLabel(plan) {
      if (!plan.estimate) {
        const budget = (plan.clarifications || []).find(
          (item) => item.code === "quick_budget_too_large"
        );
        if (budget) {
          const logical = budget.details && budget.details.logical_operations;
          const calendar = budget.details && budget.details.calendar_searches;
          const exact = budget.details && budget.details.exact_searches;
          const limit = budget.details && budget.details.limit;
          return `Не исполняется: ${logical ?? "?"} операций `
            + `(${calendar ?? "?"} календарных, ${exact ?? "?"} точных) `
            + `при лимите ${limit ?? "?"}`;
        }
        return "Недостаточно данных";
      }
      return `${plan.estimate.logical_operations} операций · `
        + `${plan.estimate.http_attempts} HTTP-попыток`;
    }

    function agentClarificationLabel(plan) {
      const clarifications = plan.clarifications || [];
      if (!clarifications.length) return "";
      return ` · ${clarifications.map((item) => item.message_ru).join(" ")}`;
    }

    function renderAgentPlan(plan) {
      currentAgentPlan = plan;
      agentEditMode = false;
      window.localStorage.setItem(agentPlanStorageKey, String(plan.plan_id));
      const summary = plan.summary || {};
      const passengers = summary.passengers || {};
      const provider = summary.provider || {};
      const hiddenCityEnabled = summary.hidden_city_enabled === true;
      const executeReady = plan.state === "awaiting_approval"
        && plan.executable === true
        && !hiddenCityEnabled;
      const cloneReady = ["consumed", "expired", "superseded"].includes(plan.state)
        && plan.coverage === "quick";
      const editReady = ["draft", "awaiting_approval"].includes(plan.state);

      document.getElementById("agent-plan-card").hidden = false;
      document.getElementById("agent-plan-status").textContent =
        `${agentPlanStateLabel(plan.state)}${agentClarificationLabel(plan)}`;
      document.getElementById("agent-plan-revision").textContent =
        `${plan.revision} · ${String(plan.revision_id).slice(0, 8)}`;
      document.getElementById("agent-plan-scope").textContent = agentScopeLabel(summary.scope || []);
      document.getElementById("agent-plan-date-mode").textContent = agentDateLabel(plan);
      document.getElementById("agent-plan-passengers").textContent = passengers.total
        ? `${passengers.adults} взр. · ${passengers.children} дет. · `
          + `${passengers.infants} мл. · всего ${passengers.total} · ${passengers.currency}`
        : "Неизвестно";
      document.getElementById("agent-plan-coverage").textContent = plan.coverage || "Неизвестно";
      document.getElementById("agent-plan-strategies").textContent =
        (plan.enabled_strategies || []).join(", ") || "Стандартный маршрут";
      document.getElementById("agent-plan-hidden-city").textContent = hiddenCityEnabled
        ? "Включён: только без регистрируемого багажа; сегменты после выхода могут отменить"
        : "Выключен";
      document.getElementById("agent-plan-estimate").textContent = agentEstimateLabel(plan);
      document.getElementById("agent-plan-rpm").textContent = provider.requests_per_minute == null
        ? "Неизвестно"
        : `${provider.requests_per_minute} запросов/мин`;
      document.getElementById("agent-plan-deadline").textContent = plan.estimate
        ? `${plan.estimate.deadline_seconds} сек.`
        : "Неизвестно";
      document.getElementById("agent-plan-source").textContent = provider.source_id
        ? `${provider.source_id} · ${provider.capability_version} · ${provider.cost_model_version}`
        : "Неизвестно";
      document.getElementById("agent-plan-expiry").textContent = plan.expires_at || "Неизвестно";

      const executeButton = document.getElementById("agent-plan-execute");
      executeButton.disabled = !executeReady;
      executeButton.title = executeReady
        ? "Запустить ровно эту замороженную ревизию"
        : hiddenCityEnabled
          ? "Для hidden-city нужно отдельное подтверждение риска"
          : "Сначала устраните уточнения или создайте новый план";
      const cloneButton = document.getElementById("agent-plan-full");
      cloneButton.disabled = !cloneReady;
      cloneButton.title = cloneReady
        ? "Создать новую full-ревизию из завершённого quick-плана"
        : "Full-ревизия доступна после завершения или истечения quick-плана";
      const editButton = document.getElementById("agent-plan-edit");
      editButton.disabled = !editReady;
      editButton.title = editReady ? "Уточнить запрос и создать новую ревизию" : "Ревизия закрыта";
      document.getElementById("agent-risky-results").hidden = !hiddenCityEnabled;
      document.getElementById("agent-risky-results-list").textContent = hiddenCityEnabled
        ? "Подтверждённых вариантов ещё нет. Рискованные варианты не смешиваются с обычными."
        : "Нет подтверждённых рискованных вариантов.";
    }

    function beginAgentPlanEdit() {
      if (
        !currentAgentPlan
        || !["draft", "awaiting_approval"].includes(currentAgentPlan.state)
      ) return;
      agentEditMode = true;
      const input = document.querySelector("#assistant-form textarea");
      input.placeholder = "Опиши изменение для текущей ревизии плана";
      input.focus();
      document.getElementById("agent-plan-status").textContent =
        "Режим изменения: следующий запрос создаст новую ревизию этого плана.";
    }

    function renderAirportChoices(optionsByRole) {
      airportChoiceList.replaceChildren();
      Object.entries(optionsByRole || {}).forEach(([role, options]) => {
        (options || []).forEach((option) => {
          const node = document.createElement("button");
          node.className = "choice-card";
          node.type = "button";
          const title = document.createElement("strong");
          title.textContent = `${role === "origin" ? "Откуда" : "Куда"} · ${option.iata_code}`;
          const meta = document.createElement("span");
          meta.className = "small";
          const duplicatePrefix = `${option.iata_code} - `;
          meta.textContent = option.label && option.label.startsWith(duplicatePrefix)
            ? option.label.slice(duplicatePrefix.length)
            : option.label;
          node.append(title, document.createTextNode("\\n"), meta);
          node.addEventListener("click", () => {
            const field = role === "origin" ? "origin" : "destination";
            document.querySelector(`[name="${field}"]`).value = option.iata_code;
            addMessage("user", `${field}: ${option.iata_code}`);
          });
          airportChoiceList.append(node);
        });
      });
      if (!airportChoiceList.children.length) {
        const empty = document.createElement("div");
        empty.className = "choice-card";
        empty.textContent = "Пока вариантов нет";
        airportChoiceList.append(empty);
      }
    }

    function renderAgentActions(actions) {
      agentActionList.replaceChildren();
      (actions || []).forEach((action) => {
        const node = document.createElement("button");
        node.className = "action-card";
        node.type = "button";
        const title = document.createElement("strong");
        title.textContent = `${action.title_ru}:`;
        const meta = document.createElement("div");
        meta.className = "small";
        const gate = action.requires_user_action
          ? "нужен явный клик"
          : "можно выполнить без live-вызова";
        meta.textContent = `${gate} · ${action.policy_decision}`;
        node.append(title, document.createTextNode("\\n"), meta);
        node.addEventListener("click", () => {
          reviseAgentPlan(action.parameters || {});
        });
        agentActionList.append(node);
      });
      if (!agentActionList.children.length) {
        const empty = document.createElement("div");
        empty.className = "action-card";
        empty.textContent = "Агент ждёт маршрут";
        agentActionList.append(empty);
      }
    }

    function typedAgentAction(parameters) {
      const allowedSelections = new Set([
        "origin",
        "destination",
        "date_mode",
        "departure_date",
        "date_start",
        "date_end",
        "return_date",
        "trip_shape",
        "currency",
        "requested_strategies"
      ]);
      const selections = {};
      Object.entries(parameters || {}).forEach(([key, value]) => {
        if (allowedSelections.has(key)) selections[key] = value;
      });
      return {
        selections,
        coverage: parameters && ["quick", "full"].includes(parameters.coverage)
          ? parameters.coverage
          : null
      };
    }

    function agentRunErrorMessage(code, fallback) {
      const messages = {
        aviasales_search_rate_limited: "Aviasales временно ограничил частоту запросов.",
        aviasales_search_blocked: "Aviasales заблокировал запрос; данные не подменены.",
        aviasales_search_unavailable: "Aviasales сейчас недоступен; показаны только подтверждённые данные.",
        agent_run_deadline_exceeded: "Дедлайн запуска истёк до завершения всей области."
      };
      return messages[code] || fallback || code || "Неизвестная ошибка запуска";
    }

    function renderAgentRun(run) {
      currentAgentRun = run;
      const progress = document.getElementById("agent-run-progress");
      const cancelButton = document.getElementById("agent-run-cancel");
      const partialErrors = document.getElementById("agent-partial-errors");
      const terminalProblem = ["partial", "failed", "cancelled"].includes(run.status);
      progress.textContent = `Запуск ${String(run.run_id).slice(0, 8)} · ${run.status} · `
        + `дедлайн ${run.deadline_at}`;
      cancelButton.disabled = !["queued", "running"].includes(run.status);
      cancelButton.title = run.status === "cancel_requested"
        ? "Отмена уже запрошена"
        : "Отменить выполняющийся запуск";
      partialErrors.hidden = !terminalProblem && !run.error_code;
      partialErrors.textContent = partialErrors.hidden
        ? ""
        : agentRunErrorMessage(run.error_code, run.public_message || `Состояние: ${run.status}`);
    }

    async function reviseAgentPlan(parameters) {
      if (
        !currentAgentPlan
        || !["draft", "awaiting_approval"].includes(currentAgentPlan.state)
      ) return;
      const revision = typedAgentAction(parameters);
      if (!revision.coverage && Object.keys(revision.selections).length === 0) {
        document.querySelector("#assistant-form textarea").focus();
        return;
      }
      const body = {
        source_revision_id: currentAgentPlan.revision_id,
        expected_revision: currentAgentPlan.revision,
        selections: revision.selections
      };
      if (revision.coverage) body.coverage = revision.coverage;
      const response = await fetch(agentPlanUrl(currentAgentPlan.plan_id), {
        method: "PATCH",
        headers: authHeaders({"Content-Type": "application/json"}),
        body: JSON.stringify(body)
      });
      if (!response.ok) throw new Error(await codedMessage(response));
      renderAgentPlan(await response.json());
      renderAgentRunPlaceholder("Новая ревизия ждёт явного запуска.");
    }

    async function editAgentPlan(prompt) {
      if (
        !currentAgentPlan
        || !["draft", "awaiting_approval"].includes(currentAgentPlan.state)
      ) return;
      addMessage("user", prompt);
      const response = await fetch(agentPlanUrl(currentAgentPlan.plan_id), {
        method: "PATCH",
        headers: authHeaders({"Content-Type": "application/json"}),
        body: JSON.stringify({
          source_revision_id: currentAgentPlan.revision_id,
          expected_revision: currentAgentPlan.revision,
          text: prompt,
          selections: {}
        })
      });
      if (!response.ok) throw new Error(await codedMessage(response));
      const plan = await response.json();
      renderAgentPlan(plan);
      renderAgentRunPlaceholder("Изменённая ревизия ждёт явного запуска.");
      addMessage("bot", `Создана ревизия ${plan.revision}: ${agentPlanStateLabel(plan.state)}.`);
    }

    async function executeAgentPlan() {
      if (
        !currentAgentPlan
        || currentAgentPlan.state !== "awaiting_approval"
        || !currentAgentPlan.executable
        || currentAgentPlan.summary.hidden_city_enabled === true
      ) return;
      const response = await fetch(`${agentPlanUrl(currentAgentPlan.plan_id)}/execute`, {
        method: "POST",
        headers: authHeaders({
          "Content-Type": "application/json",
          "Idempotency-Key": freshIdempotencyKey()
        }),
        body: JSON.stringify({
          revision_id: currentAgentPlan.revision_id,
          expected_revision: currentAgentPlan.revision,
          content_hash: currentAgentPlan.content_hash
        })
      });
      if (!response.ok) throw new Error(await codedMessage(response));
      renderAgentRun(await response.json());
      await reloadAgentPlan();
    }

    async function cloneAgentPlanAsFull() {
      if (
        !currentAgentPlan
        || !["consumed", "expired", "superseded"].includes(currentAgentPlan.state)
        || currentAgentPlan.coverage !== "quick"
      ) return;
      const response = await fetch(`${agentPlanUrl(currentAgentPlan.plan_id)}/revisions`, {
        method: "POST",
        headers: authHeaders({
          "Content-Type": "application/json",
          "Idempotency-Key": freshIdempotencyKey()
        }),
        body: JSON.stringify({
          source_revision_id: currentAgentPlan.revision_id,
          expected_revision: currentAgentPlan.revision,
          selections: {},
          coverage: "full"
        })
      });
      if (!response.ok) throw new Error(await codedMessage(response));
      renderAgentPlan(await response.json());
      renderAgentRunPlaceholder("Новая full-ревизия ждёт явного запуска.");
    }

    async function reloadAgentPlan() {
      if (!sessionToken()) return;
      const storedPlanId = window.localStorage.getItem(agentPlanStorageKey);
      if (!storedPlanId) return;
      const response = await fetch(agentPlanUrl(storedPlanId), {headers: authHeaders()});
      if (response.status === 404) {
        window.localStorage.removeItem(agentPlanStorageKey);
        currentAgentPlan = null;
        currentAgentRun = null;
        document.getElementById("agent-plan-card").hidden = true;
        return;
      }
      if (!response.ok) throw new Error(await codedMessage(response));
      renderAgentPlan(await response.json());
      const runResponse = await fetch(`${agentPlanUrl(storedPlanId)}/runs/latest`, {
        headers: authHeaders()
      });
      if (runResponse.status === 404) {
        renderAgentRunPlaceholder("Запуск ещё не создан.");
        return;
      }
      if (!runResponse.ok) throw new Error(await codedMessage(runResponse));
      const run = await runResponse.json();
      renderAgentRun(run);
      if (["queued", "running", "cancel_requested"].includes(run.status)) {
        window.setTimeout(() => pollAgentRun(run, 1000), 1000);
      }
    }

    async function pollAgentRun(run, delayMs = 1000) {
      if (!currentAgentPlan || currentAgentRun?.run_id !== run.run_id) return;
      const response = await fetch(
        `${agentPlanUrl(currentAgentPlan.plan_id)}/runs/${encodeURIComponent(run.run_id)}`,
        {headers: authHeaders()}
      );
      if (!response.ok) throw new Error(await codedMessage(response));
      const latest = await response.json();
      renderAgentRun(latest);
      if (
        latest.status === "queued"
        || latest.status === "running"
        || latest.status === "cancel_requested"
      ) {
        const nextDelay = Math.min(Math.round(delayMs * 1.5), 10000);
        window.setTimeout(() => pollAgentRun(latest, nextDelay), nextDelay);
      } else {
        const planResponse = await fetch(agentPlanUrl(currentAgentPlan.plan_id), {
          headers: authHeaders()
        });
        if (planResponse.ok) renderAgentPlan(await planResponse.json());
      }
    }

    async function cancelAgentRun() {
      if (
        !currentAgentPlan
        || !currentAgentRun
        || !["queued", "running"].includes(currentAgentRun.status)
      ) return;
      const response = await fetch(
        `${agentPlanUrl(currentAgentPlan.plan_id)}/runs/`
          + `${encodeURIComponent(currentAgentRun.run_id)}/cancel`,
        {method: "POST", headers: authHeaders()}
      );
      if (!response.ok) throw new Error(await codedMessage(response));
      renderAgentRun(await response.json());
    }

    function renderAgentRunPlaceholder(message) {
      currentAgentRun = null;
      document.getElementById("agent-run-progress").textContent = message;
      document.getElementById("agent-run-cancel").disabled = true;
      document.getElementById("agent-partial-errors").hidden = true;
      document.getElementById("agent-partial-errors").textContent = "";
    }

    async function lookupAirports(query) {
      const response = await fetch(`/api/v1/airports/search?q=${encodeURIComponent(query)}`);
      if (!response.ok) throw new Error(`airport HTTP ${response.status}`);
      return response.json();
    }

    async function requestAgentChat(prompt) {
      lastAgentPrompt = prompt;
      addMessage("user", prompt);
      statusLine.textContent = "агент думает...";
      const payload = buildSearchPayload();
      try {
        const response = await fetch("/api/v1/agent/chat/turn", {
          method: "POST",
          headers: authHeaders({"Content-Type": "application/json"}),
          body: JSON.stringify({
            message: prompt,
            passengers: payload.passengers,
            adults: payload.adults,
            children: payload.children,
            infants: payload.infants,
            currency: payload.currency
          })
        });
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        const body = await response.json();
        addMessage("bot", body.reply_ru);
        renderAgentPlan(body.proposed_plan);
        renderAgentRunPlaceholder("План создан, запуск ещё не выполнялся.");
        renderAgentRuntime(body.runtime);
        renderAirportChoices(body.airport_options);
        renderAgentActions(body.actions);
        syncExtractedRoute(body);
        statusLine.textContent = "агент готов";
      } catch (error) {
        addMessage("bot", `Агент не смог выполнить turn: ${error.message}`);
        statusLine.textContent = "ошибка агента";
      }
    }

    async function requestAgentPlan(presetId, visiblePrompt) {
      addMessage("user", visiblePrompt);
      statusLine.textContent = "ИИ думает...";
      try {
        const response = await fetch("/api/v1/agent/plan", {
          method: "POST",
          headers: authHeaders({"Content-Type": "application/json"}),
          body: JSON.stringify({preset_id: presetId, slots: currentSlots()})
        });
        if (!response.ok) throw new Error(await codedMessage(response));
        renderAgentPlan(await response.json());
        renderAgentRunPlaceholder("План создан, запуск ещё не выполнялся.");
        statusLine.textContent = "готово";
      } catch (error) {
        addMessage("bot", `Не смог собрать план: ${error.message}`);
        statusLine.textContent = "ошибка";
      }
    }

    async function runSearch(event) {
      event.preventDefault();
      submitButton.disabled = true;
      statusLine.textContent = "поиск...";
      const payload = buildSearchPayload();
      lastSearchPayload = payload;

      try {
        const response = await fetch("/api/v1/searches", {
          method: "POST",
          headers: authHeaders({"Content-Type": "application/json"}),
          body: JSON.stringify(payload)
        });
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        renderResults(await response.json());
        statusLine.textContent = "готово";
      } catch (error) {
        resultsList.replaceChildren();
        confirmationList.replaceChildren();
        const node = document.createElement("div");
        node.className = "error-state";
        node.textContent = `Ошибка поиска: ${error.message}`;
        resultsList.append(node);
        statusLine.textContent = "ошибка";
      } finally {
        submitButton.disabled = false;
      }
    }

    async function runLiveCheck() {
      if (!lastSearchPayload) return;
      const source = enabledBrowserSource();
      if (!source) {
        liveList.replaceChildren();
        const row = document.createElement("div");
        row.className = "denial-row small";
        row.textContent = "Live: demo observer выключен или нет активного разрешения.";
        liveList.append(row);
        return;
      }

      statusLine.textContent = "live check...";
      try {
        const grantResponse = await fetch("/api/v1/live-observation-grants", {
          method: "POST",
          headers: authHeaders({"Content-Type": "application/json"}),
          body: JSON.stringify({source_id: source.source_id, search_intent: lastSearchPayload})
        });
        if (!grantResponse.ok) throw new Error(`grant HTTP ${grantResponse.status}`);
        const grant = await grantResponse.json();
        const tokenField = "grant" + "_" + "token";
        const createResponse = await fetch("/api/v1/live-observations", {
          method: "POST",
          headers: authHeaders({
            "Content-Type": "application/json",
            "Idempotency-Key": `web-${Date.now()}-${Math.random().toString(16).slice(2)}`
          }),
          body: JSON.stringify({
            source_id: source.source_id,
            search_intent: lastSearchPayload,
            [tokenField]: grant[tokenField]
          })
        });
        if (!createResponse.ok) throw new Error(`observation HTTP ${createResponse.status}`);
        const created = await createResponse.json();
        const observationResponse = await fetch(
          `/api/v1/live-observations/${created.observation_id}`,
          {headers: authHeaders()}
        );
        if (!observationResponse.ok) throw new Error(`result HTTP ${observationResponse.status}`);
        renderLiveObservation(await observationResponse.json());
        statusLine.textContent = "live observed";
      } catch (error) {
        liveList.replaceChildren();
        const row = document.createElement("div");
        row.className = "denial-row small";
        row.textContent = `Live: ${error.message}`;
        liveList.append(row);
        statusLine.textContent = "live error";
      }
    }

    async function runPersonalObservation() {
      if (!lastSearchPayload || !lastSearchId) {
        liveList.replaceChildren();
        const row = document.createElement("div");
        row.className = "denial-row small";
        row.textContent = "Personal observer: сначала выполните поиск.";
        liveList.append(row);
        return;
      }
      const sourceId = choosePersonalObservationSource();
      personalObserveButton.disabled = true;
      statusLine.textContent = "browser job...";
      try {
        const grantResponse = await fetch("/api/v1/personal-observations/grants", {
          method: "POST",
          headers: authHeaders({"Content-Type": "application/json"}),
          body: JSON.stringify({source_id: sourceId, search_intent: lastSearchPayload})
        });
        if (!grantResponse.ok) throw new Error(await codedMessage(grantResponse));
        const grant = await grantResponse.json();
        const tokenField = "grant" + "_" + "token";
        const createResponse = await fetch("/api/v1/personal-observations", {
          method: "POST",
          headers: authHeaders({
            "Content-Type": "application/json",
            "Idempotency-Key": `personal-${Date.now()}-${Math.random().toString(16).slice(2)}`
          }),
          body: JSON.stringify({
            source_id: sourceId,
            search_id: lastSearchId,
            search_intent: lastSearchPayload,
            [tokenField]: grant[tokenField]
          })
        });
        if (!createResponse.ok) throw new Error(await codedMessage(createResponse));
        renderPersonalObservationJob(await createResponse.json());
        statusLine.textContent = "browser job queued";
      } catch (error) {
        liveList.replaceChildren();
        const row = document.createElement("div");
        row.className = "denial-row small";
        row.textContent = `Personal observer: ${error.message}`;
        liveList.append(row);
        statusLine.textContent = "browser job error";
      } finally {
        personalObserveButton.disabled = false;
      }
    }

    async function refreshPersonalObservation(jobId) {
      try {
        const response = await fetch(`/api/v1/personal-observations/${jobId}`, {
          headers: authHeaders()
        });
        if (!response.ok) throw new Error(await codedMessage(response));
        renderPersonalObservationJob(await response.json());
      } catch (error) {
        statusLine.textContent = `browser status error: ${error.message}`;
      }
    }

    async function controlPersonalObservation(jobId, action) {
      try {
        const response = await fetch(`/api/v1/personal-observations/${jobId}/${action}`, {
          method: "POST",
          headers: authHeaders()
        });
        if (!response.ok) throw new Error(await codedMessage(response));
        renderPersonalObservationJob(await response.json());
        statusLine.textContent = `browser checkpoint ${action} requested`;
      } catch (error) {
        statusLine.textContent = `browser checkpoint error: ${error.message}`;
      }
    }

    async function runDealDiscovery() {
      if (!lastSearchPayload || !lastSearchId) {
        denialsList.replaceChildren();
        const row = document.createElement("div");
        row.className = "denial-row small";
        row.textContent = "Deal discovery: сначала выполните поиск.";
        denialsList.append(row);
        return;
      }
      dealDiscoveryButton.disabled = true;
      statusLine.textContent = "deal discovery...";
      try {
        const response = await fetch("/api/v1/deals/discover", {
          method: "POST",
          headers: authHeaders({"Content-Type": "application/json"}),
          body: JSON.stringify({
            search_id: lastSearchId,
            search_intent: lastSearchPayload,
            limit: 5
          })
        });
        if (!response.ok) throw new Error(await codedMessage(response));
        const body = await response.json();
        denialsList.replaceChildren();
        renderDealCandidates(body.candidates || []);
        statusLine.textContent = "deal candidates ready";
      } catch (error) {
        denialsList.replaceChildren();
        const row = document.createElement("div");
        row.className = "denial-row small";
        row.textContent = `Deal discovery: ${error.message}`;
        denialsList.append(row);
        statusLine.textContent = "deal discovery unavailable";
      } finally {
        dealDiscoveryButton.disabled = false;
      }
    }

    async function codedMessage(response) {
      try {
        const body = await response.json();
        return body.code || body.message || `HTTP ${response.status}`;
      } catch (error) {
        return `HTTP ${response.status}`;
      }
    }

    document.querySelector("#search-form").addEventListener("submit", runSearch);
    document.getElementById("agent-plan-execute").addEventListener("click", executeAgentPlan);
    document.getElementById("agent-plan-full").addEventListener("click", cloneAgentPlanAsFull);
    document.getElementById("agent-run-cancel").addEventListener("click", cancelAgentRun);
    document.getElementById("agent-plan-edit").addEventListener("click", beginAgentPlanEdit);
    authForm.addEventListener("submit", acceptInvitation);
    authSignoutButton.addEventListener("click", () => {
      clearSession();
      statusLine.textContent = "session cleared";
      renderSignedOutState();
    });
    personalObserveButton.addEventListener("click", runPersonalObservation);
    dealDiscoveryButton.addEventListener("click", runDealDiscovery);
    createWatchButton.addEventListener("click", createWatchFromSearch);
    refreshWatchesButton.addEventListener("click", loadWatches);
    refreshAdminHealthButton.addEventListener("click", loadAdminHealth);
    refreshAuditButton.addEventListener("click", loadAuditEvents);
    document.querySelector("#search-form").addEventListener("input", updatePassengerSummary);
    document.querySelector("#assistant-form").addEventListener("submit", (event) => {
      event.preventDefault();
      const prompt = text(new FormData(event.currentTarget).get("agent_prompt"));
      if (!prompt) return;
      const operation = agentEditMode ? editAgentPlan(prompt) : requestAgentChat(prompt);
      void operation;
      event.currentTarget.reset();
    });
    updatePassengerSummary();
    renderAgentRuntime({
      backend: "deterministic_harness",
      agentic_loop: "approval_gated_plan_lifecycle",
      live_calls_allowed: false,
      cloudflare_ready: true
    });
    renderAirportChoices({});
    renderAgentActions([]);
    loadProviders();
    loadBrowserSources();
    loadAdminHealth();
    loadAgentPresets();
    refreshSessionState().then(loadSessionBoundData);
    window.addEventListener("unhandledrejection", (event) => {
      event.preventDefault();
      const message = event.reason instanceof Error ? event.reason.message : String(event.reason);
      document.getElementById("agent-partial-errors").hidden = false;
      document.getElementById("agent-partial-errors").textContent = `Ошибка действия: ${message}`;
      statusLine.textContent = "agent-operation-error";
    });
    if ("serviceWorker" in navigator) {
      window.addEventListener("load", () => {
        navigator.serviceWorker.register("/service-worker.js").catch(() => {});
      });
    }
  </script>
</body>
</html>
"""


def render_web_manifest() -> dict[str, object]:
    return {
        "name": "Flight Hunter",
        "short_name": "Flight Hunter",
        "description": "Self-hosted flight search and watch workbench.",
        "start_url": "/",
        "scope": "/",
        "display": "standalone",
        "background_color": "#edf1f4",
        "theme_color": "#126d7a",
        "icons": [
            {
                "src": "/pwa-icon.svg",
                "sizes": "any",
                "type": "image/svg+xml",
                "purpose": "any maskable",
            }
        ],
    }


def render_pwa_icon_svg() -> str:
    return """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 512 512">
  <rect width="512" height="512" rx="92" fill="#14242c"/>
  <path d="M104 272h248M256 128l120 144-120 112" fill="none" stroke="#fff"
    stroke-width="46" stroke-linecap="round" stroke-linejoin="round"/>
  <path d="M116 356h124" fill="none" stroke="#72d0d8" stroke-width="28"
    stroke-linecap="round"/>
</svg>
"""


def render_service_worker_js() -> str:
    return """const CACHE_NAME = "flight-hunter-shell-v1";
const SHELL_URLS = ["/", "/manifest.webmanifest", "/pwa-icon.svg"];

self.addEventListener("install", (event) => {
  event.waitUntil(
    caches.open(CACHE_NAME)
      .then((cache) => cache.addAll(SHELL_URLS))
      .then(() => self.skipWaiting())
  );
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys()
      .then((keys) => Promise.all(keys
        .filter((key) => key !== CACHE_NAME)
        .map((key) => caches.delete(key))))
      .then(() => self.clients.claim())
  );
});

self.addEventListener("fetch", (event) => {
  const url = new URL(event.request.url);
  if (
    event.request.method !== "GET" ||
    url.origin !== self.location.origin ||
    url.pathname.startsWith("/api/")
  ) {
    return;
  }
  if (!SHELL_URLS.includes(url.pathname)) {
    return;
  }
  event.respondWith(
    fetch(event.request)
      .then((response) => {
        const responseCopy = response.clone();
        caches.open(CACHE_NAME).then((cache) => cache.put(event.request, responseCopy));
        return response;
      })
      .catch(() => caches.match(event.request))
  );
});
"""
