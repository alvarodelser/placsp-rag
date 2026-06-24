import facets as fac, filters as filt


def test_full_aggregate_query_is_single_request():
    where = filt.build_where(cpv=["45"], status=["PUB"])
    pub = fac.month_buckets("2026-01-01", "2026-03-31", cap=36)
    fields = [fac.agg_total("C", where), fac.agg_groupby("C", where, "nuts"),
              *fac.agg_month_counts("C", where, "publication_date", pub)]
    gql = fac.wrap_aggregate(fields)
    assert gql.count("{ Aggregate {") == 1
    assert "total:" in gql and "nuts:" in gql and "m0:" in gql
    assert '"And"' not in gql  # enums unquoted
