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
