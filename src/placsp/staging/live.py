"""The live feed as one more archive.

PLACSP's live feed (<stem>.atom, then rel="next" pages back in time) carries what the archives do
not have yet: the month in progress. Each run reads it, newest page first, until a page is not newer
than the latest update already staged for that channel, and saves the pages as
zips/<channel>/live_<UTC timestamp>.zip. From there it is an archive like any other: extract, build
and load handle it unchanged, and its versions merge with the archives' ones by their update time.
"""
import datetime
import io
import os
import zipfile

import duckdb
import httpx
import structlog
from lxml import etree

from placsp.staging.sources import BASE, CHANNELS

log = structlog.get_logger(service="placsp")

ATOM = "{http://www.w3.org/2005/Atom}"
SYNC_HOST = "https://contrataciondelsectorpublico.gob.es"


def head_url(channel: str) -> str:
    sind, stem, _ = CHANNELS[channel]
    return f"{BASE}/{sind}/{stem}.atom"


def _ts(s: str | None) -> datetime.datetime | None:
    try:
        return datetime.datetime.fromisoformat(s) if s else None
    except ValueError:
        return None


def watermarks(data_dir: str) -> dict[str, datetime.datetime]:
    """Latest update staged per channel (from the current tables), as aware datetimes."""
    path = os.path.join(data_dir, "current", "tender.parquet")
    if not os.path.exists(path):
        return {}
    rows = duckdb.sql(f"SELECT channel, max(last_updated) FROM read_parquet('{path}') GROUP BY 1").fetchall()
    return {ch: ts for ch, ts in rows if ts is not None}


def _page(content: bytes) -> tuple[datetime.datetime | None, str | None]:
    """(newest entry update, next page URL) of one feed page."""
    root = etree.fromstring(content, parser=etree.XMLParser(huge_tree=True))
    nxt = next((l.get("href") for l in root.findall(f"{ATOM}link") if l.get("rel") == "next"), None)
    if nxt:     # feeds link to contrataciondelestado.es; the sync host serves the same pages
        nxt = nxt.replace("https://contrataciondelestado.es", SYNC_HOST)
    stamps = [t for t in (_ts(e.findtext(f"{ATOM}updated")) for e in root.findall(f"{ATOM}entry")) if t]
    return (max(stamps) if stamps else None), nxt


def fetch_live(data_dir: str, channels=None, max_pages: int = 1000, transport=None,
               now: datetime.datetime | None = None) -> dict[str, int]:
    """Save each channel's new live pages as one archive; {channel: pages saved}."""
    wm = watermarks(data_dir)
    stamp = (now or datetime.datetime.now(datetime.timezone.utc)).strftime("%Y%m%dT%H%M%S")
    out = {}
    with httpx.Client(timeout=600, transport=transport, verify=False, follow_redirects=True,
                      headers={"User-Agent": "placsp-ingest"}) as http:
        for ch in channels or CHANNELS:
            url, pages = head_url(ch), []
            while url and len(pages) < max_pages:
                r = http.get(url)
                r.raise_for_status()
                pages.append(r.content)
                newest, url = _page(r.content)
                if ch in wm and newest is not None and newest <= wm[ch]:
                    break
            dest = os.path.join(data_dir, "zips", ch, f"live_{stamp}.zip")
            os.makedirs(os.path.dirname(dest), exist_ok=True)
            buf = io.BytesIO()
            with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
                for i, content in enumerate(pages):
                    zf.writestr(f"page_{i:04d}.atom", content)
            with open(dest + ".part", "wb") as f:
                f.write(buf.getvalue())
            os.replace(dest + ".part", dest)
            out[ch] = len(pages)
            log.info("live_saved", channel=ch, pages=len(pages), watermark=str(wm.get(ch)))
    return out
