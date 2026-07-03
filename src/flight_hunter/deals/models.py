from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True, slots=True)
class SearxngSearchResult:
    title: str
    url: str
    content: str
    engine: str | None = None
    published_date: str | None = None


@dataclass(frozen=True, slots=True)
class SearxngSearchResponse:
    query: str
    received_at: datetime
    results: tuple[SearxngSearchResult, ...]


@dataclass(frozen=True, slots=True)
class DealPageMarkdown:
    url: str
    title: str
    markdown: str
    fetched_at: datetime
