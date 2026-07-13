.PHONY: help bootstrap browser-bootstrap dev dev-api test test-unit test-integration test-e2e lint typecheck migrate seed-demo quality release-check provider-contracts security source-smoke browser-smoke parse-fixture redact-url sanitize-html backup backup-verify restore cleanup-live-observations import-airports worker worker-healthcheck compose-up compose-down compose-worker-up compose-deals-up compose-deals-config

SOURCE ?= aviasales_search
FIXTURE_ARGS ?=
SANITIZE_ARGS ?=
REDACT_URL ?=
WORKER_ROLE ?=

help:
	@echo "Flight Hunter commands:"
	@echo "  make bootstrap          Install dev dependencies with uv"
	@echo "  make browser-bootstrap  Install Playwright Chromium for local E2E"
	@echo "  make dev                Run the local demo API and web screen"
	@echo "  make dev-api            Run the local demo API"
	@echo "  make test               Run current automated tests"
	@echo "  make test-unit          Run unit tests"
	@echo "  make test-integration   Run integration tests when present"
	@echo "  make test-e2e           Run E2E tests when present"
	@echo "  make lint               Run formatter check and lint"
	@echo "  make typecheck          Run mypy"
	@echo "  make migrate            Apply Alembic migrations"
	@echo "  make seed-demo          Seed deterministic local demo data"
	@echo "  make quality            Run test, lint, and typecheck"
	@echo "  make release-check      Run deterministic local v1 gates (RELEASE_ARGS optional)"
	@echo "  make provider-contracts Run current policy contract tests"
	@echo "  make security           Run local secret scanner"
	@echo "  make source-smoke SOURCE=aviasales_search Run one sanitized source smoke check"
	@echo "  make browser-smoke      Run local Playwright Chromium smoke check"
	@echo "  make parse-fixture FIXTURE_ARGS='...' Parse sanitized observer fixture"
	@echo "  make redact-url REDACT_URL='...' Redact credentials/query secrets from a URL"
	@echo "  make sanitize-html SANITIZE_ARGS='...' Sanitize a local DOM fixture"
	@echo "  make backup             Back up local SQLite demo database"
	@echo "  make backup-verify BACKUP=... Verify local SQLite backup manifest"
	@echo "  make restore BACKUP=... Restore local SQLite demo database"
	@echo "  make cleanup-live-observations Clean expired live-check demo state"
	@echo "  make import-airports AIRPORTS_CSV=... Import OurAirports airports.csv"
	@echo "  make worker             Run one local worker pass; set WORKER_ROLE=deal for one lane"
	@echo "  make worker-healthcheck Check durable worker heartbeat/queue health"
	@echo "  make compose-up         Build and start the API stack"
	@echo "  make compose-worker-up  Build and start API + worker profile"
	@echo "  make compose-deals-up   Build and start API + SearXNG profile"
	@echo "  make compose-deals-config Validate the pinned deal-discovery compose profile"
	@echo "  make compose-down       Stop the compose stack"

bootstrap:
	uv sync --group dev

browser-bootstrap:
	uv run flight-hunter-browser-bootstrap

dev: dev-api

dev-api:
	uv run uvicorn flight_hunter.api.app:app --reload --host 127.0.0.1 --port 8000

test: test-unit

test-unit:
	uv run pytest tests/unit

test-integration:
	@if [ -d tests/integration ]; then uv run pytest tests/integration; else echo "No integration tests directory yet"; fi

test-e2e:
	@if [ -d tests/e2e ]; then uv run pytest tests/e2e; else echo "No E2E tests directory yet"; fi

lint:
	uv run ruff format --check .
	uv run ruff check .

typecheck:
	uv run mypy

migrate:
	uv run alembic upgrade head

seed-demo: migrate
	uv run flight-hunter-seed-demo

quality: test lint typecheck security

release-check:
	uv run flight-hunter-release-check $(RELEASE_ARGS)

provider-contracts:
	uv run pytest tests/unit/policy

security:
	uv run flight-hunter-security-scan

source-smoke:
	uv run flight-hunter-source-smoke --source "$(SOURCE)"

browser-smoke:
	uv run flight-hunter-browser-smoke

parse-fixture:
	uv run flight-hunter-parse-fixture $(FIXTURE_ARGS)

redact-url:
	uv run flight-hunter-redact-url --url "$(REDACT_URL)"

sanitize-html:
	uv run flight-hunter-sanitize-html $(SANITIZE_ARGS)

backup:
	uv run flight-hunter-backup

backup-verify:
	uv run flight-hunter-backup-verify "$(BACKUP)"

restore:
	uv run flight-hunter-restore "$(BACKUP)"

cleanup-live-observations:
	uv run flight-hunter-cleanup-live-observations

import-airports:
	uv run flight-hunter-import-airports --airports-csv "$(AIRPORTS_CSV)"

worker:
	uv run flight-hunter-worker $(if $(WORKER_ROLE),--role $(WORKER_ROLE),)

worker-healthcheck:
	uv run flight-hunter-worker-healthcheck $(if $(WORKER_ROLE),--role $(WORKER_ROLE),)

compose-up:
	docker compose up --build

compose-worker-up:
	docker compose --profile worker up --build

compose-deals-up:
	docker compose --profile deal-discovery up --build

compose-deals-config:
	docker compose --profile deal-discovery config

compose-down:
	docker compose down
