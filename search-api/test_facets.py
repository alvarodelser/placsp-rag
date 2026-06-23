# search-api/test_facets.py
import facets as fac
import filters as filt


def test_agg_total_no_where():
    s = fac.agg_total("Placsp_licitaciones", None)
    assert s == "total: Placsp_licitaciones { meta { count } }"


def test_agg_total_with_where():
    where = filt.build_where(status=["PUB"])
    s = fac.agg_total("Placsp_licitaciones", where)
    assert s.startswith("total: Placsp_licitaciones(where: { path: [\"status_code\"]")
    assert s.endswith("{ meta { count } }")


def test_agg_groupby_nuts():
    s = fac.agg_groupby("Placsp_licitaciones", None, "nuts")
    assert s == ('nuts: Placsp_licitaciones(groupBy: ["nuts"]) '
                 "{ groupedBy { value } meta { count } }")


def test_agg_groupby_with_where_combines_args():
    where = filt.build_where(cpv=["45"])
    s = fac.agg_groupby("Placsp_licitaciones", where, "nuts")
    assert s.startswith('nuts: Placsp_licitaciones(where: { path: ["cpv"]')
    assert 'groupBy: ["nuts"]' in s


def test_wrap_aggregate():
    s = fac.wrap_aggregate(["total: X { meta { count } }"])
    assert s == "{ Aggregate { total: X { meta { count } } } }"


from datetime import date


def test_month_buckets_default_trailing_window():
    b = fac.month_buckets(None, None, cap=3, today=date(2026, 6, 15))
    assert [x["month"] for x in b] == ["2026-04", "2026-05", "2026-06"]
    assert b[0]["start"] == "2026-04-01"
    assert b[0]["end"] == "2026-04-30"
    assert b[2]["end"] == "2026-06-30"


def test_month_buckets_explicit_range_capped():
    b = fac.month_buckets("2020-01-01", "2026-06-30", cap=4, today=date(2026, 6, 15))
    assert len(b) == 4               # capped to most recent 4
    assert b[-1]["month"] == "2026-06"


def test_agg_month_counts_aliases_and_date_field():
    buckets = fac.month_buckets(None, None, cap=2, today=date(2026, 6, 15))
    fields = fac.agg_month_counts("Placsp_licitaciones", None, "publication_date", buckets)
    assert len(fields) == 2
    assert fields[0].startswith("m0: Placsp_licitaciones(where: {")
    assert "publication_date" in fields[0]
    assert "2026-05-01T00:00:00Z" in fields[0]
    assert "2026-05-31T23:59:59Z" in fields[0]
    assert fields[0].endswith("{ meta { count } }")
