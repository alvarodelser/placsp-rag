from typing import Iterable, Optional
import structlog
from placsp.core.models import RawEntry, Tombstone, ProcurementRecord, StatusEvent
from placsp.core.codelists import collapse
from placsp.ingestion.pliego_pipeline import PliegoPipeline
from placsp.parsers.atom_parser import parse_feed
from placsp.parsers.codice_extractor import extract
from placsp.parsers.renderer import render

log = structlog.get_logger(service="placsp")

def _merge_history(rec: ProcurementRecord, seen: dict):
    key = (rec.status_code, (rec.updated or "")[:10])
    if rec.status_code:
        seen.setdefault(rec.syndication_id, {})[key] = StatusEvent(rec.status_code, (rec.updated or "")[:10] or None)

def collapse(items: Iterable, codelists) -> tuple[dict[str, ProcurementRecord], list[Tombstone]]:
    latest: dict[str, ProcurementRecord] = {}
    history: dict[str, dict] = {}
    tombs: list[Tombstone] = []
    for it in items:
        if isinstance(it, Tombstone):
            tombs.append(it); continue
        rec = extract(it, codelists)
        _merge_history(rec, history)
        prev = latest.get(rec.syndication_id)
        if prev is None or (rec.updated or "") >= (prev.updated or ""):
            latest[rec.syndication_id] = rec
    for sid, rec in latest.items():
        rec.status_history = sorted(history.get(sid, {}).values(), key=lambda e: e.date or "")
    # drop ids that are tombstoned in the same batch
    tomb_ids = {t.syndication_id for t in tombs}
    for sid in tomb_ids:
        latest.pop(sid, None)
    return latest, tombs

class Pipeline:
    def __init__(self, cfg, embedder, upserter, codelists, graph_sink=None):
        self.cfg = cfg
        self.embedder = embedder
        self.upserter = upserter
        self.codelists = codelists
        self.graph_sink = graph_sink
        self.pliego_pipeline = PliegoPipeline(cfg, embedder)

    def is_offpeak(self, now) -> bool:
        s, e = self.cfg.offpeak_start, self.cfg.offpeak_end
        h = now.hour
        return (s <= h or h < e) if s > e else (s <= h < e)

    def process_files(self, paths: list[str], category: str, merge_stored: bool = False) -> dict:
        def items():
            for p in paths:
                yield from parse_feed(p, category)
        records, tombs = collapse(items(), self.codelists)
        recs = list(records.values())
        skipped = 0
        if merge_stored:
            surviving = []
            for rec in recs:
                stored = self.upserter.get_stored(rec.syndication_id)
                if stored is not None and stored.get("updated") and rec.updated is not None and rec.updated <= stored["updated"]:
                    skipped += 1
                    continue
                if stored is not None and stored.get("status_history"):
                    merged = {}
                    for e in stored["status_history"]:
                        key = (e["code"], e.get("date"))
                        merged[key] = StatusEvent(code=e["code"], date=e.get("date"))
                    for e in rec.status_history:
                        key = (e.code, e.date)
                        merged[key] = StatusEvent(code=e.code, date=e.date)
                    rec.status_history = sorted(merged.values(), key=lambda e: e.date or "")
                surviving.append(rec)
            recs = surviving
        texts = [self._summary(r) for r in recs]
        vectors = self.embedder.embed(texts) if recs else []
        upserted = self.upserter.upsert(recs, vectors) if recs else 0
        deleted = self.upserter.apply_tombstones(tombs) if tombs else 0
        
        # --- Tier 1 Pliego Processing ---
        pliego_objs = []
        for rec in recs:
            # We only process if it's a new entry and has an HTML link (the detail page)
            # The detail page URL is typically in the source_url
            if rec.source_url and "contrataciondelestado.es/wps/portal" in rec.source_url:
                obj = self.pliego_pipeline.process_tier1(rec, rec.source_url)
                if obj:
                    pliego_objs.append(obj)
        
        if pliego_objs:
            self.upserter.post_batch_raw(pliego_objs)
            log.info("pliegos_processed", count=len(pliego_objs))

        if self.graph_sink is not None:
            try:
                self.graph_sink.upsert(recs)
                self.graph_sink.apply_tombstones(tombs)
            except Exception as exc:
                log.error("graph_sink_failed", category=category, error=str(exc))
        log.info("processed", category=category, files=len(paths), upserted=upserted, deleted=deleted, skipped=skipped)
        return {"records": len(recs) + skipped, "upserted": upserted, "deleted": deleted, "skipped": skipped}

    def _summary(self, rec) -> str:
        return render(rec)[0]

    # --- append to Pipeline ---
    def watermark(self, category: str) -> Optional[str]:
        # max(updated) for a category, via GraphQL aggregate; None if empty/unsupported
        import httpx
        q = ('{Aggregate{%s(where:{path:["category"],operator:Equal,valueText:"%s"})'
             '{updated{maximum}}}}' % (self.cfg.weaviate_class, category))
        try:
            r = httpx.post(f"{self.cfg.weaviate_url.rstrip('/')}/v1/graphql",
                           json={"query": q}, timeout=60,
                           headers={"Authorization": f"Bearer {self.cfg.weaviate_api_key}"} if self.cfg.weaviate_api_key else {})
            agg = r.json()["data"]["Aggregate"][self.cfg.weaviate_class]
            return agg[0]["updated"]["maximum"] if agg else None
        except Exception as exc:
            log.warning("watermark_failed", category=category, error=str(exc))
            return None

    def run_backfill(self):
        import os, time
        from datetime import datetime
        from placsp.core.catalog import CATALOG
        from placsp.ingestion.fetcher import download, unzip
        for feed in sorted(CATALOG, key=lambda f: (f.year, f.category)):
            while not self.is_offpeak(datetime.now()):
                log.info("sleeping_until_offpeak"); time.sleep(600)
            workdir = os.path.join(self.cfg.work_dir, feed.name)
            zip_path = os.path.join(workdir, feed.name + ".zip")
            try:
                download(feed.url, zip_path)
                paths = unzip(zip_path, workdir)
                self.process_files(paths, feed.category)
            except Exception as exc:
                log.error("feed_failed", feed=feed.name, error=str(exc))
            finally:
                if os.path.exists(zip_path):
                    os.remove(zip_path)

    def run_daily(self):
        import os, tempfile
        from placsp.core.catalog import CATALOG, live_head_url
        from placsp.ingestion.fetcher import download, feed_next_link
        from placsp.parsers.atom_parser import parse_feed
        for category in sorted({f.category for f in CATALOG}):
            wm = self.watermark(category)
            url = live_head_url(category)
            page = 0
            while url and page < 1000:
                tmp = os.path.join(tempfile.gettempdir(), f"placsp_{category}_{page}.atom")
                download(url, tmp)
                self.process_files([tmp], category, merge_stored=True)
                # capture the next link and this page's newest update BEFORE deleting tmp
                newest = max((getattr(i, "updated", "") or "" for i in parse_feed(tmp, category)), default="")
                nxt = feed_next_link(tmp)
                os.remove(tmp)
                # stop when this page is entirely older than the watermark
                if wm and newest and newest <= wm:
                    break
                url, page = nxt, page + 1

    def run_reconcile(self):
        import os
        from datetime import datetime
        from placsp.core.catalog import CATALOG
        from placsp.ingestion.fetcher import download, unzip
        for feed in [f for f in CATALOG if f.incremental]:
            workdir = os.path.join(self.cfg.work_dir, feed.name + "_recon")
            zip_path = os.path.join(workdir, feed.name + ".zip")
            download(feed.url, zip_path)
            self.process_files(unzip(zip_path, workdir), feed.category, merge_stored=True)
            os.remove(zip_path)
