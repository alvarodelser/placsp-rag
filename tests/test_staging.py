import datetime, json, os, zipfile
import duckdb, httpx
from placsp.staging import sources, extract, build

FIX = "tests/fixtures"


def _zip(path, members: dict):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with zipfile.ZipFile(path, "w") as zf:
        for name, src in members.items():
            zf.write(src, name) if os.path.exists(str(src)) else zf.writestr(name, src)
    return path


def _feed(*entries, tombs=()):
    ns = ('xmlns="http://www.w3.org/2005/Atom" xmlns:at="http://purl.org/atompub/tombstones/1.0" '
          'xmlns:cbc="urn:dgpe:names:draft:codice:schema:xsd:CommonBasicComponents-2" '
          'xmlns:cac="urn:dgpe:names:draft:codice:schema:xsd:CommonAggregateComponents-2" '
          'xmlns:cpe="urn:dgpe:names:draft:codice-place-ext:schema:xsd:CommonAggregateComponents-2" '
          'xmlns:cbpe="urn:dgpe:names:draft:codice-place-ext:schema:xsd:CommonBasicComponents-2"')
    body = "".join(f'<at:deleted-entry ref="https://x/{i}" when="{w}"><at:comment type="{r}"/></at:deleted-entry>'
                   for i, w, r in tombs)
    for eid, updated, status, winner in entries:
        res = (f"<cac:TenderResult><cbc:ResultCode>8</cbc:ResultCode><cac:WinningParty><cac:PartyIdentification>"
               f"<cbc:ID schemeName=\"NIF\">{winner}</cbc:ID></cac:PartyIdentification><cac:PartyName><cbc:Name>ACME SL"
               f"</cbc:Name></cac:PartyName></cac:WinningParty></cac:TenderResult>") if winner else ""
        body += (f"<entry><id>https://x/{eid}</id><updated>{updated}</updated><cpe:ContractFolderStatus>"
                 f"<cbc:ContractFolderID>EXP-{eid}</cbc:ContractFolderID>"
                 f"<cbpe:ContractFolderStatusCode>{status}</cbpe:ContractFolderStatusCode>"
                 f"<cac:ProcurementProject><cbc:Name>Obra {eid}</cbc:Name></cac:ProcurementProject>{res}"
                 f"</cpe:ContractFolderStatus></entry>")
    return f'<?xml version="1.0" encoding="UTF-8"?><feed {ns}>{body}</feed>'


def test_archives_years_then_finished_months():
    a = sources.archives(["propios"], today=datetime.date(2026, 10, 21))
    assert [x.period for x in a][:4] == ["2022", "2023", "2024", "2025"]
    assert [x.period for x in a][4:] == [f"2026{m:02d}" for m in range(1, 10)]   # October is still in progress
    assert a[-1].url.endswith("/sindicacion_1383/EMP_SectorPublico_202609.zip")


def test_download_streams_to_part_then_renames(tmp_path):
    calls = []
    def handler(req):
        calls.append(str(req.url))
        return httpx.Response(200, content=b"PK-zipbytes", headers={"etag": '"abc"'})
    a = sources.Archive("propios", "2023", "https://h/sindicacion_1383/EMP_SectorPublico_2023.zip")
    stats = sources.download_missing(str(tmp_path), [a], transport=httpx.MockTransport(handler))
    dest = sources.zip_path(str(tmp_path), a)
    assert stats == {"downloaded": 1, "already_there": 0, "failed": 0}
    assert open(dest, "rb").read() == b"PK-zipbytes" and not os.path.exists(dest + ".part")
    assert json.load(open(dest + ".json"))["etag"] == '"abc"'
    assert sources.download_missing(str(tmp_path), [a], transport=httpx.MockTransport(handler))["already_there"] == 1
    assert len(calls) == 1


def test_extract_every_fixture_channel_and_skip_when_done(tmp_path):
    d = str(tmp_path)
    for ch, f in [("placsp_mayores", "mayores"), ("externos_mayores", "externos"),
                  ("placsp_menores", "menores"), ("propios", "propios")]:
        _zip(f"{d}/zips/{ch}/{f}_2024.zip", {f"{f}.atom": f"{FIX}/{f}.atom"})
    done = extract.extract_all(d, workers=1)
    assert sorted(s["entries"] for s in done) == [6, 6, 6, 6]
    assert extract.pending(d) == []
    con = duckdb.connect()
    n = con.execute(f"SELECT count(*) FROM read_parquet('{d}/versions/entry/*.parquet')").fetchone()[0]
    assert n == 24
    # mayores carries per-lot terms: criteria and lots must come through
    crit = con.execute(f"SELECT count(*) FROM read_parquet('{d}/versions/criterion/mayores_2024.parquet')").fetchone()[0]
    lots = con.execute(f"SELECT count(*) FROM read_parquet('{d}/versions/lot/mayores_2024.parquet')").fetchone()[0]
    assert crit > 0 and lots > 0


def test_build_merges_versions_across_archives(tmp_path):
    d = str(tmp_path)
    _zip(f"{d}/zips/placsp_mayores/m_2019.zip",
         {"a.atom": _feed(("1", "2019-11-03T10:00:00+01:00", "PUB", None), ("2", "2019-05-01T10:00:00+01:00", "PUB", None))})
    _zip(f"{d}/zips/placsp_mayores/m_2020.zip",
         {"a.atom": _feed(("1", "2020-02-14T10:00:00+01:00", "ADJ", "B-123.456"),
                          tombs=[("2", "2020-03-01T10:00:00+01:00", "CERRADA")])})
    extract.extract_all(d, workers=1)
    counts = build.build(d, FIX)
    assert counts["tender"] == 2
    con = duckdb.connect()
    t = dict(con.execute(f"SELECT entry_id, status_code FROM read_parquet('{d}/current/tender.parquet')").fetchall())
    assert t == {"1": "ADJ", "2": "PUB"}                     # a closed tender is kept
    hist = con.execute(f"SELECT status_code FROM read_parquet('{d}/current/status_history.parquet') "
                       "WHERE entry_id='1' ORDER BY first_seen").fetchall()
    assert [h[0] for h in hist] == ["PUB", "ADJ"]           # history spans both archives
    gone = con.execute(f"SELECT removed_reason FROM read_parquet('{d}/current/tender.parquet') WHERE entry_id='2'").fetchone()
    assert gone == ("CERRADA",)
    assert con.execute(f"SELECT nif_norm FROM read_parquet('{d}/current/company.parquet')").fetchall() == [("B123456",)]


class _FakeWeaviate:
    """Records batch writes."""
    def __init__(self):
        self.objects = {}

    def __call__(self, req):
        if req.url.path.endswith("/v1/batch/objects"):
            objs = json.loads(req.content)["objects"]
            for o in objs:
                self.objects[o["id"]] = o
            return httpx.Response(200, json=[{"id": o["id"], "result": {"status": "SUCCESS"}} for o in objs])
        return httpx.Response(404)


def _loader(d, wv):
    from placsp.ai.embedder import Embedder
    from placsp.storage.upserter import Upserter
    from placsp.staging.load import Loader
    emb = Embedder("http://v", transport=httpx.MockTransport(
        lambda r: httpx.Response(200, json={"embeddings": [[0.1] * 4 for _ in json.loads(r.content)["texts"]]})), workers=2)
    up = Upserter("http://w", "", "Placsp_licitaciones", transport=httpx.MockTransport(wv))
    return Loader(d, emb, up, chunk=5)


def test_load_writes_records_and_criteria_then_only_changes(staged, tmp_path):
    import shutil
    from placsp.staging.load import criteria_uuid
    from placsp.storage.upserter import object_uuid
    d = str(tmp_path / "d")
    shutil.copytree(staged, d)
    sid = duckdb.sql(f"SELECT entry_id FROM read_parquet('{d}/current/criterion.parquet') LIMIT 1").fetchone()[0]
    wv = _FakeWeaviate()
    stats = _loader(d, wv).load()
    n = duckdb.sql(f"SELECT count(*) FROM read_parquet('{d}/current/tender.parquet')").fetchone()[0]
    assert stats["tenders"] == n and stats["failed_chunks"] == 0
    lic = [o for o in wv.objects.values() if o["class"] == "Placsp_licitaciones"]
    crit = {o["id"]: o for o in wv.objects.values() if o["class"] == "Placsp_pliego_criteria"}
    assert len(lic) == n and all(o["vector"] == [0.1] * 4 for o in lic)
    rec = wv.objects[object_uuid(sid)]["properties"]
    assert rec["syndication_id"] == sid and rec["content"].startswith("Contrato")
    c = json.loads(crit[criteria_uuid(sid)]["properties"]["criteria_json"])
    assert c["criterios_adjudicacion"] and c["fuente"] == "feed"
    wv.objects.clear()
    assert _loader(d, wv).load()["tenders"] == 0                 # nothing changed: nothing reloaded
    assert wv.objects == {}


def test_live_saves_pages_until_watermark(tmp_path):
    from placsp.staging import live
    d = str(tmp_path)
    os.makedirs(f"{d}/current")
    import pyarrow as pa, pyarrow.parquet as pq
    pq.write_table(pa.table({"channel": ["propios"], "last_updated": pa.array(
        [datetime.datetime(2026, 10, 1, tzinfo=datetime.timezone.utc)])}), f"{d}/current/tender.parquet")
    pages = {"EMP_SectorPublico.atom": (_feed(("9", "2026-10-20T10:00:00+02:00", "PUB", None)), "p2.atom"),
             "p2.atom": (_feed(("8", "2026-10-05T10:00:00+02:00", "PUB", None)), "p3.atom"),
             "p3.atom": (_feed(("7", "2026-09-20T10:00:00+02:00", "PUB", None)), "p4.atom"),
             "p4.atom": (_feed(("6", "2026-09-01T10:00:00+02:00", "PUB", None)), None)}
    seen = []
    def handler(req):
        name = req.url.path.rsplit("/", 1)[-1]
        seen.append(name)
        body, nxt = pages[name]
        link = f'<link rel="next" href="https://contrataciondelestado.es/sindicacion/sindicacion_1383/{nxt}"/>' if nxt else ""
        return httpx.Response(200, content=body.replace("<entry>", link + "<entry>", 1).encode())
    out = live.fetch_live(d, ["propios"], transport=httpx.MockTransport(handler),
                          now=datetime.datetime(2026, 10, 21, tzinfo=datetime.timezone.utc))
    assert out == {"propios": 3} and seen == ["EMP_SectorPublico.atom", "p2.atom", "p3.atom"]   # p3 is older: stop
    z = f"{d}/zips/propios/live_20261021T000000.zip"
    assert zipfile.ZipFile(z).namelist() == ["page_0000.atom", "page_0001.atom", "page_0002.atom"]
    assert extract.pending(d) == [(z, "propios")]
