"""Pipeline stages. Each one is resumable: it only processes rows not yet done."""
import base64
import hashlib
import json
import re
import time
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import httpx
from lxml import etree

from placsp_pilot import classify as C
from placsp_pilot.codelists import Codelists
from placsp_pilot.codice import Parser, iter_entries
from placsp_pilot.config import PilotConfig
from placsp_pilot.detail import is_placsp_detail, parse_detail, parse_external, preferred_formats
from placsp_pilot.store import Store
from placsp_pilot.textract import extract as extract_text, sniff

FEEDS = {
    "placsp_mayores": "sindicacion_643/licitacionesPerfilesContratanteCompleto3",
    "externos_mayores": "sindicacion_1044/PlataformasAgregadasSinMenores",
    "placsp_menores": "sindicacion_1143/contratosMenoresPerfilesContratantes",
    "propios": "sindicacion_1383/EMP_SectorPublico",
}
FEED_BASE = "https://contrataciondelsectorpublico.gob.es/sindicacion"
UA = "Mozilla/5.0 (compatible; placsp-pilot/0.1)"

# Channels whose entries are published already awarded: no pliegos, no bidding decision.
NOT_ANALYSABLE = {"placsp_menores": "contrato menor: se publica ya adjudicado, sin pliegos",
                  "propios": "encargo a medio propio: se publica ya formalizado, sin licitación"}


def log(msg: str):
    print(time.strftime("%H:%M:%S"), msg, flush=True)


def _http(cfg: PilotConfig) -> httpx.Client:
    # PLACSP chains to the Spanish FNMT CA, which is missing from most trust stores.
    return httpx.Client(verify=False, follow_redirects=True, timeout=300, headers={"User-Agent": UA})


# ── select ────────────────────────────────────────────────────────────────

def select(cfg: PilotConfig, store: Store, quotas: dict[str, int], max_pages: int = 20):
    parser = Parser(Codelists(cfg.codelist_dir))
    http = _http(cfg)
    with store.stage("select") as st:
        for channel, quota in quotas.items():
            have = store.one("SELECT COUNT(*) n FROM expediente WHERE channel=?", (channel,))["n"]
            if have >= quota:
                log(f"select {channel}: already {have}")
                continue
            url, page, picked = f"{FEED_BASE}/{FEEDS[channel]}.atom", 0, {}
            while url and page < max_pages and len(picked) < quota - have:
                page += 1
                path = cfg.raw_dir / f"feed_{channel}_{page}.atom"
                r = http.get(url)
                r.raise_for_status()
                path.write_bytes(r.content)
                entries, url = iter_entries(str(path))
                # newest first; an entry id can repeat across pages, keep its latest version
                for e in sorted(entries, key=lambda e: e.findtext("{http://www.w3.org/2005/Atom}updated") or "", reverse=True):
                    rec = parser.parse_entry(e, channel)
                    if not rec.get("folder_id") or rec["id"] in picked:
                        continue
                    if store.one("SELECT 1 FROM expediente WHERE id=?", (rec["id"],)):
                        continue
                    picked[rec["id"]] = (rec, etree.tostring(e))
                    if len(picked) >= quota - have:
                        break
            for eid, (rec, raw) in picked.items():
                raw_path = cfg.raw_dir / f"{eid}.xml"
                raw_path.write_bytes(raw)
                _insert_expediente(store, rec, raw_path, len(raw))
            st["items"] += len(picked)
            log(f"select {channel}: +{len(picked)} from {page} page(s)")


def select_themes(cfg: PilotConfig, store: Store, quotas: dict[str, int], channels: list[str], max_pages: int = 200):
    """Expedientes by theme (themes.py, CPV only), newest first, from the given channels' feeds:
    page by page until every theme has its quota or the pages run out. An entry in two themes
    counts for the first one that still needs it, and keeps both."""
    from placsp_pilot.themes import THEMES, themes_of
    parser = Parser(Codelists(cfg.codelist_dir))
    http = _http(cfg)
    with store.tx() as c:
        c.execute("CREATE TABLE IF NOT EXISTS expediente_theme (exp_id TEXT NOT NULL, theme TEXT NOT NULL, quota INTEGER,"
                  " PRIMARY KEY (exp_id, theme))")
    have = Counter(r["theme"] for r in store.q("SELECT theme FROM expediente_theme WHERE quota=1"))
    need = lambda: {k: q - have[k] for k, q in quotas.items() if q > have[k]}
    unknown = set(quotas) - set(THEMES)
    if unknown:
        raise SystemExit(f"select: unknown themes {sorted(unknown)}; known: {sorted(THEMES)}")
    with store.stage("select") as st:
        for channel in channels:
            url, page, scanned = f"{FEED_BASE}/{FEEDS[channel]}.atom", 0, 0
            while url and page < max_pages and need():
                page += 1
                path = cfg.raw_dir / f"feed_{channel}_{page}.atom"
                if not path.exists():
                    r = http.get(url)
                    r.raise_for_status()
                    path.write_bytes(r.content)
                entries, url = iter_entries(str(path))
                for e in sorted(entries, key=lambda e: e.findtext("{http://www.w3.org/2005/Atom}updated") or "", reverse=True):
                    scanned += 1
                    rec = parser.parse_entry(e, channel)
                    ths = themes_of(rec)
                    if not ths or not rec.get("folder_id") or store.one("SELECT 1 FROM expediente WHERE id=?", (rec["id"],)):
                        continue
                    first = next((k for k in ths if k in need()), None)
                    if first is None:
                        continue
                    raw_path = cfg.raw_dir / f"{rec['id']}.xml"
                    raw = etree.tostring(e)
                    raw_path.write_bytes(raw)
                    _insert_expediente(store, rec, raw_path, len(raw))
                    with store.tx() as c:
                        c.executemany("INSERT OR IGNORE INTO expediente_theme VALUES (?,?,?)",
                                      [(rec["id"], k, int(k == first)) for k in ths])
                    have[first] += 1
                    st["items"] += 1
                    if not need():
                        break
                if page % 10 == 0:
                    log(f"select {channel}: {page} pages, {scanned} entries; " + ", ".join(f"{k} {have[k]}/{q}" for k, q in quotas.items()))
            log(f"select {channel}: {page} pages, {scanned} entries; " + ", ".join(f"{k} {have[k]}/{q}" for k, q in quotas.items()))
        short = need()
        if short:
            log(f"select: themes short after {max_pages} pages per channel: {short} (raise --max-pages or add channels)")


OTHER = "otros"


def pick_balanced(pool: dict, have_theme: Counter, have_cell: Counter, n: int) -> list:
    """Up to n candidates from `pool` ({(theme, type): [candidate, newest first]}): each time the theme
    with the fewest expedientes so far, and within it the contract type with the fewest; a theme or
    type with no candidates left is passed over. Updates the counters."""
    out = []
    while len(out) < n:
        themes = {th for (th, _), c in pool.items() if c}
        if not themes:
            break
        th = min(themes, key=lambda k: (have_theme[k], k))
        cell = min((k for k, c in pool.items() if c and k[0] == th), key=lambda k: (have_cell[k], k))
        out.append(pool[cell].pop(0))
        have_theme[th] += 1
        have_cell[cell] += 1
    return out


def select_balanced(cfg: PilotConfig, store: Store, n: int, channels: list[str], max_pages: int = 200):
    """n more expedientes, newest first from the given channels' feeds, spread evenly over the themes
    (themes.py, plus "otros" for an entry in none) and, within a theme, over the contract types
    (obras, servicios, suministros...), counting what the run already has. Each call adds n new ones;
    a theme the feeds have too few of takes what there is and the rest goes to the others."""
    from placsp_pilot.themes import THEMES, themes_of
    parser = Parser(Codelists(cfg.codelist_dir))
    http = _http(cfg)
    with store.tx() as c:
        c.execute("CREATE TABLE IF NOT EXISTS expediente_theme (exp_id TEXT NOT NULL, theme TEXT NOT NULL, quota INTEGER,"
                  " PRIMARY KEY (exp_id, theme))")
    ctype = lambda tender: ((tender or {}).get("contract_type") or {}).get("code") or "?"
    first = {r["exp_id"]: r["theme"] for r in store.q("SELECT exp_id, theme FROM expediente_theme WHERE quota=1")}
    have_theme, have_cell = Counter(), Counter()
    for r in store.q("SELECT id, tender_json FROM expediente"):
        th = first.get(r["id"], OTHER)
        have_theme[th] += 1
        have_cell[(th, ctype(json.loads(r["tender_json"] or "{}").get("tender")))] += 1
    themes = list(THEMES) + [OTHER]
    log("select: have " + ", ".join(f"{k} {have_theme[k]}" for k in themes))

    # Read the feeds until every theme has n candidates or the pages run out. The first page is
    # the live file and is read again each time; the older ones never change and are kept.
    pool, short = defaultdict(list), lambda: [k for k in themes if sum(len(v) for (th, _), v in pool.items() if th == k) < n]
    seen = set()
    for channel in channels:
        url, page = f"{FEED_BASE}/{FEEDS[channel]}.atom", 0
        while url and page < max_pages and short():
            page += 1
            path = cfg.raw_dir / (f"feed_{channel}_live.atom" if page == 1 else f"feed_{channel}_{url.rsplit('/', 1)[-1]}")
            if page == 1 or not path.exists():
                r = http.get(url)
                r.raise_for_status()
                path.write_bytes(r.content)
            entries, url = iter_entries(str(path))
            for e in sorted(entries, key=lambda e: e.findtext("{http://www.w3.org/2005/Atom}updated") or "", reverse=True):
                rec = parser.parse_entry(e, channel)
                if not rec.get("folder_id") or rec["id"] in seen or store.one("SELECT 1 FROM expediente WHERE id=?", (rec["id"],)):
                    continue
                seen.add(rec["id"])
                ths = themes_of(rec) or [OTHER]
                th = next((k for k in ths if k in short()), None)
                if th is None:
                    continue
                pool[(th, ctype(rec.get("tender")))].append((rec, etree.tostring(e), ths, th))
            if page % 10 == 0:
                log(f"select {channel}: {page} pages; still short of {short()}")

    with store.stage("select") as st:
        for rec, raw, ths, th in pick_balanced(pool, have_theme, have_cell, n):
            raw_path = cfg.raw_dir / f"{rec['id']}.xml"
            raw_path.write_bytes(raw)
            _insert_expediente(store, rec, raw_path, len(raw))
            with store.tx() as c:
                c.executemany("INSERT OR IGNORE INTO expediente_theme VALUES (?,?,?)",
                              [(rec["id"], k, int(k == th)) for k in ths])
            st["items"] += 1
    log("select: now " + ", ".join(f"{k} {have_theme[k]}" for k in themes))


def _insert_expediente(store: Store, rec: dict, raw_path: Path, raw_bytes: int):
    reason = NOT_ANALYSABLE.get(rec["channel"])
    technical_urls = {d["url"] for d in rec["documents"] if d["source"] == "feed_technical"}
    with store.tx() as c:
        c.execute(
            "INSERT OR IGNORE INTO expediente (id, channel, updated, link, folder_id, title, status, raw_path, raw_bytes,"
            " tender_json, analysable, skip_reason, detail_status) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (rec["id"], rec["channel"], rec["updated"], rec["link"], rec.get("folder_id"),
             rec.get("tender", {}).get("name") or rec.get("atom_title"),
             (rec.get("status") or {}).get("code"), str(raw_path), raw_bytes,
             json.dumps(rec, ensure_ascii=False), 0 if reason else 1, reason,
             "pending" if rec["link"] else "n/a"))
        for d in rec["documents"]:
            if d["source"] == "feed_technical" and d["url"] in {x["url"] for x in rec["documents"] if x["source"] == "feed_legal"}:
                continue  # combined pliego: recorded once, as feed_legal with role PCAP+PPT
            ref = dict(d, also_technical=d["source"] == "feed_legal" and d["url"] in technical_urls)
            role, rule = C.classify(ref, rec["channel"])
            c.execute(
                "INSERT OR IGNORE INTO docref (exp_id, url, source, label, type_code, notice_type, feed_hash, role, role_source)"
                " VALUES (?,?,?,?,?,?,?,?,?)",
                (rec["id"], d["url"], d["source"], d["label"], d.get("type_code"), d.get("notice_type"),
                 d.get("feed_hash"), role, rule))


# ── discover (detail pages) ───────────────────────────────────────────────

def discover(cfg: PilotConfig, store: Store):
    http = _http(cfg)
    rows = store.q("SELECT id, channel, link FROM expediente WHERE detail_status='pending'")
    with store.stage("discover") as st:
        for row in rows:
            t0 = time.time()
            try:
                r = http.get(row["link"])
                r.raise_for_status()
                (cfg.raw_dir / f"{row['id']}.detail.html").write_bytes(r.content)
                if is_placsp_detail(row["link"]):
                    refs = parse_detail(r.text)
                else:
                    known = {x["url"] for x in store.q("SELECT url FROM docref WHERE exp_id=?", (row["id"],))}
                    refs = [d for d in parse_external(r.text, str(r.url)) if d["url"] not in known]
                keep = preferred_formats(refs)
                with store.tx() as c:
                    for d in refs:
                        role, rule = C.classify(d, row["channel"])
                        skipped = d["source"] == "detail_notice" and d["url"] not in keep
                        c.execute(
                            "INSERT OR IGNORE INTO docref (exp_id, url, source, label, published, fmt, role, role_source, status, error)"
                            " VALUES (?,?,?,?,?,?,?,?,?,?)",
                            (row["id"], d["url"], d["source"], d["label"], d["published"], d["fmt"], role, rule,
                             "skipped" if skipped else "pending", "alternate_format" if skipped else None))
                store.update("expediente", {"id": row["id"]}, detail_status="ok", detail_bytes=len(r.content),
                             detail_ms=int((time.time() - t0) * 1000))
                st["items"] += 1
            except Exception as e:  # noqa: BLE001
                store.update("expediente", {"id": row["id"]}, detail_status="failed",
                             detail_ms=int((time.time() - t0) * 1000))
                log(f"discover {row['id']} failed: {e}")
            time.sleep(0.3)
        log(f"discover: {st['items']} detail pages")


# ── fetch ─────────────────────────────────────────────────────────────────

def _filename(headers, fallback: str | None) -> str | None:
    cd = headers.get("content-disposition") or ""
    m = re.search(r"filename\*?=(?:UTF-8'')?\"?([^\";]+)", cd, re.I)
    return m.group(1) if m else fallback


def _save_blob(cfg: PilotConfig, store: Store, data: bytes, filename: str | None, mime: str | None) -> str:
    sha = hashlib.sha256(data).hexdigest()
    if store.one("SELECT 1 FROM blob WHERE sha=?", (sha,)):
        return sha
    ext = sniff(data, filename, mime)
    path = cfg.files_dir / sha[:2] / f"{sha}.{ext}"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    sha1 = base64.b64encode(hashlib.sha1(data).digest()).decode()      # the file may be gone when validate runs
    with store.tx() as c:
        c.execute("INSERT OR IGNORE INTO blob (sha, bytes, mime, ext, path, sha1_b64, text_status, summary_status, ner_status,"
                  " resolve_status, describe_status) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                  (sha, len(data), mime, ext, str(path), sha1, "pending", "pending", "pending", "pending", "pending"))
    return sha


def fetch(cfg: PilotConfig, store: Store):
    rows = store.q("SELECT id, url, label FROM docref WHERE status='pending' AND url IS NOT NULL")
    by_url = defaultdict(list)
    for r in rows:
        by_url[r["url"]].append(r)
    http = _http(cfg)
    limit = cfg.max_file_mb * 2**20

    def one(url: str, refs: list):
        t0 = time.time()
        try:
            with http.stream("GET", url) as r:
                size = int(r.headers.get("content-length") or 0)
                if size > limit:
                    return url, refs, None, r.status_code, f"too_large:{size}", t0
                data = r.read()
                if r.status_code >= 400:
                    return url, refs, None, r.status_code, f"http_{r.status_code}", t0
                sha = _save_blob(cfg, store, data, _filename(r.headers, refs[0]["label"]),
                                 r.headers.get("content-type"))
                return url, refs, sha, r.status_code, None, t0
        except Exception as e:  # noqa: BLE001
            return url, refs, None, None, f"{type(e).__name__}: {e}"[:300], t0

    with store.stage("fetch") as st, ThreadPoolExecutor(cfg.fetch_workers) as pool:
        futs = [pool.submit(one, u, refs) for u, refs in by_url.items()]
        for i, f in enumerate(as_completed(futs), 1):
            url, refs, sha, code, err, t0 = f.result()
            ms = int((time.time() - t0) * 1000)
            status = "fetched" if sha else ("skipped" if err and err.startswith("too_large") else "failed")
            with store.tx() as c:
                for ref in refs:
                    c.execute("UPDATE docref SET status=?, http_status=?, error=?, fetch_ms=?, sha=? WHERE id=?",
                              (status, code, err, ms, sha, ref["id"]))
            st["items"] += 1
            if i % 50 == 0:
                log(f"fetch {i}/{len(futs)}")
        log(f"fetch: {len(futs)} urls")


# ── text ──────────────────────────────────────────────────────────────────

# Extraction outcomes after which the file is not needed again (not needs_ocr, not failed).
DONE_WITH_FILE = {"ok", "empty", "unsupported", "archive"}


def text(cfg: PilotConfig, store: Store):
    def one(b):
        t0 = time.time()
        if not b["path"] or not Path(b["path"]).exists():
            return b, None, 0
        data = Path(b["path"]).read_bytes()
        res = extract_text(data, b["ext"], cfg.ocr_url, cfg.ocr_min_chars_per_page)
        return b, res, int((time.time() - t0) * 1000)

    with store.stage("text") as st:
        while True:
            blobs = store.q("SELECT sha, path, ext FROM blob WHERE text_status='pending'")
            if not blobs:
                break
            with ThreadPoolExecutor(max(1, cfg.fetch_workers)) as pool:
                for f in as_completed([pool.submit(one, b) for b in blobs]):
                    b, res, ms = f.result()
                    if res is None:          # deleted after an earlier extraction: fetch it again to re-read it
                        store.update("blob", {"sha": b["sha"]}, text_status="failed", error="file deleted; refetch to extract again",
                                     summary_status="skipped", ner_status="skipped", resolve_status="skipped", describe_status="skipped")
                        st["items"] += 1
                        continue
                    fields = dict(text_status=res.status, text_method=res.method, pages=res.pages, text_ms=ms,
                                  ocr_pages=res.ocr_pages, ocr_ms=res.ocr_ms, error=res.error or None,
                                  text_chars=len(res.text))
                    if res.status == "archive":
                        _expand_archive(cfg, store, b["sha"], res.members)
                        fields["summary_status"] = "skipped"
                    elif res.text:
                        tp = cfg.text_dir / b["sha"][:2] / f"{b['sha']}.txt"
                        tp.parent.mkdir(parents=True, exist_ok=True)
                        tp.write_text(res.text, encoding="utf-8")
                        fields["text_path"] = str(tp)
                    if res.status != "ok":
                        fields["summary_status"] = "skipped"
                    if res.status != "ok":
                        fields.update(ner_status="skipped", resolve_status="skipped", describe_status="skipped")
                    # The text (and an archive's members) is all the pipeline reads from here on; the
                    # original is shown from PLACSP. Kept: what OCR or a retry may need again.
                    if not cfg.keep_files and res.status in DONE_WITH_FILE:
                        Path(b["path"]).unlink(missing_ok=True)
                        fields["path"] = None
                    store.update("blob", {"sha": b["sha"]}, **fields)
                    if res.ocr_ms:
                        store.log_call(service="ocr", task="ocr", sha=b["sha"], input_chars=0,
                                       output_chars=len(res.text), wall_ms=res.ocr_ms, ok=1)
                    st["items"] += 1
        log(f"text: {st['items']} files")


def _expand_archive(cfg: PilotConfig, store: Store, sha: str, members: list):
    parents = store.q("SELECT d.id, d.exp_id, e.channel FROM docref d JOIN expediente e ON e.id=d.exp_id"
                      " WHERE d.sha=? GROUP BY d.exp_id", (sha,))
    for name, data in members:
        msha = _save_blob(cfg, store, data, name, None)
        for p in parents:
            role, rule = C.classify({"source": "zip_member", "label": name}, p["channel"])
            with store.tx() as c:
                c.execute("INSERT OR IGNORE INTO docref (exp_id, url, source, label, role, role_source, parent_id, status, sha)"
                          " VALUES (?,?,?,?,?,?,?,?,?)",
                          (p["exp_id"], f"zip:{sha}/{name}", "zip_member", name, role, rule, p["id"], "fetched", msha))


