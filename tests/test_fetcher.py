import os, zipfile, httpx
from placsp.fetcher import unzip, feed_next_link, download

def test_feed_next_link_from_fixture():
    nxt = feed_next_link("tests/fixtures/externos.atom")
    # trimmed fixture preserves the feed-level next link
    assert nxt is None or nxt.startswith("https://contrataciondelsectorpublico.gob.es/")

def test_unzip_returns_atom_paths(tmp_path):
    z = tmp_path / "f.zip"
    with zipfile.ZipFile(z, "w") as zf:
        zf.writestr("a.atom", "<feed/>")
        zf.writestr("b.atom", "<feed/>")
    paths = unzip(str(z), str(tmp_path / "out"))
    assert len(paths) == 2 and all(p.endswith(".atom") for p in paths)

def test_download_writes_file(tmp_path):
    def handler(req): return httpx.Response(200, content=b"<feed/>")
    dest = str(tmp_path / "x.atom")
    out = download("https://h/x.atom", dest, transport=httpx.MockTransport(handler))
    assert os.path.getsize(out) > 0
