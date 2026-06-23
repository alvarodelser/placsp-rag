from placsp.atom_parser import parse_feed
from placsp.codice_extractor import extract
from placsp.models import RawEntry, ProcurementRecord
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

def test_date_fields_normalized_to_rfc3339():
    rec = ProcurementRecord(syndication_id="1", category="placsp_mayores",
                            updated="2026-06-19T21:50:27+02:00")
    rec.submission_deadline = "1908-10-30Z"        # date-only with a stray trailing Z
    rec.publication_date = "2020-05-01"            # clean date-only
    rec.award_date = "2020-05-01T09:30:00Z"        # already a full timestamp
    _, props = render(rec)
    assert props["submission_deadline"] == "1908-10-30T00:00:00Z"
    assert props["publication_date"] == "2020-05-01T00:00:00Z"
    assert props["award_date"] == "2020-05-01T09:30:00Z"
    # full timestamps with an offset (e.g. updated) must be left untouched
    assert props["updated"] == "2026-06-19T21:50:27+02:00"

def test_unparseable_date_is_dropped():
    rec = ProcurementRecord(syndication_id="1", category="placsp_mayores", updated="2026-06-19")
    rec.submission_deadline = "no-es-fecha"
    _, props = render(rec)
    assert "submission_deadline" not in props
