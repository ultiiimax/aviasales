# ADR 0113: PWA Shell Without API Cache

Date: 2026-06-29

## Status

Accepted.

## Context

Flight Hunter's web UI should be installable as a lightweight self-hosted workbench, but cached
prices, observations and source health must never be presented as offline-fresh data.

## Decision

- Add `/manifest.webmanifest`, `/pwa-icon.svg` and `/service-worker.js`.
- Register the service worker from the existing FastAPI-served UI.
- Cache only the app shell resources: `/`, `/manifest.webmanifest` and `/pwa-icon.svg`.
- Let all `/api/` requests pass through to the network without service-worker caching.

## Consequences

- Browsers can install Flight Hunter as a standalone PWA shell.
- Offline API states remain honest network failures rather than stale cached price displays.
- A richer offline UX can be added later only if every cached payload keeps explicit freshness and
  source timestamps.
