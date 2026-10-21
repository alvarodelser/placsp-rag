"""Level 1 into the pilot: a tender read from the staging rows is the record the pilot's own parser
gives for the same feed entry (staging.py), for every fixture channel."""
import re
import sys
from collections import defaultdict
from pathlib import Path

import pytest

from placsp_pilot import staging as ST
from placsp_pilot.codelists import Codelists
from placsp_pilot.codice import Parser, iter_entries

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "src"))
S1 = pytest.importorskip("placsp.staging.codice")     # stage 1's flattener (lxml only)


# Stage 1's tables, as its tables.py declares them (read as text: it imports pyarrow).
TABLES = re.findall(r'^    "(\w+)": \[', (REPO / "src" / "placsp" / "staging" / "tables.py").read_text(), re.M)


def stage_rows(entry, channel):
    buf = defaultdict(list, {t: [] for t in TABLES})
    S1.flatten(entry, "v", channel, "z.zip", "f.atom", buf)
    t = dict(buf["entry"][0])
    return t, {k: [dict(r, entry_id=t["entry_id"]) for r in buf[k]] for k in ST.CHILDREN}


def diff(a, b, path=""):
    if isinstance(a, dict) and isinstance(b, dict):
        return [d for k in set(a) | set(b) for d in diff(a.get(k), b.get(k), f"{path}.{k}")]
    if isinstance(a, list) and isinstance(b, list):
        if len(a) != len(b):
            return [f"{path}: {len(a)} items vs {len(b)}"]
        return [d for i, (x, y) in enumerate(zip(a, b)) for d in diff(x, y, f"{path}[{i}]")]
    if a != b and not (a in (None, [], {}) and b in (None, [], {})):
        return [f"{path}: {a!r} vs {b!r}"]
    return []


@pytest.mark.parametrize("fixture,channel", [("mayores", "placsp_mayores"), ("externos", "externos_mayores"),
                                             ("menores", "placsp_menores"), ("propios", "propios")])
def test_staging_rows_give_the_pilots_record(fixture, channel):
    parser = Parser(Codelists(REPO / "codelists"))
    labels = ST.Labels(REPO / "codelists")
    entries, _ = iter_entries(str(REPO / "tests" / "fixtures" / f"{fixture}.atom"))
    assert entries
    for e in entries:
        mine = parser.parse_entry(e, channel)
        t, rows = stage_rows(e, channel)
        theirs = ST.record(t, rows, labels)
        assert theirs["source"] == "staging"
        # Stage 1 reads more than the pilot's parser did: requirements of kind "general", and the
        # labels of document types (from GeneralContractDocuments). Everything the parser gave is equal.
        theirs["requirements"] = [r for r in theirs["requirements"] if r["group"] != "general"]
        for d in theirs["documents"]:
            d["type_label"] = next((x["type_label"] for x in mine["documents"] if x["url"] == d["url"]), None)
        drop = lambda r: {k: v for k, v in r.items() if k != "source"}
        assert diff(drop(mine), drop(theirs)) == []


def test_pick_and_read_from_current_tables(tmp_path):
    """Staging over parquet files laid out as stage 1's build writes them."""
    import json
    duckdb = pytest.importorskip("duckdb")
    tables = defaultdict(list)
    for fixture, channel in [("mayores", "placsp_mayores"), ("menores", "placsp_menores")]:
        entries, _ = iter_entries(str(REPO / "tests" / "fixtures" / f"{fixture}.atom"))
        for e in entries:
            t, rows = stage_rows(e, channel)
            tables["tender"].append(dict(t, last_updated=t["updated"], removed_reason=None))
            for k, v in rows.items():
                tables[k] += v
    cur = tmp_path / "current"
    cur.mkdir()
    con = duckdb.connect()
    for name, rows in tables.items():
        if not rows:
            continue
        src = tmp_path / f"{name}.jsonl"
        src.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows))
        con.execute(f"COPY (SELECT * FROM read_json_auto('{src}')) TO '{cur / (name + '.parquet')}' (FORMAT parquet)")
    st = ST.Staging(tmp_path, REPO / "codelists")
    mayores = st.pick(50, channels=["placsp_mayores"])
    assert mayores and all(i in {t["entry_id"] for t in tables["tender"] if t["channel"] == "placsp_mayores"} for i in mayores)
    awarded = set(st.pick(50, awarded=True, with_documents=False))
    assert awarded == {w["entry_id"] for w in tables["winner"]}
    rec = st.record(mayores[0])
    assert rec["id"] == mayores[0] and rec["source"] == "staging" and rec["lots"] and rec["documents"]
    assert st.pick(5, channels=["placsp_mayores"], exclude=set(mayores)) == []
