# Systemd Worker Supervision Runbook

Date: 2026-06-29

This runbook packages the existing `flight-hunter-worker` lanes under an external supervisor. It
does not change provider policy: browser observations still require user action, deal discovery
still requires enabled SearXNG/Crawl4AI components, and Aviasales Data remains cached.

## Files

- `deploy/systemd/flight-hunter-api.service`
- `deploy/systemd/flight-hunter-worker@.service`

## Prepare Host

```bash
sudo useradd --system --home /opt/flight-hunter --shell /usr/sbin/nologin flight-hunter
sudo mkdir -p /opt/flight-hunter /etc/flight-hunter /var/lib/flight-hunter /var/log/flight-hunter
sudo chown -R flight-hunter:flight-hunter /opt/flight-hunter /var/lib/flight-hunter /var/log/flight-hunter
```

Copy the repository to `/opt/flight-hunter`, install `uv`, then bootstrap dependencies:

```bash
cd /opt/flight-hunter
sudo -u flight-hunter uv sync --group dev --group crawler
sudo install -m 0640 -o root -g flight-hunter .env.example /etc/flight-hunter/flight-hunter.env
```

Edit `/etc/flight-hunter/flight-hunter.env` and set real secrets there. Do not put secrets in unit
files or command-line arguments.

## Install Units

```bash
sudo install -m 0644 deploy/systemd/flight-hunter-api.service /etc/systemd/system/
sudo install -m 0644 deploy/systemd/flight-hunter-worker@.service /etc/systemd/system/
sudo systemctl daemon-reload
```

Enable the API and the lanes you need:

```bash
sudo systemctl enable --now flight-hunter-api.service
sudo systemctl enable --now flight-hunter-worker@browser.service
sudo systemctl enable --now flight-hunter-worker@watch.service
sudo systemctl enable --now flight-hunter-worker@deal.service
sudo systemctl enable --now flight-hunter-worker@telegram.service
sudo systemctl enable --now flight-hunter-worker@maintenance.service
```

## Deploy Update

Before restarting workers, drain new claims from the admin UI or API, wait for active jobs to finish,
then restart:

```bash
sudo systemctl restart flight-hunter-api.service
sudo systemctl restart 'flight-hunter-worker@*.service'
```

Resume worker claims after health checks pass.

## Health Checks

```bash
systemctl status flight-hunter-api.service
systemctl status flight-hunter-worker@watch.service
journalctl -u flight-hunter-api.service -n 100 --no-pager
journalctl -u flight-hunter-worker@deal.service -n 100 --no-pager
cd /opt/flight-hunter
curl -fsS http://127.0.0.1:8000/api/v1/admin/workers/health
curl -fsS 'http://127.0.0.1:8000/api/v1/admin/workers/metrics?workers_limit=50'
sudo -u flight-hunter uv run flight-hunter-worker-healthcheck --role watch --max-age-seconds 300
sudo -u flight-hunter uv run flight-hunter-worker-healthcheck --role deal --max-age-seconds 300
sudo -u flight-hunter uv run flight-hunter-security-scan
sudo -u flight-hunter uv run flight-hunter-source-smoke --source aviasales_data
sudo -u flight-hunter uv run flight-hunter-source-smoke --source searxng
sudo -u flight-hunter uv run flight-hunter-source-smoke --source crawl4ai --url https://example.com/
```

Expected no-credential defaults are `credentials_missing`, `searxng_disabled` and
`crawl4ai_disabled`.

The metrics endpoint is Prometheus text format and intentionally omits job ids, summaries, secrets
and raw payloads. Use it for scrape-based alerting; use the JSON health endpoint for interactive
diagnosis.

`flight-hunter-worker-healthcheck` is a local DB-backed readiness command for supervisors or cron.
It exits non-zero when a requested role has no heartbeat, a stale/failed heartbeat, or a critical
queue alert. It does not call providers and does not print secrets or raw payloads.

## Browser Lane Notes

The `browser` lane uses the same unit template. For visible browser sessions, configure the host
display/session explicitly and keep `PERSONAL_OBSERVER_PROFILE_ROOT` under a path allowed by
`ReadWritePaths`. Do not point Playwright at a personal Chrome profile.

## Rollback

```bash
sudo systemctl stop 'flight-hunter-worker@*.service'
sudo systemctl stop flight-hunter-api.service
```

Restore the previous checkout and database backup, run `uv run alembic upgrade head` only after
reviewing migrations, then start services again.
