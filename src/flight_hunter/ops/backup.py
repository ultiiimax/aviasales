from __future__ import annotations

import argparse
import hashlib
import json
import shutil
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path


@dataclass(frozen=True, slots=True)
class BackupResult:
    ok: bool
    code: str
    path: Path | None
    manifest_path: Path | None = None
    checksum_sha256: str | None = None
    size_bytes: int | None = None


@dataclass(frozen=True, slots=True)
class BackupVerificationResult:
    ok: bool
    code: str
    path: Path | None
    manifest_path: Path | None
    checksum_sha256: str | None = None
    size_bytes: int | None = None


def create_sqlite_backup(
    *,
    database_path: Path,
    backup_dir: Path,
    clock: Callable[[], datetime] | None = None,
) -> BackupResult:
    if not database_path.exists():
        return BackupResult(ok=False, code="database_missing", path=None)

    now = clock or (lambda: datetime.now(UTC))
    created_at = now()
    backup_dir.mkdir(parents=True, exist_ok=True)
    backup_path = backup_dir / f"flight_hunter_{_timestamp(created_at)}.db"
    shutil.copy2(database_path, backup_path)
    checksum_sha256, size_bytes = _file_sha256_and_size(backup_path)
    manifest_path = _write_manifest(
        backup_path=backup_path,
        created_at=created_at,
        checksum_sha256=checksum_sha256,
        size_bytes=size_bytes,
    )
    return BackupResult(
        ok=True,
        code="ok",
        path=backup_path,
        manifest_path=manifest_path,
        checksum_sha256=checksum_sha256,
        size_bytes=size_bytes,
    )


def restore_sqlite_backup(
    *,
    database_path: Path,
    backup_path: Path,
    clock: Callable[[], datetime] | None = None,
) -> BackupResult:
    if not backup_path.exists():
        return BackupResult(ok=False, code="backup_missing", path=None)

    manifest_path = _manifest_path_for_backup(backup_path)
    if manifest_path.exists():
        verification = verify_sqlite_backup(backup_path=backup_path, manifest_path=manifest_path)
        if not verification.ok:
            return BackupResult(
                ok=False,
                code=verification.code,
                path=None,
                manifest_path=verification.manifest_path,
                checksum_sha256=verification.checksum_sha256,
                size_bytes=verification.size_bytes,
            )

    now = clock or (lambda: datetime.now(UTC))
    previous_path: Path | None = None
    if database_path.exists():
        previous_path = database_path.with_name(
            f"{database_path.stem}.before-restore-{_timestamp(now())}{database_path.suffix}"
        )
        shutil.copy2(database_path, previous_path)

    database_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(backup_path, database_path)
    return BackupResult(ok=True, code="ok", path=previous_path)


def verify_sqlite_backup(
    *,
    backup_path: Path,
    manifest_path: Path | None = None,
) -> BackupVerificationResult:
    if not backup_path.exists():
        return BackupVerificationResult(
            ok=False,
            code="backup_missing",
            path=None,
            manifest_path=manifest_path,
        )
    manifest_path = manifest_path or _manifest_path_for_backup(backup_path)
    if not manifest_path.exists():
        return BackupVerificationResult(
            ok=False,
            code="manifest_missing",
            path=backup_path,
            manifest_path=manifest_path,
        )
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        expected_checksum = str(manifest["checksum_sha256"])
        expected_size = int(manifest["size_bytes"])
        if manifest.get("format_version") != 1 or manifest.get("kind") != "sqlite_file":
            raise ValueError("unsupported manifest")
    except (KeyError, TypeError, ValueError, json.JSONDecodeError):
        return BackupVerificationResult(
            ok=False,
            code="manifest_invalid",
            path=backup_path,
            manifest_path=manifest_path,
        )

    checksum_sha256, size_bytes = _file_sha256_and_size(backup_path)
    if checksum_sha256 != expected_checksum:
        return BackupVerificationResult(
            ok=False,
            code="checksum_mismatch",
            path=backup_path,
            manifest_path=manifest_path,
            checksum_sha256=checksum_sha256,
            size_bytes=size_bytes,
        )
    if size_bytes != expected_size:
        return BackupVerificationResult(
            ok=False,
            code="size_mismatch",
            path=backup_path,
            manifest_path=manifest_path,
            checksum_sha256=checksum_sha256,
            size_bytes=size_bytes,
        )
    return BackupVerificationResult(
        ok=True,
        code="ok",
        path=backup_path,
        manifest_path=manifest_path,
        checksum_sha256=checksum_sha256,
        size_bytes=size_bytes,
    )


def backup_main() -> int:
    parser = argparse.ArgumentParser(description="Back up local Flight Hunter SQLite database.")
    parser.add_argument("--database", default="flight_hunter_dev.db")
    parser.add_argument("--backup-dir", default="backups")
    args = parser.parse_args()

    result = create_sqlite_backup(
        database_path=Path(args.database),
        backup_dir=Path(args.backup_dir),
    )
    print(_result_json(result))
    return 0 if result.ok else 1


def verify_main() -> int:
    parser = argparse.ArgumentParser(description="Verify a Flight Hunter SQLite backup manifest.")
    parser.add_argument("backup")
    parser.add_argument("--manifest", default=None)
    args = parser.parse_args()

    result = verify_sqlite_backup(
        backup_path=Path(args.backup),
        manifest_path=Path(args.manifest) if args.manifest is not None else None,
    )
    print(_verification_json(result))
    return 0 if result.ok else 1


def restore_main() -> int:
    parser = argparse.ArgumentParser(description="Restore local Flight Hunter SQLite database.")
    parser.add_argument("backup")
    parser.add_argument("--database", default="flight_hunter_dev.db")
    args = parser.parse_args()

    result = restore_sqlite_backup(
        database_path=Path(args.database),
        backup_path=Path(args.backup),
    )
    print(_result_json(result))
    return 0 if result.ok else 1


def _timestamp(value: datetime) -> str:
    normalized = value.astimezone(UTC)
    return normalized.strftime("%Y%m%dT%H%M%SZ")


def _manifest_path_for_backup(backup_path: Path) -> Path:
    return backup_path.with_name(f"{backup_path.name}.manifest.json")


def _write_manifest(
    *,
    backup_path: Path,
    created_at: datetime,
    checksum_sha256: str,
    size_bytes: int,
) -> Path:
    manifest_path = _manifest_path_for_backup(backup_path)
    manifest_path.write_text(
        json.dumps(
            {
                "format_version": 1,
                "kind": "sqlite_file",
                "created_at": created_at.astimezone(UTC).isoformat(),
                "backup_file": backup_path.name,
                "size_bytes": size_bytes,
                "checksum_sha256": checksum_sha256,
                "encrypted": False,
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    return manifest_path


def _file_sha256_and_size(path: Path) -> tuple[str, int]:
    digest = hashlib.sha256()
    size_bytes = 0
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
            size_bytes += len(chunk)
    return digest.hexdigest(), size_bytes


def _result_json(result: BackupResult) -> str:
    return json.dumps(
        {
            "ok": result.ok,
            "code": result.code,
            "path": str(result.path) if result.path is not None else None,
            "manifest_path": (
                str(result.manifest_path) if result.manifest_path is not None else None
            ),
            "checksum_sha256": result.checksum_sha256,
            "size_bytes": result.size_bytes,
        },
        ensure_ascii=False,
        indent=2,
    )


def _verification_json(result: BackupVerificationResult) -> str:
    return json.dumps(
        {
            "ok": result.ok,
            "code": result.code,
            "path": str(result.path) if result.path is not None else None,
            "manifest_path": (
                str(result.manifest_path) if result.manifest_path is not None else None
            ),
            "checksum_sha256": result.checksum_sha256,
            "size_bytes": result.size_bytes,
        },
        ensure_ascii=False,
        indent=2,
    )
