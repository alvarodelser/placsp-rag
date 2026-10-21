"""ZIP archive -> versions/<table>/<zip>.parquet, one row per published entry version.

Each archive is a unit of work: its tables are written under temporary names and renamed when
all are complete, then versions/_done/<zip>.json records it. A rerun skips archives already
done (same byte size), so an interrupted extract resumes where it stopped.
"""
import glob
import json
import os
import time
import zipfile
from concurrent.futures import ProcessPoolExecutor, as_completed

import pyarrow as pa
import pyarrow.parquet as pq
import structlog

from placsp.staging import codice
from placsp.staging.tables import SCHEMAS

log = structlog.get_logger(service="placsp")

FLUSH_ENTRIES = 20_000


def _done_path(data_dir: str, zip_name: str) -> str:
    return os.path.join(data_dir, "versions", "_done", zip_name + ".json")


def is_done(data_dir: str, zip_file: str) -> bool:
    p = _done_path(data_dir, os.path.basename(zip_file))
    if not os.path.exists(p):
        return False
    with open(p) as f:
        return json.load(f).get("zip_bytes") == os.path.getsize(zip_file)


class _Writers:
    def __init__(self, data_dir: str, zip_name: str):
        self.final = {t: os.path.join(data_dir, "versions", t, zip_name.replace(".zip", ".parquet")) for t in SCHEMAS}
        self.tmp = {t: p + ".tmp" for t, p in self.final.items()}
        self.w = {}
        self.rows = {t: 0 for t in SCHEMAS}

    def write(self, buf: dict):
        for t, rows in buf.items():
            if not rows:
                continue
            if t not in self.w:
                os.makedirs(os.path.dirname(self.tmp[t]), exist_ok=True)
                self.w[t] = pq.ParquetWriter(self.tmp[t], SCHEMAS[t], compression="zstd")
            self.w[t].write_table(pa.Table.from_pylist(rows, schema=SCHEMAS[t]))
            self.rows[t] += len(rows)
            rows.clear()

    def close(self):
        for t in SCHEMAS:
            if t not in self.w:     # an empty table still gets its file, so every zip has all tables
                os.makedirs(os.path.dirname(self.tmp[t]), exist_ok=True)
                pq.write_table(SCHEMAS[t].empty_table(), self.tmp[t], compression="zstd")
            else:
                self.w[t].close()
        for t in SCHEMAS:
            os.replace(self.tmp[t], self.final[t])


def extract_zip(data_dir: str, zip_file: str, channel: str) -> dict:
    t0 = time.time()
    zip_name = os.path.basename(zip_file)
    w = _Writers(data_dir, zip_name)
    buf = codice.empty()
    entries = tombs = 0
    with zipfile.ZipFile(zip_file) as zf:
        for member in sorted(n for n in zf.namelist() if n.endswith(".atom")):
            with zf.open(member) as fh:
                for pos, (kind, el) in enumerate(codice.iter_feed(fh)):
                    if kind == "tombstone":
                        buf["tombstone"].append(codice.tombstone(el, channel, zip_name, member))
                        tombs += 1
                        continue
                    codice.flatten(el, f"{zip_name}/{member}#{pos}", channel, zip_name, member, buf)
                    entries += 1
                    if entries % FLUSH_ENTRIES == 0:
                        w.write(buf)
    w.write(buf)
    w.close()
    stats = {"zip": zip_name, "channel": channel, "zip_bytes": os.path.getsize(zip_file), "entries": entries,
             "tombstones": tombs, "rows": w.rows, "seconds": round(time.time() - t0, 1)}
    os.makedirs(os.path.dirname(_done_path(data_dir, zip_name)), exist_ok=True)
    with open(_done_path(data_dir, zip_name), "w") as f:
        json.dump(stats, f, indent=1)
    return stats


def pending(data_dir: str) -> list[tuple[str, str]]:
    """(zip file, channel) for every downloaded archive not yet extracted."""
    out = []
    for z in sorted(glob.glob(os.path.join(data_dir, "zips", "*", "*.zip"))):
        if not is_done(data_dir, z):
            out.append((z, os.path.basename(os.path.dirname(z))))
    return out


def extract_all(data_dir: str, workers: int = 1) -> list[dict]:
    todo = pending(data_dir)
    log.info("extract_start", archives=len(todo), workers=workers)
    out = []
    with ProcessPoolExecutor(max(1, workers)) as pool:
        futs = {pool.submit(extract_zip, data_dir, z, ch): z for z, ch in todo}
        for f in as_completed(futs):
            try:
                s = f.result()
                out.append(s)
                log.info("extracted", zip=s["zip"], entries=s["entries"], seconds=s["seconds"])
            except Exception as exc:  # noqa: BLE001  one bad archive must not stop the others
                log.error("extract_failed", zip=os.path.basename(futs[f]), error=str(exc))
    return out
