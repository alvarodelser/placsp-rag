"""Pure builders for Weaviate Aggregate GraphQL (stdlib only, no FastAPI/httpx).

Mirrors filters.py: produces GraphQL *field* strings that the endpoint wraps in a
single { Aggregate { ... } } request using aliases, so total/nuts/month counts come
back in one round-trip. Kept dependency-free for unit testing without Weaviate.
"""
import filters as filt


def _args(where, extra=None):
    parts = []
    if where is not None:
        parts.append(filt.where_to_gql(where))  # "where: {...}"
    if extra:
        parts.append(extra)
    return f"({', '.join(parts)})" if parts else ""


def agg_total(class_name: str, where: dict | None) -> str:
    return f"total: {class_name}{_args(where)} {{ meta {{ count }} }}"


def agg_groupby(class_name: str, where: dict | None, prop: str) -> str:
    extra = f'groupBy: ["{prop}"]'
    return (f"nuts: {class_name}{_args(where, extra)} "
            "{ groupedBy { value } meta { count } }")


def wrap_aggregate(fields: list[str]) -> str:
    return "{ Aggregate { " + " ".join(fields) + " } }"
