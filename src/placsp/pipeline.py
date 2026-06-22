from typing import Iterable, Optional
import structlog
from .models import RawEntry, Tombstone, ProcurementRecord, StatusEvent
from .atom_parser import parse_feed
from .codice_extractor import extract
from .renderer import render

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
    def __init__(self, cfg, embedder, upserter, codelists):
        self.cfg = cfg
        self.embedder = embedder
        self.upserter = upserter
        self.codelists = codelists

    def is_offpeak(self, now) -> bool:
        s, e = self.cfg.offpeak_start, self.cfg.offpeak_end
        h = now.hour
        return (s <= h or h < e) if s > e else (s <= h < e)

    def process_files(self, paths: list[str], category: str) -> dict:
        def items():
            for p in paths:
                yield from parse_feed(p, category)
        records, tombs = collapse(items(), self.codelists)
        recs = list(records.values())
        texts = [self._summary(r) for r in recs]
        vectors = self.embedder.embed(texts) if recs else []
        upserted = self.upserter.upsert(recs, vectors) if recs else 0
        deleted = self.upserter.apply_tombstones(tombs) if tombs else 0
        log.info("processed", category=category, files=len(paths), upserted=upserted, deleted=deleted)
        return {"records": len(recs), "upserted": upserted, "deleted": deleted}

    def _summary(self, rec) -> str:
        return render(rec)[0]
