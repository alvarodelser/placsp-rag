from placsp.atom_parser import parse_feed
from placsp.codice_extractor import extract
from placsp.models import RawEntry
from placsp.renderer import render

def _rec(path, cat):
    for it in parse_feed(path, cat):
        if isinstance(it, RawEntry):
            return extract(it, None)

def test_summary_is_spanish_prose_with_key_facts():
    rec = _rec("tests/fixtures/mayores.atom", "placsp_mayores")
    text, props = render(rec)
    assert isinstance(text, str) and len(text) > 20
    assert rec.title.split()[0] in text
    assert props["content"] == text
    assert props["syndication_id"] == rec.syndication_id
    assert props["category"] == "placsp_mayores"

def test_properties_omit_empty_and_serialize_lists():
    rec = _rec("tests/fixtures/menores.atom", "placsp_menores")
    text, props = render(rec)
    assert "status_history" in props and isinstance(props["status_history"], list)
    assert props["status_history"][0]["code"] == rec.status_code
    # None scalars omitted
    assert all(v is not None for v in props.values())
