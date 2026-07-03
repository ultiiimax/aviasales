from __future__ import annotations

import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path

_SKIP_DIRS = {
    ".git",
    ".venv",
    ".local",
    ".pytest_cache",
    ".pytest-tmp",
    ".ruff_cache",
    ".mypy_cache",
    ".codex-runtime",
    ".playwright-mcp",
    "backups",
    "build",
    "dist",
    "node_modules",
    "__pycache__",
}
_SKIP_FILES = {"uv.lock"}
_TEXT_SUFFIXES = {
    ".css",
    ".env",
    ".html",
    ".ini",
    ".js",
    ".json",
    ".md",
    ".py",
    ".toml",
    ".txt",
    ".yaml",
    ".yml",
}
_ALLOWLIST = {"sk-test", "secret-value", "secret-token-value"}
_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("private_key_block", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")),
    ("openai_key", re.compile(r"\bsk-[A-Za-z0-9_-]{20,}\b")),
    ("github_token", re.compile(r"\bgh[pousr]_[A-Za-z0-9_]{30,}\b")),
    ("aws_access_key", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("jwt_like_token", re.compile(r"\beyJ[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{20,}\.")),
)


@dataclass(frozen=True, slots=True)
class SecurityFinding:
    file: str
    line: int
    kind: str


def main() -> int:
    root = Path.cwd()
    findings = scan_tree(root)
    print(
        json.dumps(
            {
                "ok": not findings,
                "finding_count": len(findings),
                "findings": [
                    {"file": finding.file, "line": finding.line, "kind": finding.kind}
                    for finding in findings
                ],
            },
            ensure_ascii=False,
        )
    )
    return 1 if findings else 0


def scan_tree(root: Path) -> tuple[SecurityFinding, ...]:
    findings: list[SecurityFinding] = []
    for path in sorted(root.rglob("*")):
        if not path.is_file() or _should_skip(path, root):
            continue
        findings.extend(_scan_file(path, root))
    return tuple(findings)


def _scan_file(path: Path, root: Path) -> tuple[SecurityFinding, ...]:
    try:
        text = path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return ()
    findings: list[SecurityFinding] = []
    relative = path.relative_to(root).as_posix()
    for line_number, line in enumerate(text.splitlines(), start=1):
        for kind, pattern in _PATTERNS:
            match = pattern.search(line)
            if match is None or match.group(0) in _ALLOWLIST:
                continue
            findings.append(SecurityFinding(file=relative, line=line_number, kind=kind))
    return tuple(findings)


def _should_skip(path: Path, root: Path) -> bool:
    relative_parts = path.relative_to(root).parts
    if any(part in _SKIP_DIRS for part in relative_parts):
        return True
    if path.name in _SKIP_FILES:
        return True
    if path.suffix.lower() in _TEXT_SUFFIXES:
        return False
    return path.name not in {"Dockerfile", "Makefile"}


if __name__ == "__main__":
    sys.exit(main())
