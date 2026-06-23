"""Pure filter logic for the PLACSP search API (stdlib only, no FastAPI/httpx).

Translates structured filter params into Weaviate `where` / `sort` objects and
serializes them to GraphQL argument strings. Kept dependency-free so it is
unit-testable without a running Weaviate.
"""
import json

SORT_FIELDS = {
    "publication_date", "submission_deadline", "award_date",
    "budget_amount", "estimated_value",
}
_DEFAULT_SORT = [{"path": ["publication_date"], "order": "desc"}]


def _or(operands: list[dict]) -> dict:
    return operands[0] if len(operands) == 1 else {"operator": "Or", "operands": operands}


def _prefix(prop: str, values: list[str]) -> dict:
    return _or([{"path": [prop], "operator": "Like", "valueText": f"{v}*"} for v in values])


def _equal(prop: str, values: list[str]) -> dict:
    return _or([{"path": [prop], "operator": "Equal", "valueText": v} for v in values])


def _date(prop: str, value: str, op: str, end_of_day: bool) -> dict:
    suffix = "T23:59:59Z" if end_of_day else "T00:00:00Z"
    return {"path": [prop], "operator": op, "valueDate": f"{value}{suffix}"}


def _number(prop: str, value: float, op: str) -> dict:
    return {"path": [prop], "operator": op, "valueNumber": float(value)}


def build_where(*, cpv=None, status=None, result=None, contract_type=None,
                procedure=None, nuts=None, pub_from=None, pub_to=None,
                deadline_from=None, deadline_to=None,
                budget_min=None, budget_max=None) -> dict | None:
    ops: list[dict] = []
    if cpv:
        ops.append(_prefix("cpv", cpv))
    if nuts:
        ops.append(_prefix("nuts", nuts))
    if status:
        ops.append(_equal("status_code", status))
    if result:
        ops.append(_equal("result_code", result))
    if contract_type:
        ops.append(_equal("contract_type_code", contract_type))
    if procedure:
        ops.append(_equal("procedure_code", procedure))
    if pub_from:
        ops.append(_date("publication_date", pub_from, "GreaterThanEqual", False))
    if pub_to:
        ops.append(_date("publication_date", pub_to, "LessThanEqual", True))
    if deadline_from:
        ops.append(_date("submission_deadline", deadline_from, "GreaterThanEqual", False))
    if deadline_to:
        ops.append(_date("submission_deadline", deadline_to, "LessThanEqual", True))
    if budget_min is not None:
        ops.append(_number("budget_amount", budget_min, "GreaterThanEqual"))
    if budget_max is not None:
        ops.append(_number("budget_amount", budget_max, "LessThanEqual"))
    if not ops:
        return None
    return ops[0] if len(ops) == 1 else {"operator": "And", "operands": ops}


def _node_to_gql(node: dict) -> str:
    if "operands" in node:
        inner = ", ".join(_node_to_gql(o) for o in node["operands"])
        return f"{{ operator: {node['operator']}, operands: [{inner}] }}"
    path = json.dumps(node["path"])  # ["cpv"] with double quotes -> valid GraphQL
    parts = [f"path: {path}", f"operator: {node['operator']}"]
    if "valueText" in node:
        parts.append(f"valueText: {json.dumps(node['valueText'])}")
    elif "valueDate" in node:
        parts.append(f"valueDate: {json.dumps(node['valueDate'])}")
    elif "valueNumber" in node:
        parts.append(f"valueNumber: {node['valueNumber']}")
    return "{ " + ", ".join(parts) + " }"


def where_to_gql(where: dict) -> str:
    return f"where: {_node_to_gql(where)}"


def build_sort(sort: str | None) -> list[dict]:
    if not sort:
        return list(_DEFAULT_SORT)
    parts = sort.split()
    field = parts[0] if parts else ""
    order = parts[1].lower() if len(parts) > 1 else "desc"
    if field not in SORT_FIELDS or order not in ("asc", "desc"):
        return list(_DEFAULT_SORT)
    return [{"path": [field], "order": order}]


def sort_to_gql(sort: list[dict]) -> str:
    items = ", ".join(
        f'{{ path: {json.dumps(s["path"])}, order: {s["order"]} }}' for s in sort
    )
    return f"sort: [{items}]"
