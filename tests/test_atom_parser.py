from placsp.atom_parser import parse_feed
from placsp.models import RawEntry, Tombstone

def test_parses_entries_with_syndication_id():
    items = list(parse_feed("tests/fixtures/mayores.atom", "placsp_mayores"))
    entries = [i for i in items if isinstance(i, RawEntry)]
    assert len(entries) == 6
    e = entries[0]
    assert e.syndication_id.isdigit()
    assert e.category == "placsp_mayores"
    assert e.updated and e.cfs is not None

def test_parses_tombstones_from_externos():
    items = list(parse_feed("tests/fixtures/externos.atom", "externos_mayores"))
    tombs = [i for i in items if isinstance(i, Tombstone)]
    assert len(tombs) == 1
    assert tombs[0].syndication_id.isdigit()
    assert tombs[0].reason  # e.g. CERRADA
