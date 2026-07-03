from __future__ import annotations

from flight_hunter.domain.offers import SearchIntent


class DealQueryBuilder:
    def build(self, intent: SearchIntent) -> str:
        return self.build_queries(intent)[0]

    def build_queries(self, intent: SearchIntent, *, max_queries: int = 3) -> tuple[str, ...]:
        route = _route_terms(intent)
        months = _month_terms(intent)
        query_templates = (
            ("авиабилеты", *route, "акция", "скидка", "распродажа", *months),
            (*route, "авиабилеты", "промокод", "спецпредложение", *months),
            (*route, "дешевые авиабилеты", "ошибка тарифа", "форум", *months),
        )
        queries = tuple(" ".join(dict.fromkeys(parts)) for parts in query_templates)
        return queries[: max(1, max_queries)]


def _route_terms(intent: SearchIntent) -> tuple[str, str]:
    return (intent.origin.upper(), intent.destination.upper())


def _month_terms(intent: SearchIntent) -> tuple[str, ...]:
    parts = [
        intent.departure_date[:7],
    ]
    if intent.return_date is not None:
        parts.append(intent.return_date[:7])
    return tuple(dict.fromkeys(part for part in parts if part))
