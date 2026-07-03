from __future__ import annotations

import json
import sys
from pathlib import Path

from flight_hunter.ops.sanitize_html import main


def test_sanitize_html_cli_writes_fixture_and_prints_summary(
    monkeypatch,
    capsys,
    tmp_path: Path,
) -> None:
    input_path = tmp_path / "raw.html"
    output_path = tmp_path / "fixture.html"
    input_path.write_text(
        """
        <html>
          <body>
            <script>const token = "secret-token-value";</script>
            <a href="https://example.com/deal?session=secret">Deal</a>
            Visible deal text
          </body>
        </html>
        """,
        encoding="utf-8",
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "flight-hunter-sanitize-html",
            "--input",
            str(input_path),
            "--output",
            str(output_path),
        ],
    )

    main()

    stdout = capsys.readouterr().out
    summary = json.loads(stdout)
    sanitized = output_path.read_text(encoding="utf-8")
    assert summary["ok"] is True
    assert summary["input_sha256"].startswith("sha256:")
    assert summary["output_sha256"].startswith("sha256:")
    assert "<script" not in sanitized
    assert "secret-token-value" not in sanitized
    assert "session=secret" not in sanitized
    assert "Visible deal text" in sanitized
    assert "Visible deal text" not in stdout
    assert "secret-token-value" not in stdout
