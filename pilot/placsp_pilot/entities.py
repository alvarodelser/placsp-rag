"""The entity layer: from what NER found in each chunk to one described entity per real thing.

  mentions  every /ner item becomes a mention, located in the chunk it came from (character
            offsets and page), so every fact can be traced to its passage
  resolve   per expediente, the cross-document step of nlp_service's design (its Phase B):
              1. anchor to the feed: a mention of a lot, criterion, requirement, guarantee,
                 authority, winner or contract joins the feed's node instead of making a new one
              2. merge by keys: NIF, lot number, guarantee type, normalised name
              3. merge near-identical names (typos, plurals, legal forms)
              4. what is left goes to nlp_service /resolve, type by type, with the mentions of
                 every document of the expediente (the model decides the doubtful merges)
  coref     nlp_service /coref/links on the passages that carry references ("la empresa", "la
            adjudicataria", "dicha entidad", "el órgano de contratación"...): each one becomes a
            mention of the entity it points at, with its own offsets, so it is evidence too
  refine    /ner again on each requirement's and award criterion's passages, with a narrow
            schema that pulls out thresholds, units, periods, accreditation, points, formulas
  describe  /summarize once per entity (requirement_desc / criterion_desc / entity_desc) from
            all its passages and fields, and once per relation

Scope: organizations (by NIF, else normalised name) and qualifications are shared across
expedientes; everything else belongs to one expediente.
"""
import difflib
import json
import re
import time
import unicodedata
from collections import Counter, defaultdict
from pathlib import Path

from placsp_pilot import graph as G
from placsp_pilot.config import PilotConfig
from placsp_pilot.nlpstages import PAGE, _pool, log, page_ranges, split_words
from placsp_pilot.services import ServiceError, Services
from placsp_pilot.store import Store

SCHEMA = """
CREATE TABLE IF NOT EXISTS mention (
    id          TEXT PRIMARY KEY,            -- <sha>:<chunk idx>:<k>
    sha         TEXT NOT NULL, idx INTEGER NOT NULL, k INTEGER NOT NULL,
    type        TEXT, subtype TEXT, name TEXT, surface TEXT, attributes TEXT,
    evidence    TEXT, confidence REAL,
    char_start  INTEGER, char_end INTEGER,   -- of the evidence quote, within the chunk text
    page        INTEGER, located INTEGER,
    kind        TEXT DEFAULT 'ner',          -- ner | coref (a reference that does not name the entity)
    name_start  INTEGER, name_end INTEGER    -- the name itself, within the quote: what a reader sees highlighted
);
CREATE INDEX IF NOT EXISTS mention_sha ON mention(sha);
CREATE TABLE IF NOT EXISTS mrelation (
    id TEXT PRIMARY KEY, sha TEXT, idx INTEGER, head TEXT, tail TEXT, type TEXT, subtype TEXT,
    attributes TEXT, evidence TEXT, confidence REAL
);
CREATE TABLE IF NOT EXISTS entity (
    exp_id TEXT NOT NULL, id TEXT NOT NULL,
    scope TEXT, type TEXT, label TEXT, name TEXT, subtype TEXT,
    anchor INTEGER,                          -- 1 when the entity is the feed's node
    how TEXT,                                -- feed | key | similar | llm | single
    aliases TEXT, attributes TEXT, conflicts TEXT, lots TEXT, documents TEXT, mentions INTEGER,
    PRIMARY KEY (exp_id, id)
);
CREATE TABLE IF NOT EXISTS entity_mention (
    exp_id TEXT NOT NULL, mention_id TEXT NOT NULL, entity_id TEXT NOT NULL, PRIMARY KEY (exp_id, mention_id)
);
CREATE TABLE IF NOT EXISTS entity_relation (
    exp_id TEXT NOT NULL, id TEXT NOT NULL, src TEXT, type TEXT, dst TEXT, subtype TEXT,
    attributes TEXT, evidence TEXT, mentions TEXT, PRIMARY KEY (exp_id, id)
);
CREATE TABLE IF NOT EXISTS resolution (
    exp_id TEXT PRIMARY KEY, status TEXT, ms INTEGER, mentions INTEGER, entities INTEGER,
    merges TEXT, llm_calls INTEGER, error TEXT
);
CREATE TABLE IF NOT EXISTS formula (
    exp_id TEXT NOT NULL, entity_id TEXT NOT NULL, status TEXT, ms INTEGER, result_json TEXT,
    PRIMARY KEY (exp_id, entity_id)
);
CREATE TABLE IF NOT EXISTS coref_run (
    exp_id TEXT PRIMARY KEY, status TEXT, ms INTEGER, chunks INTEGER, calls INTEGER, links INTEGER, error TEXT
);
CREATE TABLE IF NOT EXISTS refinement (
    exp_id TEXT NOT NULL, entity_id TEXT NOT NULL, status TEXT, ms INTEGER, result_json TEXT,
    PRIMARY KEY (exp_id, entity_id)
);
CREATE TABLE IF NOT EXISTS entity_description (
    exp_id TEXT NOT NULL, kind TEXT NOT NULL, item_id TEXT NOT NULL, profile TEXT, status TEXT,
    ms INTEGER, text TEXT, PRIMARY KEY (exp_id, kind, item_id)
);
"""

ORG_TYPES = {"CONTRACTING_AUTHORITY", "COMPANY", "OTHER_ORGANIZATION"}
GLOBAL_TYPES = ORG_TYPES | {"JOINT_VENTURE", "QUALIFICATION"}
# Relations that tie an entity to a lot, whichever side the lot is on.
LOT_RELS = {"HAS_CRITERION", "REQUIRES", "INCLUDES", "BID_FOR", "CONTRACT_FOR", "REVIEWS", "AWARDED_TO",
            "DECLARED_VOID", "TENDERS"}
SIMILAR = 0.9            # near-identical names of the same type merge without asking the model
ANCHOR_SIMILAR = 0.72    # a document item joins the feed's when names are this close (points must agree)
LLM_BATCH = 80           # /resolve candidates per call
REFINE_TYPES = ("REQUIREMENT", "AWARD_CRITERION")
GENERIC_AUTHORITY = {"ayuntamiento", "el ayuntamiento", "organo de contratacion", "el organo de contratacion",
                     "entidad contratante", "poder adjudicador", "la administracion", "administracion contratante",
                     "diputacion", "consejeria", "ajuntament", "concello", "alcaldia", "pleno"}
# The authority's own bodies: mentions of them are the authority acting, not another organization.
_AUTHORITY_BODY = re.compile(r"^(la |el )?(mesa|junta|comision|unidad|servicio|organo)( permanente)? de "
                             r"(contratacion|asistencia|valoracion|compras)|^junta de gobierno|^alcald|^presidencia")
_REFERENCE_ONLY = re.compile(r"(cl[aá]usula|pliego|pcap|anexo|apartado|seg[uú]n|de acuerdo|conforme|ver\b)", re.I)
# Feed requirement groups -> the document requirement subtypes that spell them out.
_GROUP_SUBTYPES = {"financial": {"TURNOVER", "INSURANCE"},
                   "technical": {"SIMILAR_SERVICES", "TEAM", "CREDENTIAL", "COMMITMENT"},
                   "classification": {"CLASSIFICATION"}}


def schema(store: Store):
    with store.tx() as c:
        c.executescript(SCHEMA)
        cols = {r[1] for r in c.execute("PRAGMA table_info(mention)")}
        if "kind" not in cols:          # pilot.db from before coref
            c.execute("ALTER TABLE mention ADD COLUMN kind TEXT DEFAULT 'ner'")
        if "name_start" not in cols:
            c.execute("ALTER TABLE mention ADD COLUMN name_start INTEGER")
            c.execute("ALTER TABLE mention ADD COLUMN name_end INTEGER")


# ── text helpers ──────────────────────────────────────────────────────────

def fold(s: str | None) -> str:
    s = unicodedata.normalize("NFKD", (s or "").lower())
    return "".join(ch for ch in s if not unicodedata.combining(ch))


def _norm_map(text: str) -> tuple[str, list[int]]:
    """Case/accent-folded text with runs of whitespace collapsed, and each output character's
    index in the original."""
    out, idx, space = [], [], False
    for i, ch in enumerate(text):
        if ch.isspace():
            if not space and out:
                out.append(" ")
                idx.append(i)
            space = True
            continue
        space = False
        for f in fold(ch):
            out.append(f)
            idx.append(i)
    return "".join(out), idx


def locate(chunk: str, quote: str) -> tuple[int, int] | None:
    """Character span of `quote` in `chunk`: exact, then folded, then the longest common block
    when it covers most of the quote (the model sometimes trims or re-spaces what it quotes)."""
    quote = (quote or "").strip()
    if len(quote) < 3:
        return None
    i = chunk.find(quote)
    if i >= 0:
        return i, i + len(quote)
    norm, imap = _norm_map(chunk)
    q, _ = _norm_map(quote)
    j = norm.find(q)
    if j >= 0:
        return imap[j], imap[j + len(q) - 1] + 1
    m = difflib.SequenceMatcher(None, norm, q, autojunk=False).find_longest_match(0, len(norm), 0, len(q))
    if m.size >= max(20, 0.6 * len(q)):
        start = max(0, m.a - m.b)
        end = min(len(norm), start + len(q))
        return imap[start], imap[end - 1] + 1
    return None


def _name_span(chunk: str, quote: tuple[int, int], *names: str) -> tuple[int, int] | None:
    """Where the entity is named inside its quote (the quote is the sentence around it)."""
    seg, imap = _norm_map(chunk[quote[0]:quote[1]])
    for n in names:
        q, _ = _norm_map(n.strip().strip("“”\"'"))
        if len(q) >= 2:
            i = seg.find(q)
            if i >= 0:
                return quote[0] + imap[i], quote[0] + imap[i + len(q) - 1] + 1
    return None


def page_at(chunk: str, offset: int, chunk_page: int | None) -> int | None:
    marks = [(m.start(), int(m.group(1))) for m in PAGE.finditer(chunk)]
    before = [p for pos, p in marks if pos <= offset]
    return before[-1] if before else chunk_page


_STOP = {"de", "del", "la", "las", "el", "los", "y", "e", "en", "para", "por", "con", "a", "al", "o", "u"}


def tokens(name: str) -> set[str]:
    return {t.rstrip("s") for t in G.norm_name(name).split() if t not in _STOP}


def similarity(a: str, b: str) -> float:
    """Close names score high: typos (sequence ratio) and reordered or extended names (shared
    content words, when both have at least three)."""
    na, nb = G.norm_name(a), G.norm_name(b)
    if not na or not nb:
        return 0.0
    seq = difflib.SequenceMatcher(None, na, nb).ratio()
    ta, tb = tokens(a), tokens(b)
    share = len(ta & tb) / max(1, min(len(ta), len(tb))) if min(len(ta), len(tb)) >= 3 else 0.0
    return max(seq, share * 0.95)


def same_codes(a: str, b: str) -> bool:
    code = lambda x: {t for t in tokens(x) if any(c.isdigit() for c in t)}
    return code(a) == code(b)


def typo_equal(a: str, b: str) -> bool:
    """Same words up to typos: every content word has a close twin on the other side, and codes
    (anything with a digit: ENI-03, Tier III is not, ISO 9001 is) are identical."""
    ta, tb = tokens(a), tokens(b)
    if not ta or not tb or not same_codes(a, b):
        return False
    close = lambda x, ys: any(x == y or difflib.SequenceMatcher(None, x, y).ratio() >= 0.8 for y in ys)
    return all(close(x, tb) for x in ta) and all(close(y, ta) for y in tb)


def _value(k: str, v):
    """Attribute values compared in a normal form: NIFs without dashes, CPVs without check digit."""
    if k == "nif":
        return G.norm_nif(v) or v
    if k == "cpv" and isinstance(v, str):
        return ", ".join(sorted({c.strip().split("-")[0] for c in v.split(",") if c.strip()}))
    if k == "points":
        return _points(v)
    return _num(v) if isinstance(v, (int, float)) else str(v).strip()


def _num(v):
    try:
        return round(float(v), 2)
    except (TypeError, ValueError):
        return None


def _points(v):
    """A criterion's weight. 0 is what an acta gives a bid, not a weight: it says nothing."""
    p = _num(v)
    return p if p else None


# ── mentions ──────────────────────────────────────────────────────────────

def mentions(cfg: PilotConfig, store: Store):
    """Rebuild the mention and mention-relation tables from every chunk NER has read."""
    schema(store)
    texts: dict[str, list[str]] = {}
    pages: dict[str, list] = {}
    rows, rels = [], []
    for r in store.q("SELECT c.sha, c.idx, c.result_json, b.text_path FROM chunk c JOIN blob b ON b.sha=c.sha"
                     " WHERE c.status='ok' ORDER BY c.sha, c.idx"):
        sha = r["sha"]
        if sha not in texts:
            texts[sha] = split_words(Path(r["text_path"]).read_text(encoding="utf-8"), cfg.chunk_words)
            pages[sha] = page_ranges(texts[sha])
        if r["idx"] >= len(texts[sha]):
            continue
        chunk = texts[sha][r["idx"]]
        out = json.loads(r["result_json"])
        ids = []
        for k, e in enumerate(out.get("entities", [])):
            mid = f"{sha}:{r['idx']}:{k}"
            ids.append(mid)
            span = locate(chunk, e.get("evidence_text") or "") or locate(chunk, e.get("mention_text") or e.get("name") or "")
            page = page_at(chunk, span[0], pages[sha][r["idx"]][0]) if span else pages[sha][r["idx"]][0]
            name = _name_span(chunk, span, e.get("mention_text") or "", e.get("name") or "") if span else None
            rows.append((mid, sha, r["idx"], k, e.get("type"), e.get("subtype"), (e.get("name") or "").strip(),
                         e.get("mention_text"), json.dumps(e.get("attributes") or {}, ensure_ascii=False),
                         e.get("evidence_text"), e.get("confidence"), span[0] if span else None,
                         span[1] if span else None, page, int(span is not None),
                         name[0] if name else None, name[1] if name else None))
        for k, rel in enumerate(out.get("relations", [])):
            if 0 <= rel.get("head", -1) < len(ids) and 0 <= rel.get("tail", -1) < len(ids):
                rels.append((f"{sha}:{r['idx']}:r{k}", sha, r["idx"], ids[rel["head"]], ids[rel["tail"]], rel["type"],
                             rel.get("subtype"), json.dumps(rel.get("attributes") or {}, ensure_ascii=False),
                             rel.get("evidence_text"), rel.get("confidence")))
    with store.stage("mentions") as st, store.tx() as c:
        c.execute("DELETE FROM mention")
        c.execute("DELETE FROM mrelation")
        c.execute("DELETE FROM coref_run")
        c.executemany("INSERT INTO mention (id, sha, idx, k, type, subtype, name, surface, attributes, evidence, confidence,"
                      " char_start, char_end, page, located, name_start, name_end, kind)"
                      " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,'ner')", rows)
        c.executemany("INSERT INTO mrelation VALUES (?,?,?,?,?,?,?,?,?,?)", rels)
        st["items"] = len(rows)
    located = sum(r[14] for r in rows)
    log(f"mentions: {len(rows)} mentions ({located} located in their chunk), {len(rels)} relations")


# ── resolve ───────────────────────────────────────────────────────────────

class _UF:
    def __init__(self):
        self.parent: dict[str, str] = {}
        self.anchor: dict[str, str | None] = {}   # root -> the feed node it is, if any

    def add(self, x: str, anchor: str | None = None):
        if x not in self.parent:
            self.parent[x] = x
            self.anchor[x] = anchor

    def find(self, x: str) -> str:
        while self.parent[x] != x:
            self.parent[x] = self.parent[self.parent[x]]
            x = self.parent[x]
        return x

    def union(self, a: str, b: str) -> bool:
        ra, rb = self.find(a), self.find(b)
        if ra == rb:
            return False
        if self.anchor[ra] and self.anchor[rb]:
            return False          # two feed nodes are never the same thing
        self.parent[ra] = rb
        self.anchor[rb] = self.anchor[rb] or self.anchor[ra]
        return True

    def groups(self) -> dict[str, list[str]]:
        out = defaultdict(list)
        for x in self.parent:
            out[self.find(x)].append(x)
        return out


def _anchors(eid: str, e, t: dict) -> tuple[G.Graph, dict]:
    """The feed's nodes for this expediente, built exactly as graph.py builds them."""
    g = G.Graph()
    _, sk = G._feed_skeleton(g, eid, e, t, None)
    return g, sk


def _attrs(m) -> dict:
    return json.loads(m["attributes"] or "{}")


def _lot_of(m, lots: dict[str, str]) -> str | None:
    num = re.sub(r"(?i)^lote\s*", "", str(_attrs(m).get("number") or "")).strip()
    if num in lots:
        return lots[num]
    hit = re.search(r"(?i)\blote\s*(?:n[º°.]?\s*)?(\w+)", m["name"] or "")
    if hit and hit.group(1) in lots:
        return lots[hit.group(1)]
    return next(iter(lots.values())) if len(lots) == 1 else None


def resolve(cfg: PilotConfig, store: Store):
    schema(store)
    svc = Services(cfg, store)
    done = {r["exp_id"]: r["mentions"] for r in store.q("SELECT exp_id, mentions FROM resolution WHERE status='ok'")}
    exps = store.q("SELECT * FROM expediente ORDER BY id")
    with store.stage("resolve") as st:
        for e in exps:
            ms = store.q("SELECT m.* FROM mention m WHERE m.kind='ner' AND m.sha IN"
                         " (SELECT sha FROM docref WHERE exp_id=? AND status='fetched') ORDER BY m.id", (e["id"],))
            if done.get(e["id"]) == len(ms):
                continue
            t0 = time.time()
            try:
                stats = _resolve_expediente(svc, store, e, ms)
                status, err = ("ok" if not stats.get("llm_failed") else "partial"), None
            except Exception as exc:  # keep going: validation reports the expediente
                stats, status, err = {}, "failed", f"{type(exc).__name__}: {exc}"[:500]
            with store.tx() as c:
                c.execute("INSERT OR REPLACE INTO resolution VALUES (?,?,?,?,?,?,?,?)",
                          (e["id"], status, int((time.time() - t0) * 1000), len(ms), stats.get("entities"),
                           json.dumps(stats.get("merges", {})), stats.get("llm_calls", 0), err))
            st["items"] += 1
            log(f"resolve {e['id']}: {len(ms)} mentions -> {stats.get('entities')} entities {stats.get('merges', {})} {err or ''}")


def _resolve_expediente(svc: Services, store: Store, e, ms: list) -> dict:
    eid = e["id"]
    t = json.loads(e["tender_json"])
    fg, sk = _anchors(eid, e, t)
    lots = {fg.nodes[l]["number"]: l for l in sk["lots"].values()}
    lot_names = {l: fg.nodes[l].get("name") or "" for l in sk["lots"].values()}
    feed = defaultdict(list)                       # label -> feed nodes
    for n in fg.nodes.values():
        feed[n["label"]].append(n)
    auth_id = sk["auth"]
    by_id = {m["id"]: m for m in ms}
    uf = _UF()
    merges = Counter()
    for m in ms:
        uf.add(m["id"])
    for n in feed["AwardCriterion"] + [n for n in feed["Requirement"] if not _reference_only(n)]:
        uf.add(n["id"], n["id"])

    def join(a: str, b: str, how: str):
        if uf.union(a, b):
            merges[how] += 1

    def anchor(m_id: str, node_id: str, how: str = "feed"):
        uf.add(node_id, node_id)
        join(m_id, node_id, how)

    # 1. Feed anchors and keys.
    keys: dict[tuple, str] = {}
    for m in ms:
        typ, a = m["type"], _attrs(m)
        key = None
        if typ in ORG_TYPES or typ == "JOINT_VENTURE":
            nif = G.norm_nif(a.get("nif"))
            if (typ == "CONTRACTING_AUTHORITY" and _is_authority(m["name"], fg.nodes[auth_id], nif)) or \
                    (typ == "OTHER_ORGANIZATION" and _AUTHORITY_BODY.search(G.norm_name(m["name"]))):
                anchor(m["id"], auth_id)
                continue
            prefix = "jv" if typ == "JOINT_VENTURE" else "org"
            if nif:
                oid = f"{prefix}:nif:{nif}"
                if oid in fg.nodes:
                    anchor(m["id"], oid)
                    continue
                key = ("org", oid)
            else:
                key = ("org", f"{prefix}:name:{G.norm_name(m['name'])}")
        elif typ == "LOT":
            lid = _lot_of(m, lots)
            if lid is None:
                best = max(lot_names.items(), key=lambda kv: similarity(kv[1], m["name"]), default=None)
                lid = best[0] if best and similarity(best[1], m["name"]) >= ANCHOR_SIMILAR else None
            if lid:
                anchor(m["id"], lid)
                continue
            key = ("LOT", G.norm_name(m["name"]))
        elif typ == "AWARD_CRITERION":
            hit = _best_feed(m, feed["AwardCriterion"], points=True)
            if hit:
                anchor(m["id"], hit)
                continue
        elif typ == "REQUIREMENT":
            hit = _best_feed(m, [n for n in feed["Requirement"] if not _reference_only(n)])
            if hit:
                anchor(m["id"], hit)
                continue
        elif typ == "GUARANTEE":
            sub = (m["subtype"] or "").upper()
            hit = next((n["id"] for n in feed["Guarantee"] if _guarantee_kind(n) == sub), None)
            if hit:
                anchor(m["id"], hit)
                continue
            key = ("GUARANTEE", sub or G.norm_name(m["name"]))
        elif typ == "CONTRACT" and len(sk["contracts"]) == 1:
            anchor(m["id"], sk["contracts"][0])
            continue
        if key is None:
            key = (typ, G.norm_name(m["name"]))
        if key in keys:
            join(m["id"], keys[key], "key")
        else:
            keys[key] = m["id"]
            if key[0] == "org" and key[1] in fg.nodes:
                anchor(m["id"], key[1])

    # Bids: one per lot and bidder. The bidder comes from SUBMITTED_BY, else from the bid's name.
    _resolve_bids(store, ms, uf, fg, sk, lots, join, anchor)

    # 2. Near-identical names of the same type (typos, plurals, "S.A." vs ", SA").
    roots = _roots(uf, by_id)
    for typ, rs in roots.items():
        if typ in ("LOT", "BID"):
            continue
        for i, a in enumerate(rs):
            for b in rs[i + 1:]:
                if uf.find(a["root"]) == uf.find(b["root"]):
                    continue
                if _compatible(a, b) and similarity(a["name"], b["name"]) >= SIMILAR and typo_equal(a["name"], b["name"]):
                    join(a["root"], b["root"], "similar")
    # Companies without NIF that are a known company of this expediente misspelt.
    orgs = [r for r in _roots(uf, by_id).get("COMPANY", [])]
    for a in orgs:
        for b in orgs:
            if a is not b and a["nif"] and not b["nif"] and similarity(a["name"], b["name"]) >= 0.85:
                join(b["root"], a["root"], "similar")

    # 3. The model, type by type, over what is left (feed nodes included as candidates).
    llm_calls, llm_failed = 0, False
    roots = _roots(uf, by_id, fg)
    for typ, rs in roots.items():
        if typ in ("LOT", "BID", "CONTRACTING_AUTHORITY") or len(rs) < 2:
            continue
        rs = sorted(rs, key=lambda r: G.norm_name(r["name"]))
        for i in range(0, len(rs), LLM_BATCH):
            batch = rs[i:i + LLM_BATCH]
            names = defaultdict(list)
            for r in batch:
                names[r["name"]].append(r["root"])
            body = [{"name": n, "type": typ, "subtype": next((r["subtype"] for r in batch if r["name"] == n), None),
                     "evidence": next((r["evidence"] for r in batch if r["name"] == n), "") or n} for n in names]
            try:
                out = svc.resolve(body, [], exp_id=eid)
                llm_calls += 1
            except ServiceError:
                llm_failed = True
                continue
            info = {r["root"]: r for r in batch}
            for ent in out.get("entities", []):
                group = [root for n in ent.get("names", []) for root in names.get(n, [])]
                for other in group[1:]:
                    if _compatible(info[other], info[group[0]]):
                        join(other, group[0], "llm")

    n = _write(store, eid, e, t, ms, by_id, uf, fg, sk, lots)
    return {"entities": n, "merges": dict(merges), "llm_calls": llm_calls, "llm_failed": llm_failed}


def _is_authority(name: str, auth: dict, nif: str | None) -> bool:
    if nif and auth.get("nif") and nif == auth["nif"]:
        return True
    n = G.norm_name(name)
    if n in GENERIC_AUTHORITY or len(tokens(name)) <= 1 or _AUTHORITY_BODY.search(n):
        return True
    an = auth.get("name") or ""
    ta, tm = tokens(an), tokens(name)
    return similarity(an, name) >= 0.75 or (len(tm) >= 2 and (tm <= ta or ta <= tm))


def _reference_only(n: dict) -> bool:
    text = n.get("text") or n.get("name") or ""
    return n.get("amount") is None and len(text) < 160 and bool(_REFERENCE_ONLY.search(text))


def _guarantee_kind(n: dict) -> str | None:
    """CODICE GuaranteeTypeCode (in the feed node's id): 1 provisional, 2 definitive ("Final"), 3 complementary."""
    code = n["id"].split(":")[2] if n["id"].count(":") >= 3 else None
    by_code = {"1": "PROVISIONAL", "2": "DEFINITIVE", "3": "COMPLEMENTARY"}.get(code)
    f = fold(n.get("name"))
    return by_code or ("DEFINITIVE" if "definitiv" in f or "final" in f else "PROVISIONAL" if "provisional" in f
                       else "COMPLEMENTARY" if "complementari" in f else None)


def _best_feed(m, nodes: list[dict], points: bool = False) -> str | None:
    p = _points(_attrs(m).get("points"))
    best, score = None, 0.0
    for n in nodes:
        s = similarity(n.get("name") or "", m["name"])
        np_ = _points(n.get("points"))
        if points and p is not None and np_ is not None:
            if p == np_:
                s += 0.15
            elif s < 0.9:
                continue       # same words, different weight: a different line of the baremo
        if s > score:
            best, score = n["id"], s
    return best if score >= ANCHOR_SIMILAR else None


def _resolve_bids(store, ms, uf, fg, sk, lots, join, anchor):
    mention_of = {m["id"]: m for m in ms}
    bidder = {}
    shas = sorted({m["sha"] for m in ms})
    for r in store.q("SELECT head, tail FROM mrelation WHERE type='SUBMITTED_BY' AND sha IN (%s)"
                     % ",".join("?" * len(shas)), shas) if shas else []:
        if r["head"] in mention_of and r["tail"] in mention_of:
            bidder[r["head"]] = r["tail"]
    winners = {}
    for b in [n for n in fg.nodes.values() if n["label"] == "Bid"]:
        lid = next((l for l in fg.into(b["id"], "RECEIVED_BID")), None)
        for o in fg.out(b["id"], "SUBMITTED_BY"):
            winners[(lid, o)] = b["id"]
    seen = {}
    for m in ms:
        if m["type"] != "BID":
            continue
        lid = _lot_of(m, lots)
        org = None
        if m["id"] in bidder:
            org = _root_org(uf, bidder[m["id"]])
        if org is None:   # "Oferta de X al lote 1": the company whose name is in the bid's
            cands = [x for x in ms if x["type"] in ("COMPANY", "JOINT_VENTURE") and x["name"]
                     and similarity(x["name"], m["name"]) > 0 and G.norm_name(x["name"]) in G.norm_name(m["name"])]
            cands = cands or [x for x in ms if x["type"] in ("COMPANY", "JOINT_VENTURE")
                              and G.norm_name(x["name"]) and len(tokens(x["name"]) & tokens(m["name"])) >= 2]
            org = _root_org(uf, cands[0]["id"]) if cands else None
        if org and (lid, org) in winners:
            anchor(m["id"], winners[(lid, org)])
            continue
        key = (lid, org or G.norm_name(m["name"]))
        if key in seen:
            join(m["id"], seen[key], "key")
        else:
            seen[key] = m["id"]


def _root_org(uf: _UF, mention_id: str) -> str:
    r = uf.find(mention_id)
    return uf.anchor.get(r) or r


def _roots(uf: _UF, by_id: dict, fg: G.Graph | None = None) -> dict[str, list[dict]]:
    """One candidate per current group: its type, a name, a quote, NIF and points."""
    out = defaultdict(list)
    for root, members in uf.groups().items():
        ms = [by_id[x] for x in members if x in by_id]
        anchor = uf.anchor.get(root)
        if not ms and not (fg and anchor):
            continue
        if anchor and fg is not None and anchor in fg.nodes:
            node = fg.nodes[anchor]
            typ = ms[0]["type"] if ms else _TYPE_OF_LABEL.get(node["label"])
            name = node.get("name") or (ms[0]["name"] if ms else anchor)
            evidence = node.get("formula") or node.get("text") or (ms[0]["evidence"] if ms else "")
        elif ms:
            typ = Counter(m["type"] for m in ms).most_common(1)[0][0]
            name = Counter(m["name"] for m in ms).most_common(1)[0][0]
            evidence = next((m["evidence"] for m in ms if m["evidence"]), "")
        else:
            continue
        if not typ:
            continue
        nif = next((G.norm_nif(_attrs(m).get("nif")) for m in ms if G.norm_nif(_attrs(m).get("nif"))), None)
        pts = next((_points(_attrs(m).get("points")) for m in ms if _points(_attrs(m).get("points"))), None)
        sub = Counter(m["subtype"] for m in ms if m["subtype"]).most_common(1)
        out[typ].append({"root": root, "name": name, "evidence": evidence, "nif": nif, "points": pts,
                         "subtype": sub[0][0] if sub else None, "anchor": anchor})
    return out


_TYPE_OF_LABEL = {"AwardCriterion": "AWARD_CRITERION", "Requirement": "REQUIREMENT", "Guarantee": "GUARANTEE",
                  "Organization": "COMPANY", "Lot": "LOT", "Contract": "CONTRACT", "Bid": "BID"}


def _compatible(a: dict, b: dict) -> bool:
    if a["anchor"] and b["anchor"]:
        return False
    if a["nif"] and b["nif"] and a["nif"] != b["nif"]:
        return False
    if a["points"] is not None and b["points"] is not None and a["points"] != b["points"]:
        return False
    return True


def _entity_id(typ: str, eid: str, name: str, nif: str | None, taken: set) -> tuple[str, str]:
    if typ in ORG_TYPES:
        return G.org_id(name, nif), "global"
    if typ == "JOINT_VENTURE":
        return f"jv:{nif or G.norm_name(name)}", "global"
    if typ == "QUALIFICATION":
        return f"qualification:{G.norm_name(name)[:80]}", "global"
    base = f"{typ.lower()}:{eid}:{G.norm_name(name)[:80]}"
    nid, k = base, 2
    while nid in taken:
        nid, k = f"{base}~{k}", k + 1
    return nid, "expediente"


def _merge_attrs(ms: list, feed_node: dict | None) -> tuple[dict, dict]:
    """Most frequent value per attribute (confidence breaks ties); feed values win. Values that
    disagree are kept as conflicts, with how many mentions said each."""
    seen: dict[str, Counter] = defaultdict(Counter)
    conf: dict[tuple, float] = {}
    for m in ms:
        for k, v in _attrs(m).items():
            key = _value(k, v) if v not in (None, "") else None
            if key in (None, ""):
                continue
            seen[k][key] += 1
            conf[(k, key)] = max(conf.get((k, key), 0), m["confidence"] or 0)
    out, conflicts = {}, {}
    for k, c in seen.items():
        ranked = sorted(c.items(), key=lambda kv: (-kv[1], -conf[(k, kv[0])]))
        out[k] = ranked[0][0]
        if len(ranked) > 1:
            conflicts[k] = [{"value": v, "mentions": n} for v, n in ranked]
    if feed_node:
        for k in list(out):
            fv = feed_node.get(k)
            if fv not in (None, "", []):
                if _value(k, ", ".join(fv) if isinstance(fv, list) else fv) != out[k]:
                    conflicts.setdefault(k, [{"value": out[k], "mentions": seen[k][out[k]]}])
                    conflicts[k].insert(0, {"value": fv, "source": "feed"})
                out[k] = fv
    return out, conflicts


def _write(store, eid, e, t, ms, by_id, uf, fg, sk, lots) -> int:
    lot_of_mention = {}
    for r in store.q("SELECT head, tail, type FROM mrelation WHERE sha IN (SELECT sha FROM docref WHERE exp_id=?)", (eid,)):
        if r["type"] in LOT_RELS:
            for lot_side, other in ((r["head"], r["tail"]), (r["tail"], r["head"])):
                if lot_side in by_id and by_id[lot_side]["type"] == "LOT":
                    lot_of_mention.setdefault(other, set()).add(lot_side)
    groups = uf.groups()
    root_entity, rows, links, taken = {}, [], [], set()
    for root, members in groups.items():
        mm = [by_id[x] for x in members if x in by_id]
        anchor = uf.anchor.get(root)
        if not mm:
            continue
        typ = Counter(m["type"] for m in mm).most_common(1)[0][0]
        node = fg.nodes.get(anchor) if anchor else None
        nif = next((G.norm_nif(_attrs(m).get("nif")) for m in mm if G.norm_nif(_attrs(m).get("nif"))), None)
        names = Counter(m["name"] for m in mm if m["name"])
        best = sorted(names.items(), key=lambda kv: (-kv[1], -len(kv[0])))
        name = (node or {}).get("name") or (best[0][0] if best else "")
        if node:
            nid, scope = anchor, ("global" if anchor.startswith(("org:", "jv:")) else "expediente")
        else:
            nid, scope = _entity_id(typ, eid, name, nif, taken)
        taken.add(nid)
        attrs, conflicts = _merge_attrs(mm, node)
        if nif:
            attrs["nif"] = nif
        sub = Counter(m["subtype"] for m in mm if m["subtype"]).most_common()
        subtype = (node or {}).get("subtype") or (sub[0][0] if sub else None)
        if node and node.get("subtype") and sub and sub[0][0] != node["subtype"]:
            conflicts["subtype"] = [{"value": node["subtype"], "source": "feed"}] + [{"value": v, "mentions": n} for v, n in sub]
        lot_ids = set()
        for m in mm:
            for lm in lot_of_mention.get(m["id"], ()):
                lid = _root_lot(uf, lm, by_id, lots)
                if lid:
                    lot_ids.add(lid)
        root_entity[root] = nid
        rows.append((eid, nid, scope, typ, G.LABEL.get(typ, typ.title()), name, subtype, int(bool(node)),
                     "feed" if node else ("single" if len(mm) == 1 else "merged"),
                     json.dumps(sorted({m["name"] for m in mm if m["name"]}), ensure_ascii=False),
                     json.dumps(attrs, ensure_ascii=False), json.dumps(conflicts, ensure_ascii=False),
                     json.dumps(sorted(lot_ids)), json.dumps(sorted({m["sha"] for m in mm})), len(mm)))
        links += [(eid, m["id"], nid) for m in mm]
    # Feed criteria and requirements nobody mentioned are still entities: they get described too.
    mentioned = {r[1] for r in rows}
    for n in fg.nodes.values():
        if n["label"] in ("AwardCriterion", "Requirement") and n["id"] not in mentioned:
            typ = _TYPE_OF_LABEL[n["label"]]
            rows.append((eid, n["id"], "expediente", typ, n["label"], n.get("name"), n.get("subtype"), 1, "feed",
                         "[]", json.dumps({k: n[k] for k in ("points", "formula", "text", "amount") if n.get(k) is not None},
                                          ensure_ascii=False), "{}", "[]", "[]", 0))
    rel_rows = _relations(store, eid, by_id, uf, root_entity)
    # Feed requirements that only point at the PCAP are spelt out by the requirements of the
    # documents where solvency is set (the pliego administrativo and the notice), not the PPT's.
    role_of = {r["sha"]: r["role"] for r in store.q("SELECT sha, MIN(role) role FROM docref WHERE exp_id=? GROUP BY sha", (eid,))}
    solvency_docs = {"PCAP", "PCAP+PPT", "TenderNotice", "Clarification"}
    req_rows = [r for r in rows if r[3] == "REQUIREMENT" and any(role_of.get(x) in solvency_docs for x in json.loads(r[13]))]
    for n in fg.nodes.values():
        if n["label"] == "Requirement" and _reference_only(n):
            want = _GROUP_SUBTYPES.get(n.get("group") or "", set())
            for r in req_rows:
                if not r[7] and r[6] in want:
                    rel_rows.append((eid, f"{n['id']}|DETAILED_BY|{r[1]}", n["id"], "DETAILED_BY", r[1], None, "{}", "[]", "[]"))
    with store.tx() as c:
        # What was refined and described for the previous entities no longer applies: their
        # members may have changed. Shared entities are described again from all expedientes.
        shared = [r[1] for r in rows if r[2] == "global"]
        c.executemany("DELETE FROM entity_description WHERE exp_id='*' AND kind='entity' AND item_id=?", [(x,) for x in shared])
        for table in ("entity", "entity_mention", "entity_relation", "refinement", "entity_description", "coref_run", "formula"):
            c.execute(f"DELETE FROM {table} WHERE exp_id=?", (eid,))
        c.execute("DELETE FROM mention WHERE kind='coref' AND id LIKE ?", (f"%:c:{eid}:%",))
        c.execute("DELETE FROM extraction WHERE exp_id=? AND kind='tender_description'", (eid,))
        c.executemany("INSERT OR REPLACE INTO entity VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", rows)
        c.executemany("INSERT OR REPLACE INTO entity_mention VALUES (?,?,?)", links)
        c.executemany("INSERT OR REPLACE INTO entity_relation VALUES (?,?,?,?,?,?,?,?,?)", rel_rows)
    return len(rows)


def _root_lot(uf, lot_mention, by_id, lots) -> str | None:
    a = uf.anchor.get(uf.find(lot_mention))
    if a:
        return a
    return _lot_of(by_id[lot_mention], lots)


def _relations(store, eid, by_id, uf, root_entity) -> list[tuple]:
    agg: dict[tuple, dict] = {}
    for r in store.q("SELECT * FROM mrelation WHERE sha IN (SELECT sha FROM docref WHERE exp_id=? AND status='fetched')", (eid,)):
        if r["head"] not in by_id or r["tail"] not in by_id:
            continue
        src, dst = root_entity.get(uf.find(r["head"])), root_entity.get(uf.find(r["tail"]))
        if not src or not dst or src == dst:
            continue
        a = agg.setdefault((src, r["type"], dst), {"subtype": r["subtype"], "attrs": {}, "evidence": [], "mentions": []})
        for k, v in json.loads(r["attributes"] or "{}").items():
            if v not in (None, ""):
                a["attrs"].setdefault(k, v)
        if r["evidence"] and r["evidence"] not in a["evidence"]:
            a["evidence"].append(r["evidence"])
        a["mentions"].append(r["id"])
    return [(eid, f"{s}|{t}|{d}", s, t, d, a["subtype"], json.dumps(a["attrs"], ensure_ascii=False),
             json.dumps(a["evidence"][:8], ensure_ascii=False), json.dumps(a["mentions"]))
            for (s, t, d), a in agg.items()]


# ── passages: what an entity's description and refinement read ───────────

def passages(store: Store, cfg: PilotConfig, exp_id: str, entity_id: str, window: int = 600, limit: int = 6) -> list[str]:
    """Each located mention with the text around it, headed by document position, role and page."""
    rows = store.q(
        "SELECT m.*, (SELECT MIN(role) FROM docref WHERE sha=m.sha) role, b.text_path FROM entity_mention em"
        " JOIN mention m ON m.id=em.mention_id JOIN blob b ON b.sha=m.sha"
        " WHERE em.exp_id=? AND em.entity_id=? ORDER BY m.kind='ner' DESC, m.located DESC, m.confidence DESC", (exp_id, entity_id))
    out, seen, texts = [], {}, {}
    for m in rows:
        if m["sha"] not in texts:
            texts[m["sha"]] = split_words(Path(m["text_path"]).read_text(encoding="utf-8"), cfg.chunk_words)
        chunk = texts[m["sha"]][m["idx"]]
        if m["located"]:
            # A mention already inside a passage taken for this entity adds nothing new.
            if any(x <= m["char_start"] and m["char_end"] <= y for x, y in seen.get((m["sha"], m["idx"]), [])):
                continue
            a, b = max(0, m["char_start"] - window), min(len(chunk), m["char_end"] + window)
            body = chunk[a:b]
            seen.setdefault((m["sha"], m["idx"]), []).append((a, b))
        else:
            body = m["evidence"] or ""
        if not body.strip():
            continue
        ref = f" · referencia «{m['name']}»" if m["kind"] == "coref" else ""
        out.append(f"[{m['role'] or 'Documento'} · pág. {m['page'] or '?'}{ref}] {body.strip()}")
        if len(out) >= limit:
            break
    return out


# ── coref ─────────────────────────────────────────────────────────────────

# What a passage needs for a reference to be worth asking about: a definite description of a
# party, a demonstrative, or an anaphoric "el mismo / la misma".
CUE = re.compile(
    r"\b(la|dicha|esta|la citada|la referida|la mencionada|la indicada)\s+(empresa|entidad|mercantil|sociedad|licitadora|"
    r"adjudicataria|contratista|uni[oó]n temporal)\b"
    r"|\b(el|dicho|el citado|el referido|el mencionado)\s+(adjudicatario|licitador propuesto|licitador seleccionado)\b"
    r"|\b(dicho|este|el citado|el referido|el mencionado|esta|dicha|la citada|la referida)\s+"
    r"(contratista|ayuntamiento|lote|contrato|organismo|corporaci[oó]n|alcald[ií]a|administraci[oó]n|mesa|"
    r"diputaci[oó]n|consejer[ií]a|[oó]rgano)\b"
    r"|\b(la misma|el mismo|las mismas|los mismos)\b", re.I)
COREF_TYPES = ("CONTRACTING_AUTHORITY", "COMPANY", "JOINT_VENTURE", "OTHER_ORGANIZATION", "LOT", "CONTRACT")
COREF_CANDIDATES = 15


def coref(cfg: PilotConfig, store: Store):
    schema(store)
    svc = Services(cfg, store)
    done = {r["exp_id"] for r in store.q("SELECT exp_id FROM coref_run WHERE status=?", ("ok" if cfg.coref else "off",))}
    with store.stage("coref") as st:
        for e in store.q("SELECT e.* FROM expediente e JOIN resolution r ON r.exp_id=e.id WHERE r.status IN ('ok','partial')"):
            if e["id"] in done:
                continue
            t0 = time.time()
            stats = _coref_expediente(cfg, store, svc, e["id"]) if cfg.coref else \
                {"status": "off", "chunks": 0, "calls": 0, "links": 0}
            with store.tx() as c:
                c.execute("INSERT OR REPLACE INTO coref_run VALUES (?,?,?,?,?,?,?)",
                          (e["id"], stats["status"], int((time.time() - t0) * 1000), stats["chunks"], stats["calls"],
                           stats["links"], stats.get("error")))
            st["items"] += 1
            if stats["status"] == "failed":
                # Every call failed: the service is down or lacks /coref/links, and so it will be for the rest.
                raise SystemExit(f"coref {e['id']}: all {stats['calls']} /coref/links calls failed, last error: "
                                 f"{stats.get('error')}. Update nlp_service, or set PILOT_COREF=0 to skip this stage.")
            log(f"coref {e['id']}: {stats['chunks']} passages with references, {stats['links']} references linked")


def _coref_expediente(cfg: PilotConfig, store: Store, svc: Services, eid: str) -> dict:
    cands = store.q("SELECT id, type, name, attributes FROM entity WHERE exp_id=? AND type IN (%s) ORDER BY mentions DESC"
                    % ",".join("?" * len(COREF_TYPES)), (eid, *COREF_TYPES))[:COREF_CANDIDATES]
    if not cands:
        return {"status": "ok", "chunks": 0, "calls": 0, "links": 0}
    listing = [{"name": c["name"], "type": c["type"]} for c in cands]
    rows = store.q("SELECT c.sha, c.idx, b.text_path, (SELECT MIN(role) FROM docref WHERE sha=c.sha AND exp_id=?) role,"
                   " (SELECT MIN(label) FROM docref WHERE sha=c.sha AND exp_id=?) label FROM chunk c JOIN blob b ON b.sha=c.sha"
                   " WHERE c.status='ok' AND c.sha IN (SELECT sha FROM docref WHERE exp_id=? AND status='fetched')"
                   " ORDER BY c.sha, c.idx", (eid, eid, eid))
    texts, pages, jobs = {}, {}, []
    for r in rows:
        if r["sha"] not in texts:
            texts[r["sha"]] = split_words(Path(r["text_path"]).read_text(encoding="utf-8"), cfg.chunk_words)
            pages[r["sha"]] = page_ranges(texts[r["sha"]])
        chunk = texts[r["sha"]][r["idx"]] if r["idx"] < len(texts[r["sha"]]) else ""
        if CUE.search(chunk):
            jobs.append((r, chunk))
    # What NER already placed, so a reference is not annotated twice.
    named = defaultdict(list)
    for m in store.q("SELECT m.sha, m.idx, m.char_start, m.char_end FROM entity_mention em JOIN mention m ON m.id=em.mention_id"
                     " WHERE em.exp_id=? AND m.located=1", (eid,)):
        named[(m["sha"], m["idx"])].append((m["char_start"], m["char_end"]))

    def one(job):
        r, chunk = job
        try:
            return job, svc.coref_links(chunk, listing, f"{r['role'] or 'Documento'}: {r['label'] or ''}", exp_id=eid, sha=r["sha"]), None
        except ServiceError as exc:
            return job, [], str(exc)

    new_mentions, links, errors, k = [], [], [], 0
    with _pool(cfg.nlp_workers) as pool:
        for (r, chunk), found, err in pool.map(one, jobs):
            if err:
                errors.append(err)
            taken = list(named[(r["sha"], r["idx"])])
            for link in found:
                span = _locate_reference(chunk, link["mention"], link.get("evidence") or "", taken)
                cand = cands[link["candidate"]]
                k += 1
                mid = f"{r['sha']}:{r['idx']}:c:{eid}:{k}"
                if span:
                    taken.append(span)
                page = page_at(chunk, span[0], pages[r["sha"]][r["idx"]][0]) if span else pages[r["sha"]][r["idx"]][0]
                new_mentions.append((mid, r["sha"], r["idx"], k, cand["type"], None, link["mention"], link["mention"], "{}",
                                     link.get("evidence"), None, span[0] if span else None, span[1] if span else None,
                                     page, int(span is not None), "coref", span[0] if span else None, span[1] if span else None))
                links.append((eid, mid, cand["id"]))
    if errors and len(errors) == len(jobs):
        return {"status": "failed", "chunks": len(jobs), "calls": len(jobs), "links": 0, "error": errors[-1][:300]}
    with store.tx() as c:
        c.execute("DELETE FROM mention WHERE kind='coref' AND id LIKE ?", (f"%:c:{eid}:%",))
        c.execute("DELETE FROM entity_mention WHERE exp_id=? AND mention_id LIKE ?", (eid, f"%:c:{eid}:%"))
        c.executemany("INSERT INTO mention (id, sha, idx, k, type, subtype, name, surface, attributes, evidence, confidence,"
                      " char_start, char_end, page, located, kind, name_start, name_end)"
                      " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", new_mentions)
        c.executemany("INSERT OR REPLACE INTO entity_mention VALUES (?,?,?)", links)
        # Descriptions and the expediente summary read the mentions: what was written before these is stale.
        c.execute("DELETE FROM entity_description WHERE exp_id=? AND kind='entity'", (eid,))
        c.execute("DELETE FROM extraction WHERE exp_id=? AND kind='tender_description'", (eid,))
    return {"status": "ok", "chunks": len(jobs), "calls": len(jobs), "links": len(links),
            "error": errors[0][:300] if errors else None}


def _locate_reference(chunk: str, mention: str, evidence: str, taken: list) -> tuple[int, int] | None:
    """The reference inside its sentence, else its first free occurrence in the chunk."""
    def free(a, b):
        return all(b <= x or a >= y for x, y in taken)
    ev = locate(chunk, evidence) if evidence else None
    if ev:
        seg = chunk[ev[0]:ev[1]]
        i = fold(seg).find(fold(mention))
        if i >= 0 and free(ev[0] + i, ev[0] + i + len(mention)):
            return ev[0] + i, ev[0] + i + len(mention)
    f, m = fold(chunk), fold(mention)
    i = f.find(m)
    while i >= 0:
        if free(i, i + len(mention)):
            return i, i + len(mention)
        i = f.find(m, i + 1)
    return None


# ── refine ────────────────────────────────────────────────────────────────

REFINE_SCHEMAS = {
    "REQUIREMENT": {"entity_types": [{
        "name": "REQUIREMENT_DETAIL",
        "description": "El requisito exigido a los licitadores que describe el texto, con sus cifras exactas.",
        "subtypes": [{"name": s, "description": d} for s, d in [
            ("ECONOMIC_TURNOVER", "Volumen anual de negocios"), ("ECONOMIC_NET_WORTH", "Patrimonio neto o ratios financieros"),
            ("INSURANCE", "Seguro de responsabilidad civil u otro"), ("SIMILAR_WORK", "Trabajos o servicios similares ejecutados"),
            ("STAFF_QUALIFICATION", "Titulación o experiencia del personal"), ("TEAM_MINIMUM", "Equipo o número mínimo de personas"),
            ("MATERIAL_MEANS", "Medios materiales, instalaciones, maquinaria"), ("CERTIFICATION", "Certificación o norma (ISO, ENS...)"),
            ("CLASSIFICATION", "Clasificación empresarial (grupo, subgrupo, categoría)"),
            ("PROFESSIONAL_REGISTRATION", "Habilitación o inscripción profesional"),
            ("TECHNICAL_SPECIFICATION", "Especificación técnica de la prestación"), ("COMMITMENT", "Compromiso de adscripción o similar"),
            ("OTHER", "Otro")]],
        "attributes": [
            {"name": "threshold_amount", "datatype": "number", "description": "Cifra mínima exigida, sin unidad"},
            {"name": "threshold_unit", "datatype": "string", "description": "Unidad de la cifra: EUR, contratos, años, personas, %, horas..."},
            {"name": "period_years", "datatype": "number", "description": "Periodo de referencia en años (p. ej. 3 últimos ejercicios)"},
            {"name": "reference_base", "datatype": "string", "description": "Respecto a qué se mide (p. ej. 'mejor ejercicio', '1,5 veces el valor anual medio')"},
            {"name": "accreditation", "datatype": "string", "description": "Documentos o medios con que se acredita"},
            {"name": "standard", "datatype": "string", "description": "Norma, certificación o clasificación exigida, literal"},
            {"name": "applies_to_lots", "datatype": "string", "description": "Lotes a los que se aplica, si el texto lo dice"},
            {"name": "nature", "datatype": "string", "description": "solvencia (admisión) | condición de ejecución | criterio de adjudicación | especificación técnica"},
            {"name": "mandatory", "datatype": "boolean", "description": "true si es obligatorio para participar"},
        ]}], "relation_types": []},
    "AWARD_CRITERION": {"entity_types": [{
        "name": "CRITERION_DETAIL",
        "description": "El criterio de adjudicación que describe el texto, con sus puntos y su forma de valoración.",
        "subtypes": [{"name": "JUDGEMENT", "description": "Evaluable mediante juicio de valor"},
                     {"name": "FORMULA", "description": "Evaluable mediante fórmula o de forma automática"}],
        "attributes": [
            {"name": "points", "datatype": "number", "description": "Puntuación máxima del criterio"},
            {"name": "formula", "datatype": "string", "description": "Fórmula o regla de puntuación, literal"},
            {"name": "scoring_rule", "datatype": "string", "description": "Cómo se asignan los puntos, en una frase"},
            {"name": "subcriteria", "datatype": "string", "description": "Subcriterios con sus puntos, separados por ';'"},
            {"name": "threshold_points", "datatype": "number", "description": "Umbral mínimo de puntos para seguir en el procedimiento"},
            {"name": "envelope", "datatype": "string", "description": "Sobre o archivo en que se presenta"},
            {"name": "evidence_required", "datatype": "string", "description": "Documentación que debe aportar el licitador"},
            {"name": "applies_to_lots", "datatype": "string", "description": "Lotes a los que se aplica, si el texto lo dice"},
        ]}], "relation_types": []},
}


def refine(cfg: PilotConfig, store: Store):
    schema(store)
    svc = Services(cfg, store)
    done = {(r["exp_id"], r["entity_id"]) for r in store.q("SELECT exp_id, entity_id FROM refinement WHERE status='ok'")}
    jobs = [r for r in store.q("SELECT exp_id, id, type, name, attributes FROM entity WHERE type IN (%s)"
                               % ",".join("?" * len(REFINE_TYPES)), REFINE_TYPES) if (r["exp_id"], r["id"]) not in done]

    def one(r):
        t0 = time.time()
        text = "\n\n".join(passages(store, cfg, r["exp_id"], r["id"]))
        feed = json.loads(r["attributes"] or "{}")
        if not text.strip():
            text = " ".join(str(v) for v in [r["name"], feed.get("formula"), feed.get("text")] if v)
        text = f"{r['name']}\n\n{text}"[:6000]
        try:
            out = svc.ner(text, REFINE_SCHEMAS[r["type"]], exp_id=r["exp_id"])
        except ServiceError as e:
            return r, "failed", {"error": str(e)}, int((time.time() - t0) * 1000)
        ents = out.get("entities", [])
        best = max(ents, key=lambda x: (similarity(x.get("name") or "", r["name"]), x.get("confidence") or 0), default=None)
        result = {"subtype": best.get("subtype"), **{k: v for k, v in (best.get("attributes") or {}).items() if v not in (None, "")}} if best else {}
        return r, "ok", result, int((time.time() - t0) * 1000)

    with store.stage("refine") as st, _pool(cfg.nlp_workers) as pool:
        for f in pool.map(one, jobs):
            r, status, result, ms = f
            with store.tx() as c:
                c.execute("INSERT OR REPLACE INTO refinement VALUES (?,?,?,?,?)",
                          (r["exp_id"], r["id"], status, ms, json.dumps(result, ensure_ascii=False)))
            st["items"] += 1
    log(f"refine: {len(jobs)} requirements and criteria")


# ── formulas ──────────────────────────────────────────────────────────────

def formulas(cfg: PilotConfig, store: Store):
    """Each criterion scored by a rule (not a judgement): its formula as an expression with every
    symbol explained (nlp_service criterion_formula), for the viewer to render and evaluate."""
    schema(store)
    svc = Services(cfg, store)
    done = {(r["exp_id"], r["entity_id"]) for r in store.q("SELECT exp_id, entity_id FROM formula WHERE status='ok'")}
    refined = {(r["exp_id"], r["entity_id"]): json.loads(r["result_json"]) for r in
               store.q("SELECT exp_id, entity_id, result_json FROM refinement WHERE status='ok'")}
    jobs = []
    for r in store.q("SELECT exp_id, id, name, subtype, attributes FROM entity WHERE type='AWARD_CRITERION'"):
        ref = refined.get((r["exp_id"], r["id"]), {})
        if (r["exp_id"], r["id"]) in done or (ref.get("subtype") or r["subtype"]) == "JUDGEMENT":
            continue
        jobs.append((r, ref))

    def one(job):
        r, ref = job
        t0 = time.time()
        attrs = json.loads(r["attributes"] or "{}")
        points = _points(ref.get("points")) or _points(attrs.get("points"))
        fields = {"name": r["name"], "points": points if points is not None else "no consta",
                  "attributes_text": attributes_text(attrs, ref, {}),
                  "evidence": [p[:1500] for p in passages(store, cfg, r["exp_id"], r["id"], window=900, limit=4)]
                  or [r["name"]]}
        try:
            return r, "ok", svc.summarize("criterion_formula", fields, exp_id=r["exp_id"]), int((time.time() - t0) * 1000)
        except ServiceError as e:
            return r, "failed", {"error": str(e)}, int((time.time() - t0) * 1000)

    if jobs:
        r, status, out, ms = one(jobs[0])                  # a service without the profile: say so once
        if status == "failed" and ("422" in out["error"] or "404" in out["error"]):
            log("formulas: nlp_service has no criterion_formula profile yet; update it and run this stage again")
            return
        results = [(r, status, out, ms)]
    else:
        results = []
    found = failed = 0
    with store.stage("formulas") as st, _pool(cfg.nlp_workers) as pool:
        for r, status, out, ms in results + list(pool.map(one, jobs[1:])):
            with store.tx() as c:
                c.execute("INSERT OR REPLACE INTO formula VALUES (?,?,?,?,?)",
                          (r["exp_id"], r["id"], status, ms, json.dumps(out, ensure_ascii=False)))
            st["items"] += 1
            found += status == "ok" and bool(out.get("has_formula"))
            failed += status == "failed"
    log(f"formulas: {len(jobs)} criteria not judged by value, {found} with a formula, {failed} failed")


# ── describe ──────────────────────────────────────────────────────────────

PROFILE = {"REQUIREMENT": "requirement_desc", "TECHNICAL_REQUIREMENT": "requirement_desc",
           "AWARD_CRITERION": "criterion_desc"}
_FALLBACK = set()     # profiles the deployed nlp_service does not know yet


def attributes_text(attrs: dict, refined: dict, conflicts: dict) -> str:
    lines = [f"- {k}: {v}" for k, v in {**attrs, **refined}.items() if v not in (None, "", [], {})]
    for k, vs in conflicts.items():
        lines.append(f"- DISCREPANCIA en {k}: " + "; ".join(
            f"{v['value']} ({'feed' if v.get('source') else str(v.get('mentions')) + ' menciones'})" for v in vs))
    return "\n".join(lines) or "- (sin atributos)"


def describe(cfg: PilotConfig, store: Store):
    schema(store)
    svc = Services(cfg, store)
    done = {(r["exp_id"], r["kind"], r["item_id"]) for r in store.q("SELECT exp_id, kind, item_id FROM entity_description WHERE status='ok'")}
    refined = {(r["exp_id"], r["entity_id"]): json.loads(r["result_json"]) for r in
               store.q("SELECT * FROM refinement WHERE status='ok'")}
    jobs = []
    # Shared entities (organizations, qualifications) are described once, from every expediente.
    shared = defaultdict(list)
    for r in store.q("SELECT * FROM entity ORDER BY exp_id"):
        if r["scope"] == "global":
            shared[r["id"]].append(r)
            continue
        if (r["exp_id"], "entity", r["id"]) not in done:
            jobs.append(("entity", r["exp_id"], r["id"], r, [r["exp_id"]]))
    for nid, rs in shared.items():
        if ("*", "entity", nid) not in done:
            jobs.append(("entity", "*", nid, rs[0], [x["exp_id"] for x in rs]))
    if cfg.describe_relations:
        names = {(r["exp_id"], r["id"]): r["name"] for r in store.q("SELECT exp_id, id, name FROM entity")}
        for r in store.q("SELECT * FROM entity_relation WHERE type != 'DETAILED_BY'"):
            if (r["exp_id"], "relation", r["id"]) not in done:
                jobs.append(("relation", r["exp_id"], r["id"], r, names))

    def one(job):
        kind, exp_id, item_id, r, extra = job
        t0 = time.time()
        if kind == "relation":
            profile = "relation_desc"
            fields = {"head": extra.get((r["exp_id"], r["src"]), r["src"]), "tail": extra.get((r["exp_id"], r["dst"]), r["dst"]),
                      "type": r["type"], "subtype": r["subtype"], "attributes": r["attributes"],
                      "evidence": json.loads(r["evidence"] or "[]") or [r["type"]]}
        else:
            profile = PROFILE.get(r["type"], "entity_desc")
            evidence = [p for x in extra for p in passages(store, cfg, x, item_id, window=300, limit=6)][:10]
            attrs = json.loads(r["attributes"] or "{}")
            conflicts = json.loads(r["conflicts"] or "{}")
            ref = refined.get((r["exp_id"], item_id), {})
            fields = {"name": r["name"], "type": r["type"], "subtype": ref.get("subtype") or r["subtype"],
                      "attributes_text": attributes_text(attrs, ref, conflicts),
                      "evidence": evidence or [f"{r['name']}: " + attributes_text(attrs, ref, {})]}
        if profile in _FALLBACK:
            profile, fields = "entity_desc", dict(fields, evidence=[fields.get("attributes_text", "")] + fields["evidence"])
        try:
            out = svc.summarize(profile, fields, exp_id=None if exp_id == "*" else exp_id)
        except ServiceError as e:
            if profile in ("requirement_desc", "criterion_desc") and "422" in str(e):
                _FALLBACK.add(profile)      # nlp_service without the new profiles: generic one, fields in the evidence
                return one(job)
            return job, profile, "failed", str(e), int((time.time() - t0) * 1000)
        return job, profile, "ok", out.get("description"), int((time.time() - t0) * 1000)

    with store.stage("describe") as st, _pool(cfg.nlp_workers) as pool:
        for i, (job, profile, status, text, ms) in enumerate(pool.map(one, jobs), 1):
            kind, exp_id, item_id, _, _ = job
            with store.tx() as c:
                c.execute("INSERT OR REPLACE INTO entity_description VALUES (?,?,?,?,?,?,?)",
                          (exp_id, kind, item_id, profile, status, ms, text))
            st["items"] += 1
            if i % 50 == 0 or i == len(jobs):
                log(f"describe {i}/{len(jobs)}")
    if _FALLBACK:
        log(f"describe: nlp_service has no {sorted(_FALLBACK)}; used entity_desc with the fields as evidence")
