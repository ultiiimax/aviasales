from __future__ import annotations

from datetime import UTC, datetime

from flight_hunter.ops.backup import (
    BackupResult,
    create_sqlite_backup,
    restore_sqlite_backup,
    verify_sqlite_backup,
)

NOW = datetime(2026, 6, 23, 12, 0, tzinfo=UTC)


def test_backup_reports_missing_database_without_creating_file(tmp_path) -> None:
    result = create_sqlite_backup(
        database_path=tmp_path / "missing.db",
        backup_dir=tmp_path / "backups",
        clock=lambda: NOW,
    )

    assert result == BackupResult(ok=False, code="database_missing", path=None)
    assert not (tmp_path / "backups").exists()


def test_backup_copies_sqlite_database_to_timestamped_file(tmp_path) -> None:
    database_path = tmp_path / "flight_hunter_dev.db"
    database_path.write_bytes(b"sqlite-data")

    result = create_sqlite_backup(
        database_path=database_path,
        backup_dir=tmp_path / "backups",
        clock=lambda: NOW,
    )

    assert result.ok is True
    assert result.code == "ok"
    assert result.path is not None
    assert result.path.name == "flight_hunter_20260623T120000Z.db"
    assert result.path.read_bytes() == b"sqlite-data"
    assert result.manifest_path is not None
    assert result.manifest_path.name == "flight_hunter_20260623T120000Z.db.manifest.json"

    verification = verify_sqlite_backup(backup_path=result.path)

    assert verification.ok is True
    assert verification.code == "ok"
    assert verification.size_bytes == len(b"sqlite-data")
    assert verification.checksum_sha256 == (
        "58cf0e05e245276612c75970c691676ea412ff1f9022742a15a50005e4e3d2fd"
    )


def test_restore_replaces_database_from_backup_and_saves_previous_copy(tmp_path) -> None:
    database_path = tmp_path / "flight_hunter_dev.db"
    backup_path = tmp_path / "backup.db"
    database_path.write_bytes(b"old")
    backup_path.write_bytes(b"restored")

    result = restore_sqlite_backup(
        database_path=database_path,
        backup_path=backup_path,
        clock=lambda: NOW,
    )

    assert result.ok is True
    assert result.code == "ok"
    assert database_path.read_bytes() == b"restored"
    assert (
        tmp_path / "flight_hunter_dev.before-restore-20260623T120000Z.db"
    ).read_bytes() == b"old"


def test_restore_rejects_corrupted_backup_when_manifest_exists(tmp_path) -> None:
    database_path = tmp_path / "flight_hunter_dev.db"
    database_path.write_bytes(b"original")
    backup_result = create_sqlite_backup(
        database_path=database_path,
        backup_dir=tmp_path / "backups",
        clock=lambda: NOW,
    )
    assert backup_result.path is not None
    backup_result.path.write_bytes(b"corrupted")

    result = restore_sqlite_backup(
        database_path=database_path,
        backup_path=backup_result.path,
        clock=lambda: NOW,
    )

    assert result.ok is False
    assert result.code == "checksum_mismatch"
    assert result.path is None
    assert result.manifest_path == backup_result.manifest_path
    assert result.checksum_sha256 is not None
    assert result.size_bytes == len(b"corrupted")
    assert database_path.read_bytes() == b"original"
