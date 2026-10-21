import os, zipfile
import duckdb, pytest
from placsp.staging import extract, build, load

FIX = "tests/fixtures"
CHANNELS = {"placsp_mayores": "mayores", "externos_mayores": "externos", "placsp_menores": "menores", "propios": "propios"}


@pytest.fixture(scope="session")
def staged(tmp_path_factory):
    """A data dir with the four fixture feeds extracted and built."""
    d = str(tmp_path_factory.mktemp("staged"))
    for ch, f in CHANNELS.items():
        os.makedirs(f"{d}/zips/{ch}")
        with zipfile.ZipFile(f"{d}/zips/{ch}/{f}_2024.zip", "w") as zf:
            zf.write(f"{FIX}/{f}.atom", f"{f}.atom")
    extract.extract_all(d, workers=1)
    build.build(d, FIX)
    return d


def staged_records(data_dir: str) -> dict:
    """{entry_id: (ProcurementRecord, criteria dict or None)} for every staged tender."""
    con = duckdb.connect()
    cur = lambda t: f"read_parquet('{data_dir}/current/{t}.parquet')"
    L = load.Labels(con.execute(f"SELECT list, code, label FROM {cur('codelist')}").fetchall())
    tenders = load.fetch_dicts(con, f"SELECT * FROM {cur('tender')}")
    rows = {t["entry_id"]: {c: [] for c in load.CHILDREN} for t in tenders}
    for c in load.CHILDREN:
        for r in load.fetch_dicts(con, f"SELECT * FROM {cur(c)}"):
            rows[r["entry_id"]][c].append(r)
    return {t["entry_id"]: (load.to_record(t, rows[t["entry_id"]], L), load.to_criteria(t, rows[t["entry_id"]], L))
            for t in tenders}
