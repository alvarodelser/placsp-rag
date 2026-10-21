"""The PLACSP ZIP archives and their download.

Past years are published as one ZIP per year. The current year is published as one ZIP per
finished month (the yearly ZIP of the current year exists too, but it is cumulative and is
regenerated every day, so it is not used). The month in progress is only in the live feed.
"""
import datetime
import json
import os
import time
from dataclasses import dataclass

import httpx
import structlog

log = structlog.get_logger(service="placsp")

BASE = "https://contrataciondelsectorpublico.gob.es/sindicacion"
CHANNELS = {
    "placsp_mayores":   ("sindicacion_643",  "licitacionesPerfilesContratanteCompleto3", 2012),
    "externos_mayores": ("sindicacion_1044", "PlataformasAgregadasSinMenores",           2016),
    "placsp_menores":   ("sindicacion_1143", "contratosMenoresPerfilesContratantes",     2018),
    "propios":          ("sindicacion_1383", "EMP_SectorPublico",                         2022),
}


@dataclass(frozen=True)
class Archive:
    channel: str
    period: str          # "2019" for a year, "202609" for a month
    url: str

    @property
    def name(self) -> str:
        return self.url.rsplit("/", 1)[-1]

    @property
    def year(self) -> int:
        return int(self.period[:4])


def archives(channels=None, years=None, today: datetime.date | None = None) -> list[Archive]:
    today = today or datetime.date.today()
    out = []
    for ch, (sind, stem, start) in CHANNELS.items():
        if channels and ch not in channels:
            continue
        for year in range(start, today.year + 1):
            if years and year not in years:
                continue
            if year < today.year:
                out.append(Archive(ch, str(year), f"{BASE}/{sind}/{stem}_{year}.zip"))
            else:
                out += [Archive(ch, f"{year}{m:02d}", f"{BASE}/{sind}/{stem}_{year}{m:02d}.zip")
                        for m in range(1, today.month)]
    return out


def zip_path(data_dir: str, a: Archive) -> str:
    return os.path.join(data_dir, "zips", a.channel, a.name)


def download(a: Archive, dest: str, retries: int = 3, timeout: float = 600, transport=None) -> dict:
    """Stream the archive to dest (via dest.part, so a cut download never looks complete) and
    write dest.json with what the server said about it."""
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    part = dest + ".part"
    for attempt in range(1, retries + 1):
        t0 = time.time()
        try:
            # PLACSP chains to the Spanish FNMT CA, which is missing from most trust stores.
            with httpx.Client(timeout=timeout, transport=transport, verify=False, follow_redirects=True,
                              headers={"User-Agent": "placsp-ingest"}) as c, c.stream("GET", a.url) as r:
                r.raise_for_status()
                with open(part, "wb") as f:
                    for chunk in r.iter_bytes(1 << 20):
                        f.write(chunk)
                meta = {"url": a.url, "bytes": os.path.getsize(part), "etag": r.headers.get("etag"),
                        "last_modified": r.headers.get("last-modified"),
                        "downloaded_at": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"),
                        "seconds": round(time.time() - t0, 1)}
            os.replace(part, dest)
            with open(dest + ".json", "w") as f:
                json.dump(meta, f, indent=1)
            return meta
        except (httpx.HTTPError, OSError) as exc:
            log.warning("download_failed", archive=a.name, attempt=attempt, error=str(exc))
            if os.path.exists(part):
                os.remove(part)
            if attempt == retries:
                raise
            time.sleep(30 * attempt)


def download_missing(data_dir: str, todo: list[Archive], transport=None) -> dict:
    got = have = failed = 0
    for a in todo:
        dest = zip_path(data_dir, a)
        if os.path.exists(dest):
            have += 1
            continue
        try:
            meta = download(a, dest, transport=transport)
            got += 1
            log.info("downloaded", archive=a.name, mb=round(meta["bytes"] / 2**20, 1), seconds=meta["seconds"])
        except (httpx.HTTPError, OSError):
            failed += 1
    return {"downloaded": got, "already_there": have, "failed": failed}
