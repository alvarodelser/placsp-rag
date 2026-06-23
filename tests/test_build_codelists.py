import json
import build_codelists_json as b


def test_gc_to_json_map_reads_fixture():
    m = b.gc_to_json_map("tests/fixtures/ContractCode.gc")
    assert m["1"] == "Suministros"
    assert len(m) >= 3


def test_main_writes_json(tmp_path, monkeypatch):
    monkeypatch.setattr(b, "MAPPING", {"contract_type": "ContractCode.gc"})
    b.main(["--codelists-dir", "tests/fixtures", "--out-dir", str(tmp_path)])
    out = json.loads((tmp_path / "contract_type.json").read_text(encoding="utf-8"))
    assert out["1"] == "Suministros"
