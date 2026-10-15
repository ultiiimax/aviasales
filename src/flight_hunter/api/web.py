# ruff: noqa: E501, RUF001

from __future__ import annotations


def render_index_html() -> str:
    return """<!doctype html>
<html lang="ru">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Flight Hunter</title>
  <meta name="theme-color" content="#155eef">
  <link rel="manifest" href="/manifest.webmanifest">
  <meta name="description" content="Flight Hunter: семейный поиск авиабилетов с честной свежестью цен.">
  <link rel="icon" href='data:image/svg+xml,
    <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64">
      <rect width="64" height="64" rx="12" fill="%230b1f3a"/>
      <path d="M13 34h31M32 16l15 18-15 14" fill="none" stroke="%23ffffff"
        stroke-width="6" stroke-linecap="round" stroke-linejoin="round"/>
    </svg>'>
  <style>
    @font-face {
      font-family: "Twemoji Country Flags";
      src: url("https://cdn.jsdelivr.net/npm/country-flag-emoji-polyfill@0.1.8/dist/TwemojiCountryFlags.woff2") format("woff2");
      font-display: swap;
      unicode-range: U+1F1E6-1F1FF;
    }

    :root {
      color-scheme: light;
      --bg: #f3f5f8;
      --ink: #0b1f3a;
      --muted: #64748b;
      --surface: #ffffff;
      --surface-soft: #f7f9fc;
      --line: #dbe3ee;
      --line-strong: #c4d0df;
      --accent: #155eef;
      --accent-strong: #0f49bd;
      --accent-soft: #edf4ff;
      --coral: #ff5d3d;
      --warning: #a35d00;
      --warning-soft: #fff4dc;
      --danger: #b42318;
      --danger-soft: #feeceb;
      --ok: #16803c;
      --ok-soft: #eaf8ef;
      --shadow: 0 24px 68px rgba(26, 54, 93, 0.10);
      font-family:
        "Twemoji Country Flags", Aptos, "Segoe UI Variable", "Segoe UI", ui-sans-serif,
        system-ui, sans-serif;
    }

    * { box-sizing: border-box; }

    html { scroll-behavior: smooth; }

    body {
      margin: 0;
      min-height: 100dvh;
      background:
        radial-gradient(circle at 50% -12%, rgba(21, 94, 239, 0.10), transparent 34rem),
        linear-gradient(180deg, #fbfcfe 0%, var(--bg) 58%, #eef1f5 100%);
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
    textarea:focus-visible,
    summary:focus-visible,
    a:focus-visible {
      outline: 3px solid rgba(21, 94, 239, 0.22);
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

    .auth-controls {
      display: grid;
      gap: 10px;
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

    .agent-hidden-city-warning {
      display: grid;
      gap: 8px;
      padding: 12px;
      border: 1px solid rgba(160, 74, 45, 0.35);
      border-radius: 12px;
      background: rgba(255, 238, 226, 0.8);
    }

    .agent-hidden-city-warning[hidden] {
      display: none;
    }

    .agent-hidden-city-warning ul {
      margin: 0;
      padding-left: 20px;
    }

    .agent-hidden-city-result-list {
      display: grid;
      gap: 10px;
    }

    .agent-hidden-city-result {
      display: grid;
      gap: 7px;
      padding: 11px;
      border: 1px solid rgba(160, 74, 45, 0.28);
      border-radius: 12px;
      background: rgba(255, 247, 240, 0.88);
    }

    .agent-hidden-city-result ul {
      margin: 0;
      padding-left: 20px;
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

    .carrier-strip {
      display: flex;
      align-items: center;
      gap: 8px;
      min-width: 0;
    }

    .result-row > .carrier-strip {
      grid-column: 1 / -1;
    }

    .carrier-chip {
      display: inline-flex;
      align-items: center;
      gap: 6px;
      min-width: 0;
      color: var(--muted);
      font-size: 12px;
      font-weight: 700;
    }

    .carrier-mark {
      position: relative;
      display: grid;
      flex: 0 0 30px;
      width: 30px;
      height: 30px;
      place-items: center;
      overflow: hidden;
      border: 1px solid var(--line);
      border-radius: 50%;
      background: var(--surface-soft);
    }

    .carrier-monogram {
      color: var(--ink);
      font-size: 10px;
      line-height: 1;
    }

    .carrier-logo {
      position: absolute;
      inset: 0;
      width: 100%;
      height: 100%;
      object-fit: contain;
      background: var(--surface);
      opacity: 0;
    }

    .carrier-logo.carrier-logo-loaded {
      opacity: 1;
    }

    .carrier-logo-failed .carrier-monogram {
      color: var(--danger);
    }

    .carrier-label {
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
    }

    .carrier-overflow {
      color: var(--muted);
      font-size: 12px;
      font-weight: 760;
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

    /* Search-first v1 shell. Existing result/agent class names stay stable for JS. */
    body {
      overflow-x: hidden;
    }

    ::selection {
      background: rgba(21, 94, 239, 0.18);
    }

    .skip-link {
      position: fixed;
      top: 8px;
      left: 8px;
      z-index: 60;
      transform: translateY(-140%);
      border-radius: 10px;
      background: var(--ink);
      color: white;
      padding: 10px 14px;
      text-decoration: none;
      transition: transform 180ms ease;
    }

    .skip-link:focus {
      transform: translateY(0);
    }

    .shell {
      width: min(1360px, calc(100% - 40px));
      padding: 0 0 64px;
    }

    .topbar {
      position: sticky;
      top: 0;
      z-index: 30;
      min-height: 68px;
      margin: 0 -20px;
      padding: 12px 20px;
      border-bottom: 1px solid rgba(196, 208, 223, 0.72);
      background: rgba(251, 252, 254, 0.90);
      box-shadow: 0 10px 32px rgba(26, 54, 93, 0.05);
      backdrop-filter: blur(18px) saturate(135%);
    }

    .brand {
      flex: 0 1 auto;
    }

    .mark {
      width: 42px;
      height: 42px;
      border-radius: 12px;
      background: var(--ink);
      box-shadow: 0 12px 28px rgba(11, 31, 58, 0.18);
    }

    .brand-title strong {
      font-family: Bahnschrift, "Aptos Display", Aptos, sans-serif;
      font-size: 21px;
      font-weight: 690;
      letter-spacing: -0.035em;
    }

    .brand-title span {
      font-size: 12px;
    }

    .topnav {
      display: flex;
      align-items: center;
      gap: 6px;
      margin-left: auto;
    }

    .topnav a {
      border-radius: 10px;
      color: #53657c;
      font-size: 13px;
      font-weight: 680;
      padding: 9px 11px;
      text-decoration: none;
      transition: background 180ms ease, color 180ms ease;
    }

    .topnav a:hover,
    .topnav a:focus-visible {
      background: var(--accent-soft);
      color: var(--accent-strong);
      outline: none;
    }

    .topbar-actions {
      display: flex;
      align-items: center;
      gap: 12px;
    }

    .status-line {
      display: inline-flex;
      align-items: center;
      gap: 7px;
      max-width: 260px;
      color: #53657c;
      font-size: 12px;
      text-align: left;
    }

    .status-line::before {
      content: "";
      flex: 0 0 auto;
      width: 7px;
      height: 7px;
      border-radius: 50%;
      background: #22a55b;
      box-shadow: 0 0 0 4px rgba(34, 165, 91, 0.10);
    }

    .account-menu {
      position: relative;
      flex: 0 0 auto;
    }

    .account-menu > summary {
      min-height: 42px;
      display: inline-flex;
      align-items: center;
      gap: 9px;
      border: 1px solid var(--line-strong);
      border-radius: 12px;
      background: rgba(255, 255, 255, 0.92);
      color: var(--ink);
      cursor: pointer;
      font-size: 13px;
      font-weight: 720;
      list-style: none;
      padding: 0 12px;
      transition: border-color 180ms ease, box-shadow 180ms ease, transform 180ms ease;
    }

    .account-menu > summary::-webkit-details-marker,
    .technical-details > summary::-webkit-details-marker,
    .exact-search > summary::-webkit-details-marker,
    .utility-panel > summary::-webkit-details-marker {
      display: none;
    }

    .account-menu > summary:hover {
      border-color: #92ace0;
      box-shadow: 0 8px 24px rgba(26, 54, 93, 0.08);
    }

    .account-menu[open] > summary {
      border-color: var(--accent);
    }

    .account-icon {
      width: 26px;
      height: 26px;
      display: grid;
      place-items: center;
      border-radius: 8px;
      background: var(--accent-soft);
      color: var(--accent);
    }

    .account-chevron {
      color: var(--muted);
      transition: transform 180ms ease;
    }

    .account-menu[open] .account-chevron {
      transform: rotate(180deg);
    }

    .account-popover {
      position: absolute;
      top: calc(100% + 10px);
      right: 0;
      width: min(430px, calc(100vw - 28px));
      border: 1px solid var(--line);
      border-radius: 18px;
      background: rgba(255, 255, 255, 0.98);
      box-shadow: 0 28px 80px rgba(18, 43, 78, 0.20);
      overflow: hidden;
    }

    .account-copy {
      padding: 18px 18px 0;
    }

    .account-copy h2 {
      margin: 0;
      font-family: Bahnschrift, "Aptos Display", Aptos, sans-serif;
      font-size: 19px;
      letter-spacing: -0.02em;
    }

    .account-copy p {
      max-width: 42ch;
      margin: 6px 0 0;
      color: var(--muted);
      font-size: 13px;
      line-height: 1.45;
    }

    .auth-controls {
      gap: 12px;
      padding: 16px 18px 18px;
    }

    .auth-controls .secondary {
      width: 100%;
    }

    #invitation-login-form {
      display: grid;
      gap: 10px;
    }

    #invitation-login-form[hidden] {
      display: none;
    }

    .auth-state {
      grid-column: 1 / -1;
      min-height: 20px;
      order: -1;
      border-radius: 10px;
      background: var(--surface-soft);
      padding: 8px 10px;
    }

    .hero-search {
      width: min(1080px, 100%);
      margin: 72px auto 22px;
      scroll-margin-top: 90px;
    }

    .hero-copy {
      margin: 0 auto 24px;
      text-align: center;
    }

    .eyebrow {
      display: inline-flex;
      align-items: center;
      gap: 8px;
      margin: 0 0 10px;
      color: var(--accent-strong);
      font-size: 12px;
      font-weight: 780;
      letter-spacing: 0.08em;
      text-transform: uppercase;
    }

    .eyebrow::before {
      content: "";
      width: 22px;
      height: 2px;
      border-radius: 2px;
      background: var(--coral);
    }

    .hero-copy h1 {
      max-width: 820px;
      margin: 0 auto;
      font-family: Bahnschrift, "Aptos Display", Aptos, sans-serif;
      font-size: clamp(42px, 6vw, 72px);
      line-height: 0.98;
      letter-spacing: -0.055em;
      text-wrap: balance;
    }

    .hero-copy p:last-child {
      max-width: 650px;
      margin: 16px auto 0;
      color: #53657c;
      font-size: 16px;
      line-height: 1.55;
      text-wrap: balance;
    }

    .hero-card {
      position: relative;
      border: 1px solid rgba(196, 208, 223, 0.88);
      border-radius: 24px;
      background: rgba(255, 255, 255, 0.96);
      box-shadow: var(--shadow);
      overflow: hidden;
    }

    .hero-card::before {
      content: "";
      position: absolute;
      inset: 0 0 auto;
      height: 3px;
      background: linear-gradient(90deg, var(--accent), #65a7ff 72%, var(--coral));
    }

    .assistant-body {
      gap: 16px;
      padding: 22px;
    }

    #assistant-form { order: 1; }
    #preset-list { order: 2; }
    #chat-log { order: 3; }
    #agent-plan-card { order: 4; }
    #decision-rail { order: 5; }
    .technical-details { order: 6; }

    .hero-card .quick-actions {
      justify-content: center;
    }

    .hero-card #preset-list {
      display: grid;
      grid-template-columns: repeat(4, auto);
      justify-content: center;
    }

    .hero-card .chip {
      min-height: 42px;
      border-color: var(--line-strong);
      border-radius: 12px;
      color: #31445c;
      font-size: 13px;
      font-weight: 680;
      padding: 0 15px;
    }

    .hero-card .chip:hover {
      border-color: #91addf;
      background: var(--accent-soft);
      color: var(--accent-strong);
      transform: translateY(-1px);
    }

    .chat-log {
      min-height: 72px;
      max-height: 290px;
      border: 0;
      border-radius: 16px;
      background: var(--surface-soft);
      padding: 12px;
    }

    .message {
      max-width: min(82%, 720px);
      border-radius: 14px;
      padding: 11px 13px;
    }

    .message.bot {
      border-color: #d6e4fb;
      background: #ffffff;
      color: #31445c;
    }

    .message.user {
      background: var(--ink);
      box-shadow: 0 8px 18px rgba(11, 31, 58, 0.12);
    }

    .assistant-input {
      grid-template-columns: minmax(0, 1fr) auto;
      gap: 10px;
      align-items: end;
      border: 1px solid var(--line-strong);
      border-radius: 18px;
      background: #ffffff;
      padding: 8px;
      box-shadow: 0 10px 30px rgba(26, 54, 93, 0.06);
      transition: border-color 180ms ease, box-shadow 180ms ease;
    }

    .assistant-input:focus-within {
      border-color: #7fa5ee;
      box-shadow: 0 0 0 4px rgba(21, 94, 239, 0.10), 0 18px 38px rgba(26, 54, 93, 0.08);
    }

    .assistant-input textarea {
      min-height: 92px;
      max-height: 220px;
      border: 0;
      border-radius: 12px;
      padding: 16px;
      color: var(--ink);
      font-size: 17px;
      line-height: 1.45;
      outline: none;
    }

    .assistant-input textarea::placeholder {
      color: #8795a8;
    }

    .assistant-input .primary {
      min-width: 180px;
      min-height: 54px;
      border-radius: 13px;
      box-shadow: 0 12px 24px rgba(21, 94, 239, 0.18);
      padding: 0 20px;
    }

    .primary {
      background: var(--accent);
    }

    .primary:hover {
      background: var(--accent-strong);
      transform: translateY(-1px);
    }

    .secondary,
    .chip {
      border-color: var(--line-strong);
    }

    .technical-details {
      border-top: 1px solid var(--line);
      padding-top: 2px;
    }

    .technical-details > summary {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 12px;
      min-height: 42px;
      border-radius: 10px;
      color: #53657c;
      cursor: pointer;
      font-size: 12px;
      font-weight: 680;
      list-style: none;
      padding: 0 8px;
    }

    .technical-details > summary:hover {
      background: var(--surface-soft);
      color: var(--ink);
    }

    .technical-details .runtime-strip {
      margin-top: 8px;
    }

    .runtime-node {
      border-color: var(--line);
      border-radius: 12px;
      background: var(--surface-soft);
    }

    .runtime-node span {
      text-transform: none;
    }

    .agent-sidecars {
      border-top: 1px solid var(--line);
      padding-top: 16px;
    }

    .agent-sidecars:not(:has(.choice-card, .action-card)) {
      display: none;
    }

    .agent-plan-card {
      border-color: #c9d9f3;
      border-radius: 18px;
      background: linear-gradient(180deg, #f7faff 0%, #ffffff 100%);
      box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.75);
      padding: 18px;
    }

    .agent-plan-card h3,
    .agent-plan-card h4 {
      margin: 0 0 6px;
      color: var(--ink);
      letter-spacing: -0.02em;
    }

    .agent-plan-grid {
      grid-template-columns: repeat(3, minmax(0, 1fr));
      border: 1px solid var(--line);
      border-radius: 14px;
      background: white;
      padding: 4px;
    }

    .agent-plan-grid div {
      min-height: 66px;
      border-radius: 10px;
      padding: 10px;
    }

    .agent-plan-grid div:nth-child(odd) {
      background: var(--surface-soft);
    }

    .exact-search {
      width: min(1160px, 100%);
      margin: 18px auto 30px;
      scroll-margin-top: 92px;
      overflow: hidden;
    }

    .exact-search > summary {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 20px;
      cursor: pointer;
      list-style: none;
      padding: 18px 20px;
      transition: background 180ms ease;
    }

    .exact-search > summary:hover {
      background: var(--surface-soft);
    }

    .exact-summary-copy {
      display: grid;
      gap: 4px;
    }

    .exact-summary-copy .panel-title {
      font-size: 18px;
    }

    .summary-action {
      display: inline-flex;
      align-items: center;
      gap: 8px;
      flex: 0 0 auto;
      border-radius: 10px;
      background: var(--accent-soft);
      color: var(--accent-strong);
      font-size: 12px;
      font-weight: 760;
      padding: 10px 12px;
    }

    .summary-action::after {
      content: "↓";
      transition: transform 180ms ease;
    }

    .summary-label-open {
      display: none;
    }

    .exact-search[open] .summary-label-closed {
      display: none;
    }

    .exact-search[open] .summary-label-open {
      display: inline;
    }

    .exact-search[open] .summary-action::after {
      transform: rotate(180deg);
    }

    .exact-search[open] > summary {
      border-bottom: 1px solid var(--line);
    }

    .exact-search[open] {
      overflow: visible;
    }

    .search-form {
      grid-template-columns: repeat(4, minmax(0, 1fr));
      gap: 14px;
      padding: 20px;
    }

    label {
      gap: 7px;
      color: #465a72;
      font-size: 12px;
      font-weight: 710;
    }

    input,
    textarea {
      border-color: var(--line-strong);
      border-radius: 11px;
    }

    input {
      height: 48px;
      font-weight: 620;
    }

    input:hover,
    textarea:hover {
      border-color: #9eb2ca;
    }

    .place-field,
    .place-combobox {
      position: relative;
      min-width: 0;
    }

    .place-field {
      display: grid;
      gap: 7px;
    }

    .place-field > label {
      display: block;
    }

    .place-combobox {
      display: block;
    }

    .place-listbox {
      position: absolute;
      z-index: 40;
      inset: calc(100% + 6px) 0 auto;
      display: grid;
      width: 100%;
      max-width: calc(100vw - 40px);
      max-height: min(320px, calc(100dvh - 160px));
      overflow-y: auto;
      overscroll-behavior: contain;
      border: 1px solid var(--line-strong);
      border-radius: 12px;
      background: #ffffff;
      box-shadow: 0 18px 48px rgba(26, 54, 93, 0.18);
    }

    .place-listbox[hidden] {
      display: none;
    }

    .place-listbox[data-placement="above"] {
      inset: auto 0 calc(100% + 6px);
    }

    .place-option {
      display: grid;
      grid-template-columns: auto minmax(0, 1fr);
      gap: 10px;
      min-height: 44px;
      padding: 9px 11px;
      border-bottom: 1px solid var(--line);
      background: #ffffff;
      color: var(--ink);
      text-align: left;
    }

    .place-option:last-child {
      border-bottom: 0;
    }

    .place-option:hover,
    .place-option[aria-selected="true"] {
      background: var(--accent-soft);
    }

    .place-option-flag {
      padding-top: 1px;
      font-size: 19px;
      line-height: 1.25;
    }

    .place-option-copy {
      display: grid;
      gap: 2px;
      min-width: 0;
    }

    .place-option-name {
      overflow-wrap: anywhere;
      font-size: 14px;
      font-weight: 720;
      line-height: 1.25;
    }

    .place-option-meta,
    .place-status {
      color: var(--muted);
      font-size: 12px;
      font-weight: 560;
      line-height: 1.35;
    }

    .place-status {
      min-height: 16px;
    }

    .place-field input[aria-invalid="true"] {
      border-color: var(--danger);
    }

    .search-form .form-actions {
      margin-top: 2px;
      border-top: 1px solid var(--line);
      padding-top: 16px;
    }

    .search-form .primary,
    .search-form .secondary {
      min-height: 44px;
      border-radius: 11px;
    }

    .panel {
      border-color: rgba(196, 208, 223, 0.88);
      border-radius: 18px;
      background: rgba(255, 255, 255, 0.96);
      box-shadow: 0 18px 50px rgba(26, 54, 93, 0.07);
    }

    .panel-header {
      align-items: center;
      border-bottom-color: var(--line);
      background: rgba(255, 255, 255, 0.88);
      padding: 18px 20px;
    }

    .panel-title {
      font-family: Bahnschrift, "Aptos Display", Aptos, sans-serif;
      font-size: 21px;
      font-weight: 650;
      letter-spacing: -0.035em;
    }

    .panel-kicker {
      color: #68798d;
    }

    .results-panel {
      scroll-margin-top: 92px;
      margin: 0 0 22px;
    }

    .results-panel .panel-header {
      padding-block: 20px;
    }

    .result-row {
      grid-template-columns: minmax(250px, 1.1fr) minmax(140px, 0.48fr) minmax(270px, 0.92fr);
      gap: 18px;
      padding: 18px 20px;
      transition: background 180ms ease, transform 180ms ease;
    }

    .result-row:hover {
      background: #fbfdff;
    }

    .route {
      color: var(--ink);
      font-size: 16px;
    }

    .price {
      color: var(--ink);
      font-size: 24px;
      letter-spacing: -0.025em;
    }

    .badge {
      border-radius: 8px;
    }

    .utility-grid {
      display: grid;
      grid-template-columns: repeat(12, minmax(0, 1fr));
      gap: 18px;
      align-items: start;
    }

    .providers-panel {
      grid-column: span 4;
    }

    .watches-panel {
      grid-column: span 8;
      scroll-margin-top: 92px;
    }

    .utility-panel {
      grid-column: span 6;
    }

    .utility-panel > summary {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 18px;
      cursor: pointer;
      list-style: none;
      padding: 18px 20px;
    }

    .utility-panel > summary::after {
      content: "+";
      width: 28px;
      height: 28px;
      display: grid;
      place-items: center;
      border-radius: 9px;
      background: var(--surface-soft);
      color: var(--accent-strong);
      font-size: 18px;
      transition: transform 180ms ease;
    }

    .utility-panel[open] > summary {
      border-bottom: 1px solid var(--line);
    }

    .utility-panel[open] > summary::after {
      transform: rotate(45deg);
    }

    .panel-toolbar {
      display: flex;
      justify-content: flex-end;
      border-bottom: 1px solid var(--line);
      background: var(--surface-soft);
      padding: 10px 16px;
    }

    .panel-toolbar .secondary {
      min-height: 36px;
    }

    .empty-state,
    .error-state {
      padding: 32px 20px;
    }

    .agent-plan-card {
      gap: 16px;
      background: #ffffff;
      box-shadow: 0 18px 44px rgba(26, 54, 93, 0.08);
    }

    .agent-plan-head {
      display: flex;
      align-items: flex-start;
      justify-content: space-between;
      gap: 16px;
    }

    .agent-plan-head h3 {
      font-size: 21px;
    }

    #agent-plan-status {
      color: #53657c;
      font-size: 13px;
      line-height: 1.45;
    }

    .agent-progress-shell {
      display: grid;
      gap: 14px;
      border: 1px solid #c9d9f3;
      border-radius: 16px;
      background: linear-gradient(135deg, #f5f9ff, #ffffff 68%);
      padding: 16px;
    }

    .agent-stage-scroll {
      overflow-x: auto;
      scrollbar-width: thin;
    }

    .agent-stage-track {
      display: grid;
      grid-template-columns: repeat(5, minmax(118px, 1fr));
      min-width: 650px;
      margin: 0;
      padding: 0;
      list-style: none;
    }

    .agent-stage {
      position: relative;
      display: grid;
      justify-items: center;
      gap: 7px;
      color: #7a899d;
      font-size: 11px;
      font-weight: 690;
      line-height: 1.25;
      text-align: center;
    }

    .agent-stage:not(:last-child)::after {
      content: "";
      position: absolute;
      z-index: 0;
      top: 14px;
      left: calc(50% + 18px);
      width: calc(100% - 36px);
      height: 2px;
      background: #dbe5f3;
    }

    .agent-stage-dot {
      position: relative;
      z-index: 1;
      width: 30px;
      height: 30px;
      display: grid;
      place-items: center;
      border: 2px solid #cfdaea;
      border-radius: 50%;
      background: #ffffff;
      color: #718198;
      font-size: 11px;
      font-variant-numeric: tabular-nums;
    }

    .agent-stage.is-done,
    .agent-stage.is-active {
      color: var(--ink);
    }

    .agent-stage.is-done .agent-stage-dot {
      border-color: var(--ok);
      background: var(--ok-soft);
      color: var(--ok);
    }

    .agent-stage.is-done .agent-stage-dot::before {
      content: "✓";
    }

    .agent-stage.is-done .agent-stage-dot {
      font-size: 0;
    }

    .agent-stage.is-done .agent-stage-dot::before {
      font-size: 13px;
    }

    .agent-stage.is-done:not(:last-child)::after {
      background: #8fd0a5;
    }

    .agent-stage.is-active .agent-stage-dot {
      border-color: var(--accent);
      background: var(--accent);
      color: #ffffff;
      box-shadow: 0 0 0 5px rgba(21, 94, 239, 0.10);
    }

    .agent-stage.is-error .agent-stage-dot {
      border-color: var(--danger);
      background: var(--danger-soft);
      color: var(--danger);
    }

    #agent-run-progress {
      color: #31445c;
      font-size: 14px;
      font-weight: 680;
      line-height: 1.45;
      text-align: center;
    }

    .agent-plan-details {
      border: 1px solid var(--line);
      border-radius: 13px;
      background: var(--surface-soft);
      overflow: hidden;
    }

    .agent-plan-details > summary {
      min-height: 44px;
      display: flex;
      align-items: center;
      justify-content: space-between;
      cursor: pointer;
      list-style: none;
      color: #53657c;
      font-size: 12px;
      font-weight: 720;
      padding: 0 13px;
    }

    .agent-plan-details > summary::-webkit-details-marker {
      display: none;
    }

    .agent-plan-details > summary::after {
      content: "+";
      color: var(--accent-strong);
      font-size: 18px;
    }

    .agent-plan-details[open] > summary::after {
      content: "−";
    }

    .agent-plan-details[open] > summary {
      border-bottom: 1px solid var(--line);
      background: #ffffff;
    }

    .agent-plan-details-body {
      display: grid;
      gap: 12px;
      padding: 12px;
    }

    .agent-run-meta {
      color: var(--muted);
      font-size: 11px;
      overflow-wrap: anywhere;
    }

    #agent-confirmed-results {
      display: grid;
      gap: 12px;
      border: 0;
      background: transparent;
      padding: 0;
    }

    #agent-confirmed-results[hidden] {
      display: none;
    }

    #agent-confirmed-results-heading {
      font-size: 19px;
    }

    .agent-result-list {
      display: grid;
      gap: 12px;
    }

    .agent-result-pagination {
      display: flex;
      flex-wrap: wrap;
      gap: 10px;
      align-items: center;
      justify-content: space-between;
      color: var(--muted);
      font-size: 14px;
      padding: 4px 2px 0;
    }

    .agent-result-card {
      display: grid;
      gap: 12px;
      border: 1px solid var(--line);
      border-radius: 16px;
      background: #ffffff;
      box-shadow: 0 10px 28px rgba(26, 54, 93, 0.06);
      padding: 16px;
    }

    .agent-result-card:hover {
      border-color: #a9bfdf;
      box-shadow: 0 16px 34px rgba(26, 54, 93, 0.09);
    }

    .agent-result-head {
      display: grid;
      grid-template-columns: minmax(0, 1fr) auto;
      gap: 16px;
      align-items: start;
    }

    .agent-result-route {
      color: var(--ink);
      font-size: 17px;
      font-weight: 790;
      line-height: 1.3;
    }

    .agent-result-price {
      color: var(--ink);
      font-size: 23px;
      font-weight: 840;
      font-variant-numeric: tabular-nums;
      white-space: nowrap;
    }

    .agent-result-badges,
    .agent-result-facts,
    .agent-result-actions {
      display: flex;
      flex-wrap: wrap;
      gap: 7px;
      align-items: center;
    }

    .agent-result-fact {
      min-height: 30px;
      display: inline-flex;
      align-items: center;
      border-radius: 9px;
      background: var(--surface-soft);
      color: #4d6078;
      font-size: 12px;
      font-weight: 650;
      padding: 5px 9px;
    }

    .agent-result-warning {
      border-radius: 10px;
      background: var(--warning-soft);
      color: var(--warning);
      font-size: 12px;
      line-height: 1.45;
      padding: 9px 11px;
    }

    .agent-result-segments {
      border-top: 1px solid var(--line);
      padding-top: 10px;
    }

    .agent-result-segments > summary {
      cursor: pointer;
      color: #53657c;
      font-size: 12px;
      font-weight: 700;
    }

    .agent-segment-list {
      display: grid;
      gap: 6px;
      margin-top: 9px;
    }

    .agent-segment-row {
      display: flex;
      justify-content: space-between;
      gap: 12px;
      color: #53657c;
      font-size: 12px;
      line-height: 1.4;
    }

    .agent-result-actions .primary {
      min-height: 42px;
    }

    .agent-result-actions:empty {
      display: none;
    }

    @media (max-width: 1080px) {
      .topnav {
        display: none;
      }

      .status-line {
        max-width: 180px;
      }

      .hero-search {
        margin-top: 54px;
      }

      .agent-plan-grid {
        grid-template-columns: repeat(2, minmax(0, 1fr));
      }

      .providers-panel,
      .watches-panel,
      .utility-panel {
        grid-column: span 12;
      }
    }

    @media (max-width: 760px) {
      .shell {
        width: min(100% - 24px, 1360px);
      }

      .topbar {
        position: relative;
        min-height: auto;
        align-items: center;
        flex-direction: row;
        flex-wrap: wrap;
        margin: 0 -12px;
        padding: 10px 12px;
      }

      .brand-title span,
      .status-line {
        display: none;
      }

      .topbar-actions {
        margin-left: auto;
      }

      .account-popover {
        position: fixed;
        top: 68px;
        right: 12px;
        left: 12px;
        width: auto;
        max-height: calc(100dvh - 84px);
        overflow: auto;
      }

      .hero-search {
        margin-top: 42px;
      }

      .hero-copy h1 {
        font-size: clamp(42px, 13vw, 62px);
      }

      .hero-copy p:last-child {
        font-size: 15px;
      }

      .assistant-body {
        padding: 16px;
      }

      .hero-card .quick-actions {
        display: flex;
        justify-content: flex-start;
        flex-wrap: nowrap;
        margin: 0 -16px;
        overflow-x: auto;
        padding: 0 16px 4px;
        scrollbar-width: none;
      }

      .hero-card #preset-list {
        display: flex;
        grid-template-columns: none;
        justify-content: flex-start;
      }

      .hero-card .quick-actions::-webkit-scrollbar {
        display: none;
      }

      .hero-card .chip {
        flex: 0 0 auto;
      }

      .assistant-input {
        grid-template-columns: 1fr;
      }

      .assistant-input .primary {
        width: 100%;
      }

      .runtime-strip,
      .agent-plan-grid,
      .agent-sidecars {
        grid-template-columns: 1fr;
      }

      .agent-result-head {
        grid-template-columns: 1fr;
      }

      .agent-result-price {
        font-size: 21px;
      }

      .search-form {
        grid-template-columns: repeat(2, minmax(0, 1fr));
      }

      .result-row {
        grid-template-columns: 1fr;
      }

      .price,
      .caveats,
      .result-actions,
      .confirmation-actions,
      .confirmation-status {
        text-align: left;
        justify-content: flex-start;
      }
    }

    @media (max-width: 520px) {
      .brand-title strong {
        font-size: 18px;
      }

      .mark {
        width: 38px;
        height: 38px;
      }

      .account-menu > summary {
        min-height: 38px;
        padding-inline: 9px;
      }

      .account-icon,
      .account-chevron {
        display: none;
      }

      .search-form {
        grid-template-columns: 1fr;
      }

      .hero-card {
        border-radius: 20px;
      }

      .hero-copy {
        text-align: left;
      }

      .hero-copy h1,
      .hero-copy p:last-child {
        margin-inline: 0;
      }

      .hero-copy h1 {
        font-size: 46px;
      }

      .exact-search > summary {
        align-items: flex-start;
      }

      .summary-action {
        width: 38px;
        height: 38px;
        justify-content: center;
        overflow: hidden;
        padding: 0;
        white-space: nowrap;
        color: transparent;
      }

      .summary-action::after {
        color: var(--accent-strong);
      }

      .form-actions,
      .form-actions .quick-actions {
        width: 100%;
      }

      .search-form .primary,
      .search-form .secondary {
        width: 100%;
      }

      .agent-result-actions .primary,
      .agent-result-actions .secondary {
        width: 100%;
      }
    }

    @media (prefers-reduced-motion: reduce) {
      *,
      *::before,
      *::after {
        scroll-behavior: auto !important;
        transition-duration: 0.01ms !important;
        animation-duration: 0.01ms !important;
        animation-iteration-count: 1 !important;
      }
    }
  </style>
</head>
<body>
  <a class="skip-link" href="#main-search">Перейти к поиску</a>
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
          <span>личный помощник по дешёвым маршрутам</span>
        </div>
      </div>
      <nav class="topnav" aria-label="Основные разделы">
        <a href="#main-search">Поиск</a>
        <a href="#results-heading">Результаты</a>
        <a href="#watches-heading">Отслеживания</a>
      </nav>
      <div class="topbar-actions">
        <div class="status-line" id="status-line">цены с отметкой свежести</div>
        <details class="account-menu">
          <summary aria-controls="account-popover">
            <span class="account-icon" aria-hidden="true">
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none">
                <circle cx="12" cy="8" r="3.5" stroke="currentColor" stroke-width="1.8"/>
                <path d="M5 20c.6-4 3-6 7-6s6.4 2 7 6" stroke="currentColor"
                  stroke-width="1.8" stroke-linecap="round"/>
              </svg>
            </span>
            <span id="account-label">Войти</span>
            <span class="account-chevron" aria-hidden="true">⌄</span>
          </summary>
          <div class="account-popover" id="account-popover">
            <div class="account-copy">
              <h2 id="auth-heading">Вход в семейный профиль</h2>
              <p>Введите имя и одноразовый код приглашения. Ваши данные сохраняются в семейном профиле на сервере.</p>
            </div>
            <div class="auth-controls">
              <div class="auth-state" id="auth-state" role="status" aria-live="polite">Требуется вход.</div>
              <form id="invitation-login-form" hidden>
                <label for="invitation-name">Ваше имя</label>
                <input id="invitation-name" type="text" maxlength="160" autocomplete="name" required>
                <label for="invitation-code">Код приглашения</label>
                <input id="invitation-code" type="password" maxlength="200" autocomplete="one-time-code" required>
                <button class="primary" type="submit" id="invitation-login-submit">Войти</button>
              </form>
              <section id="invitation-admin-panel" hidden>
                <h3>Пригласить члена семьи</h3>
                <form id="invitation-create-form">
                  <label for="invitation-recipient">Nom du membre (facultatif)</label>
                  <input id="invitation-recipient" type="text" maxlength="160" autocomplete="off">
                  <button class="secondary" type="submit" id="invitation-create-submit">Créer un code d’invitation</button>
                </form>
                <div id="invitation-created-result" class="auth-state" role="status" aria-live="polite"></div>
              </section>
              <button class="secondary" type="button" id="auth-reconnect-button" hidden>Выйти / сменить профиль</button>
            </div>
          </div>
        </details>
      </div>
    </header>

    <section class="agent-cockpit hero-search" id="main-search" aria-labelledby="assistant-heading">
      <div class="hero-copy">
        <p class="eyebrow">Умный поиск маршрута</p>
        <h1 id="assistant-heading">Куда летим?</h1>
        <p>Опишите поездку обычными словами. Если маршрута и дат достаточно, агент сразу проверит живые варианты — без второго подтверждения.</p>
      </div>
      <div class="hero-card">
        <div class="assistant-body">
          <div class="quick-actions" id="preset-list" aria-label="Сценарии ИИ">
            <button class="chip" type="button" data-preset="flexible_dates">Даты ±3 дня</button>
            <button class="chip" type="button" data-preset="nearby_airports">Аэропорты рядом</button>
            <button class="chip" type="button" data-preset="buy_timing">Когда покупать</button>
          </div>
          <details class="technical-details">
            <summary>
              <span>Как работает поиск</span>
              <span class="badge ok" id="agent-mode">локальный агент</span>
            </summary>
            <div class="runtime-strip" id="runtime-strip" aria-label="Технические параметры агента">
              <div class="runtime-node">
                <span>Режим</span>
                <strong id="agent-runtime">локальный</strong>
              </div>
              <div class="runtime-node">
                <span>План</span>
                <strong id="agent-loop">запускается из полного запроса</strong>
              </div>
              <div class="runtime-node">
                <span>Актуальные цены</span>
                <strong id="agent-live-policy">сразу после отправки запроса</strong>
              </div>
              <div class="runtime-node">
                <span>Данные</span>
                <strong id="agent-edge-ready">хранятся локально</strong>
              </div>
            </div>
          </details>
          <div class="chat-log" id="chat-log" aria-live="polite">
            <div class="message bot">Напишите откуда, куда и когда. Если чего-то критичного не хватает, я задам один короткий вопрос.</div>
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
            <div class="agent-plan-head">
              <div>
              <h3 id="agent-plan-heading">План поиска</h3>
              <div id="agent-plan-status" role="status" aria-live="polite">План не создан</div>
              </div>
            </div>
            <div class="agent-progress-shell">
              <div class="agent-stage-scroll">
                <ol class="agent-stage-track" id="agent-stage-track" aria-label="Ход поиска">
                  <li class="agent-stage" data-agent-stage="0"><span class="agent-stage-dot">1</span><span>Понимаю маршрут</span></li>
                  <li class="agent-stage" data-agent-stage="1"><span class="agent-stage-dot">2</span><span>Проверяю даты и аэропорты</span></li>
                  <li class="agent-stage" data-agent-stage="2"><span class="agent-stage-dot">3</span><span>Ищу живые варианты</span></li>
                  <li class="agent-stage" data-agent-stage="3"><span class="agent-stage-dot">4</span><span>Сравниваю маршруты</span></li>
                  <li class="agent-stage" data-agent-stage="4"><span class="agent-stage-dot">5</span><span>Готово</span></li>
                </ol>
              </div>
              <div id="agent-run-progress" role="status" aria-live="polite">Готов принять маршрут.</div>
            </div>
            <button class="secondary" type="button" id="agent-run-cancel" disabled hidden>Остановить поиск</button>
            <details class="agent-plan-details">
              <summary>Детали и ручное управление</summary>
              <div class="agent-plan-details-body">
                <div class="agent-run-meta" id="agent-run-meta">Запуск ещё не создан.</div>
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
                <section class="agent-hidden-city-warning" id="agent-hidden-city-warning" hidden>
                  <strong>Отдельное подтверждение hidden-city</strong>
                  <ul id="agent-hidden-city-warning-list"></ul>
                  <label>
                    <input type="checkbox" id="agent-hidden-city-ack">
                    Я прочитал риски багажа, отмены следующих сегментов и правил перевозчика.
                  </label>
                </section>
                <div class="quick-actions" aria-label="Действия с планом">
                  <button class="secondary" type="button" id="agent-plan-edit">Изменить план</button>
                  <button class="secondary" type="button" id="agent-plan-full">Проверить всю область</button>
                  <button class="primary" type="button" id="agent-plan-execute" disabled>Запустить вручную</button>
                </div>
              </div>
            </details>
            <section class="agent-plan-region" id="agent-fare-analysis" aria-labelledby="agent-fare-analysis-heading" hidden>
              <h4 id="agent-fare-analysis-heading">Анализ цены</h4>
              <div id="agent-fare-analysis-list">Анализ ещё не рассчитан.</div>
            </section>
            <section class="agent-plan-region" id="agent-confirmed-results" aria-labelledby="agent-confirmed-results-heading" hidden>
              <h4 id="agent-confirmed-results-heading">Подтверждённые варианты</h4>
              <div class="agent-result-list" id="agent-confirmed-results-list">Подтверждённых вариантов ещё нет.</div>
            </section>
            <section class="agent-plan-region" id="agent-risky-results" aria-labelledby="agent-risky-results-heading" hidden>
              <h4 id="agent-risky-results-heading">Hidden-city исследования</h4>
              <div id="agent-risky-results-list">Нет подтверждённых рискованных вариантов.</div>
            </section>
            <div class="agent-plan-region" id="agent-partial-errors" role="alert" hidden></div>
          </section>
          <form class="assistant-input" id="assistant-form">
            <textarea name="agent_prompt" aria-label="Опишите поездку"
              placeholder="Например: самый дешёвый путь из Санкт-Петербурга во Францию в сентябре на неделю"></textarea>
            <button class="primary" type="submit">Найти варианты</button>
          </form>
        </div>
      </div>
    </section>

    <details class="panel exact-search" aria-labelledby="search-heading">
      <summary>
        <span class="exact-summary-copy">
          <span class="fineprint">Если уже знаете аэропорты и даты</span>
          <span class="panel-title" id="search-heading">Задать точный маршрут</span>
          <span class="panel-kicker">Быстрый поиск по конкретным параметрам без диалога с агентом.</span>
        </span>
        <span class="summary-action">
          <span class="summary-label-closed">Открыть форму</span>
          <span class="summary-label-open">Скрыть форму</span>
        </span>
      </summary>
        <form class="search-form" id="search-form">
          <div class="place-field" data-place-role="origin">
            <label for="origin-place-input">Откуда</label>
            <span class="place-combobox">
              <input id="origin-place-input" type="text" value="Варшава — Шопен" role="combobox"
                aria-autocomplete="list" aria-expanded="false" aria-controls="origin-place-listbox"
                autocomplete="off" spellcheck="false">
              <input name="origin" type="hidden" value="WAW">
              <input name="origin_kind" type="hidden" value="airport">
              <span id="origin-place-listbox" role="listbox" class="place-listbox" hidden></span>
            </span>
            <span id="origin-place-status" class="place-status" role="status" aria-live="polite"></span>
          </div>
          <div class="place-field" data-place-role="destination">
            <label for="destination-place-input">Куда</label>
            <span class="place-combobox">
              <input id="destination-place-input" type="text" value="Барселона — Эль-Прат" role="combobox"
                aria-autocomplete="list" aria-expanded="false" aria-controls="destination-place-listbox"
                autocomplete="off" spellcheck="false">
              <input name="destination" type="hidden" value="BCN">
              <input name="destination_kind" type="hidden" value="airport">
              <span id="destination-place-listbox" role="listbox" class="place-listbox" hidden></span>
            </span>
            <span id="destination-place-status" class="place-status" role="status" aria-live="polite"></span>
          </div>
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
              <button class="secondary" type="button" id="personal-observe-button">Проверить в браузере</button>
              <button class="secondary" type="button" id="deal-discovery-button">Найти спеццены</button>
              <button class="primary" type="submit" id="submit-button">Найти билеты</button>
            </div>
          </div>
        </form>
    </details>

    <section class="panel results-panel" aria-labelledby="results-heading">
      <div class="panel-header">
        <div>
          <h2 class="panel-title" id="results-heading">Лучшие варианты</h2>
          <div class="panel-kicker">Цена, пересадки, риск, источник и свежесть — в одном месте.</div>
        </div>
        <span class="small" id="results-count">0 вариантов</span>
      </div>
      <div class="result-list" id="results-list">
        <div class="empty-state">Опишите поездку выше или задайте точный маршрут — найденные билеты появятся здесь.</div>
      </div>
      <div class="denial-list" id="confirmation-list"></div>
      <div class="denial-list" id="live-list"></div>
      <div class="denial-list" id="denials-list"></div>
    </section>

    <section class="utility-grid" aria-label="Личные данные и диагностика">
      <section class="panel watches-panel" aria-labelledby="watches-heading">
        <div class="panel-header">
          <div>
            <h2 class="panel-title" id="watches-heading">Отслеживания</h2>
            <div class="panel-kicker">Сохраняйте маршрут и получайте изменения цены без повторного ввода.</div>
          </div>
        </div>
        <div class="watch-toolbar">
          <button class="secondary" type="button" id="create-watch-button">Следить за маршрутом</button>
          <button class="secondary" type="button" id="refresh-watches-button">Обновить список</button>
        </div>
        <div class="watch-list" id="watch-list">
          <div class="empty-state">Подключаем локальный профиль…</div>
        </div>
        <div class="watch-history" id="watch-history-list"></div>
      </section>

      <aside class="panel providers-panel" aria-labelledby="providers-heading">
        <div class="panel-header">
          <div>
            <h2 class="panel-title" id="providers-heading">Источники и точность</h2>
            <div class="panel-kicker">Какие данные доступны сейчас и требуют ли они проверки.</div>
          </div>
        </div>
        <div class="provider-list" id="providers-list">
          <div class="empty-state">Проверяю доступные источники...</div>
        </div>
      </aside>

      <details class="panel utility-panel" aria-labelledby="admin-health-heading">
        <summary>
          <span>
            <span class="panel-title" id="admin-health-heading">Диагностика</span>
            <span class="panel-kicker">Состояние источников и фоновых задач без запуска поиска.</span>
          </span>
        </summary>
        <div class="panel-toolbar">
          <button class="secondary" type="button" id="refresh-admin-health-button">Обновить</button>
        </div>
        <div class="admin-health-list" id="admin-health-list">
          <div class="empty-state">Загружаю состояние...</div>
        </div>
      </details>

      <details class="panel utility-panel" aria-labelledby="audit-heading">
        <summary>
          <span>
            <span class="panel-title" id="audit-heading">Журнал действий</span>
            <span class="panel-kicker">История операций внутри вашей локальной группы.</span>
          </span>
        </summary>
        <div class="panel-toolbar">
          <button class="secondary" type="button" id="refresh-audit-button">Обновить</button>
        </div>
        <div class="admin-health-list" id="audit-list">
          <div class="empty-state">Подключаем локальный профиль…</div>
        </div>
      </details>
    </section>
  </main>

  <script>
    const carrierCodePattern = /^[A-Z0-9]{2}$/;
    const carrierLogoOrigin = "https://pics.avs.io/80/80/";
    const agentResultPageSize = 20;
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
    const authState = document.querySelector("#auth-state");
    const authReconnectButton = document.querySelector("#auth-reconnect-button");
    const invitationLoginForm = document.querySelector("#invitation-login-form");
    const invitationNameInput = document.querySelector("#invitation-name");
    const invitationCodeInput = document.querySelector("#invitation-code");
    const invitationAdminPanel = document.querySelector("#invitation-admin-panel");
    const invitationCreateForm = document.querySelector("#invitation-create-form");
    const invitationRecipientInput = document.querySelector("#invitation-recipient");
    const invitationCreatedResult = document.querySelector("#invitation-created-result");
    const accountMenu = document.querySelector(".account-menu");
    const accountLabel = document.querySelector("#account-label");
    let browserSources = [];
    let agentPresets = [];
    let lastSearchPayload = null;
    let lastSearchId = null;
    let lastExternalLinks = [];
    let lastRequestedRoute = null;
    let watchRecords = [];
    let currentAgentPlan = null;
    let currentAgentRun = null;
    let agentExecuteInFlight = false;
    let agentExecuteGeneration = 0;
    let lastAgentPrompt = "";
    let agentEditMode = false;
    let agentSessionGeneration = 0;
    let pendingAgentChat = null;
    let agentVisibleResultCount = agentResultPageSize;
    let agentVisibleResultRunId = null;
    const sessionTokenKey = "flight_hunter_session_token";
    const agentPlanStorageKey = "flight_hunter_agent_plan_id_v1";
    const agentRunStorageKey = "flight_hunter_agent_run_id_v1";
    const placeSelectionError = "Сначала выберите города или аэропорты из списка.";
    const placeLocale = "ru";
    const placeLookupBatchLimit = 64;
    const placeCache = new Map();
    let placeDirectoryVersion = null;

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

    function sessionIdentityIsCurrent(token, sessionGeneration) {
      return token === sessionToken()
        && sessionGeneration === agentSessionGeneration;
    }

    function householdRoleLabel(role) {
      return ({owner: "Владелец", admin: "Администратор", member: "Участник", viewer: "Просмотр"})[role]
        || "Профиль";
    }

    function updateInvitationAdminPanel(role) {
      invitationAdminPanel.hidden = role !== "owner";
      if (role !== "owner") invitationCreatedResult.textContent = "";
    }

    function storeSession(session) {
      clearAgentSessionState();
      window.localStorage.setItem(sessionTokenKey, session.session_token);
      accountLabel.textContent = "Семейный профиль";
      authState.textContent = `Вход выполнен · ${householdRoleLabel(session.role)} · ${session.household_id.slice(0, 8)}`;
      invitationLoginForm.hidden = true;
      authReconnectButton.hidden = false;
      authReconnectButton.disabled = false;
      updateInvitationAdminPanel(session.role);
      accountMenu.open = false;
    }

    function clearAgentSessionState() {
      agentSessionGeneration += 1;
      currentAgentPlan = null;
      currentAgentRun = null;
      agentExecuteGeneration += 1;
      agentExecuteInFlight = false;
      agentEditMode = false;
      lastAgentPrompt = "";
      pendingAgentChat = null;
      document.getElementById("main-search").classList.remove("search-active");
      document.getElementById("agent-plan-card").hidden = true;
      [
        "agent-plan-status",
        "agent-plan-revision",
        "agent-plan-scope",
        "agent-plan-date-mode",
        "agent-plan-passengers",
        "agent-plan-coverage",
        "agent-plan-strategies",
        "agent-plan-hidden-city",
        "agent-plan-estimate",
        "agent-plan-rpm",
        "agent-plan-deadline",
        "agent-plan-source",
        "agent-plan-expiry",
        "agent-run-meta",
        "agent-run-progress",
        "agent-fare-analysis-list",
        "agent-confirmed-results-list",
        "agent-risky-results-list",
        "agent-partial-errors"
      ].forEach((id) => {
        document.getElementById(id).textContent = "";
      });
      document.getElementById("agent-plan-execute").disabled = true;
      document.getElementById("agent-plan-execute").setAttribute("aria-busy", "false");
      document.getElementById("agent-hidden-city-warning").hidden = true;
      document.getElementById("agent-hidden-city-warning-list").replaceChildren();
      document.getElementById("agent-hidden-city-ack").checked = false;
      document.getElementById("agent-plan-full").disabled = true;
      document.getElementById("agent-plan-edit").disabled = true;
      document.getElementById("agent-run-cancel").disabled = true;
      document.getElementById("agent-run-cancel").hidden = true;
      document.getElementById("agent-fare-analysis").hidden = true;
      document.getElementById("agent-confirmed-results").hidden = true;
      document.getElementById("agent-risky-results").hidden = true;
      document.getElementById("agent-partial-errors").hidden = true;
      renderAgentStages(-1);
      agentActionList.replaceChildren();
      airportChoiceList.replaceChildren();
      chatLog.replaceChildren();
      addMessage("bot", "Опишите поездку обычными словами — я соберу маршрут и проверю доступные варианты.");
    }

    function renderLocalProfilePendingConfirmationState() {
      confirmationList.innerHTML = '<div class="empty-state">Подключаем локальный профиль…</div>';
    }

    async function loadSessionBoundData() {
      if (!sessionToken()) return;
      await Promise.all([
        loadManualConfirmations(),
        loadWatches(),
        loadAuditEvents(),
        reloadAgentPlan()
      ]);
    }

    async function ensureLocalSession() {
      if (sessionToken()) return true;

      accountMenu.open = true;
      invitationLoginForm.hidden = false;
      authReconnectButton.hidden = true;
      authState.textContent = "Введите имя и одноразовый код приглашения.";
      statusLine.textContent = "требуется вход";
      return false;
    }

    async function refreshSessionState() {
      const token = sessionToken();
      if (!token) return ensureLocalSession();
      const sessionGeneration = agentSessionGeneration;
      try {
        const response = await fetch("/api/v1/auth/me", {
          headers: {"Authorization": `Bearer ${token}`}
        });
        if (!sessionIdentityIsCurrent(token, sessionGeneration)) return false;
        if (response.status === 401) {
          window.localStorage.removeItem(sessionTokenKey);
          clearAgentSessionState();
          return ensureLocalSession();
        }
        if (!response.ok) throw new Error(await codedMessage(response));
        const session = await response.json();
        if (!sessionIdentityIsCurrent(token, sessionGeneration)) return false;
        accountLabel.textContent = "Семейный профиль";
        authState.textContent = `Вход выполнен · ${householdRoleLabel(session.role)} · ${session.household_id.slice(0, 8)}`;
        invitationLoginForm.hidden = true;
        authReconnectButton.hidden = false;
        authReconnectButton.disabled = false;
        updateInvitationAdminPanel(session.role);
        return true;
      } catch (error) {
        if (!sessionIdentityIsCurrent(token, sessionGeneration)) return false;
        authState.textContent = `Профиль временно недоступен: ${error.message}`;
        statusLine.textContent = "локальный профиль временно недоступен";
        return false;
      }
    }

    async function reconnectLocalSession() {
      authReconnectButton.disabled = true;
      window.localStorage.removeItem(sessionTokenKey);
      clearAgentSessionState();
      invitationLoginForm.reset();
      invitationLoginForm.hidden = false;
      authReconnectButton.hidden = true;
      invitationAdminPanel.hidden = true;
      invitationCreatedResult.textContent = "";
      accountMenu.open = true;
      authState.textContent = "Введите одноразовый код приглашения для входа.";
      statusLine.textContent = "требуется вход";
      authReconnectButton.disabled = false;
      return false;
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

    function isoCountryFlag(countryCode) {
      const normalized = text(countryCode).toUpperCase();
      if (!/^[A-Z]{2}$/.test(normalized)) return "";
      return String.fromCodePoint(
        ...Array.from(normalized, (letter) => 127397 + letter.codePointAt(0))
      );
    }

    function normalizePlaceRef(ref) {
      const kind = text(ref?.kind);
      const code = text(ref?.code).toUpperCase();
      if (!["city", "airport"].includes(kind) || !/^[A-Z]{3}$/.test(code)) return null;
      return {kind, code};
    }

    function placeCacheKey(ref, locale, directoryVersion) {
      // Cache identity: kind|code|locale|directory_version.
      const kind = text(ref?.kind);
      const code = text(ref?.code).toUpperCase();
      return `${kind}|${code}|${locale}|${directoryVersion}`;
    }

    function cachePlaceOption(option, locale = placeLocale, directoryVersion = null) {
      const ref = normalizePlaceRef(option?.ref);
      const version = text(directoryVersion || option?.directory_version);
      if (!ref || !version) return null;
      const cached = {
        ...option,
        ref,
        resolved: option?.resolved !== false,
        directory_version: version
      };
      placeCache.set(placeCacheKey(ref, locale, version), cached);
      placeDirectoryVersion = version;
      return cached;
    }

    function cachedPlaceOption(ref, directoryVersion = null, locale = placeLocale) {
      const normalized = normalizePlaceRef(ref);
      const version = directoryVersion === null
        ? text(placeDirectoryVersion)
        : text(directoryVersion);
      if (!normalized || !version) return null;
      return placeCache.get(placeCacheKey(normalized, locale, version)) || null;
    }

    function formatPlaceLabel(place, includeCode = false) {
      const ref = normalizePlaceRef(place?.ref || place);
      const rawCode = ref?.code || text(place?.ref?.code || place?.code).toUpperCase() || "???";
      const displayName = text(place?.display_name?.text);
      const codeOnly = place?.display_name?.fallback_reason === "code_only"
        || displayName.toUpperCase() === rawCode;
      if (place?.resolved === false || !displayName || codeOnly) {
        return `${rawCode} · Название не найдено`;
      }
      const flag = isoCountryFlag(place?.country_code);
      const humanName = `${flag ? `${flag} ` : ""}${displayName}`;
      return includeCode ? `${humanName} (${rawCode})` : humanName;
    }

    function formatPlaceRoute(origin, destination, includeCode = false) {
      return `${formatPlaceLabel(origin, includeCode)} → ${formatPlaceLabel(destination, includeCode)}`;
    }

    function formatPlaceRouteFromCache(
      originRef,
      destinationRef,
      includeCode = false,
      directoryVersion = null
    ) {
      const origin = cachedPlaceOption(originRef, directoryVersion) || originRef;
      const destination = cachedPlaceOption(destinationRef, directoryVersion) || destinationRef;
      return formatPlaceRoute(origin, destination, includeCode);
    }

    async function lookupPlaceRefs(refs, directoryVersion = null) {
      const unique = new Map();
      (refs || []).forEach((ref) => {
        const normalized = normalizePlaceRef(ref);
        if (normalized) unique.set(`${normalized.kind}|${normalized.code}`, normalized);
      });
      const requested = Array.from(unique.values());
      const missing = requested.filter((ref) => !cachedPlaceOption(ref, directoryVersion));
      for (let offset = 0; offset < missing.length; offset += placeLookupBatchLimit) {
        const batch = missing.slice(offset, offset + placeLookupBatchLimit);
        try {
          const response = await fetch("/api/v1/places/lookup", {
            method: "POST",
            headers: {"Content-Type": "application/json"},
            body: JSON.stringify({locale: placeLocale, places: batch})
          });
          if (!response.ok) continue;
          const body = await response.json();
          const responseVersion = text(body.directory_version);
          if (body.catalog_status !== "ready" || !responseVersion) continue;
          (body.items || []).forEach((item) => {
            cachePlaceOption(item, placeLocale, responseVersion);
          });
        } catch (error) {
          // Rendering keeps the raw typed code when lookup is unavailable.
        }
      }
      return requested.map((ref) => cachedPlaceOption(ref, directoryVersion)
        || {ref, resolved: false});
    }

    async function lookupAirportPlaces(codes, directoryVersion = null) {
      return lookupPlaceRefs(
        (codes || []).map((code) => (
          typeof code === "string" ? {kind: "airport", code} : code
        )),
        directoryVersion
      );
    }

    function seedRequestedRoutePlaceCache(requestedRoute) {
      lastRequestedRoute = requestedRoute || null;
      [requestedRoute?.origin, requestedRoute?.destination].forEach((option) => {
        if (option) cachePlaceOption(option);
      });
    }

    function setupPlaceCombobox(field) {
      const input = document.getElementById(`${field}-place-input`);
      const canonicalCode = document.querySelector(`[name="${field}"]`);
      const canonicalKind = document.querySelector(`[name="${field}_kind"]`);
      const listbox = document.getElementById(`${field}-place-listbox`);
      const status = document.getElementById(`${field}-place-status`);
      let options = [];
      let activeIndex = -1;
      let debounceTimer = null;
      let requestController = null;
      let requestSequence = 0;

      const closeListbox = () => {
        listbox.hidden = true;
        input.setAttribute("aria-expanded", "false");
        input.removeAttribute("aria-activedescendant");
        activeIndex = -1;
      };

      const positionListbox = () => {
        if (listbox.hidden) return;
        listbox.dataset.placement = "below";
        listbox.style.maxHeight = "";
        const inputRect = input.getBoundingClientRect();
        const listboxRect = listbox.getBoundingClientRect();
        const viewportTop = window.visualViewport?.offsetTop ?? 0;
        const viewportHeight = window.visualViewport?.height ?? window.innerHeight;
        const viewportBottom = viewportTop + viewportHeight;
        const viewportPadding = 8;
        const popupGap = 6;
        const spaceBelow = Math.max(
          0,
          viewportBottom - inputRect.bottom - viewportPadding - popupGap
        );
        const spaceAbove = Math.max(
          0,
          inputRect.top - viewportTop - viewportPadding - popupGap
        );
        const placeAbove = listboxRect.height > spaceBelow && spaceAbove > spaceBelow;
        if (placeAbove) {
          listbox.dataset.placement = "above";
        }
        const availableHeight = placeAbove ? spaceAbove : spaceBelow;
        listbox.style.maxHeight = `${Math.max(0, Math.min(320, availableHeight))}px`;
      };

      const clearCanonical = () => {
        canonicalCode.value = "";
        canonicalKind.value = "";
      };

      const setActiveOption = (nextIndex) => {
        if (!options.length) return;
        activeIndex = (nextIndex + options.length) % options.length;
        Array.from(listbox.children).forEach((node, index) => {
          node.setAttribute("aria-selected", String(index === activeIndex));
        });
        const activeNode = listbox.children[activeIndex];
        input.setAttribute("aria-activedescendant", activeNode.id);
        activeNode.scrollIntoView({block: "nearest"});
      };

      const selectOption = (option) => {
        const code = text(option?.ref?.code).toUpperCase();
        const kind = text(option?.ref?.kind);
        if (!/^[A-Z]{3}$/.test(code) || !["city", "airport"].includes(kind)) return;
        const displayName = text(option?.display_name?.text) || code;
        const kindLabel = kind === "city" ? "Все аэропорты" : "Аэропорт";
        const flag = isoCountryFlag(option?.country_code);
        canonicalCode.value = code;
        canonicalKind.value = kind;
        cachePlaceOption(option);
        input.value = `${flag ? `${flag} ` : ""}${displayName} · ${kindLabel} · ${code}`;
        input.setAttribute("aria-invalid", "false");
        status.textContent = `Выбрано: ${displayName}, ${kindLabel}, ${code}.`;
        closeListbox();
      };

      const renderOptions = (items) => {
        options = items.filter((option) => {
          const code = text(option?.ref?.code).toUpperCase();
          return /^[A-Z]{3}$/.test(code)
            && ["city", "airport"].includes(text(option?.ref?.kind))
            && Boolean(text(option?.display_name?.text));
        });
        activeIndex = -1;
        listbox.replaceChildren();
        options.forEach((option, index) => {
          const button = document.createElement("button");
          button.type = "button";
          button.id = `${field}-place-option-${index}`;
          button.className = "place-option";
          button.setAttribute("role", "option");
          button.setAttribute("aria-selected", "false");

          const flag = document.createElement("span");
          flag.className = "place-option-flag";
          flag.setAttribute("aria-hidden", "true");
          flag.textContent = isoCountryFlag(option.country_code);

          const copy = document.createElement("span");
          copy.className = "place-option-copy";
          const name = document.createElement("span");
          name.className = "place-option-name";
          name.textContent = text(option.display_name?.text) || option.ref.code;
          const meta = document.createElement("span");
          meta.className = "place-option-meta";
          const kindLabel = option.ref.kind === "city" ? "Все аэропорты" : "Аэропорт";
          const cityName = text(option.city_name?.text);
          meta.textContent = [
            option.ref.kind === "airport" ? cityName : "",
            kindLabel,
            text(option.ref.code).toUpperCase()
          ].filter(Boolean).join(" · ");
          copy.append(name, meta);
          button.append(flag, copy);
          button.addEventListener("pointerdown", (event) => event.preventDefault());
          button.addEventListener("click", () => {
            selectOption(option);
            input.focus();
          });
          listbox.append(button);
        });
        listbox.hidden = options.length === 0;
        input.setAttribute("aria-expanded", String(options.length > 0));
        positionListbox();
      };

      const requestOptions = async (query, sequence) => {
        requestController = new AbortController();
        try {
          const response = await fetch(
            `/api/v1/places/suggest?q=${encodeURIComponent(query)}&locale=ru&limit=10`,
            {signal: requestController.signal}
          );
          if (!response.ok) throw new Error(`HTTP ${response.status}`);
          const body = await response.json();
          if (sequence !== requestSequence) return;
          if (body.catalog_status !== "ready") {
            options = [];
            listbox.replaceChildren();
            closeListbox();
            status.textContent = "Справочник мест сейчас недоступен.";
            return;
          }
          renderOptions(Array.isArray(body.items) ? body.items : []);
          status.textContent = options.length
            ? `Найдено вариантов: ${options.length}. Выберите город или аэропорт.`
            : "Ничего не найдено.";
        } catch (error) {
          if (error.name === "AbortError") return;
          options = [];
          listbox.replaceChildren();
          closeListbox();
          status.textContent = "Не удалось загрузить варианты мест.";
        }
      };

      input.addEventListener("input", () => {
        clearCanonical();
        input.setAttribute("aria-invalid", "false");
        window.clearTimeout(debounceTimer);
        requestSequence += 1;
        if (requestController) requestController.abort();
        options = [];
        listbox.replaceChildren();
        closeListbox();
        const query = input.value.trim();
        if (query.length < 2) {
          status.textContent = query ? "Введите ещё один символ." : "";
          return;
        }
        status.textContent = "Ищу города и аэропорты...";
        const sequence = requestSequence;
        debounceTimer = window.setTimeout(() => {
          void requestOptions(query, sequence);
        }, 180);
      });

      input.addEventListener("keydown", (event) => {
        if (event.key === "ArrowDown") {
          if (!options.length) return;
          event.preventDefault();
          listbox.hidden = false;
          input.setAttribute("aria-expanded", "true");
          setActiveOption(activeIndex + 1);
          positionListbox();
        } else if (event.key === "ArrowUp") {
          if (!options.length) return;
          event.preventDefault();
          listbox.hidden = false;
          input.setAttribute("aria-expanded", "true");
          setActiveOption(activeIndex < 0 ? options.length - 1 : activeIndex - 1);
          positionListbox();
        } else if (event.key === "Enter" && !listbox.hidden && activeIndex >= 0) {
          event.preventDefault();
          selectOption(options[activeIndex]);
        } else if (event.key === "Escape") {
          event.preventDefault();
          closeListbox();
        }
      });

      document.addEventListener("pointerdown", (event) => {
        if (!event.target.closest(`[data-place-role="${field}"]`)) closeListbox();
      });
    }

    function validateTypedPlaceSelections() {
      const form = new FormData(document.querySelector("#search-form"));
      const missingField = ["origin", "destination"].find((field) => {
        const code = text(form.get(field)).toUpperCase();
        const kind = text(form.get(`${field}_kind`));
        const valid = /^[A-Z]{3}$/.test(code) && ["city", "airport"].includes(kind);
        document.getElementById(`${field}-place-input`).setAttribute(
          "aria-invalid",
          String(!valid)
        );
        return !valid;
      });
      if (!missingField) return true;
      statusLine.textContent = placeSelectionError;
      document.getElementById(`${missingField}-place-status`).textContent = placeSelectionError;
      document.getElementById(`${missingField}-place-input`).focus();
      return false;
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
        origin_kind: text(form.get("origin_kind")),
        destination_kind: text(form.get("destination_kind")),
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
      if (["origin", "destination"].includes(name)) {
        document.getElementById(`${name}-place-input`).value = value || "";
        document.querySelector(`[name="${name}"]`).value = "";
        document.querySelector(`[name="${name}_kind"]`).value = "";
        return;
      }
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
        ? `ИИ-модель · ${details.model}`
        : "детерминированный локальный режим";
      agentLoop.textContent = "полный запрос → сразу живой поиск";
      agentLivePolicy.textContent = details.live_calls_allowed
        ? "живой поиск уже запущен"
        : "запустится из полного запроса";
      agentEdgeReady.textContent = details.cloudflare_ready
        ? "локальное хранение · переносимый запуск"
        : "только локально";
      agentMode.textContent = ["openai_responses", "codex_cli"].includes(details.backend)
        ? "ИИ подключён"
        : "локальный агент";
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

    async function lookupWatchPlaces(watches) {
      const refsByVersion = new Map();
      (watches || []).forEach((watch) => {
        const directoryVersion = text(watch.directory_version);
        const refs = refsByVersion.get(directoryVersion) || [];
        refs.push(
          {kind: watch.origin_kind, code: watch.origin},
          {kind: watch.destination_kind, code: watch.destination}
        );
        refsByVersion.set(directoryVersion, refs);
      });
      for (const [directoryVersion, refs] of refsByVersion) {
        await lookupPlaceRefs(refs, directoryVersion);
      }
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
        const originRef = {kind: watch.origin_kind, code: watch.origin};
        const destinationRef = {kind: watch.destination_kind, code: watch.destination};
        const state = watchStatus(watch);
        const row = document.createElement("div");
        row.className = "provider-row";
        row.innerHTML = `
          <div class="row-main">
            <div class="provider-name"></div>
            <span class="badge"></span>
          </div>
          <div class="small"></div>
          <div class="watch-actions"></div>
        `;
        row.querySelector(".provider-name").textContent = formatPlaceRouteFromCache(
          originRef,
          destinationRef,
          false,
          watch.directory_version
        );
        row.querySelector(".badge").classList.add(state.tone);
        row.querySelector(".badge").textContent = state.label;
        row.querySelector(".small").textContent =
          `${watch.origin} → ${watch.destination} · ${watchMeta(watch)}`;
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
        `${formatPlaceRouteFromCache(
          {kind: watch.origin_kind, code: watch.origin},
          {kind: watch.destination_kind, code: watch.destination},
          false,
          watch.directory_version
        )}. Snapshots не являются live-гарантией.`
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
        const watches = body.watches || [];
        await lookupWatchPlaces(watches);
        renderWatches(watches);
      } catch (error) {
        watchList.replaceChildren();
        const row = document.createElement("div");
        row.className = "denial-row small";
        row.textContent = `Watches: ${error.message}`;
        watchList.append(row);
      }
    }

    async function createWatchFromSearch() {
      if (!validateTypedPlaceSelections()) return;
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
            origin_kind: payload.origin_kind,
            destination_kind: payload.destination_kind,
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

    async function createWatchFromAgentAnalysis(action, button) {
      if (!action?.available) return;
      button.disabled = true;
      statusLine.textContent = "создаю отслеживание по анализу...";
      try {
        const response = await fetch("/api/v1/watches", {
          method: "POST",
          headers: authHeaders({"Content-Type": "application/json"}),
          body: JSON.stringify({
            origin: action.origin,
            destination: action.destination,
            departure_date: action.departure_date,
            return_date: action.return_date,
            passengers: action.passengers,
            currency: action.currency,
            allowed_provider_ids: []
          })
        });
        if (!response.ok) throw new Error(await codedMessage(response));
        const watch = await response.json();
        statusLine.textContent = `отслеживание создано · v${watch.version}`;
        await loadWatches();
        await loadAuditEvents();
        await loadWatchHistory(watch);
      } catch (error) {
        statusLine.textContent = `ошибка отслеживания: ${error.message}`;
      } finally {
        button.disabled = false;
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

    function requestedRouteOptionForCode(requestedRoute, code) {
      const normalizedCode = text(code).toUpperCase();
      return [requestedRoute?.origin, requestedRoute?.destination].find(
        (option) => text(option?.ref?.code).toUpperCase() === normalizedCode
      ) || null;
    }

    function formatRequestedRoute(requestedRoute, fallbackOrigin = null, fallbackDestination = null) {
      const origin = requestedRoute?.origin || fallbackOrigin || {code: "???"};
      const destination = requestedRoute?.destination || fallbackDestination || {code: "???"};
      return formatPlaceRoute(origin, destination);
    }

    function formatConcreteSegments(segments, fallbackOrigin = null, fallbackDestination = null) {
      const concrete = (segments || []).filter((segment) => (
        /^[A-Z]{3}$/.test(text(segment?.origin).toUpperCase())
        && /^[A-Z]{3}$/.test(text(segment?.destination).toUpperCase())
      ));
      if (concrete.length > 0) {
        return concrete.map((segment) => formatPlaceRouteFromCache(
          {kind: "airport", code: segment.origin},
          {kind: "airport", code: segment.destination},
          true
        )).join(" · ");
      }
      return formatPlaceRouteFromCache(
        {kind: "airport", code: fallbackOrigin},
        {kind: "airport", code: fallbackDestination},
        true
      );
    }

    function formatExternalRoute(link, requestedRoute) {
      const directoryVersion = text(
        requestedRoute?.origin?.directory_version
        || requestedRoute?.destination?.directory_version
      );
      const resolvedExternalPlace = (code) => {
        const requested = requestedRouteOptionForCode(requestedRoute, code);
        if (requested) return requested;
        const resolved = [
          cachedPlaceOption({kind: "airport", code}, directoryVersion),
          cachedPlaceOption({kind: "city", code}, directoryVersion)
        ].filter((option) => Boolean(option) && option.resolved !== false);
        return resolved.length === 1 ? resolved[0] : {code};
      };
      const origin = resolvedExternalPlace(link?.origin);
      const destination = resolvedExternalPlace(link?.destination);
      return formatPlaceRoute(origin, destination);
    }

    async function lookupSearchResultPlaces(body) {
      seedRequestedRoutePlaceCache(body?.requested_route);
      const offers = body?.priced_offers || body?.offers || [];
      const requestedRoute = body?.requested_route;
      const directoryVersion = text(
        requestedRoute?.origin?.directory_version
        || requestedRoute?.destination?.directory_version
      );
      const lookupRefs = [];
      const addAirport = (code) => lookupRefs.push({kind: "airport", code});
      offers.forEach((offer) => {
        if ((offer.segments || []).length > 0) {
          offer.segments.forEach((segment) => {
            addAirport(segment.origin);
            addAirport(segment.destination);
          });
        } else {
          addAirport(offer.origin);
          addAirport(offer.destination);
        }
      });
      (body?.browser_observed_offers || []).forEach((offer) => {
        addAirport(offer.origin);
        addAirport(offer.destination);
      });
      (body?.deal_candidates || []).forEach((candidate) => {
        addAirport(candidate.extracted_origin);
        addAirport(candidate.extracted_destination);
      });
      (body?.external_links || []).forEach((link) => {
        [link.origin, link.destination].forEach((code) => {
          if (requestedRouteOptionForCode(requestedRoute, code)) return;
          lookupRefs.push({kind: "airport", code}, {kind: "city", code});
        });
      });
      await lookupPlaceRefs(lookupRefs, directoryVersion);
    }

    function appendOfferBadges(container, offer) {
      (offer.ranking_reasons || []).forEach((reason) => {
        const badge = document.createElement("span");
        const tone = reason === "cached_price" || reason === "recent_price" ? "ok" : "warn";
        badge.className = `badge ${tone}`;
        badge.textContent = reasonLabel(reason);
        container.append(badge);
      });
      const risk = offer.risk || {};
      const level = risk.level || "unknown";
      const levelBadge = document.createElement("span");
      levelBadge.className = `badge ${riskTone(level)}`;
      levelBadge.textContent = riskLevelLabel(offer);
      container.append(levelBadge);
      (risk.flags || []).forEach((flag) => {
        const badge = document.createElement("span");
        badge.className = "badge warn";
        badge.textContent = reasonLabel(flag);
        container.append(badge);
      });
    }

    function appendCarrierStrip(container, segments) {
      const segmentFacts = Array.isArray(segments) ? segments : [];
      if (segmentFacts.length === 0) return;

      const seen = new Set();
      const carriers = [];
      segmentFacts.forEach((segment) => {
        const code = text(segment?.airline_code).toUpperCase();
        const safeCode = carrierCodePattern.test(code) ? code : "";
        const name = text(segment?.airline_name);
        const normalizedName = name.toLocaleLowerCase("ru-RU");
        const identity = safeCode
          ? `code:${safeCode}`
          : name
            ? `name:${normalizedName}`
            : "unknown";
        if (seen.has(identity)) return;
        seen.add(identity);
        carriers.push({code: safeCode, name});
      });

      const strip = document.createElement("div");
      strip.className = "carrier-strip";
      carriers.slice(0, 3).forEach((carrier) => {
        const chip = document.createElement("span");
        chip.className = "carrier-chip";
        const mark = document.createElement("span");
        mark.className = "carrier-mark";
        const monogram = document.createElement("span");
        monogram.className = "carrier-monogram";
        monogram.textContent = carrier.code || carrier.name
          .split(/\\s+/)
          .filter(Boolean)
          .slice(0, 2)
          .map((part) => part[0])
          .join("")
          .toUpperCase() || "?";
        mark.append(monogram);

        if (carrier.code) {
          const image = document.createElement("img");
          image.className = "carrier-logo";
          image.alt = "";
          image.loading = "lazy";
          image.decoding = "async";
          image.addEventListener("load", () => {
            image.classList.add("carrier-logo-loaded");
          }, {once: true});
          image.addEventListener("error", () => {
            chip.classList.add("carrier-logo-failed");
            image.removeAttribute("src");
            image.hidden = true;
          }, {once: true});
          image.src = `${carrierLogoOrigin}${encodeURIComponent(carrier.code)}.png`;
          mark.append(image);
        }

        const label = document.createElement("span");
        label.className = "carrier-label";
        label.textContent = carrier.name || carrier.code || "Авиакомпания не указана";
        chip.append(mark, label);
        strip.append(chip);
      });

      if (carriers.length > 3) {
        const overflow = document.createElement("span");
        overflow.className = "carrier-overflow";
        overflow.textContent = `+${carriers.length - 3}`;
        strip.append(overflow);
      }
      container.append(strip);
    }

    function renderResults(body) {
      const offers = body.priced_offers || body.offers || [];
      const externalLinks = body.external_links || [];
      const observedOffers = body.browser_observed_offers || [];
      const dealCandidates = body.deal_candidates || [];
      const freshnessSummary = body.freshness_summary || {};
      const requestedRoute = body.requested_route || lastRequestedRoute;
      seedRequestedRoutePlaceCache(requestedRoute);
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
        row.innerHTML = `
          <div>
            <div class="route"></div>
            <div class="segment-route small"></div>
            <div class="result-meta small"></div>
          </div>
          <div class="price"></div>
          <div>
            <div class="caveats"></div>
            <div class="risk-detail small"></div>
            <div class="result-actions">
              <button class="secondary live-check-button" type="button">Проверить live</button>
            </div>
          </div>
        `;
        row.querySelector(".route").textContent = formatRequestedRoute(
          body.requested_route,
          {kind: lastSearchPayload?.origin_kind, code: offer.origin},
          {kind: lastSearchPayload?.destination_kind, code: offer.destination}
        );
        row.querySelector(".segment-route").textContent =
          `Фактически: ${formatConcreteSegments(
            offer.segments,
            offer.origin,
            offer.destination
          )}`;
        row.querySelector(".result-meta").textContent =
          `${offer.departure_date}${offer.return_date ? " — " + offer.return_date : ""}`
          + ` · ${offer.passengers} пасс. · ${providerLabel(offer.provider_id)}`
          + `${priceBasisLabel(offer)} · ${offer.freshness}`;
        row.querySelector(".price").textContent = offer.total_price.formatted;
        appendOfferBadges(row.querySelector(".caveats"), offer);
        row.querySelector(".risk-detail").textContent = riskExplanationText(offer);
        row.querySelector(".live-check-button").addEventListener("click", () => runLiveCheck());
        appendManualConfirmationActions(row.querySelector(".result-actions"), pricedOfferTarget(offer));
        if ((offer.segments || []).length > 0) {
          appendCarrierStrip(row, offer.segments);
        }
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
        row.querySelector(".route").textContent = formatExternalRoute(link, requestedRoute);
        row.querySelector(".small").textContent =
          `${link.source_name} · ${link.origin} → ${link.destination} · `
          + `${link.departure_date}${link.return_date ? " — " + link.return_date : ""}`
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
        const title = document.createElement("div");
        title.className = "route";
        title.textContent = formatRequestedRoute(
          requestedRoute,
          {kind: "airport", code: offer.origin},
          {kind: "airport", code: offer.destination}
        );
        const concreteRoute = document.createElement("div");
        concreteRoute.className = "small";
        concreteRoute.textContent = `Фактически: ${formatPlaceRouteFromCache(
          {kind: "airport", code: offer.origin},
          {kind: "airport", code: offer.destination},
          true
        )}`;
        const details = document.createElement("div");
        details.className = "small";
        details.textContent =
          `${offer.source_name}: ${offer.total_price ? offer.total_price.formatted : "цена не найдена"}`
          + ` · confidence=${offer.confidence} · ${offer.parser_warnings.join(", ") || "без предупреждений"}`;
        row.append(title, concreteRoute, details);
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
        renderLocalProfilePendingConfirmationState();
      }
    }

    async function lookupLiveObservationPlaces(observation) {
      const codes = (observation?.offers || []).flatMap((offer) => [
        offer.origin,
        offer.destination
      ]);
      await lookupAirportPlaces(codes);
    }

    function renderLiveObservation(observation) {
      liveList.replaceChildren();
      const row = document.createElement("div");
      row.className = "denial-row";
      const offer = (observation.offers || [])[0];
      if (!offer) {
        row.textContent = `Live: ${observation.status}`;
        liveList.append(row);
        return;
      }
      const title = document.createElement("div");
      title.className = "route";
      title.textContent = formatRequestedRoute(
        lastRequestedRoute,
        {kind: "airport", code: offer.origin},
        {kind: "airport", code: offer.destination}
      );
      const concreteRoute = document.createElement("div");
      concreteRoute.className = "small";
      concreteRoute.textContent = `Фактически: ${formatPlaceRouteFromCache(
        {kind: "airport", code: offer.origin},
        {kind: "airport", code: offer.destination},
        true
      )}`;
      const details = document.createElement("div");
      details.className = "small";
      details.textContent = `Live observed · ${offer.total_price.formatted}`
        + ` · наблюдалось ${observation.observed_at}`;
      row.append(title, concreteRoute, details);
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
        const route = document.createElement("div");
        route.className = "small";
        route.textContent = candidate.extracted_origin || candidate.extracted_destination
          ? `Маршрут: ${formatPlaceRouteFromCache(
            {kind: "airport", code: candidate.extracted_origin},
            {kind: "airport", code: candidate.extracted_destination},
            true
          )}`
          : "Маршрут в источнике не указан.";
        const expiry = document.createElement("div");
        expiry.className = "small";
        expiry.textContent = dealCandidateExpiryLabel(candidate);
        row.append(details, route, expiry);
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
        agentMode.textContent = "локальный агент";
      }
      presetList.replaceChildren();
      const examples = {
        flexible_dates: "Найди самый дешёвый билет из Санкт-Петербурга в Париж около 15 сентября, проверь даты ±3 дня",
        nearby_airports: "Найди самый дешёвый путь из Москвы в Милан и проверь аэропорты в радиусе 150 км",
        buy_timing: "Когда лучше покупать билет из Санкт-Петербурга в Стамбул на 12 октября? Проверь текущие цены",
        split_ticket: "Найди дешёвый путь из Санкт-Петербурга в Лиссабон, включая отдельные билеты и самостоятельные пересадки",
        hidden_city: "Проверь hidden-city варианты из Москвы в Париж без багажа и сначала покажи риски",
        error_fare_sources: "Где сейчас искать аномально дешёвые билеты из России в Азию?",
        geo_currency: "Сравни стоимость рейса Москва — Дубай в доступных валютах и странах сайта"
      };
      agentPresets.forEach((preset) => {
        const button = document.createElement("button");
        button.className = "chip";
        button.type = "button";
        button.textContent = preset.title_ru;
        button.title = "Подставить пример в запрос";
        button.addEventListener("click", () => {
          const input = document.querySelector("#assistant-form textarea");
          input.value = examples[preset.id] || preset.description_ru || preset.title_ru;
          input.focus();
          input.setSelectionRange(input.value.length, input.value.length);
        });
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
        draft: "Нужно уточнить маршрут",
        awaiting_approval: "Маршрут готов к поиску",
        consumed: "Маршрут принят, поиск выполняется",
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
      const hiddenCityWarnings = summary.hidden_city_warnings || [];
      const executeReady = plan.state === "awaiting_approval"
        && plan.executable === true;
      const cloneReady = ["consumed", "expired", "superseded"].includes(plan.state)
        && plan.coverage === "quick";
      const editReady = ["draft", "awaiting_approval"].includes(plan.state);

      document.getElementById("agent-plan-card").hidden = false;
      document.getElementById("main-search").classList.add("search-active");
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
      const strategyLabels = {
        nearby_airports: "ближайшие аэропорты",
        flexible_dates: "гибкие даты",
        split_ticket: "отдельные билеты",
        self_transfer: "самостоятельные пересадки",
        hidden_city: "hidden-city"
      };
      const selectedStrategies = (plan.enabled_strategies || [])
        .map((value) => strategyLabels[value] || value);
      if (summary.baggage_preference === "checked") selectedStrategies.push("с багажом");
      if (summary.baggage_preference === "carry_on") selectedStrategies.push("только ручная кладь");
      if (summary.baggage_preference === "none") selectedStrategies.push("без багажа");
      if (summary.wants_watch === true) selectedStrategies.push("слежение за ценой");
      document.getElementById("agent-plan-strategies").textContent =
        selectedStrategies.join(", ") || "Стандартный маршрут";
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

      const warningRegion = document.getElementById("agent-hidden-city-warning");
      const warningList = document.getElementById("agent-hidden-city-warning-list");
      const warningAck = document.getElementById("agent-hidden-city-ack");
      warningRegion.hidden = !hiddenCityEnabled;
      if (hiddenCityEnabled) document.querySelector(".agent-plan-details").open = true;
      warningAck.checked = false;
      warningList.replaceChildren();
      hiddenCityWarnings.forEach((warning) => {
        const item = document.createElement("li");
        item.textContent = warning.message_ru;
        warningList.append(item);
      });

      const executeButton = document.getElementById("agent-plan-execute");
      executeButton.disabled = agentExecuteInFlight
        || !executeReady
        || (hiddenCityEnabled && !warningAck.checked);
      executeButton.title = executeReady && !hiddenCityEnabled
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
      document.getElementById("agent-confirmed-results").hidden = true;
      document.getElementById("agent-confirmed-results-list").textContent =
        "Подтверждённых вариантов ещё нет.";
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

    function renderAgentStages(activeIndex, state = "active") {
      document.querySelectorAll("[data-agent-stage]").forEach((node) => {
        const index = Number(node.dataset.agentStage);
        node.classList.toggle("is-done", activeIndex >= 0 && index < activeIndex);
        node.classList.toggle("is-active", state === "active" && index === activeIndex);
        node.classList.toggle("is-error", state === "error" && index === activeIndex);
        if (state === "done" && activeIndex === 4) {
          node.classList.toggle("is-done", index <= activeIndex);
          node.classList.remove("is-active", "is-error");
        }
      });
    }

    function agentRunStage(run) {
      if (run.status === "queued") return 1;
      if (run.status === "running" || run.status === "cancel_requested") {
        const operations = run.operation_counts || {};
        if ((operations.succeeded || 0) > 0) return 3;
        if ((operations.attempted || 0) > 0 || (operations.leased || 0) > 0) return 2;
        return 1;
      }
      return 4;
    }

    function agentRunProgressMessage(run) {
      const operations = run.operation_counts || {};
      const attempted = operations.attempted || 0;
      const total = operations.total || 0;
      const progress = total > 0 ? ` Проверено операций: ${attempted} из ${total}.` : "";
      const messages = {
        queued: "Маршрут понятен. Поиск поставлен в очередь.",
        running: `Проверяю живые цены и сравниваю маршруты.${progress}`,
        cancel_requested: "Останавливаю поиск и сохраняю уже найденные варианты.",
        completed: "Готово. Ниже только варианты, подтверждённые источником.",
        partial: "Поиск завершён частично. Показываю всё, что удалось подтвердить.",
        failed: "Поиск не завершился. Выдуманных вариантов не добавлено.",
        cancelled: "Поиск остановлен. Уже подтверждённые данные сохранены."
      };
      return messages[run.status] || `Состояние поиска: ${run.status}.`;
    }

    function renderAgentRun(run) {
      currentAgentRun = run;
      window.localStorage.setItem(agentRunStorageKey, String(run.run_id));
      const progress = document.getElementById("agent-run-progress");
      const cancelButton = document.getElementById("agent-run-cancel");
      const partialErrors = document.getElementById("agent-partial-errors");
      const terminalProblem = ["partial", "failed", "cancelled"].includes(run.status);
      const terminalSuccess = run.status === "completed";
      const stage = agentRunStage(run);
      renderAgentStages(stage, terminalSuccess ? "done" : terminalProblem ? "error" : "active");
      progress.textContent = agentRunProgressMessage(run);
      progress.title = `Запуск ${String(run.run_id).slice(0, 8)}`;
      document.getElementById("agent-run-meta").textContent =
        `Запуск ${run.run_id} · статус ${run.status} · дедлайн ${formatIsoMinute(run.deadline_at)}`;
      cancelButton.disabled = !["queued", "running"].includes(run.status);
      cancelButton.hidden = !["queued", "running", "cancel_requested"].includes(run.status);
      cancelButton.title = run.status === "cancel_requested"
        ? "Отмена уже запрошена"
        : "Отменить выполняющийся запуск";
      partialErrors.hidden = !terminalProblem && !run.error_code;
      partialErrors.textContent = partialErrors.hidden
        ? ""
        : agentRunErrorMessage(run.error_code, run.public_message || `Состояние: ${run.status}`);
    }

    function renderAgentFareAnalysis(analysis) {
      const region = document.getElementById("agent-fare-analysis");
      const list = document.getElementById("agent-fare-analysis-list");
      const requestedModes = analysis?.requested_modes || [];
      list.replaceChildren();
      if (!analysis || requestedModes.length === 0) {
        region.hidden = true;
        list.textContent = "Анализ не запрашивался.";
        return;
      }
      region.hidden = false;
      const appendLine = (text, tone = "") => {
        const line = document.createElement("div");
        line.className = tone ? `agent-analysis-line ${tone}` : "agent-analysis-line";
        line.textContent = text;
        list.append(line);
      };
      if (analysis.scope_status === "unsupported_trip_structure") {
        appendLine(
          "Исторический анализ цены полного маршрута пока недоступен для open-jaw, "
          + "multi-city и составных split/self-transfer билетов. Цена отдельного участка "
          + "не выдаётся за цену всей поездки.",
          "warn"
        );
        return;
      }
      appendLine(
        `${formatMinorAmount(
          analysis.primary_amount.minor_units,
          analysis.primary_amount.currency
        )} · ${analysis.passengers} пасс. · ${analysis.provider_id} · `
        + `${String(analysis.freshness).toUpperCase()} · ${formatIsoMinute(analysis.observed_at)}`
      );
      const buyTiming = analysis.buy_timing;
      if (requestedModes.includes("buy_timing")) {
        if (!buyTiming || buyTiming.status === "insufficient_data") {
          const sampleCount = buyTiming?.sample_count ?? 0;
          const watchHint = buyTiming?.watch_action_available
            ? " Можно создать отдельный мониторинг текущей цены; "
              + "он не увеличивает выборку этого анализа."
            : "";
          appendLine(
            `Лучшее время покупки: Недостаточно данных (${sampleCount} наблюдений; `
            + `нужно ${buyTiming?.thresholds?.minimum_observations ?? 40}, `
            + `${buyTiming?.thresholds?.minimum_history_span_days ?? 21} дней и `
            + `${buyTiming?.thresholds?.minimum_distinct_dates ?? 14} дат).${watchHint}`,
            "warn"
          );
        } else if (buyTiming.status === "historically_low") {
          appendLine(
            `Текущая цена исторически низкая: не выше 20-го процентиля `
            + `(${formatMinorAmount(
              buyTiming.twentieth_percentile_minor_units,
              analysis.primary_amount.currency
            )}).`,
            "ok"
          );
        } else {
          appendLine("Сигнала «покупать сейчас» по накопленной истории нет.");
        }
        const weekdayNames = [
          "понедельник",
          "вторник",
          "среда",
          "четверг",
          "пятница",
          "суббота",
          "воскресенье"
        ];
        if (Number.isInteger(buyTiming?.recommended_weekday)) {
          appendLine(
            `По истории выгоднее бронировать в ${weekdayNames[buyTiming.recommended_weekday]}: `
            + `медиана ниже примерно на ${buyTiming.weekday_savings_percent}%.`
          );
        }
        if (Number.isInteger(buyTiming?.recommended_four_hour_bucket)) {
          const startHour = buyTiming.recommended_four_hour_bucket;
          const endHour = (startHour + 4) % 24;
          appendLine(
            `Выгодное окно бронирования: ${String(startHour).padStart(2, "0")}:00–`
            + `${String(endHour).padStart(2, "0")}:00 (${buyTiming.timezone}); `
            + `медиана ниже примерно на ${buyTiming.four_hour_savings_percent}%.`
          );
        }
        if (buyTiming?.watch_action_available && analysis.watch_action?.available) {
          const watchButton = document.createElement("button");
          watchButton.type = "button";
          watchButton.className = "secondary";
          watchButton.textContent = "Создать отдельный мониторинг цены";
          watchButton.addEventListener("click", () => {
            void createWatchFromAgentAnalysis(analysis.watch_action, watchButton);
          });
          list.append(watchButton);
        }
      }
      const anomaly = analysis.anomaly;
      if (requestedModes.includes("error_fare")) {
        if (!anomaly || anomaly.status === "insufficient_data") {
          appendLine("Проверка аномалии: Недостаточно данных.", "warn");
        } else if (anomaly.status === "suspected_anomaly") {
          appendLine(
            "Подозрение на аномально низкую цену — это не гарантия ошибочного тарифа.",
            "warn"
          );
        } else {
          appendLine("Цена не прошла строгие пороги подозрения на аномалию.");
        }
      }
      const currency = analysis.currency_comparison;
      if (requestedModes.includes("currency_compare")) {
        const referenceAmount = currency
          ? formatMinorAmount(
              currency.reference_amount.minor_units,
              currency.reference_amount.currency
            )
          : null;
        const candidateAmount = currency?.candidate_amount
          ? formatMinorAmount(
              currency.candidate_amount.minor_units,
              currency.candidate_amount.currency
            )
          : null;
        const comparedAmounts = candidateAmount
          ? ` Базовый вариант: ${referenceAmount}; альтернативный: ${candidateAmount}.`
          : ` Базовый вариант: ${referenceAmount}.`;
        if (!currency || currency.status === "fx_provider_unavailable") {
          appendLine(
            `Сравнение валют: FX-провайдер не настроен. Экономия не рассчитана.${comparedAmounts}`,
            "warn"
          );
        } else if (currency.status === "not_comparable") {
          appendLine(
            `Сравнение валют: варианты материально несопоставимы.${comparedAmounts}`,
            "warn"
          );
        } else if (
          Number.isSafeInteger(Number(currency.savings_minor_units))
          && Number(currency.savings_minor_units) > 0
        ) {
          const percent = currency.savings_percent
            ? ` (${currency.savings_percent}%)`
            : "";
          appendLine(
            `Сравнение валют: подтверждённая экономия `
            + `${formatMinorAmount(
              currency.savings_minor_units,
              currency.comparison_currency
            )}${percent}.${comparedAmounts}`,
            "ok"
          );
        } else {
          appendLine(
            `Сравнение валют: положительная экономия не подтверждена.${comparedAmounts}`
          );
        }
      }
    }

    async function lookupAgentResultPlaces(results) {
      const codes = [];
      (results?.candidates || []).forEach((candidate) => {
        (candidate.ordered_legs || []).forEach((leg) => {
          codes.push(leg.origin, leg.destination);
        });
        (candidate.segments || []).forEach((segment) => {
          codes.push(segment.origin, segment.destination);
        });
      });
      (results?.hidden_city_candidates || []).forEach((candidate) => {
        codes.push(candidate.desired_airport, candidate.ticketed_destination);
        [...(candidate.flown_segments || []), ...(candidate.skipped_segments || [])]
          .forEach((segment) => codes.push(segment.origin, segment.destination));
      });
      await lookupAirportPlaces(codes);
    }

    function appendAgentRankingBadges(container, candidate) {
      const labels = {
        balanced: ["Лучший вариант", "ok"],
        cheapest: ["Самый дешёвый", "ok"],
        fastest: ["Самый быстрый", "ok"],
        low_risk: ["Меньше риска", "ok"],
        split_self_transfer: ["Отдельные билеты", "warn"],
        risky: ["Повышенный риск", "high"]
      };
      const winners = (candidate.rankings || []).filter((ranking) => ranking.rank === 1);
      winners.forEach((ranking) => {
        const [label, tone] = labels[ranking.view] || [ranking.view, "off"];
        const badge = document.createElement("span");
        badge.className = `badge ${tone}`;
        badge.textContent = label;
        container.append(badge);
      });
      const confirmed = document.createElement("span");
      confirmed.className = "badge off";
      confirmed.textContent = "Подтверждено источником";
      container.append(confirmed);
    }

    function agentProtectionLabel(value) {
      return ({
        explicitly_protected: "Пересадка защищена единым билетом",
        self_transfer: "Самостоятельная пересадка",
        unknown: "Защита пересадки неизвестна"
      })[value] || "Защита пересадки неизвестна";
    }

    function agentAirportChanges(segments) {
      const changes = [];
      for (let index = 1; index < (segments || []).length; index += 1) {
        const previous = segments[index - 1] || {};
        const current = segments[index] || {};
        if (
          previous.destination
          && current.origin
          && previous.destination !== current.origin
        ) {
          changes.push({arrival: previous.destination, departure: current.origin});
        }
      }
      return changes;
    }

    async function resolveAgentBooking(token, button) {
      if (!token || !currentAgentPlan || !currentAgentRun || button.disabled) return;
      const originalLabel = button.textContent;
      button.disabled = true;
      button.textContent = "Открываю билет…";
      try {
        const response = await fetch(
          `${agentPlanUrl(currentAgentPlan.plan_id)}/runs/${encodeURIComponent(currentAgentRun.run_id)}/booking-actions/resolve`,
          {
            method: "POST",
            headers: authHeaders({"Content-Type": "application/json"}),
            body: JSON.stringify({token})
          }
        );
        if (!response.ok) throw new Error(await codedMessage(response));
        const body = await response.json();
        if (body.status !== "resolved" || !body.url) {
          throw new Error("Ссылка на билет больше недоступна");
        }
        const target = new URL(body.url, window.location.origin);
        if (!["http:", "https:"].includes(target.protocol)) {
          throw new Error("Источник вернул неподдерживаемую ссылку");
        }
        window.location.assign(target.href);
      } catch (error) {
        button.disabled = false;
        button.textContent = originalLabel;
        const errors = document.getElementById("agent-partial-errors");
        errors.hidden = false;
        errors.textContent = `Не удалось открыть билет: ${error.message}`;
      }
    }

    function renderAgentConfirmedResults(results) {
      const region = document.getElementById("agent-confirmed-results");
      const list = document.getElementById("agent-confirmed-results-list");
      const candidates = results.candidates || [];
      const runId = currentAgentRun?.run_id || null;
      if (runId !== agentVisibleResultRunId) {
        agentVisibleResultRunId = runId;
        agentVisibleResultCount = agentResultPageSize;
      }
      list.replaceChildren();
      region.hidden = results.state === "not_ready";
      if (results.state !== "ready" || candidates.length === 0) {
        list.textContent = results.state === "unavailable"
          ? "Подтверждённые варианты недоступны: сохранённые данные не прошли проверку."
          : "По этому запросу подтверждённых вариантов пока нет.";
        return;
      }
      const visibleCandidates = candidates.slice(0, agentVisibleResultCount);
      visibleCandidates.forEach((candidate) => {
        const segments = candidate.segments || [];
        const legs = candidate.ordered_legs || [];
        const airportChanges = agentAirportChanges(segments);
        const amount = candidate.total_amount || {};
        const card = document.createElement("article");
        card.className = "agent-result-card";

        const head = document.createElement("div");
        head.className = "agent-result-head";
        const route = document.createElement("div");
        route.className = "agent-result-route";
        route.textContent = legs.map((leg) => (
          formatPlaceRouteFromCache(
            {kind: "airport", code: leg.origin},
            {kind: "airport", code: leg.destination},
            true
          )
        )).join(" · ") || "Маршрут не указан";
        const price = document.createElement("div");
        price.className = "agent-result-price";
        price.textContent = Number.isInteger(amount.minor_units) && amount.currency
          ? formatMinorAmount(amount.minor_units, amount.currency)
          : "Цена не подтверждена";
        head.append(route, price);

        const badges = document.createElement("div");
        badges.className = "agent-result-badges";
        appendAgentRankingBadges(badges, candidate);

        const facts = document.createElement("div");
        facts.className = "agent-result-facts";
        const transferCount = Math.max(0, segments.length - Math.max(legs.length, 1));
        const baggageValues = [...new Set((candidate.baggage_summaries || []).filter(Boolean))];
        const sources = (candidate.sources || [])
          .map((source) => providerLabels[source] || source)
          .join(", ") || "источник не указан";
        [
          `${candidate.passengers || 1} пасс.`,
          transferCount === 0 ? "Без пересадок" : `${transferCount} пересадок`,
          agentProtectionLabel(candidate.protection_status),
          baggageValues.length ? `Багаж: ${baggageValues.join(", ")}` : "Багаж: данных нет",
          `Источник: ${sources}`,
          `Проверено: ${formatIsoMinute(candidate.observed_at)}`
        ].forEach((value) => {
          const fact = document.createElement("span");
          fact.className = "agent-result-fact";
          fact.textContent = value;
          facts.append(fact);
        });

        card.append(head, badges);
        if (segments.length > 0) appendCarrierStrip(card, segments);
        card.append(facts);

        const separateTickets = (candidate.ticket_boundaries || []).length;
        const unknownCosts = (candidate.unknown_costs || []).length;
        if (
          separateTickets > 1
          || unknownCosts > 0
          || airportChanges.length > 0
          || candidate.price_comparison_status !== "fully_priced"
        ) {
          const warning = document.createElement("div");
          warning.className = "agent-result-warning";
          const parts = [];
          if (separateTickets > 1) parts.push(`${separateTickets} отдельных билета — перепроверьте пересадки`);
          airportChanges.forEach((change) => {
            const route = formatPlaceRouteFromCache(
              {kind: "airport", code: change.arrival},
              {kind: "airport", code: change.departure},
              true
            );
            parts.push(`Смена аэропорта ${route}: стоимость наземного переезда не подтверждена`);
          });
          if (unknownCosts > 0) parts.push(`не подтверждена стоимость ${unknownCosts} обязательных расходов`);
          if (candidate.price_comparison_status === "non_comparable") parts.push("итоговая цена несопоставима с обычным единым билетом");
          warning.textContent = parts.join(" · ") || "В итоговой стоимости есть неподтверждённые обязательные расходы.";
          card.append(warning);
        }

        if (segments.length > 0) {
          const details = document.createElement("details");
          details.className = "agent-result-segments";
          const summary = document.createElement("summary");
          summary.textContent = `Показать ${segments.length} сегм.`;
          const segmentList = document.createElement("div");
          segmentList.className = "agent-segment-list";
          segments.forEach((segment) => {
            const row = document.createElement("div");
            row.className = "agent-segment-row";
            const segmentRoute = document.createElement("span");
            segmentRoute.textContent = formatPlaceRouteFromCache(
              {kind: "airport", code: segment.origin},
              {kind: "airport", code: segment.destination},
              true
            );
            const schedule = document.createElement("span");
            const flight = [segment.airline_code, segment.flight_number].filter(Boolean).join(" ");
            schedule.textContent = `${flight ? `${flight} · ` : ""}${formatIsoMinute(segment.depart_at)} → ${formatIsoMinute(segment.arrive_at)}`;
            row.append(segmentRoute, schedule);
            segmentList.append(row);
          });
          details.append(summary, segmentList);
          card.append(details);
        }

        const actions = document.createElement("div");
        actions.className = "agent-result-actions";
        if (candidate.booking_action?.available && candidate.booking_action.token) {
          const booking = document.createElement("button");
          booking.className = "primary";
          booking.type = "button";
          booking.textContent = "Перейти к билету";
          booking.addEventListener("click", () => {
            void resolveAgentBooking(candidate.booking_action.token, booking);
          });
          actions.append(booking);
        }
        card.append(actions);
        list.append(card);
      });

      const pagination = document.createElement("div");
      pagination.className = "agent-result-pagination";
      const summary = document.createElement("span");
      summary.textContent = `Показано ${visibleCandidates.length} из ${candidates.length}`;
      pagination.append(summary);
      if (visibleCandidates.length < candidates.length) {
        const more = document.createElement("button");
        more.type = "button";
        more.className = "secondary";
        more.textContent = `Показать ещё ${Math.min(agentResultPageSize, candidates.length - visibleCandidates.length)}`;
        more.addEventListener("click", () => {
          agentVisibleResultCount += agentResultPageSize;
          renderAgentConfirmedResults(results);
        });
        pagination.append(more);
      }
      list.append(pagination);
    }

    function renderAgentRunResults(results) {
      renderAgentFareAnalysis(results.analysis);
      renderAgentConfirmedResults(results);
      const region = document.getElementById("agent-risky-results");
      const list = document.getElementById("agent-risky-results-list");
      const candidates = results.hidden_city_candidates || [];
      list.replaceChildren();
      if (results.state !== "ready" || candidates.length === 0) {
        region.hidden = !(currentAgentPlan?.summary?.hidden_city_enabled === true);
        list.textContent = results.state === "unavailable"
          ? "Hidden-city результаты недоступны: сохранённые evidence не прошли проверку."
          : "Подтверждённых hidden-city вариантов нет.";
        return;
      }
      region.hidden = false;
      list.className = "agent-hidden-city-result-list";
      const warningLabels = {
        checked_baggage_continues: "Сданный багаж может улететь до конечного аэропорта билета.",
        later_segments_may_be_cancelled: "Пропуск сегмента может отменить следующие сегменты.",
        carrier_contract_risk: "Маршрут может конфликтовать с правилами тарифа или перевозчика."
      };
      candidates.forEach((candidate) => {
        const card = document.createElement("article");
        card.className = "agent-hidden-city-result";
        const hiddenCitySegments = [
          ...(candidate.flown_segments || []),
          ...(candidate.skipped_segments || [])
        ];
        const title = document.createElement("strong");
        const desiredPlace = cachedPlaceOption({kind: "airport", code: candidate.desired_airport})
          || {kind: "airport", code: candidate.desired_airport};
        const ticketedPlace = cachedPlaceOption({
          kind: "airport",
          code: candidate.ticketed_destination
        }) || {kind: "airport", code: candidate.ticketed_destination};
        title.textContent =
          `Выйти в ${formatPlaceLabel(desiredPlace, true)}; билет оформлен до `
          + `${formatPlaceLabel(ticketedPlace, true)}`;
        const facts = document.createElement("div");
        facts.className = "small";
        const amount = candidate.total_amount || {};
        const actionability = candidate.actionability === "eligible"
          ? "условно применим без регистрируемого багажа"
          : "только исследование: багаж не подтверждён";
        facts.textContent =
          `${formatMinorAmount(amount.minor_units, amount.currency)} · `
          + `${candidate.passengers} пасс. · LIVE · ${candidate.source_id} · `
          + `наблюдалось ${candidate.observed_at} · ${actionability}`;
        const route = document.createElement("div");
        route.className = "small";
        const flown = (candidate.flown_segments || [])
          .map((segment) => formatPlaceRouteFromCache(
            {kind: "airport", code: segment.origin},
            {kind: "airport", code: segment.destination},
            true
          ))
          .join(" · ");
        const skipped = (candidate.skipped_segments || [])
          .map((segment) => formatPlaceRouteFromCache(
            {kind: "airport", code: segment.origin},
            {kind: "airport", code: segment.destination},
            true
          ))
          .join(" · ");
        route.textContent = `Летим: ${flown || "неизвестно"} · пропускаем: ${skipped || "неизвестно"}`;
        const warnings = document.createElement("ul");
        (candidate.warnings || []).forEach((code) => {
          const item = document.createElement("li");
          item.textContent = warningLabels[code] || code;
          warnings.append(item);
        });
        const actionsDisabled = candidate.booking_action_available === false
          && candidate.watch_available === false;
        const actions = document.createElement("div");
        actions.className = "small";
        actions.textContent = actionsDisabled
          ? "Покупка и отслеживание отключены для hidden-city результата."
          : "Действия заблокированы: некорректный контракт результата.";
        card.append(title);
        if (hiddenCitySegments.length > 0) {
          appendCarrierStrip(card, hiddenCitySegments);
        }
        card.append(facts, route, warnings, actions);
        list.append(card);
      });
    }

    async function loadAgentRunResults(
      planId,
      runId,
      sessionGeneration = agentSessionGeneration
    ) {
      const response = await agentSessionFetch(
        `${agentPlanUrl(planId)}/runs/${encodeURIComponent(runId)}/results`,
        {headers: authHeaders()},
        sessionGeneration
      );
      if (!response) return;
      if (!response.ok) {
        const message = await codedMessage(response);
        if (!agentSessionIsCurrent(sessionGeneration)) return;
        throw new Error(message);
      }
      const results = await response.json();
      if (!agentSessionIsCurrent(sessionGeneration)) return;
      await lookupAgentResultPlaces(results);
      if (!agentSessionIsCurrent(sessionGeneration)) return;
      renderAgentRunResults(results);
    }

    function agentSessionIsCurrent(sessionGeneration) {
      return sessionGeneration === agentSessionGeneration && Boolean(sessionToken());
    }

    async function agentSessionFetch(url, options, sessionGeneration) {
      try {
        const response = await fetch(url, options);
        return agentSessionIsCurrent(sessionGeneration) ? response : null;
      } catch (error) {
        if (!agentSessionIsCurrent(sessionGeneration)) return null;
        throw error;
      }
    }

    async function reviseAgentPlan(parameters) {
      if (
        !currentAgentPlan
        || !["draft", "awaiting_approval"].includes(currentAgentPlan.state)
      ) return;
      const revision = typedAgentAction(parameters);
      if (!revision.coverage && Object.keys(revision.selections).length === 0) {
        beginAgentPlanEdit();
        return;
      }
      const sessionGeneration = agentSessionGeneration;
      const plan = currentAgentPlan;
      const body = {
        source_revision_id: plan.revision_id,
        expected_revision: plan.revision,
        selections: revision.selections
      };
      if (revision.coverage) body.coverage = revision.coverage;
      const response = await agentSessionFetch(
        agentPlanUrl(plan.plan_id),
        {
          method: "PATCH",
          headers: authHeaders({"Content-Type": "application/json"}),
          body: JSON.stringify(body)
        },
        sessionGeneration
      );
      if (!response) return;
      if (!response.ok) {
        const message = await codedMessage(response);
        if (!agentSessionIsCurrent(sessionGeneration)) return;
        throw new Error(message);
      }
      const revisedPlan = await response.json();
      if (!agentSessionIsCurrent(sessionGeneration)) return;
      renderAgentPlan(revisedPlan);
      renderAgentRunPlaceholder("Новая ревизия ждёт явного запуска.");
    }

    async function editAgentPlan(prompt) {
      if (
        !currentAgentPlan
        || !["draft", "awaiting_approval"].includes(currentAgentPlan.state)
      ) return;
      const sessionGeneration = agentSessionGeneration;
      const currentPlan = currentAgentPlan;
      addMessage("user", prompt);
      const response = await agentSessionFetch(
        agentPlanUrl(currentPlan.plan_id),
        {
          method: "PATCH",
          headers: authHeaders({"Content-Type": "application/json"}),
          body: JSON.stringify({
            source_revision_id: currentPlan.revision_id,
            expected_revision: currentPlan.revision,
            text: prompt,
            selections: {}
          })
        },
        sessionGeneration
      );
      if (!response) return;
      if (!response.ok) {
        const message = await codedMessage(response);
        if (!agentSessionIsCurrent(sessionGeneration)) return;
        throw new Error(message);
      }
      const plan = await response.json();
      if (!agentSessionIsCurrent(sessionGeneration)) return;
      renderAgentPlan(plan);
      renderAgentRunPlaceholder("Изменённая ревизия ждёт явного запуска.");
      addMessage("bot", `Создана ревизия ${plan.revision}: ${agentPlanStateLabel(plan.state)}.`);
    }

    async function executeAgentPlan() {
      if (agentExecuteInFlight) return;
      const summary = currentAgentPlan ? currentAgentPlan.summary || {} : {};
      const hiddenCityEnabled = summary.hidden_city_enabled === true;
      const hiddenCityAcknowledged = document.getElementById("agent-hidden-city-ack").checked;
      if (
        !currentAgentPlan
        || currentAgentPlan.state !== "awaiting_approval"
        || !currentAgentPlan.executable
        || (hiddenCityEnabled && !hiddenCityAcknowledged)
      ) return;
      const sessionGeneration = agentSessionGeneration;
      const plan = currentAgentPlan;
      const executeButton = document.getElementById("agent-plan-execute");
      const executeGeneration = ++agentExecuteGeneration;
      agentExecuteInFlight = true;
      executeButton.disabled = true;
      executeButton.setAttribute("aria-busy", "true");
      try {
        const response = await agentSessionFetch(
          `${agentPlanUrl(plan.plan_id)}/execute`,
          {
            method: "POST",
            headers: authHeaders({
              "Content-Type": "application/json",
              "Idempotency-Key": freshIdempotencyKey()
            }),
            body: JSON.stringify({
              revision_id: plan.revision_id,
              expected_revision: plan.revision,
              content_hash: plan.content_hash,
              hidden_city_warning_version: hiddenCityEnabled
                ? summary.hidden_city_warning_version
                : null
            })
          },
          sessionGeneration
        );
        if (!response) return;
        if (!response.ok) {
          const message = await codedMessage(response);
          if (!agentSessionIsCurrent(sessionGeneration)) return;
          throw new Error(message);
        }
        const run = await response.json();
        if (!agentSessionIsCurrent(sessionGeneration)) return;
        renderAgentRun(run);
        await reloadAgentPlan();
      } finally {
        if (executeGeneration !== agentExecuteGeneration) return;
        agentExecuteInFlight = false;
        executeButton.setAttribute("aria-busy", "false");
        if (agentSessionIsCurrent(sessionGeneration) && currentAgentPlan) {
          const currentSummary = currentAgentPlan.summary || {};
          const needsHiddenCityAck = currentSummary.hidden_city_enabled === true
            && !document.getElementById("agent-hidden-city-ack").checked;
          executeButton.disabled = currentAgentPlan.state !== "awaiting_approval"
            || !currentAgentPlan.executable
            || needsHiddenCityAck;
        }
      }
    }

    async function cloneAgentPlanAsFull() {
      if (
        !currentAgentPlan
        || !["consumed", "expired", "superseded"].includes(currentAgentPlan.state)
        || currentAgentPlan.coverage !== "quick"
      ) return;
      const sessionGeneration = agentSessionGeneration;
      const plan = currentAgentPlan;
      const response = await agentSessionFetch(
        `${agentPlanUrl(plan.plan_id)}/revisions`,
        {
          method: "POST",
          headers: authHeaders({
            "Content-Type": "application/json",
            "Idempotency-Key": freshIdempotencyKey()
          }),
          body: JSON.stringify({
            source_revision_id: plan.revision_id,
            expected_revision: plan.revision,
            selections: {},
            coverage: "full"
          })
        },
        sessionGeneration
      );
      if (!response) return;
      if (!response.ok) {
        const message = await codedMessage(response);
        if (!agentSessionIsCurrent(sessionGeneration)) return;
        throw new Error(message);
      }
      const fullPlan = await response.json();
      if (!agentSessionIsCurrent(sessionGeneration)) return;
      renderAgentPlan(fullPlan);
      renderAgentRunPlaceholder("Новая full-ревизия ждёт явного запуска.");
    }

    async function reloadAgentPlan() {
      if (!sessionToken()) return;
      const sessionGeneration = agentSessionGeneration;
      const storedPlanId = window.localStorage.getItem(agentPlanStorageKey);
      const storedRunId = window.localStorage.getItem(agentRunStorageKey);
      if (!storedPlanId) return;
      const response = await agentSessionFetch(
        agentPlanUrl(storedPlanId),
        {headers: authHeaders()},
        sessionGeneration
      );
      if (!response) return;
      if (response.status === 404) {
        window.localStorage.removeItem(agentPlanStorageKey);
        window.localStorage.removeItem(agentRunStorageKey);
        currentAgentPlan = null;
        currentAgentRun = null;
        document.getElementById("agent-plan-card").hidden = true;
        return;
      }
      if (!response.ok) {
        const message = await codedMessage(response);
        if (!agentSessionIsCurrent(sessionGeneration)) return;
        throw new Error(message);
      }
      const plan = await response.json();
      if (!agentSessionIsCurrent(sessionGeneration)) return;
      renderAgentPlan(plan);
      let run = null;
      if (storedRunId) {
        const storedRunResponse = await agentSessionFetch(
          `${agentPlanUrl(storedPlanId)}/runs/${encodeURIComponent(storedRunId)}`,
          {headers: authHeaders()},
          sessionGeneration
        );
        if (!storedRunResponse) return;
        if (storedRunResponse.status === 404) {
          window.localStorage.removeItem(agentRunStorageKey);
        } else if (!storedRunResponse.ok) {
          const message = await codedMessage(storedRunResponse);
          if (!agentSessionIsCurrent(sessionGeneration)) return;
          throw new Error(message);
        } else {
          run = await storedRunResponse.json();
          if (run.revision_id !== plan.revision_id) {
            window.localStorage.removeItem(agentRunStorageKey);
            run = null;
          }
        }
      }
      if (!run) {
        const runListResponse = await agentSessionFetch(
          `${agentPlanUrl(storedPlanId)}/runs`,
          {headers: authHeaders()},
          sessionGeneration
        );
        if (!runListResponse) return;
        if (!runListResponse.ok) {
          const message = await codedMessage(runListResponse);
          if (!agentSessionIsCurrent(sessionGeneration)) return;
          throw new Error(message);
        }
        const runList = await runListResponse.json();
        run = (runList.runs || [])
          .filter((item) => item.revision_id === plan.revision_id)
          .at(-1) || null;
      }
      if (!run) {
        window.localStorage.removeItem(agentRunStorageKey);
        renderAgentRunPlaceholder("Запуск ещё не создан.");
        return;
      }
      if (!agentSessionIsCurrent(sessionGeneration)) return;
      renderAgentRun(run);
      if (["queued", "running", "cancel_requested"].includes(run.status)) {
        window.setTimeout(() => pollAgentRun(run, 1000, sessionGeneration), 1000);
      } else {
        await loadAgentRunResults(storedPlanId, run.run_id, sessionGeneration);
      }
    }

    async function pollAgentRun(
      run,
      delayMs = 1000,
      sessionGeneration = agentSessionGeneration
    ) {
      if (
        sessionGeneration !== agentSessionGeneration
        || !sessionToken()
        || !currentAgentPlan
        || currentAgentRun?.run_id !== run.run_id
      ) return;
      const response = await agentSessionFetch(
        `${agentPlanUrl(currentAgentPlan.plan_id)}/runs/${encodeURIComponent(run.run_id)}`,
        {headers: authHeaders()},
        sessionGeneration
      );
      if (!response) return;
      if (!response.ok) {
        const message = await codedMessage(response);
        if (!agentSessionIsCurrent(sessionGeneration)) return;
        throw new Error(message);
      }
      const latest = await response.json();
      if (!agentSessionIsCurrent(sessionGeneration)) return;
      renderAgentRun(latest);
      if (
        latest.status === "queued"
        || latest.status === "running"
        || latest.status === "cancel_requested"
      ) {
        const nextDelay = Math.min(Math.round(delayMs * 1.5), 10000);
        window.setTimeout(
          () => pollAgentRun(latest, nextDelay, sessionGeneration),
          nextDelay
        );
      } else {
        const planResponse = await agentSessionFetch(
          agentPlanUrl(currentAgentPlan.plan_id),
          {headers: authHeaders()},
          sessionGeneration
        );
        if (!planResponse) return;
        if (planResponse.ok) {
          const plan = await planResponse.json();
          if (!agentSessionIsCurrent(sessionGeneration)) return;
          renderAgentPlan(plan);
        }
        await loadAgentRunResults(
          currentAgentPlan.plan_id,
          latest.run_id,
          sessionGeneration
        );
      }
    }

    async function cancelAgentRun() {
      if (
        !currentAgentPlan
        || !currentAgentRun
        || !["queued", "running"].includes(currentAgentRun.status)
      ) return;
      const sessionGeneration = agentSessionGeneration;
      const planId = currentAgentPlan.plan_id;
      const runId = currentAgentRun.run_id;
      const response = await agentSessionFetch(
        `${agentPlanUrl(planId)}/runs/${encodeURIComponent(runId)}/cancel`,
        {method: "POST", headers: authHeaders()},
        sessionGeneration
      );
      if (!response) return;
      if (!response.ok) {
        const message = await codedMessage(response);
        if (!agentSessionIsCurrent(sessionGeneration)) return;
        throw new Error(message);
      }
      const run = await response.json();
      if (!agentSessionIsCurrent(sessionGeneration)) return;
      renderAgentRun(run);
    }

    function renderAgentRunPlaceholder(message, stageIndex = -1) {
      currentAgentRun = null;
      window.localStorage.removeItem(agentRunStorageKey);
      document.getElementById("agent-run-progress").textContent = message;
      document.getElementById("agent-run-meta").textContent = "Запуск ещё не создан.";
      renderAgentStages(stageIndex);
      document.getElementById("agent-run-cancel").disabled = true;
      document.getElementById("agent-run-cancel").hidden = true;
      document.getElementById("agent-partial-errors").hidden = true;
      document.getElementById("agent-partial-errors").textContent = "";
    }

    async function lookupAirports(query) {
      const response = await fetch(`/api/v1/airports/search?q=${encodeURIComponent(query)}`);
      if (!response.ok) throw new Error(`airport HTTP ${response.status}`);
      return response.json();
    }

    async function requestAgentChat(prompt) {
      if (!(await ensureLocalSession())) {
        addMessage("bot", "Не удалось подключить локальный профиль. Нажмите «Переподключить профиль» и попробуйте ещё раз.");
        return;
      }
      const sessionGeneration = agentSessionGeneration;
      lastAgentPrompt = prompt;
      addMessage("user", prompt);
      statusLine.textContent = "понимаю маршрут...";
      const payload = buildSearchPayload();
      const turnBody = {
        message: prompt,
        passengers: payload.passengers,
        adults: payload.adults,
        children: payload.children,
        infants: payload.infants,
        currency: payload.currency
      };
      const requestSignature = JSON.stringify(turnBody);
      if (!pendingAgentChat || pendingAgentChat.signature !== requestSignature) {
        pendingAgentChat = {signature: requestSignature, key: freshIdempotencyKey()};
      }
      const idempotencyKey = pendingAgentChat.key;
      const submit = document.querySelector("#assistant-form button[type='submit']");
      submit.disabled = true;
      submit.setAttribute("aria-busy", "true");
      document.getElementById("main-search").classList.add("search-active");
      document.getElementById("agent-plan-card").hidden = false;
      document.getElementById("agent-plan-status").textContent = "Разбираю маршрут и ограничения";
      renderAgentRunPlaceholder("Понимаю маршрут и проверяю, хватает ли данных для поиска.", 0);
      try {
        const response = await agentSessionFetch(
          "/api/v1/agent/chat/turn",
          {
            method: "POST",
            headers: authHeaders({
              "Content-Type": "application/json",
              "Idempotency-Key": idempotencyKey
            }),
            body: JSON.stringify(turnBody)
          },
          sessionGeneration
        );
        if (!response) return;
        if (!response.ok) {
          const message = await codedMessage(response);
          if (!agentSessionIsCurrent(sessionGeneration)) return;
          throw new Error(message);
        }
        const body = await response.json();
        if (!agentSessionIsCurrent(sessionGeneration)) return;
        pendingAgentChat = null;
        addMessage("bot", body.reply_ru);
        renderAgentPlan(body.proposed_plan);
        renderAgentRuntime(body.runtime);
        renderAirportChoices(body.airport_options);
        renderAgentActions(body.actions);
        syncExtractedRoute(body);
        if (["run_started", "watch_created"].includes(body.outcome) && body.run) {
          renderAgentRun(body.run);
          if (body.idempotent_replay) {
            addMessage("bot", "Этот же запрос уже был запущен — продолжаю существующий поиск без дубля.");
          }
          if (["queued", "running", "cancel_requested"].includes(body.run.status)) {
            statusLine.textContent = body.outcome === "watch_created"
              ? "поиск и слежение запущены"
              : "ищу варианты...";
            window.setTimeout(() => pollAgentRun(body.run, 1000, sessionGeneration), 1000);
          } else {
            await loadAgentRunResults(body.proposed_plan.plan_id, body.run.run_id, sessionGeneration);
            statusLine.textContent = "готово";
          }
        } else {
          renderAgentRunPlaceholder(body.reply_ru, 0);
          statusLine.textContent = "нужно уточнение";
        }
        if ((body.warnings || []).length > 0) {
          const warningLabels = {
            agent_watch_scope_not_materializable: "Поиск запущен, но для слежения нужен точный город или аэропорт и конкретная дата."
          };
          const message = body.warnings.map((code) => warningLabels[code] || code).join(" ");
          addMessage("bot", message);
          const warnings = document.getElementById("agent-partial-errors");
          warnings.hidden = false;
          warnings.textContent = message;
        }
        document.getElementById("agent-plan-card").scrollIntoView({behavior: "smooth", block: "start"});
      } catch (error) {
        if (!agentSessionIsCurrent(sessionGeneration)) return;
        renderAgentStages(0, "error");
        document.getElementById("agent-run-progress").textContent =
          "Не удалось начать поиск. Запрос можно отправить ещё раз — дубль не создастся.";
        addMessage("bot", `Не удалось начать поиск: ${error.message}`);
        statusLine.textContent = "ошибка агента";
      } finally {
        submit.disabled = false;
        submit.setAttribute("aria-busy", "false");
      }
    }

    async function requestAgentPlan(presetId, visiblePrompt) {
      if (!(await ensureLocalSession())) {
        addMessage("bot", "Не удалось подключить локальный профиль. Нажмите «Переподключить профиль» и повторите сценарий.");
        return;
      }
      const sessionGeneration = agentSessionGeneration;
      addMessage("user", visiblePrompt);
      statusLine.textContent = "ИИ думает...";
      try {
        const response = await agentSessionFetch(
          "/api/v1/agent/plan",
          {
            method: "POST",
            headers: authHeaders({"Content-Type": "application/json"}),
            body: JSON.stringify({preset_id: presetId, slots: currentSlots()})
          },
          sessionGeneration
        );
        if (!response) return;
        if (!response.ok) {
          const message = await codedMessage(response);
          if (!agentSessionIsCurrent(sessionGeneration)) return;
          throw new Error(message);
        }
        const plan = await response.json();
        if (!agentSessionIsCurrent(sessionGeneration)) return;
        renderAgentPlan(plan);
        renderAgentRunPlaceholder("План создан, запуск ещё не выполнялся.");
        statusLine.textContent = "готово";
      } catch (error) {
        if (!agentSessionIsCurrent(sessionGeneration)) return;
        addMessage("bot", `Не смог собрать план: ${error.message}`);
        statusLine.textContent = "ошибка";
      }
    }

    async function runSearch(event) {
      event.preventDefault();
      if (!validateTypedPlaceSelections()) return;
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
        const body = await response.json();
        await lookupSearchResultPlaces(body);
        renderResults(body);
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
        const observation = await observationResponse.json();
        await lookupLiveObservationPlaces(observation);
        renderLiveObservation(observation);
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
        const candidates = body.candidates || [];
        await lookupAirportPlaces(candidates.flatMap((candidate) => [
          candidate.extracted_origin,
          candidate.extracted_destination
        ]));
        renderDealCandidates(candidates);
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
    setupPlaceCombobox("origin");
    setupPlaceCombobox("destination");
    document.getElementById("agent-plan-execute").addEventListener("click", executeAgentPlan);
    document.getElementById("agent-hidden-city-ack").addEventListener("change", (event) => {
      if (!currentAgentPlan) return;
      const hiddenCityEnabled = currentAgentPlan.summary.hidden_city_enabled === true;
      const executeReady = currentAgentPlan.state === "awaiting_approval"
        && currentAgentPlan.executable === true;
      document.getElementById("agent-plan-execute").disabled =
        agentExecuteInFlight || !executeReady || (hiddenCityEnabled && !event.target.checked);
    });
    document.getElementById("agent-plan-full").addEventListener("click", cloneAgentPlanAsFull);
    document.getElementById("agent-run-cancel").addEventListener("click", cancelAgentRun);
    document.getElementById("agent-plan-edit").addEventListener("click", beginAgentPlanEdit);
    authReconnectButton.addEventListener("click", reconnectLocalSession);
    invitationLoginForm.addEventListener("submit", async (event) => {
      event.preventDefault();
      const submitButton = document.getElementById("invitation-login-submit");
      const displayName = invitationNameInput.value.trim();
      const invitationCode = invitationCodeInput.value.trim();
      if (!displayName || !invitationCode) return;

      submitButton.disabled = true;
      authState.textContent = "Проверяем код приглашения…";
      try {
        const response = await fetch("/api/v1/auth/accept-invitation", {
          method: "POST",
          headers: {"Content-Type": "application/json"},
          body: JSON.stringify({
            display_name: displayName,
            invitation_code: invitationCode
          })
        });
        if (!response.ok) throw new Error(await codedMessage(response));

        const session = await response.json();
        if (!session.session_token || !session.household_id || !session.role) {
          throw new Error("Ответ сервера авторизации некорректен");
        }
        storeSession(session);
        invitationLoginForm.reset();
        statusLine.textContent = "профиль подключен";
        try {
          await loadSessionBoundData();
        } catch (loadError) {
          authState.textContent = `Вход выполнен, но часть данных не загрузилась: ${loadError.message}`;
        }
      } catch (error) {
        invitationLoginForm.hidden = false;
        authReconnectButton.hidden = true;
        authState.textContent = `Не удалось войти: ${error.message}`;
      } finally {
        submitButton.disabled = false;
      }
    });
    invitationCreateForm.addEventListener("submit", async (event) => {
      event.preventDefault();
      const submitButton = document.getElementById("invitation-create-submit");
      submitButton.disabled = true;
      invitationCreatedResult.textContent = "Création de l’invitation…";
      try {
        const response = await fetch("/api/v1/auth/invitations", {
          method: "POST",
          headers: authHeaders({"Content-Type": "application/json"}),
          body: JSON.stringify({
            recipient_label: invitationRecipientInput.value.trim() || null,
            ttl_hours: 168
          })
        });
        if (!response.ok) throw new Error(await codedMessage(response));
        const invitation = await response.json();
        invitationCreatedResult.textContent =
          `Code à usage unique (valable jusqu’au ${new Date(invitation.expires_at).toLocaleString()}): ${invitation.invitation_code}. Copiez-le et transmettez-le en privé.`;
        invitationRecipientInput.value = "";
      } catch (error) {
        invitationCreatedResult.textContent = `Impossible de créer l’invitation : ${error.message}`;
      } finally {
        submitButton.disabled = false;
      }
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
      const assistantForm = event.currentTarget;
      const prompt = text(new FormData(assistantForm).get("agent_prompt"));
      if (!prompt) return;
      const operation = agentEditMode ? editAgentPlan(prompt) : requestAgentChat(prompt);
      void operation.then(() => {
        if (sessionToken()) assistantForm.reset();
      });
    });
    updatePassengerSummary();
    renderAgentRuntime({
      backend: "deterministic_gateway",
      agentic_loop: "immediate_durable_search",
      live_calls_allowed: true,
      cloudflare_ready: true
    });
    renderAirportChoices({});
    renderAgentActions([]);
    loadProviders();
    loadBrowserSources();
    loadAdminHealth();
    loadAgentPresets();
    refreshSessionState().then((ready) => {
      if (ready) return loadSessionBoundData();
      return undefined;
    });
    window.addEventListener("unhandledrejection", (event) => {
      event.preventDefault();
      if (!sessionToken()) return;
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
        "description": "Локальный помощник для поиска и отслеживания авиабилетов.",
        "start_url": "/",
        "scope": "/",
        "display": "standalone",
        "background_color": "#f3f5f8",
        "theme_color": "#155eef",
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
  <rect width="512" height="512" rx="92" fill="#0b1f3a"/>
  <path d="M104 272h248M256 128l120 144-120 112" fill="none" stroke="#fff"
    stroke-width="46" stroke-linecap="round" stroke-linejoin="round"/>
  <path d="M116 356h124" fill="none" stroke="#65a7ff" stroke-width="28"
    stroke-linecap="round"/>
</svg>
"""


def render_service_worker_js() -> str:
    return """const CACHE_NAME = "flight-hunter-shell-v2";
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
