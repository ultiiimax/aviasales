from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from flight_hunter.browser.html_extractor import sanitize_dom_html_for_fixture


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="flight-hunter-sanitize-html",
        description="Sanitize a local browser DOM HTML file into a safe diagnostic fixture.",
    )
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()

    raw_html = args.input.read_text(encoding="utf-8")
    sanitized_html = sanitize_dom_html_for_fixture(raw_html)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(sanitized_html, encoding="utf-8")

    print(
        json.dumps(
            {
                "ok": True,
                "input_bytes": len(raw_html.encode("utf-8")),
                "output_bytes": len(sanitized_html.encode("utf-8")),
                "input_sha256": _sha256(raw_html),
                "output_sha256": _sha256(sanitized_html),
            },
            ensure_ascii=False,
        )
    )


def _sha256(value: str) -> str:
    return "sha256:" + hashlib.sha256(value.encode("utf-8")).hexdigest()
