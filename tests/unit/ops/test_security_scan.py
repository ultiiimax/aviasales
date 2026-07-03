from __future__ import annotations

from pathlib import Path

from flight_hunter.ops.security_scan import scan_tree


def test_security_scan_reports_high_confidence_secret_patterns(tmp_path: Path) -> None:
    (tmp_path / "safe.py").write_text('API_KEY = "sk-test"\n', encoding="utf-8")
    (tmp_path / "leak.py").write_text(
        'API_KEY = "sk-' + ("a" * 30) + '"\n',
        encoding="utf-8",
    )

    findings = scan_tree(tmp_path)

    assert len(findings) == 1
    assert findings[0].file == "leak.py"
    assert findings[0].kind == "openai_key"


def test_security_scan_skips_local_runtime_dirs(tmp_path: Path) -> None:
    local_dir = tmp_path / ".local"
    local_dir.mkdir()
    (local_dir / "raw.txt").write_text(
        'API_KEY = "sk-' + ("a" * 30) + '"\n',
        encoding="utf-8",
    )

    assert scan_tree(tmp_path) == ()
