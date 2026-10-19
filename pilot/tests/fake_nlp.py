"""A stand-in for nlp_service with the same HTTP contracts, for tests and dry runs without a GPU.

    python tests/fake_nlp.py 8765   # then NLP_SERVICE_URL=http://localhost:8765

/ner finds a few things with regexes (lots, companies with a legal suffix and NIF, criteria with
points) so the downstream stages and the graph get realistic shapes. It is not an extractor.
"""
import json
import re
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

COMPANY = re.compile(r"([A-ZÁÉÍÓÚÑ][\wÁÉÍÓÚÑáéíóúñ&.,\- ]{2,60}?,? S\.?\s?[LA]\.?U?\.?)(?:[^\n]{0,40}?\b([A-HJ-NP-SUVW]\d{7}[0-9A-J]))?")
LOT = re.compile(r"\b[Ll]ote\s+(?:n[º°.]\s*)?(\d{1,3})\b")
CRIT = re.compile(r"([A-ZÁÉÍÓÚa-záéíóúñ][^\n:]{3,80}?)[:\s]+(?:hasta\s+)?(\d{1,3}(?:[.,]\d+)?)\s+puntos", re.I)


def ner(text: str) -> dict:
    ents, rels = [], []

    def add(name, typ, ev, subtype=None, **attrs):
        ents.append({"name": name.strip(), "mention_text": name.strip(), "type": typ, "subtype": subtype,
                     "evidence_text": ev[:300], "attributes": attrs, "confidence": 0.8})
        return len(ents) - 1

    lots = {}
    for m in LOT.finditer(text):
        if m.group(1) not in lots:
            lots[m.group(1)] = add(f"Lote {m.group(1)}", "LOT", m.group(0), number=m.group(1))
    for m in CRIT.finditer(text):
        i = add(m.group(1), "AWARD_CRITERION", m.group(0), "FORMULA", points=float(m.group(2).replace(",", ".")))
        for l in lots.values():
            rels.append({"head": l, "tail": i, "type": "HAS_CRITERION", "subtype": None, "evidence_text": m.group(0),
                         "attributes": {}, "confidence": 0.7})
    for m in COMPANY.finditer(text):
        attrs = {"nif": m.group(2)} if m.group(2) else {}
        add(m.group(1), "COMPANY", m.group(0), **attrs)
    return {"entities": ents[:40], "relations": rels[:40]}


def resolve(body: dict) -> dict:
    groups: dict[tuple, list] = {}
    for e in body["entities"]:
        groups.setdefault((e["type"], e["name"].lower()), []).append(e)
    ents, by_name = [], {}
    for i, ((typ, _), members) in enumerate(groups.items()):
        names = sorted({m["name"] for m in members})
        ents.append({"id": str(i), "canonical_name": names[0], "names": names, "type": typ,
                     "subtype": members[0].get("subtype"), "evidence": [m["evidence"] for m in members][:5]})
        for n in names:
            by_name[n] = str(i)
    rels = [{"head_id": by_name[r["head"]], "tail_id": by_name[r["tail"]], "type": r["type"], "subtype": r.get("subtype"),
             "evidence": [r["evidence"]], "attributes": r.get("attributes", {}), "confidence": r["confidence"]}
            for r in body["relations"] if r["head"] in by_name and r["tail"] in by_name]
    return {"entities": ents, "relations": rels}


def coref_links(body: dict) -> list:
    """Links every "la empresa" / "la adjudicataria" to the first company among the candidates."""
    companies = [i for i, c in enumerate(body["candidates"]) if c.get("type") == "COMPANY"]
    if not companies:
        return []
    return [{"mention": m.group(0), "candidate": companies[0], "evidence": body["text"][max(0, m.start() - 40):m.end() + 40]}
            for m in re.finditer(r"\b(la empresa|la adjudicataria|dicha empresa)\b", body["text"], re.I)]


def summarize(body: dict) -> dict:
    f = body["fields"]
    if body["profile"] == "article":
        words = f["text"].split()
        return {"result": {"headline": " ".join(words[:10]) or f.get("title", ""), "summary": " ".join(words[:60]) + "."}}
    if body["profile"] in ("entity_desc", "relation_desc", "aggregate", "requirement_desc", "criterion_desc"):
        name = f.get("name") or f"{f.get('head')} -> {f.get('tail')}"
        return {"result": {"description": f"{name} ({f.get('type')}): descripción de prueba."}}
    return None


def embed(text: str, dim: int = 1024) -> list[float]:
    """Deterministic unit vector from the text's hash, with BGE-M3's dimension."""
    import hashlib
    import math
    seed = hashlib.sha256(text.encode()).digest()
    v = [((seed[i % 32] * (i + 7)) % 251) / 251 - 0.5 for i in range(dim)]
    n = math.sqrt(sum(x * x for x in v)) or 1.0
    return [x / n for x in v]


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        if self.path == "/ner":
            out = ner(body["text"])
        elif self.path == "/resolve":
            out = resolve(body)
        elif self.path == "/coref/links":
            out = {"links": coref_links(body)}
        elif self.path == "/summarize":
            out = summarize(body)
        elif self.path == "/embed":
            out = {"embeddings": [embed(t) for t in body["texts"]]}
        elif self.path == "/nli":
            text = body["text"].lower()
            out = {"scores": [{"hypothesis": h, "score": 0.9 if any(w in text for w in h.split()[1:3]) else 0.1}
                              for h in body["hypotheses"]]}
        else:
            out = None
        data = json.dumps(out).encode()
        self.send_response(200 if out is not None else 404)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


def serve(port: int = 0) -> ThreadingHTTPServer:
    srv = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


if __name__ == "__main__":
    s = serve(int(sys.argv[1]) if len(sys.argv) > 1 else 8765)
    print(f"fake nlp_service on http://127.0.0.1:{s.server_port}")
    threading.Event().wait()
