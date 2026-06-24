"""Pure builders for Weaviate Aggregate GraphQL (stdlib only, no FastAPI/httpx).

Mirrors filters.py: produces GraphQL *field* strings that the endpoint wraps in a
single { Aggregate { ... } } request using aliases, so total/nuts/month counts come
back in one round-trip. Kept dependency-free for unit testing without Weaviate.
"""
from calendar import monthrange
from datetime import date

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


def _month_iter(start: date, end: date):
    y, m = start.year, start.month
    while (y, m) <= (end.year, end.month):
        yield y, m
        m = 1 if m == 12 else m + 1
        y = y + 1 if m == 1 else y


def month_buckets(from_date, to_date, cap: int = 36, today: date | None = None):
    today = today or date.today()
    end = date.fromisoformat(to_date) if to_date else today
    if from_date:
        start = date.fromisoformat(from_date)
    else:
        # trailing `cap` months ending at `end`
        y, m = end.year, end.month
        for _ in range(cap - 1):
            m = 12 if m == 1 else m - 1
            y = y - 1 if m == 12 else y
        start = date(y, m, 1)
    out = []
    for y, m in _month_iter(date(start.year, start.month, 1), end):
        last = monthrange(y, m)[1]
        out.append({
            "month": f"{y:04d}-{m:02d}",
            "start": f"{y:04d}-{m:02d}-01",
            "end": f"{y:04d}-{m:02d}-{last:02d}",
        })
    return out[-cap:]


def parse_aggregate(raw: dict, pub_buckets, plazo_buckets) -> dict:
    agg = ((raw.get("data") or {}).get("Aggregate") or {})

    def _count(alias):
        node = agg.get(alias) or []
        return (node[0].get("meta", {}).get("count", 0)) if node else 0

    nuts = {}
    for g in (agg.get("nuts") or []):
        val = (g.get("groupedBy") or {}).get("value")
        if val:
            nuts[val] = g.get("meta", {}).get("count", 0)

    def _series(buckets, offset):
        return [{"month": b["month"], "count": _count(f"m{offset + i}")}
                for i, b in enumerate(buckets)]

    return {
        "total": _count("total"),
        "nuts": nuts,
        "dates": {
            "publication": _series(pub_buckets, 0),
            "plazo": _series(plazo_buckets, len(pub_buckets)),
        },
    }


def agg_month_counts(class_name, base_where, date_field, buckets):
    fields = []
    for i, b in enumerate(buckets):
        rng = filt.build_where(**{
            "pub_from": b["start"], "pub_to": b["end"],
        }) if date_field == "publication_date" else filt.build_where(**{
            "deadline_from": b["start"], "deadline_to": b["end"],
        })
        combined = rng if base_where is None else {
            "operator": "And", "operands": [base_where, rng]}
        fields.append(
            f"m{i}: {class_name}({filt.where_to_gql(combined)}) {{ meta {{ count }} }}")
    return fields
