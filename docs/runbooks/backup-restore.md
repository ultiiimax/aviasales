# Backup and Restore Runbook

Date: 2026-07-13

## Local SQLite v1

Create a backup:

```powershell
uv run flight-hunter-backup --database .\flight_hunter_dev.db --backup-dir .\backups
```

The command writes:

- `flight_hunter_YYYYMMDDTHHMMSSZ.db`
- `flight_hunter_YYYYMMDDTHHMMSSZ.db.manifest.json`

Verify the backup before moving or restoring it:

```powershell
uv run flight-hunter-backup-verify .\backups\flight_hunter_YYYYMMDDTHHMMSSZ.db
make backup-verify BACKUP=.\backups\flight_hunter_YYYYMMDDTHHMMSSZ.db
```

Restore only after verification succeeds:

```powershell
uv run flight-hunter-restore .\backups\flight_hunter_YYYYMMDDTHHMMSSZ.db --database .\flight_hunter_dev.db
```

If the destination database exists, restore first copies it to
`flight_hunter_dev.before-restore-YYYYMMDDTHHMMSSZ.db`.

If a manifest exists and checksum verification fails, restore exits non-zero and leaves the current
database unchanged.

## Restore Drill

1. Stop the API and workers.
2. Run `flight-hunter-backup-verify` on the chosen backup.
3. Copy the current database aside or let `flight-hunter-restore` create the before-restore copy.
4. Restore the backup.
5. Run `uv run alembic upgrade head`.
6. Start the API.
7. Run `uv run pytest tests/integration -ra` or the deployment smoke checks.
8. Confirm `/healthz` and authenticated household routes work.

Also confirm `/readyz` returns current migration head and
`flight-hunter-worker-healthcheck --role flight_hunter_worker` returns `ok` after
the worker is restarted.

## Docker Compose Volume

Create and verify an online backup while the stack is running:

```powershell
docker compose exec api uv run flight-hunter-backup --database /data/flight_hunter.db --backup-dir /data/backups
docker compose exec api uv run flight-hunter-backup-verify /data/backups/flight_hunter_YYYYMMDDTHHMMSSZ.db
```

Copy both artifacts off the named volume:

```powershell
docker compose cp api:/data/backups/flight_hunter_YYYYMMDDTHHMMSSZ.db .\backups\
docker compose cp api:/data/backups/flight_hunter_YYYYMMDDTHHMMSSZ.db.manifest.json .\backups\
```

Restore only with both services stopped:

```powershell
docker compose stop worker api
docker compose run --rm --no-deps api uv run flight-hunter-backup-verify /data/backups/flight_hunter_YYYYMMDDTHHMMSSZ.db
docker compose run --rm --no-deps api uv run flight-hunter-restore /data/backups/flight_hunter_YYYYMMDDTHHMMSSZ.db --database /data/flight_hunter.db
docker compose up -d
```

Do not use `docker compose down --volumes` unless permanent deletion of the
database and in-volume backups is intended.

## Unsupported public/PostgreSQL deployment

The supported v1 deployment is local SQLite. A future public PostgreSQL/PostGIS deployment needs a separate
encrypted backup job:

- run `pg_dump` or managed-provider snapshots on a schedule;
- encrypt backup artifacts before off-host storage;
- keep retention and deletion policy explicit;
- store credentials in a secret manager, not scripts or manifests;
- verify checksums after upload;
- rehearse restore into an isolated database at least once per release;
- document RPO/RTO, backup location, restore owner and last successful drill date.

Do not mark production backup coverage complete until the deployment actually runs scheduled
encrypted PostgreSQL backups and a restore drill has passed.
