# ADR 0118: Backup manifest and restore integrity

Date: 2026-06-29

## Status

Accepted for the current implementation slice.

## Context

Flight Hunter already had local SQLite backup/restore commands for demo deployments. Those commands
copied files safely, but they did not create an integrity manifest or give operators a repeatable
restore drill check. The architecture still calls for production-grade encrypted PostgreSQL backups,
so the local SQLite command must not pretend to be the full production backup subsystem.

## Decision

Improve the current local backup path:

- `flight-hunter-backup` writes a sidecar manifest next to each SQLite backup.
- The manifest records format version, backup kind, creation time, backup filename, byte size,
  SHA-256 checksum and `encrypted=false`.
- `flight-hunter-backup-verify BACKUP` verifies the backup against its manifest.
- `flight-hunter-restore BACKUP` verifies the manifest first when it exists and refuses to restore
  a corrupted backup.
- `make backup-verify BACKUP=...` exposes the verification command through the project command
  surface.
- A runbook documents the local SQLite flow and the still-required production PostgreSQL encrypted
  backup/restore drill.

No migration is required.

## Consequences

Positive:

- Local backups now have a deterministic integrity check.
- Restore refuses corrupted backups when a manifest is present.
- Operators can rehearse a restore drill without editing code or reading internals.

Tradeoffs:

- Existing legacy backup files without a manifest still restore for compatibility.
- The manifest is not encryption and does not make SQLite file backups suitable for production
  PostgreSQL deployments.
- Production encrypted PostgreSQL automation remains a separate deployment slice.

## Verification

- `uv run pytest tests/unit/ops/test_backup_restore.py tests/unit/ops/test_makefile_commands.py -q`
  -> 5 passed.
