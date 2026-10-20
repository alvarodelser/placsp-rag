"""Theme selection by CPV: a code takes its subtree, minus exclusions; "=" takes the code alone."""
from placsp_pilot.themes import cpv_themes, themes_of


def test_codes_take_their_subtree_less_exclusions():
    assert cpv_themes("71354100") == ["cartografia"]          # cartografía digital, under 71354000
    assert cpv_themes("71351810") == ["cartografia"]          # topográficos, under 71351800
    assert cpv_themes("71354500") == []                       # investigación marítima: excluded
    assert cpv_themes("71421000") == []                       # jardinería paisajística: excluded
    assert cpv_themes("71410000") == ["urbanismo"]


def test_a_root_marked_exact_does_not_take_its_subtree():
    assert cpv_themes("90700000") == ["sostenibilidad"]
    assert cpv_themes("90711500") == ["sostenibilidad"]       # listed through 90710000
    assert cpv_themes("90500000") == [] and cpv_themes("90680000") == []


def test_an_entry_is_themed_by_any_cpv_of_the_tender_or_its_lots():
    rec = {"tender": {"cpv": ["45233252"]}, "lots": [{"cpv": ["71410000"]}, {"cpv": ["38221000"]}]}
    assert themes_of(rec) == ["urbanismo", "cartografia"]
    assert themes_of({"tender": {"cpv": ["66511000"], "name": "Seguro de la Sociedad Urbanística"}}) == []


def test_balanced_pick_fills_the_thinnest_theme_then_the_thinnest_type():
    from collections import Counter
    from placsp_pilot.stages import pick_balanced
    pool = {("urbanismo", "2"): ["u1", "u2", "u3"], ("otros", "1"): ["o1", "o2"], ("otros", "2"): ["s1", "s2"]}
    have_theme = Counter({"otros": 1})
    have_cell = Counter({("otros", "2"): 1})
    got = pick_balanced(pool, have_theme, have_cell, 5)
    assert got == ["u1", "o1", "u2", "o2", "u3"]   # ties go by name
    assert have_theme == Counter({"otros": 3, "urbanismo": 3})
    # a theme with nothing left is passed over
    assert pick_balanced({("cartografia", "2"): [], ("otros", "1"): ["x"]}, Counter(), Counter(), 3) == ["x"]
