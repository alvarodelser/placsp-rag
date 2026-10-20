"""Assemble the data-model graph from the feed and the nlp_service output.

Two sources per expediente:
- feed (CODICE): authority, tender, lots, notices, award criteria, solvency requirements,
  guarantees, execution conditions, results with winners, contracts, modifications. Structured
  and authoritative, so it is the skeleton.
- documents: every document is a Document node with its gist. The entities found in them come
  already resolved per expediente (entities.py): one node per real thing, the feed's own node
  when the feed has it, with EXTRACTED_FROM edges to the documents that mention it and the
  mention-level provenance kept for the chunk index (g.mentions).

Output under <run>/out: expedientes/<id>.json, nodes.jsonl, edges.jsonl.
Roles (client, awarded, partner, competitor) are derived at query time, never stored.
"""
import json
import re
import time
import unicodedata
from collections import Counter, defaultdict

from placsp_pilot import classify as C
from placsp_pilot.config import PilotConfig
from placsp_pilot.order import order_documents
from placsp_pilot.store import Store

# Legal forms at the end of a name, after punctuation became spaces ("S.A.U." -> "s a u").
_LEGAL = re.compile(r"\b(sociedad (anonima|limitada|cooperativa)( (laboral|unipersonal))?|sociedad unipersonal|unipersonal"
                    r"|s\s?a\s?u|s\s?l\s?u|s\s?l\s?l|s\s?l\s?p|s\s?coop|s\s?a|s\s?l|s\s?c|coop)$", re.I)

# Ontology entity type -> graph label. Organizations are one label with kinds.
LABEL = {
    "CONTRACTING_AUTHORITY": "Organization", "COMPANY": "Organization", "OTHER_ORGANIZATION": "Organization",
    "JOINT_VENTURE": "JointVenture", "LOT": "Lot", "AWARD_CRITERION": "AwardCriterion",
    "REQUIREMENT": "Requirement", "QUALIFICATION": "Qualification", "GUARANTEE": "Guarantee", "BID": "Bid",
    "CONTRACT": "Contract", "MODIFICATION": "Modification", "PENALTY": "Penalty", "DELIVERABLE": "Deliverable",
    "TEAM_PROFILE": "TeamProfile", "TECHNICAL_REQUIREMENT": "TechnicalRequirement",
}
ORG_KIND = {"CONTRACTING_AUTHORITY": "ContractingAuthority", "COMPANY": "Company", "OTHER_ORGANIZATION": "Other"}
# Entities with no lot relation of their own are attached to every lot with this edge.
LOT_EDGE = {"AWARD_CRITERION": "HAS_CRITERION", "REQUIREMENT": "REQUIRES", "GUARANTEE": "REQUIRES",
            "TECHNICAL_REQUIREMENT": "REQUIRES", "DELIVERABLE": "INCLUDES", "TEAM_PROFILE": "INCLUDES",
            "PENALTY": "INCLUDES"}

# Where each document role hangs in the model.
_ANCHOR = {
    C.BOARD_MINUTES: "Lot", C.VALUATION_REPORT: "Lot", C.ABNORMAL_BID_REPORT: "Lot", C.AWARD_PROPOSAL: "Lot",
    C.AWARD_RESOLUTION: "Result", C.AWARD_NOTICE: "Result",
    C.CONTRACT_DOCUMENT: "Contract", C.FORMALIZATION_NOTICE: "Contract",
    C.MODIFICATION: "Modification", C.MODIFICATION_NOTICE: "Modification",
}


def norm_name(name: str | None) -> str:
    s = unicodedata.normalize("NFKD", (name or "").lower()).encode("ascii", "ignore").decode()
    s = re.sub(r"[^\w\s]", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    prev = None
    while prev != s:
        prev = s
        s = _LEGAL.sub("", s).strip()
    return s


def norm_nif(nif) -> str | None:
    if not nif or not isinstance(nif, str):
        return None
    s = re.sub(r"[^0-9A-Za-z]", "", nif).upper()
    return s if 8 <= len(s) <= 10 else None


def org_id(name: str | None, nif) -> str:
    n = norm_nif(nif)
    return f"org:nif:{n}" if n else f"org:name:{norm_name(name)}"


class Graph:
    def __init__(self):
        self.nodes: dict[str, dict] = {}
        self.edges: list[dict] = []
        self._edge_keys: set = set()
        self._out: dict[str, set] = {}
        self._in: dict[str, set] = {}
        self._props: dict[tuple, dict] = {}
        # (expediente, sha) -> chunk idx -> mentions in that chunk (entity id, offsets, page, quote)
        self.mentions: dict[tuple, dict[int, list[dict]]] = {}

    def node(self, nid: str, label: str, **props) -> str:
        cur = self.nodes.get(nid)
        if cur is None:
            self.nodes[nid] = {"id": nid, "label": label, **{k: v for k, v in props.items() if v not in (None, [], {}, "")}}
        else:
            for k, v in props.items():
                if v not in (None, [], {}, "") and cur.get(k) in (None, [], {}, ""):
                    cur[k] = v
        return nid

    def add_to_list(self, nid: str, key: str, value):
        if value in (None, ""):
            return
        lst = self.nodes[nid].setdefault(key, [])
        if value not in lst:
            lst.append(value)

    def edge(self, src: str, rel: str, dst: str, **props):
        # Edges that belong to one expediente's sequence (NEXT_DOCUMENT) are keyed by it too:
        # two sibling expedientes can share a document pair in different chains.
        key = (src, rel, dst, props.get("tender") or props.get("key"))
        if key in self._edge_keys:
            return
        self._edge_keys.add(key)
        self._out.setdefault(src, set()).add((rel, dst))
        self._in.setdefault(dst, set()).add((rel, src))
        clean = {k: v for k, v in props.items() if v not in (None, "", {})}
        self._props[key] = clean
        self.edges.append({"src": src, "rel": rel, "dst": dst, **clean})

    def edge_props(self, src: str, rel: str, dst: str) -> dict:
        return self._props.get((src, rel, dst, None), {})

    def out(self, src: str, rel: str | None = None) -> list[str]:
        return [d for r, d in self._out.get(src, ()) if rel is None or r == rel]

    def into(self, dst: str, rel: str | None = None) -> list[str]:
        return [s for r, s in self._in.get(dst, ()) if rel is None or r == rel]

    def org(self, name, nif, kind: str, **props) -> str:
        nid = self.node(org_id(name, nif), "Organization", name=name, nif=norm_nif(nif), **props)
        self.add_to_list(nid, "kinds", kind)
        self.add_to_list(nid, "aliases", name)
        return nid


def _feed_req_kind(r: dict) -> str:
    label = ((r.get("type") or {}).get("label") or "").lower()
    text = (r.get("text") or "").lower()
    both = label + " " + text
    if r["group"] == "classification":
        return "CLASSIFICATION"
    if "negocio" in both or "turnover" in label:
        return "TURNOVER"
    if "seguro" in both or "insurance" in label:
        return "INSURANCE"
    if any(k in both for k in ("trabajos", "servicios", "suministros", "similar", "principales")):
        return "SIMILAR_SERVICES"
    if any(k in both for k in ("personal", "técnico", "equipo", "titulaci")):
        return "TEAM"
    if any(k in both for k in ("certific", "iso", "calidad", "medioambient")):
        return "CREDENTIAL"
    return "OTHER"


def _feed_skeleton(g: Graph, eid: str, e, t: dict, tender_desc: str | None) -> tuple[str, dict]:
    tender = t.get("tender", {})
    a = t.get("authority") or {}
    auth = g.org(a.get("name"), a.get("nif"), "ContractingAuthority", dir3=a.get("dir3"),
                 platform_id=a.get("platform_id"), authority_type=(a.get("type") or {}).get("label"),
                 activity=(a.get("activity") or {}).get("label"), hierarchy=a.get("hierarchy"), city=a.get("city"))
    tid = g.node(f"tender:{eid}", "Tender",
                 name=tender.get("name") or e["title"], aliases=[x for x in [t.get("folder_id"), t.get("ted_uuid")] if x],
                 expediente=t.get("folder_id"), channel=e["channel"], status=(t.get("status") or {}).get("label"),
                 description=tender_desc,
                 contract_type=(tender.get("contract_type") or {}).get("label"),
                 subtype=(tender.get("subtype") or {}).get("label"),
                 procedure=(tender.get("procedure") or {}).get("label"), sara=tender.get("sara"),
                 value=tender.get("value_estimated"), budget=tender.get("budget_tax_excl"), budget_total=tender.get("budget_total"),
                 cpv=tender.get("cpv"), nuts=(tender.get("location") or {}).get("nuts"),
                 duration=tender.get("duration"), extension=tender.get("extension"),
                 published=min([n["published"] for n in t.get("notices", []) if n.get("published")] or [None]),
                 deadline=(tender.get("deadline") or {}).get("date"),
                 analysable=bool(e["analysable"]), skip_reason=e["skip_reason"], source_url=t.get("link"),
                 terms=t.get("terms_other"), subcontracting=t.get("subcontracting"))
    g.edge(auth, "PUBLISHED", tid)

    lots = {}
    for lot in t.get("lots", []):
        lid = g.node(f"lot:{eid}:{lot['number']}", "Lot", number=str(lot["number"]), name=lot.get("name"),
                     cpv=lot.get("cpv"), budget=lot.get("budget_tax_excl"), budget_total=lot.get("budget_total"),
                     value=lot.get("value_estimated"), nuts=(lot.get("location") or {}).get("nuts"),
                     place=", ".join(x for x in [(lot.get("location") or {}).get("city"),
                                                 (lot.get("location") or {}).get("region")] if x) or None,
                     implicit=lot.get("implicit"))
        lots[str(lot["number"])] = lid
        g.edge(tid, "HAS_LOT", lid)

    def lots_for(n) -> list[str]:
        return [lots[str(n)]] if n not in (None, "", "*") and str(n) in lots else list(lots.values())

    for i, n in enumerate(t.get("notices", [])):
        g.edge(tid, "HAS_NOTICE", g.node(f"notice:{eid}:{i}", "Notice", type=(n.get("type") or {}).get("code"),
                                         type_label=(n.get("type") or {}).get("label"), published=n.get("published"),
                                         media=n.get("media")))
    # One node per line of the baremo or the solvency table, linked to every lot it applies to:
    # a criterion shared by 36 lots is one criterion, not 36.
    for i, c in enumerate(t.get("award_criteria", [])):
        cid = g.node(f"crit:{eid}:feed{i}", "AwardCriterion", name=c.get("name"),
                     subtype={"judgement": "JUDGEMENT", "formula": "FORMULA"}.get(c.get("kind")),
                     points=c.get("points"), formula=c.get("detail"), lot=c.get("lot"), source="feed")
        for lid in lots_for(c.get("lot")):
            g.edge(lid, "HAS_CRITERION", cid)
    for i, r in enumerate(x for x in t.get("requirements", []) if x["group"] != "declaration"):
        rid = g.node(f"req:{eid}:feed{i}", "Requirement", name=(r.get("text") or "")[:120],
                     subtype=_feed_req_kind(r), group=r["group"], text=r.get("text"), amount=r.get("threshold"),
                     lot=r.get("lot"), source="feed")
        for lid in lots_for(r.get("lot")):
            g.edge(lid, "REQUIRES", rid)
    for gr in t.get("guarantees", []):
        code = (gr.get("type") or {}).get("code")
        name = {"1": "Garantía provisional", "2": "Garantía definitiva", "3": "Garantía complementaria"}.get(code) \
            or (gr.get("type") or {}).get("label")
        g.edge(tid, "REQUIRES", g.node(f"guarantee:{eid}:{code}:{gr.get('lot') or '*'}", "Guarantee", name=name,
                                       amount=gr.get("amount"), pct=gr.get("rate_pct"), source="feed"))
    for i, ec in enumerate(t.get("execution_conditions", [])):
        g.edge(tid, "HAS_CONDITION", g.node(f"cond:{eid}:{i}", "ExecutionCondition", name=ec.get("name"),
                                            kind=(ec.get("type") or {}).get("label"), text=ec.get("text")))

    contracts = []
    for res in t.get("results", []):
        targets = [lid for n in res["lots"] for lid in lots_for(n)] if res.get("lots") else lots_for(None)
        for lid in dict.fromkeys(targets):
            code = (res.get("result") or {}).get("code")
            status = {"3": "desierto", "4": "cancelled", "5": "cancelled", "6": "desierto", "7": "desierto"}.get(code, "awarded")
            rid = g.node(f"result:{lid}", "Result", status=status, result=(res.get("result") or {}).get("label"),
                         date=res.get("award_date"), bids_received=res.get("bids_received"), sme_bids=res.get("sme_bids"),
                         lowest_bid=res.get("lowest_bid"), highest_bid=res.get("highest_bid"),
                         sme_awarded=res.get("sme_awarded"), source="feed")
            g.edge(lid, "HAS_RESULT", rid)
            winners = res.get("winners") or []
            if not winners:
                continue
            win_orgs = [g.org(w["name"], w.get("nif"), "Company") for w in winners]
            bid = g.node(f"bid:{lid}:{'+'.join(sorted(win_orgs))}", "Bid", outcome="admitted",
                         price=res.get("amount_tax_excl"), winner=True, source="feed")
            g.edge(lid, "RECEIVED_BID", bid)
            g.edge(rid, "WINNER", bid)
            for o in win_orgs:
                g.edge(bid, "SUBMITTED_BY", o)
            for k, c in enumerate(res.get("contracts") or []):
                cid = g.node(f"contract:{lid}:{k}", "Contract", name=c.get("id"), contract_id=c.get("id"),
                             signed_date=c.get("signed"), start=res.get("start_date"), price=res.get("amount_tax_excl"),
                             source="feed")
                g.edge(bid, "RESULTED_IN", cid)
                contracts.append(cid)
    for i, m in enumerate(t.get("modifications", [])):
        mid = g.node(f"modification:{eid}:feed{m.get('id') or i}", "Modification", name=f"Modificación {m.get('id') or i}",
                     subtype="EXTENSION" if re.search(r"pr[oó]rroga", m.get("note") or "", re.I) else "MODIFICATION",
                     amount_change=m.get("amount_change"), new_total=m.get("final_amount"),
                     duration_change_days=m.get("duration_change"), reason=m.get("note"), contract_ref=m.get("contract_id"),
                     source="feed")
        g.edge(mid, "MODIFIES", contracts[0] if contracts else tid)
    return tid, {"lots": lots, "contracts": contracts, "auth": auth}


def _entities(g: Graph, store: Store, eid: str, sk: dict) -> tuple[Counter, Counter]:
    """Put the expediente's resolved entities on the graph. Returns entities and relations per document."""
    from placsp_pilot.entities import divided, lot_mention_ok, lot_object, schema
    schema(store)
    is_divided = divided(json.loads(store.one("SELECT tender_json FROM expediente WHERE id=?", (eid,))["tender_json"]))
    lot_names = [g.nodes[l].get("name") or "" for l in sk["lots"].values()]
    lot_entities = set()
    descs = {(r["kind"], r["item_id"]): r["text"] for r in store.q(
        "SELECT kind, item_id, text FROM entity_description WHERE status='ok' AND exp_id IN (?, '*')", (eid,))}
    refined = {r["entity_id"]: json.loads(r["result_json"]) for r in store.q(
        "SELECT entity_id, result_json FROM refinement WHERE exp_id=? AND status='ok'", (eid,))}
    formulas = {r["entity_id"]: f for r in store.q(
        "SELECT entity_id, result_json FROM formula WHERE exp_id=? AND status='ok'", (eid,))
        if (f := json.loads(r["result_json"])).get("has_formula")}
    lots = list(sk["lots"].values())
    for r in store.q("SELECT * FROM entity WHERE exp_id=?", (eid,)):
        typ, nid = r["type"], r["id"]
        g.node(nid, r["label"], name=r["name"], subtype=r["subtype"])
        n = g.nodes[nid]
        if typ in ORG_KIND:
            g.add_to_list(nid, "kinds", ORG_KIND[typ])
        for alias in json.loads(r["aliases"] or "[]"):
            g.add_to_list(nid, "aliases", alias)
        for k, v in json.loads(r["attributes"] or "{}").items():
            if n.get(k) in (None, "", [], {}):
                n[k] = v                                  # the feed's own values are already there and win
        if json.loads(r["conflicts"] or "{}"):
            n["conflicts"] = json.loads(r["conflicts"])
        if refined.get(nid):
            n["detail"] = refined[nid]
        if formulas.get(nid):
            n["formula_model"] = formulas[nid]
        n["source"] = "feed+documents" if r["anchor"] and r["mentions"] else "feed" if r["anchor"] else "documents"
        n["mentions"] = (n.get("mentions") or 0) + r["mentions"]
        if typ == "LOT":
            lot_entities.add(nid)                     # mentions recounted and described below, from the kept ones
        elif descs.get(("entity", nid)):
            n["description"] = descs[("entity", nid)]
        for sha in json.loads(r["documents"] or "[]"):
            g.add_to_list(nid, "documents", sha)
        rel = LOT_EDGE.get(typ)
        if rel and not g.into(nid, rel):
            entity_lots = json.loads(r["lots"] or "[]")
            for lid in entity_lots or lots:              # unsaid lot: the entity applies to all of them
                g.edge(lid, rel, nid, inferred=not entity_lots or None)
    for r in store.q("SELECT * FROM entity_relation WHERE exp_id=?", (eid,)):
        if r["src"] in g.nodes and r["dst"] in g.nodes:
            ev = json.loads(r["evidence"] or "[]")
            g.edge(r["src"], r["type"], r["dst"], attributes=json.loads(r["attributes"] or "{}") or None,
                   evidence=ev[0][:500] if ev else None, description=descs.get(("relation", r["id"])),
                   mentions=len(json.loads(r["mentions"] or "[]")) or None)
    ent_per_doc, per_pair = Counter(), Counter()
    lot_kept = defaultdict(list)
    for m in store.q("SELECT em.entity_id, m.* FROM entity_mention em JOIN mention m ON m.id=em.mention_id"
                     " WHERE em.exp_id=?", (eid,)):
        if m["entity_id"] in lot_entities:
            # What NER called a lot but names none (an undivided contract's "Lote 1", earlier runs) is not evidence.
            if not (is_divided and (m["kind"] == "coref" or lot_mention_ok(m, lot_names, True))):
                continue
            lot_kept[m["entity_id"]].append(m["evidence"] or "")
        g.mentions.setdefault((eid, m["sha"]), {}).setdefault(m["idx"], []).append({
            "entity_id": m["entity_id"], "mention_id": m["id"], "surface": m["name"], "quote": (m["evidence"] or "")[:400],
            "char_start": m["char_start"], "char_end": m["char_end"], "page": m["page"], "located": bool(m["located"]),
            "kind": m["kind"] or "ner", "name_start": m["name_start"], "name_end": m["name_end"]})
        per_pair[(m["entity_id"], m["sha"])] += 1
    for nid in lot_entities:
        n, kept = g.nodes[nid], lot_kept.get(nid, [])
        n["mentions"] = len(kept)
        if n.get("source") == "feed+documents" and not kept:
            n["source"] = "feed"
        n["description"] = lot_object(n.get("number") or "", kept) if is_divided else None
    for (nid, sha), count in per_pair.items():
        if f"doc:{sha}" in g.nodes and nid in g.nodes:
            g.edge(nid, "EXTRACTED_FROM", f"doc:{sha}", mentions=count)
            ent_per_doc[sha] += 1
    rel_per_doc = Counter({r["sha"]: r["n"] for r in store.q(
        "SELECT sha, COUNT(*) n FROM mrelation WHERE sha IN (SELECT sha FROM docref WHERE exp_id=?) GROUP BY sha", (eid,))})
    return ent_per_doc, rel_per_doc


def build_expediente(g: Graph, store: Store, e) -> dict:
    t = json.loads(e["tender_json"])
    eid = e["id"]
    agg = store.one("SELECT result_json FROM extraction WHERE exp_id=? AND kind='tender_description' AND status='ok'", (eid,))
    tender_desc = json.loads(agg["result_json"]).get("description") if agg else None
    title = store.one("SELECT result_json FROM extraction WHERE exp_id=? AND kind='tender_title' AND status='ok'", (eid,))
    tid, sk = _feed_skeleton(g, eid, e, t, tender_desc)
    if store.one("SELECT name FROM sqlite_master WHERE name='expediente_theme'"):
        g.nodes[tid]["themes"] = [r["theme"] for r in store.q(
            "SELECT theme FROM expediente_theme WHERE exp_id=? ORDER BY quota DESC, theme", (eid,))] or None
    if title:
        g.nodes[tid]["short_title"] = json.loads(title["result_json"]).get("title")

    # A file from inside an archive links to the archive as published (its own url is "zip:…").
    rows = store.q("SELECT d.sha, d.role, d.label, d.source, d.published, d.notice_type, d.url, p.url AS archive_url,"
                   " b.bytes, b.ext, b.pages, b.text_chars, b.text_status, b.summary_json, b.ner_chunks_total, b.ner_chunks_selected"
                   " FROM docref d LEFT JOIN blob b ON b.sha=d.sha LEFT JOIN docref p ON p.id=d.parent_id"
                   " WHERE d.exp_id=? AND d.status='fetched' ORDER BY d.id", (eid,))
    first: dict[str, dict] = {}
    for r in rows:
        d = dict(r)
        cur = first.get(d["sha"])
        if cur is None:
            first[d["sha"]] = d
        else:  # same file referenced twice: keep the earliest date and every source
            cur["published"] = min(x for x in (cur["published"], d["published"]) if x) if (cur["published"] or d["published"]) else None
            cur["notice_type"] = cur["notice_type"] or d["notice_type"]
            cur["source"] = cur["source"] if d["source"] in cur["source"] else f"{cur['source']}+{d['source']}"
    doc_list, prev = [], None
    for d in order_documents(list(first.values()), t):
        s = json.loads(d["summary_json"]) if d["summary_json"] else {}
        did = g.node(f"doc:{d['sha']}", "Document", sha256=d["sha"], role=d["role"], title=s.get("headline") or d["label"],
                     filename=d["label"], source=d["source"], published=d["published"],
                     url=d["archive_url"] if (d["url"] or "").startswith("zip:") else d["url"],
                     in_archive=(d["url"] or "").startswith("zip:") or None,
                     bytes=d["bytes"], ext=d["ext"], pages=d["pages"], chars=d["text_chars"],
                     text_status=d["text_status"], summary=s.get("summary"),
                     ner_chunks=d["ner_chunks_total"], ner_chunks_processed=d["ner_chunks_selected"])
        # The tender holds the complete, ordered list; the anchor says what the document is about.
        g.edge(tid, "HAS_DOCUMENT", did, seq=d["seq"], stage=d["stage_name"], effective_date=d["effective_date"],
               date_source=d["date_source"], role=d["role"])
        if prev:
            g.edge(prev, "NEXT_DOCUMENT", did, tender=eid)
        prev = did
        anchor = _ANCHOR.get(d["role"])
        targets = {
            None: [],
            "Lot": list(sk["lots"].values()),
            "Result": [r for r in (f"result:{l}" for l in sk["lots"].values()) if r in g.nodes],
            "Contract": sk["contracts"],
            "Modification": [n for n in g.nodes if n.startswith(f"modification:{eid}:")] or sk["contracts"],
        }[anchor]
        for tgt in targets:
            g.edge(did, "CONCERNS", tgt)
        doc_list.append(dict({k: v for k, v in g.nodes[did].items() if k not in ("id", "label")},
                             seq=d["seq"], stage=d["stage_name"], effective_date=d["effective_date"],
                             date_source=d["date_source"]))
    ent_per_doc, rel_per_doc = _entities(g, store, eid, sk)
    for d in doc_list:
        d["entities"], d["relations"] = ent_per_doc[d["sha256"]], rel_per_doc[d["sha256"]]

    return {"id": eid, "channel": e["channel"], "folder_id": t.get("folder_id"), "title": e["title"],
            "analysable": bool(e["analysable"]), "skip_reason": e["skip_reason"], "description": tender_desc,
            "feed": t, "documents": doc_list}


def build(cfg: PilotConfig, store: Store):
    g = Graph()
    exp_dir = cfg.out_dir / "expedientes"
    exp_dir.mkdir(parents=True, exist_ok=True)
    with store.stage("graph") as st:
        for e in store.q("SELECT * FROM expediente ORDER BY channel, id"):
            t0 = time.time()
            rec = build_expediente(g, store, e)
            store.update("expediente", {"id": e["id"]}, graph_status="ok", graph_ms=int((time.time() - t0) * 1000))
            rec["graph"] = {"nodes": [n for n in g.nodes.values() if f":{e['id']}:" in n["id"] or n["id"].endswith(f":{e['id']}")]}
            (exp_dir / f"{e['id']}.json").write_text(json.dumps(rec, ensure_ascii=False, indent=1), encoding="utf-8")
            st["items"] += 1
        with (cfg.out_dir / "nodes.jsonl").open("w", encoding="utf-8") as fh:
            for n in g.nodes.values():
                fh.write(json.dumps(n, ensure_ascii=False) + "\n")
        with (cfg.out_dir / "edges.jsonl").open("w", encoding="utf-8") as fh:
            for ed in g.edges:
                fh.write(json.dumps(ed, ensure_ascii=False) + "\n")
    print(f"graph: {len(g.nodes)} nodes, {len(g.edges)} edges")
    return g
