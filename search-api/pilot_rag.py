"""Questions over a tender's documents: hybrid retrieval, reranking and a cited answer.

  1. Retrieval: the chunks closest in meaning (BGE-M3, dense) and by keywords (BM25 sparse
     vector, pilot_lexical.py) in one Qdrant query, fused by reciprocal rank.
  2. Reranking: a cross-encoder (bge-reranker-v2-m3 in the placsp-reranker container, Hugging
     Face text-embeddings-inference) reads the question with each candidate and orders them.
  3. Answer: a small model on Ollama (gemma4:e4b) writes from the best passages only, citing
     each claim as [n]; it is streamed as NDJSON events.
Each step that is not available is skipped and said so in `info`, never silently.

  RERANKER_URL        text-embeddings-inference with a reranker (POST /rerank); empty: no rerank
  ANSWER_OLLAMA_URL   the Ollama that writes answers; empty: passages only
  ANSWER_MODEL        default gemma4:e4b
  ANSWER_KEEP_ALIVE   how long Ollama keeps the model loaded after a question (default 30m)
"""
import json
import os
import re
import time
from typing import Iterator

import httpx

import pilot_lexical as lexical

RERANKER_URL = os.getenv("RERANKER_URL", "").rstrip("/")
ANSWER_OLLAMA_URL = os.getenv("ANSWER_OLLAMA_URL", "").rstrip("/")
ANSWER_MODEL = os.getenv("ANSWER_MODEL", "gemma4:e4b")
ANSWER_KEEP_ALIVE = os.getenv("ANSWER_KEEP_ALIVE", "30m")

CANDIDATES = 30          # fused candidates sent to the reranker
PASSAGES = 8             # passages the answer is written from
PASSAGE_CHARS = 1600     # each passage as the model reads it
RERANK_CHARS = 1500      # each candidate as the reranker reads it (it truncates to its window anyway)

CHUNK_FIELDS = ["tender_id", "doc_sha256", "doc_seq", "doc_role", "doc_title", "chunk_idx", "page_from", "page_to", "text"]


def status() -> tuple[str, str]:
    """(reranker, answer model): "ok …", "off" when not configured, "error: …" when not answering."""
    rr = "off"
    if RERANKER_URL:
        try:
            r = httpx.post(f"{RERANKER_URL}/rerank", json={"query": "prueba", "texts": ["prueba"]}, timeout=10)
            r.raise_for_status()
            rr = "ok"
        except httpx.HTTPError as e:
            rr = f"error: {type(e).__name__} at {RERANKER_URL}"
    am = "off"
    if ANSWER_OLLAMA_URL:
        try:
            r = httpx.get(f"{ANSWER_OLLAMA_URL}/api/tags", timeout=10)
            r.raise_for_status()
            names = {m["name"] for m in r.json().get("models", [])}
            am = f"ok ({ANSWER_MODEL})" if ANSWER_MODEL in names else f"error: {ANSWER_MODEL} not pulled on {ANSWER_OLLAMA_URL}"
        except httpx.HTTPError as e:
            am = f"error: {type(e).__name__} at {ANSWER_OLLAMA_URL}"
    return rr, am


def retrieve(qdrant, coll: str, q: str, dense: list[float], tender_id: str = "") -> tuple[list[dict], dict]:
    """The best passages for `q`, reranked when the reranker answers. Returns (passages, info)."""
    from qdrant_client import models as m
    flt = m.Filter(must=[m.FieldCondition(key="tender_id", match=m.MatchValue(value=tender_id))]) if tender_id else None
    idx, vals = lexical.query_vector(q)
    info = {"hybrid": False, "reranked": False, "notes": []}
    try:
        prefetch = [m.Prefetch(query=dense, using="text", filter=flt, limit=CANDIDATES)]
        if idx:
            prefetch.append(m.Prefetch(query=m.SparseVector(indices=idx, values=vals), using="bm25", filter=flt, limit=CANDIDATES))
        pts = qdrant.query_points(coll, prefetch=prefetch, query=m.FusionQuery(fusion=m.Fusion.RRF),
                                  limit=CANDIDATES, with_payload=CHUNK_FIELDS).points
        info["hybrid"] = bool(idx)
    except Exception as e:  # an index built before the keyword vectors: meaning only
        info["notes"].append(f"sin búsqueda por palabras clave ({type(e).__name__}); reindexa el piloto")
        pts = qdrant.query_points(coll, query=dense, using="text", query_filter=flt, limit=CANDIDATES,
                                  with_payload=CHUNK_FIELDS).points
    cands = [dict(p.payload, fused=round(p.score, 4)) for p in pts]
    if cands and RERANKER_URL:
        try:
            r = httpx.post(f"{RERANKER_URL}/rerank", timeout=60,
                           json={"query": q, "texts": [c["text"][:RERANK_CHARS] for c in cands], "truncate": True})
            r.raise_for_status()
            order = sorted(r.json(), key=lambda x: -x["score"])
            cands = [dict(cands[x["index"]], rerank=round(x["score"], 4)) for x in order]
            info["reranked"] = True
        except httpx.HTTPError as e:
            info["notes"].append(f"sin reordenación: el reranker no responde ({type(e).__name__})")
    elif not RERANKER_URL:
        info["notes"].append("sin reordenación: RERANKER_URL no está configurado")
    return cands[:PASSAGES], info


SYSTEM = """Respondes preguntas sobre un expediente de contratación pública usando SOLO los fragmentos que se te dan.
Reglas:
- Responde en español, breve y preciso: de 1 a 5 frases, o una lista corta si la pregunta pide varias cosas.
- Cada afirmación lleva su fuente entre corchetes: [1], [2]… o [F] para los datos del expediente.
- Copia literalmente cifras, importes, porcentajes, plazos y nombres.
- Si los fragmentos no contienen la respuesta, di «Los documentos recuperados no lo dicen.» y nada más. No inventes.
- No cites un fragmento que no hayas usado."""


def prompt(q: str, facts: str, passages: list[dict]) -> str:
    parts = [f"PREGUNTA: {q}", "", "FRAGMENTOS:"]
    if facts:
        parts.append(f"[F] Datos del expediente en PLACSP:\n{facts}")
    for i, p in enumerate(passages, 1):
        where = ", ".join(x for x in [p.get("doc_role"), f"pág. {p['page_from']}" if p.get("page_from") else None] if x)
        text = re.sub(r"[ \t]+", " ", p["text"][:PASSAGE_CHARS]).strip()
        parts.append(f"[{i}] ({where}) {text}")
    return "\n\n".join(parts)


def facts_of(t: dict) -> str:
    """The tender's own data as one short passage, for questions the feed already answers."""
    lines = [f"Objeto: {t.get('name')}"]
    if t.get("authority"):
        lines.append(f"Órgano de contratación: {t['authority'].get('name')}")
    for k, label in [("status", "Estado"), ("procedure", "Procedimiento"), ("contract_type", "Tipo"), ("published", "Publicado"),
                     ("deadline", "Fin de plazo"), ("value", "Valor estimado (EUR)"), ("budget", "Presupuesto sin IVA (EUR)")]:
        if t.get(k) not in (None, ""):
            lines.append(f"{label}: {t[k] if not isinstance(t[k], dict) else json.dumps(t[k], ensure_ascii=False)}")
    if t.get("duration"):
        d = t["duration"]
        lines.append(f"Duración: {d.get('value')} {d.get('unit')}" if isinstance(d, dict) else f"Duración: {d}")
    for g in t.get("guarantees") or []:
        name = {"Final": "definitiva"}.get(g.get("name"), g.get("name"))      # the feed's word for it
        lines.append(f"Garantía {name}: {g.get('pct')}%" if g.get("pct") is not None else f"Garantía {name}")
    for lot in t.get("lots") or []:
        crit = "; ".join(f"{c.get('name')} ({c.get('points')} puntos)" for c in lot.get("award_criteria") or [] if c.get("source") != "documents")
        if crit:
            lines.append(f"Criterios del lote {lot.get('number')}: {crit}")
    return "\n".join(lines)


def answer(q: str, facts: str, passages: list[dict]) -> Iterator[str]:
    """The answer's text as Ollama writes it. Raises httpx.HTTPError when Ollama is not there."""
    body = {"model": ANSWER_MODEL, "stream": True, "think": False, "keep_alive": ANSWER_KEEP_ALIVE,
            "options": {"temperature": 0.1, "num_ctx": 8192},
            "messages": [{"role": "system", "content": SYSTEM}, {"role": "user", "content": prompt(q, facts, passages)}]}
    with httpx.stream("POST", f"{ANSWER_OLLAMA_URL}/api/chat", json=body, timeout=httpx.Timeout(300, connect=10)) as r:
        r.raise_for_status()
        for line in r.iter_lines():
            if not line:
                continue
            msg = json.loads(line)
            if msg.get("error"):
                raise httpx.HTTPError(msg["error"])
            piece = (msg.get("message") or {}).get("content") or ""
            if piece:
                yield piece
            if msg.get("done"):
                return


def cited(text: str, n: int) -> list:
    """The sources an answer cites, in order of first use: passage numbers and "F"."""
    out = []
    for x in re.findall(r"\[(\d+|F)\]", text):
        v = x if x == "F" else int(x)
        if v not in out and (v == "F" or 1 <= v <= n):
            out.append(v)
    return out


def events(q: str, facts: str, passages: list[dict], info: dict) -> Iterator[bytes]:
    """NDJSON: the passages first, then the answer as it is written, then what it cited."""
    def ev(**kw):
        return (json.dumps(kw, ensure_ascii=False) + "\n").encode()
    yield ev(type="passages", passages=[{k: p.get(k) for k in CHUNK_FIELDS + ["fused", "rerank"]} | {"text": p["text"][:900]}
                                        for p in passages], info=info, model=ANSWER_MODEL if ANSWER_OLLAMA_URL else None)
    if not ANSWER_OLLAMA_URL:
        yield ev(type="done", text="", cited=[], note="sin respuesta redactada: ANSWER_OLLAMA_URL no está configurado")
        return
    if not passages and not facts:
        yield ev(type="done", text="Los documentos recuperados no lo dicen.", cited=[])
        return
    t0, text = time.time(), ""
    try:
        for piece in answer(q, facts, passages):
            text += piece
            yield ev(type="token", text=piece)
    except httpx.HTTPError as e:
        yield ev(type="error", error=f"El modelo {ANSWER_MODEL} no responde en {ANSWER_OLLAMA_URL}: {e}")
        return
    yield ev(type="done", text=text, cited=cited(text, len(passages)), ms=int((time.time() - t0) * 1000))
