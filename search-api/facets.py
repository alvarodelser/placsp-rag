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


def agg_total(class_name: str, where: dict | None, alias: str = "total") -> str:
    return f"{alias}: {class_name}{_args(where)} {{ meta {{ count }} }}"


def agg_groupby(class_name: str, where: dict | None, prop: str) -> str:
    extra = f'groupBy: ["{prop}"]'
    return (f"nuts: {class_name}{_args(where, extra)} "
            "{ groupedBy { value } meta { count } }")


def agg_groupby_field(class_name: str, where: dict | None, prop: str, alias: str) -> str:
    """Generic group-by aggregate for any single-value field, returned under `alias`."""
    extra = f'groupBy: ["{prop}"]'
    return (f"{alias}: {class_name}{_args(where, extra)} "
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


import math
B_MIN = 1000
B_MAX = 100000000
B_LMIN = math.log(B_MIN)
B_LSPAN = math.log(B_MAX) - B_LMIN

def budget_buckets(num=15):
    buckets = []
    for i in range(num):
        t1 = i / num
        t2 = (i + 1) / num
        min_v = math.exp(B_LMIN + t1 * B_LSPAN)
        max_v = math.exp(B_LMIN + t2 * B_LSPAN)
        if i == 0: min_v = 0
        if i == num - 1: max_v = None
        buckets.append({"min": min_v, "max": max_v})
    return buckets


def parse_aggregate(
    res: dict,
    pub_buckets: list[dict],
    plazo_buckets: list[dict],
    budg_buckets: list[dict] = None,
    extra_groupby: list[str] = None
) -> dict:
    """Parse Weaviate Aggregate response.

    extra_groupby: list of alias strings for additional group-by fields
    (e.g. ['status', 'result', 'contract_type', 'procedure']), each mapped
    from its corresponding alias in the Aggregate block.
    """
    agg = ((res.get("data") or {}).get("Aggregate") or {})
    extra_groupby = extra_groupby or []

    def _count(alias):
        node = agg.get(alias) or []
        return (node[0].get("meta", {}).get("count", 0)) if node else 0

    def _groupby_counts(alias):
        out = {}
        for g in (agg.get(alias) or []):
            val = (g.get("groupedBy") or {}).get("value")
            if val:
                out[val] = g.get("meta", {}).get("count", 0)
        return out

    nuts = _groupby_counts("nuts")

    def _series(buckets, prefix):
        return [{"month": b.get("month"), "min": b.get("min"), "max": b.get("max"), "count": _count(f"{prefix}{i}")}
                for i, b in enumerate(buckets)]

    result = {
        "total": _count("total"),
        "totals": {
            "cpv": _count("t_cpv"),
            "nuts": _count("t_nuts"),
            "status": _count("t_status"),
            "result": _count("t_result"),
            "contract_type": _count("t_contract_type"),
            "procedure": _count("t_procedure"),
            "dates": _count("t_dates"),
            "budget": _count("t_budget"),
        },
        "nuts": nuts,
        "dates": {
            "publication": _series(pub_buckets, "m_") if pub_buckets else [],
            "plazo": _series(plazo_buckets, "p_") if plazo_buckets else [],
        },
        "budget": _series(budg_buckets, "b") if budg_buckets else [],
    }
    for alias in extra_groupby:
        result[alias] = _groupby_counts(alias)
    return result


def agg_month_counts(class_name, base_where, date_field, buckets, prefix="m"):
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
            f"{prefix}{i}: {class_name}({filt.where_to_gql(combined)}) {{ meta {{ count }} }}")
    return fields

def agg_budget_counts(class_name, base_where, buckets):
    fields = []
    for i, b in enumerate(buckets):
        rng = filt.build_where(**{
            "budget_min": b["min"], "budget_max": b["max"],
        })
        combined = rng if base_where is None else {
            "operator": "And", "operands": [base_where, rng]}
        fields.append(
            f"b{i}: {class_name}({filt.where_to_gql(combined)}) {{ meta {{ count }} }}")
    return fields
