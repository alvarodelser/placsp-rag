"""Assemble the data-model graph from the feed and the nlp_service output.

Two sources per expediente:
- feed (CODICE): authority, tender, lots, notices, award criteria, solvency requirements,
  guarantees, execution conditions, results with winners, contracts, modifications. Structured
  and authoritative, so it is the skeleton.
- documents: every document is a Document node with its gist; its resolved NER entities and
  relations hang from it (EXTRACTED_FROM) and attach to the skeleton: LOT entities map onto the
  feed's lots, companies merge by NIF (else normalised name) across all expedientes, and the
  other entities merge by name within the expediente (a criterion in the PCAP and in its
  rectification is one node).

Output under <run>/out: expedientes/<id>.json, nodes.jsonl, edges.jsonl.
Roles (client, awarded, partner, competitor) are derived at query time, never stored.
"""
import difflib
import json
import re
import time
import unicodedata

from placsp_pilot import classify as C
from placsp_pilot.config import PilotConfig
from placsp_pilot.order import order_documents
from placsp_pilot.store import Store

_LEGAL = re.compile(r"\b(s\.?\s?l\.?\s?u?|s\.?\s?a\.?\s?u?|s\.?\s?l\.?\s?l|s\.?\s?coop\.?|sociedad limitada|sociedad anonima|slp|s\.?\s?c\.?)\.?$", re.I)

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


def _similar(a: str, b: str) -> float:
    return difflib.SequenceMatcher(None, norm_name(a), norm_name(b)).ratio()


class Graph:
    def __init__(self):
        self.nodes: dict[str, dict] = {}
        self.edges: list[dict] = []
        self._edge_keys: set = set()
        self._out: dict[str, set] = {}
        self._in: dict[str, set] = {}
        self._props: dict[tuple, dict] = {}
        # sha -> {surface name in the text -> node id}, to link chunks to the entities they mention
        self.doc_names: dict[str, dict[str, str]] = {}

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
        key = (src, rel, dst, props.get("tender"))
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
                 value=tender.get("value_estimated"), budget=tender.get("budget_tax_excl"),
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
                     implicit=lot.get("implicit"))
        lots[str(lot["number"])] = lid
        g.edge(tid, "HAS_LOT", lid)

    def lots_for(n) -> list[str]:
        return [lots[str(n)]] if n not in (None, "", "*") and str(n) in lots else list(lots.values())

    for i, n in enumerate(t.get("notices", [])):
        g.edge(tid, "HAS_NOTICE", g.node(f"notice:{eid}:{i}", "Notice", type=(n.get("type") or {}).get("code"),
                                         type_label=(n.get("type") or {}).get("label"), published=n.get("published"),
                                         media=n.get("media")))
    for i, c in enumerate(t.get("award_criteria", [])):
        for lid in lots_for(c.get("lot")):
            g.edge(lid, "HAS_CRITERION", g.node(f"crit:{lid}:feed{i}", "AwardCriterion", name=c.get("name"),
                                                subtype={"judgement": "JUDGEMENT", "formula": "FORMULA"}.get(c.get("kind")),
                                                points=c.get("points"), formula=c.get("detail"), source="feed"))
    for i, r in enumerate(x for x in t.get("requirements", []) if x["group"] != "declaration"):
        for lid in lots_for(r.get("lot")):
            g.edge(lid, "REQUIRES", g.node(f"req:{lid}:feed{i}", "Requirement", name=(r.get("text") or "")[:120],
                                           subtype=_feed_req_kind(r), text=r.get("text"), amount=r.get("threshold"),
                                           source="feed"))
    for gr in t.get("guarantees", []):
        g.edge(tid, "REQUIRES", g.node(f"guarantee:{eid}:{(gr.get('type') or {}).get('code')}:{gr.get('lot') or '*'}",
                                       "Guarantee", name=(gr.get("type") or {}).get("label"), amount=gr.get("amount"),
                                       pct=gr.get("rate_pct"), source="feed"))
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


def _doc_entities(g: Graph, store: Store, eid: str, sha: str, did: str, sk: dict, lot_names: dict):
    """Map one document's resolved entities and relations onto the graph."""
    from placsp_pilot.nlpstages import join_attributes
    row = store.one("SELECT resolve_json FROM blob WHERE sha=? AND resolve_status='ok'", (sha,))
    if row is None:
        return 0, 0
    res = json.loads(row["resolve_json"])
    attrs = res.get("attrs", [])
    descs = {(r["kind"], r["item_id"]): r["text"] for r in
             store.q("SELECT kind, item_id, text FROM description WHERE sha=? AND status='ok'", (sha,))}
    lots = sk["lots"]
    idmap: dict[str, str] = {}
    types: dict[str, str] = {}
    for ent in res.get("entities", []):
        etype, name = ent["type"], ent["canonical_name"]
        at = join_attributes(ent["names"], attrs)
        if etype in ORG_KIND:
            nid = g.org(name, at.get("nif"), ORG_KIND[etype])
        elif etype == "JOINT_VENTURE":
            nid = g.node(f"jv:{norm_nif(at.get('nif')) or norm_name(name)}", "JointVenture", name=name, nif=norm_nif(at.get("nif")))
        elif etype == "QUALIFICATION":
            nid = g.node(f"qualification:{norm_name(name)}", "Qualification", name=name, subtype=ent.get("subtype"))
        elif etype == "LOT":
            num = str(at.get("number") or "").strip()
            num = re.sub(r"(?i)^lote\s*", "", num)
            nid = lots.get(num)
            if nid is None:
                m = re.search(r"(?i)lote\s*(\w+)", name)
                nid = lots.get(m.group(1)) if m else None
            if nid is None and len(lots) == 1:
                nid = next(iter(lots.values()))
            if nid is None:
                best = max(lot_names.items(), key=lambda kv: _similar(kv[0], name), default=None)
                nid = best[1] if best and _similar(best[0], name) > 0.7 else None
            if nid is None:
                nid = g.node(f"lot:{eid}:doc:{norm_name(name)}", "Lot", name=name, number=num or None, source="document")
                g.edge(f"tender:{eid}", "HAS_LOT", nid)
        elif etype == "CONTRACT" and len(sk["contracts"]) == 1:
            nid = sk["contracts"][0]
        else:
            nid = g.node(f"{etype.lower()}:{eid}:{norm_name(name)[:80]}", LABEL.get(etype, etype.title()), name=name)
        node = g.nodes[nid]
        if etype not in ORG_KIND and etype != "LOT":
            node.setdefault("subtype", ent.get("subtype"))
            for k, v in at.items():
                node.setdefault(k, v)
        g.add_to_list(nid, "descriptions", descs.get(("entity", ent["id"])))
        g.add_to_list(nid, "documents", sha)
        for ev in ent.get("evidence", [])[:2]:
            g.add_to_list(nid, "evidence", ev[:500])
        g.edge(nid, "EXTRACTED_FROM", did)
        names = g.doc_names.setdefault(sha, {})
        for n in ent["names"]:
            names[n] = nid
        idmap[ent["id"]] = nid
        types[nid] = etype
    n_rel = 0
    for k, rel in enumerate(res.get("relations", [])):
        src, dst = idmap.get(rel["head_id"]), idmap.get(rel["tail_id"])
        if not src or not dst:
            continue
        g.edge(src, rel["type"], dst, attributes=rel.get("attributes"), description=descs.get(("relation", str(k))),
               evidence=(rel.get("evidence") or [""])[0][:500], doc=sha, confidence=rel.get("confidence"))
        n_rel += 1
    # Entities that should hang from a lot but the text did not say which one: attach to all lots.
    lot_ids = set(lots.values())
    for nid, etype in types.items():
        rel = LOT_EDGE.get(etype)
        if rel and not any(nid in g.out(l, rel) for l in lot_ids | {n for n, t in types.items() if t == "LOT"}):
            for l in lot_ids:
                g.edge(l, rel, nid, inferred=True)
    return len(idmap), n_rel


def build_expediente(g: Graph, store: Store, e) -> dict:
    t = json.loads(e["tender_json"])
    eid = e["id"]
    agg = store.one("SELECT result_json FROM extraction WHERE exp_id=? AND kind='tender_description' AND status='ok'", (eid,))
    tender_desc = json.loads(agg["result_json"]).get("description") if agg else None
    tid, sk = _feed_skeleton(g, eid, e, t, tender_desc)
    lot_names = {(g.nodes[l].get("name") or ""): l for l in sk["lots"].values() if g.nodes[l].get("name")}

    rows = store.q("SELECT d.sha, d.role, d.label, d.source, d.published, d.notice_type, d.url, b.bytes, b.ext, b.pages,"
                   " b.text_chars, b.text_status, b.summary_json, b.ner_chunks_total, b.ner_chunks_selected, b.path"
                   " FROM docref d LEFT JOIN blob b ON b.sha=d.sha WHERE d.exp_id=? AND d.status='fetched' ORDER BY d.id", (eid,))
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
                     filename=d["label"], source=d["source"], published=d["published"], url=d["url"],
                     bytes=d["bytes"], ext=d["ext"], pages=d["pages"], chars=d["text_chars"], file_path=d["path"],
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
        n_ent, n_rel = _doc_entities(g, store, eid, d["sha"], did, sk, lot_names)
        doc_list.append(dict({k: v for k, v in g.nodes[did].items() if k not in ("id", "label")},
                             seq=d["seq"], stage=d["stage_name"], effective_date=d["effective_date"],
                             date_source=d["date_source"], entities=n_ent, relations=n_rel))

    # Link document criteria to the feed's when they are the same line of the baremo.
    for lid in sk["lots"].values():
        crits = [g.nodes[c] for c in g.out(lid, "HAS_CRITERION")]
        feed = [c for c in crits if c.get("source") == "feed"]
        for c in crits:
            if c.get("source") == "feed":
                continue
            best = max(feed, key=lambda f: _similar(f.get("name") or "", c.get("name") or ""), default=None)
            if best and _similar(best.get("name") or "", c.get("name") or "") > 0.75:
                g.edge(c["id"], "SAME_AS", best["id"])

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
        for x in store.q("SELECT sha, result_json FROM extraction WHERE kind='org_description' AND status='ok'"):
            if x["sha"] in g.nodes:
                g.nodes[x["sha"]]["description"] = json.loads(x["result_json"]).get("description")
        for n in g.nodes.values():
            if not n.get("description") and n.get("descriptions"):
                n["description"] = n["descriptions"][0]
        with (cfg.out_dir / "nodes.jsonl").open("w", encoding="utf-8") as fh:
            for n in g.nodes.values():
                fh.write(json.dumps(n, ensure_ascii=False) + "\n")
        with (cfg.out_dir / "edges.jsonl").open("w", encoding="utf-8") as fh:
            for ed in g.edges:
                fh.write(json.dumps(ed, ensure_ascii=False) + "\n")
    print(f"graph: {len(g.nodes)} nodes, {len(g.edges)} edges")
    return g
