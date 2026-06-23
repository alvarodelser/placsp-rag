import filters as f


def test_build_where_none_when_empty():
    assert f.build_where() is None


def test_build_where_single_cpv_prefix():
    w = f.build_where(cpv=["45"])
    assert w == {"path": ["cpv"], "operator": "Like", "valueText": "45*"}


def test_build_where_multi_cpv_is_or():
    w = f.build_where(cpv=["45", "72"])
    assert w["operator"] == "Or"
    assert {"path": ["cpv"], "operator": "Like", "valueText": "45*"} in w["operands"]
    assert {"path": ["cpv"], "operator": "Like", "valueText": "72*"} in w["operands"]


def test_build_where_status_exact():
    w = f.build_where(status=["PUB"])
    assert w == {"path": ["status_code"], "operator": "Equal", "valueText": "PUB"}


def test_build_where_date_range_rfc3339():
    w = f.build_where(pub_from="2026-01-01", pub_to="2026-01-31")
    paths = [o for o in w["operands"]]
    assert w["operator"] == "And"
    assert {"path": ["publication_date"], "operator": "GreaterThanEqual",
            "valueDate": "2026-01-01T00:00:00Z"} in paths
    assert {"path": ["publication_date"], "operator": "LessThanEqual",
            "valueDate": "2026-01-31T23:59:59Z"} in paths


def test_build_where_budget_range():
    w = f.build_where(budget_min=1000, budget_max=5000)
    assert {"path": ["budget_amount"], "operator": "GreaterThanEqual",
            "valueNumber": 1000.0} in w["operands"]


def test_build_where_combines_with_and():
    w = f.build_where(cpv=["45"], status=["PUB"])
    assert w["operator"] == "And"
    assert len(w["operands"]) == 2


def test_where_to_gql_leaf():
    s = f.where_to_gql({"path": ["cpv"], "operator": "Like", "valueText": "45*"})
    assert s == 'where: { path: ["cpv"], operator: Like, valueText: "45*" }'


def test_where_to_gql_nested_enums_unquoted():
    w = {"operator": "And", "operands": [
        {"path": ["cpv"], "operator": "Like", "valueText": "45*"},
        {"path": ["status_code"], "operator": "Equal", "valueText": "PUB"},
    ]}
    s = f.where_to_gql(w)
    assert "operator: And" in s
    assert "operator: Like" in s
    assert '"And"' not in s  # operator enum must not be quoted


def test_build_sort_default_and_allowlist():
    assert f.build_sort(None) == [{"path": ["publication_date"], "order": "desc"}]
    assert f.build_sort("budget_amount asc") == [{"path": ["budget_amount"], "order": "asc"}]
    # unknown field falls back to default
    assert f.build_sort("DROP TABLE desc") == [{"path": ["publication_date"], "order": "desc"}]


def test_sort_to_gql():
    s = f.sort_to_gql([{"path": ["publication_date"], "order": "desc"}])
    assert s == 'sort: [{ path: ["publication_date"], order: desc }]'
