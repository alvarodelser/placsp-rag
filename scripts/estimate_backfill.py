"""Estimate a full backfill before running it: archive sizes, tenders, and time per step.

Sizes come from PLACSP (the ETag of each archive carries its size; nothing is downloaded), the
embedding rate is measured against the vectorizer, and the other rates were measured on the
sample archives (docs/STAGING_REPORT.md):

  python scripts/estimate_backfill.py [--vectorizer http://localhost:8089] [--mbps 1] [--workers 2]
"""
import argparse, os, sys, time
from concurrent.futures import ThreadPoolExecutor

import httpx

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))
from placsp.staging.sources import archives, zip_path   # noqa: E402

# Measured on the 2013-2026 samples: entries per MB of ZIP, share of entries that are distinct
# tenders within an archive, and extraction seconds per MB on one core.
RATES = {"placsp_mayores": (400, 0.47, 0.35), "externos_mayores": (2700, 0.33, 0.75),
         "placsp_menores": (2000, 0.97, 0.80), "propios": (2000, 0.96, 0.40)}
LOAD_PER_S = 3000          # loader without embedding (mocked stores)
BUILD_S_PER_M = 7          # build seconds per million tenders (0.9 M -> 6 s)


def size(client, a, data_dir) -> tuple[int | None, bool]:
    local = zip_path(data_dir, a)
    if os.path.exists(local):
        return os.path.getsize(local), True
    try:
        with client.stream("GET", a.url) as r:
            if r.status_code != 200:
                return None, False
            if r.headers.get("content-length"):
                return int(r.headers["content-length"]), False
            etag = (r.headers.get("etag") or "").strip('W/"')
            return int(etag.split("-")[0], 16), False      # Apache: "<size hex>-<mtime hex>"
    except (httpx.HTTPError, ValueError):
        return None, False


def embed_rate(url: str, n: int = 480) -> float | None:
    text = ("Contrato de Servicios: Servicio de limpieza de edificios municipales {i}. Órgano de contratación: "
            "Alcaldía del Ayuntamiento de Ejemplo. Importes: presupuesto base 120.000,00 EUR. CPV: 90910000. "
            "Procedimiento: Abierto. Estado: Resuelta. Adjudicatario: Limpiezas Ejemplo SL. Lugar de ejecución: Madrid.")
    try:
        with httpx.Client(timeout=600) as c:
            c.post(url.rstrip("/") + "/embed", json={"texts": ["calentamiento"], "normalize": True}).raise_for_status()
            t0 = time.time()
            for i in range(0, n, 48):
                c.post(url.rstrip("/") + "/embed", json={"texts": [text.format(i=j) for j in range(i, i + 48)],
                                                         "normalize": True}).raise_for_status()
            return n / (time.time() - t0)
    except httpx.HTTPError as exc:
        print(f"vectorizer not reachable ({exc}); pass --embed-rate")
        return None


def hours(s: float) -> str:
    return f"{s / 3600:.1f} h" if s >= 3600 else f"{s / 60:.0f} min"


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default=os.getenv("PLACSP_DATA_DIR", "./data"))
    ap.add_argument("--vectorizer", default=os.getenv("VECTORIZER_URL", "http://localhost:8089"))
    ap.add_argument("--embed-rate", type=float, help="texts per second, instead of measuring it")
    ap.add_argument("--embed-workers", type=int, default=int(os.getenv("PLACSP_EMBED_WORKERS", "2")))
    ap.add_argument("--mbps", type=float, default=1.0, help="download speed in MB/s (we saw 0.6-15)")
    ap.add_argument("--workers", type=int, default=int(os.getenv("PLACSP_EXTRACT_WORKERS", "2")))
    a = ap.parse_args()

    todo = archives()
    with httpx.Client(timeout=300, verify=False, follow_redirects=True, headers={"User-Agent": "placsp-ingest"}) as c, \
            ThreadPoolExecutor(4) as pool:
        sizes = list(pool.map(lambda x: size(c, x, a.data), todo))
    per = {}
    unknown = []
    for arc, (b, have) in zip(todo, sizes):
        if b is None:
            unknown.append(arc.name)
            continue
        p = per.setdefault(arc.channel, {"archives": 0, "mb": 0.0, "missing_mb": 0.0})
        p["archives"] += 1
        p["mb"] += b / 2**20
        p["missing_mb"] += 0 if have else b / 2**20
    print(f"{'channel':18} {'archives':>8} {'GB':>7} {'to fetch':>9} {'entries':>11} {'tenders~':>10}")
    tot = {"mb": 0, "missing": 0, "entries": 0, "tenders": 0, "extract_s": 0}
    for ch, p in per.items():
        epm, distinct, spm = RATES[ch]
        entries = p["mb"] * epm
        tenders = entries * distinct
        tot["mb"] += p["mb"]; tot["missing"] += p["missing_mb"]; tot["entries"] += entries
        tot["tenders"] += tenders; tot["extract_s"] += p["mb"] * spm
        print(f"{ch:18} {p['archives']:>8} {p['mb'] / 1024:>7.1f} {p['missing_mb'] / 1024:>8.1f}G {entries:>11,.0f} {tenders:>10,.0f}")
    if unknown:
        print(f"size unknown (not counted): {len(unknown)} — {', '.join(unknown[:6])}")
    rate = a.embed_rate or embed_rate(a.vectorizer)
    print(f"\ntotal {tot['mb'] / 1024:.1f} GB, about {tot['entries'] / 1e6:.1f} M entry versions, "
          f"{tot['tenders'] / 1e6:.1f} M tenders (fewer: a tender in two archives counts once)")
    print(f"disk: zips {tot['mb'] / 1024:.0f} GB + versions ~{0.55 * tot['mb'] / 1024:.0f} GB "
          f"+ current ~{0.3 * tot['mb'] / 1024:.0f} GB")
    print(f"\ndownload  {hours(tot['missing'] / a.mbps)}   at {a.mbps} MB/s")
    print(f"extract   {hours(tot['extract_s'] / a.workers)}   with {a.workers} workers")
    print(f"build     {hours(tot['tenders'] / 1e6 * BUILD_S_PER_M)}   (per run; daily too)")
    if rate:
        eff = min(rate * a.embed_workers * 0.9, LOAD_PER_S)   # in-flight requests overlap, roughly
        print(f"load      {hours(tot['tenders'] / eff)}   embedding measured at {rate:.0f} texts/s per request stream, "
              f"{a.embed_workers} in flight (Neo4j writes not included)")
