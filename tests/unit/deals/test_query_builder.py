from __future__ import annotations

from flight_hunter.deals.query_builder import DealQueryBuilder
from flight_hunter.domain.offers import SearchIntent


def test_deal_query_builder_uses_route_and_month_without_duplicates() -> None:
    intent = SearchIntent(
        origin="mow",
        destination="ist",
        departure_date="2026-09-10",
        return_date="2026-09-20",
        passengers=1,
        currency="rub",
    )
    query = DealQueryBuilder().build(intent)

    assert "MOW" in query
    assert "IST" in query
    assert "акция" in query
    assert query.count("2026-09") == 1


def test_deal_query_builder_returns_bounded_multi_query_strategy() -> None:
    intent = SearchIntent(
        origin="MOW",
        destination="IST",
        departure_date="2026-09-10",
        return_date="2026-10-20",
        passengers=1,
        currency="RUB",
    )

    queries = DealQueryBuilder().build_queries(intent, max_queries=2)

    assert len(queries) == 2
    assert queries[0].startswith("авиабилеты MOW IST")
    assert "2026-09" in queries[0]
    assert "2026-10" in queries[0]
    assert "промокод" in queries[1]
    assert all("MOW" in query and "IST" in query for query in queries)
