# Backup and Restore Runbook

Date: 2026-06-29

## Local SQLite Demo

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

## Production PostgreSQL

The SQLite commands are for local/demo deployments. Production PostgreSQL/PostGIS needs a separate
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
