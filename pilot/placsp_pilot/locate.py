"""Find the feed's entities in the documents, without the model.

The feed (CODICE) already gives an expediente's authority, lots, award criteria and points,
solvency requirements, guarantees and winners. NER does not look for them again (see the
ontology's `source: feed`); this stage finds where the documents name them, so each one gets the
same provenance an NER mention has (document, chunk, offsets, page) and the later stages (refine,
formulas, describe, summary) read those passages.

  criteria      a line (or two, when the name wraps) that holds the criterion's words, short enough
                to be about it; a one-word name ("Precio") only with its points beside it
  requirements  one that only points at the pliego ("según cláusula 8ª PCAP") is found at that
                clause's heading in the PCAP: "CLÁUSULA 8", "Cláusula octava", "8. SOLVENCIA",
                "Apartado H", "Anexo II"; without a pointer, at the solvency heading of its group.
                One with its own text, where its words are
  lots          "Lote 2", "lote nº 3" (only in a contract divided into lots)
  organizations the authority and the winners, by NIF and by name
  guarantees    "garantía definitiva / provisional / complementaria"

Headings in a table of contents ("CLÁUSULA 8. SOLVENCIA ........ 12") are not the clause.
Each find becomes a mention of kind `feed` whose `target` is the feed node; resolution joins it to
that node directly.
"""
import json
import re
from bisect import bisect_left, bisect_right
from pathlib import Path

from placsp_pilot import graph as G
from placsp_pilot.lexical import STOP, fold, stem, terms
from placsp_pilot.nlpstages import log, page_ranges, reference_only
from placsp_pilot.sections import load_layout

# Documents too large and too far from the tender's terms to be worth scanning.
SKIP_ROLES = {"ProjectDocument", "TechnicalAnnex"}
PCAP_ROLES = {"PCAP", "PCAP+PPT"}
MAX_PER_DOC = 30                     # mentions of one entity in one document

from placsp_pilot.sections import (HEADINGS as _HEADINGS, ORDINAL_RE as _ORDINAL_RE, TOC as _TOC, Structure,  # noqa: F401
                                   document, heading_like as _heading_like, norm_num, ordinal, pieces, roman)

_REF = [
    ("clause", re.compile(rf"cl[aá]usula\s+(\d{{1,2}}(?:\.\d{{1,2}}){{0,3}}|{_ORDINAL_RE}|[IVXL]{{1,6}}(?=[\s.,;)]|$))", re.I)),
    ("section", re.compile(r"apartado\s+([A-Z0-9]\w{0,3}(?:\.\d{1,2}){0,3})(?=[\s,.;:)]|$)", re.I)),
    ("annex", re.compile(r"anexo\s+([IVXLC]+|\d{1,2})\b", re.I)),
]
_SOLVENCY = {"financial": re.compile(r"solvencia\b.{0,30}(econ[oó]mica|financiera)", re.I),
             "technical": re.compile(r"solvencia\b.{0,40}(t[eé]cnica|profesional)", re.I),
             "classification": re.compile(r"clasificaci[oó]n", re.I)}
_SOLVENCY_ANY = re.compile(r"solvencia|aptitud|capacidad para contratar|clasificaci[oó]n", re.I)
_LOT = re.compile(r"\blote\s*(?:n(?:[º°o.]|ú?mero)?\s*)?(\d{1,3})\b", re.I)
_NIF = re.compile(r"\b([A-HJ-NP-SUVW]-?\d{7}-?[0-9A-J]|\d{8}-?[A-Z])\b")
_GUARANTEE = {"1": re.compile(r"garant[ií]a\s+provisional", re.I), "2": re.compile(r"garant[ií]a\s+definitiva", re.I),
              "3": re.compile(r"garant[ií]a\s+complementaria", re.I)}


class Doc:
    """A document's text, its lines, headings and furniture (sections.py), and the map from text
    offsets to chunk offsets."""

    def __init__(self, text: str, chunk_words: int, chunker: str | None = None, text_path: str | None = None,
                 layout: dict | None = None):
        self.text = text
        if text_path:
            self.chunks = document(str(text_path), chunk_words, chunker)[0]
        else:
            self.chunks = pieces(text, chunk_words, chunker, layout)
        self.pages = page_ranges(self.chunks)
        counts = [len(c.split()) for c in self.chunks]
        self.chunk_start = [sum(counts[:i]) for i in range(len(counts))]
        self.words = [m.span() for m in re.finditer(r"\S+", text)]
        self.word_starts = [s for s, _ in self.words]
        self.structure = Structure(text, layout)
        self.lines = self.structure.lines
        self.furniture = self.structure.furniture
        self.headings = self.structure.headings

    def in_furniture(self, offset: int) -> bool:
        return self.structure.line_of(offset) in self.furniture

    def line_at(self, start: int, end: int) -> str:
        """The whole line(s) a span is on."""
        a = self.text.rfind("\n", 0, start) + 1
        b = self.text.find("\n", end)
        return self.text[a:b if b >= 0 else len(self.text)].strip()

    def windows(self, span: int = 2):
        """Each line alone and joined with the next ones (names wrap)."""
        for i, (start, line) in enumerate(self.lines):
            if i in self.furniture:
                continue
            text = line
            yield start, start + len(line), text
            for j in range(i + 1, min(i + span, len(self.lines))):
                text = text + " " + self.lines[j][1]
                yield start, self.lines[j][0] + len(self.lines[j][1]), text

    def to_chunk(self, start: int, end: int) -> tuple[int, int, int] | None:
        """(chunk index, start, end) within that chunk, of the words the text span covers. A span
        that runs into the next chunk is cut at the end of the first."""
        if not self.words or not self.chunks:
            return None
        a = max(0, bisect_right(self.word_starts, start) - 1)
        if self.words[a][1] <= start:
            a += 1
        b = bisect_left(self.word_starts, end) - 1
        if a >= len(self.words) or b < a:
            return None
        idx = bisect_right(self.chunk_start, a) - 1
        if idx + 1 < len(self.chunk_start):
            b = min(b, self.chunk_start[idx + 1] - 1)
        spans = [m.span() for m in re.finditer(r"\S+", self.chunks[idx])]
        la, lb = a - self.chunk_start[idx], b - self.chunk_start[idx]
        if lb >= len(spans):
            return None
        # A word is the same characters in the text and in the chunk: cut inside it as the span does.
        head = max(0, start - self.words[a][0])
        tail = max(0, self.words[b][1] - end) if b == bisect_left(self.word_starts, end) - 1 else 0
        return idx, spans[la][0] + head, spans[lb][1] - tail


def _points_re(points) -> re.Pattern | None:
    if points in (None, ""):
        return None
    p = float(points)
    whole = str(int(p)) if p == int(p) else str(p).replace(".", "[.,]")
    return re.compile(rf"(?<![\d.,]){whole}(?:[.,]0+)?\s*(?:puntos|ptos|pts|p\.|%|$)", re.I)


_WORD = re.compile(r"[^\W_]+")


def cluster(text: str, offset: int, want: set[str], max_len: int) -> tuple[int, int]:
    """The shortest stretch of `text` holding the most of `want`'s terms, as absolute offsets: the
    name inside the line that holds it."""
    hits = [(m.start(), m.end(), stem(t)) for m in _WORD.finditer(text)
            if (t := fold(m.group())) not in STOP and stem(t) in want]
    if not hits:
        return offset, offset + len(text)
    best = (0, 0, 1)
    for i in range(len(hits)):
        seen = set()
        for j in range(i, len(hits)):
            if hits[j][1] - hits[i][0] > max_len:
                break
            seen.add(hits[j][2])
            if (len(seen), -(hits[j][1] - hits[i][0])) > (best[2], -(hits[best[1]][1] - hits[best[0]][0])):
                best = (i, j, len(seen))
    return offset + hits[best[0]][0], offset + hits[best[1]][1]


def find_criterion(doc: Doc, name: str, points) -> list[tuple[int, int]]:
    want = set(terms(name or ""))
    if not want:
        return []
    pts = _points_re(points)
    hits, last_end = [], -1
    for start, end, text in doc.windows():
        if start < last_end:
            continue
        have = terms(text)
        if not have:
            continue
        cover = len(want & set(have)) / len(want)
        short = len(have) <= 2 * len(want) + 8
        with_points = bool(pts and pts.search(text))
        # A one-word name ("Precio", "Prezo") with its points at the start of its line: the layout
        # pass joins a criterion's line with the explanation that follows it.
        head = terms(text[:120])
        if (len(want) == 1 and cover == 1 and with_points and (len(have) <= 14 or (want & set(head[:4])
                                                                                    and pts.search(text[:160])))) or \
                (len(want) > 1 and cover >= 0.8 and (short or with_points)):
            hits.append(cluster(text, start, want, 2 * len(name) + 20))
            last_end = end
    return hits


def find_text(doc: Doc, text: str) -> list[tuple[int, int]]:
    """Where a requirement written in the feed is written in the document (its first 25 terms)."""
    want = set(terms(text or "")[:25])
    if len(want) < 3:
        return []
    out, last_end = [], -1
    for start, end, window in doc.windows(span=3):
        if start < last_end:
            continue
        if len(want & set(terms(window))) / len(want) >= 0.75:
            out.append(cluster(window, start, want, 2 * len(text) + 40))
            last_end = end
    return out


def references(text: str) -> list[tuple[str, str]]:
    """What a feed requirement points at, outermost first: [("annex", "I"), ("section", "9.1")]
    for "apartado 9.1 del anexo I"; [("clause", "10"), ("letter", "C")] for "cláusula X. C)"."""
    out = []
    for kind, rx in _REF:
        for m in rx.finditer(text or ""):
            num = norm_num(kind, m.group(1))
            out.append((m.start(), kind, num))
    for m in re.finditer(r"(?<![A-Za-z])([A-Z])\)", text or ""):
        out.append((m.start(), "letter", m.group(1)))
    rank = {"annex": 0, "clause": 1, "section": 2, "letter": 3}
    return [(k, n) for _, k, n in sorted(out, key=lambda x: (rank[x[1]], x[0]))]


_KINDS = {"annex": ("annex",), "clause": ("clause", "number"), "section": ("section", "letter", "number"),
          "letter": ("letter", "section")}


def find_clause(doc: Doc, req: dict) -> list[tuple[int, int]]:
    """The heading of the clause a feed requirement points at, each pointer looked for after the
    one that contains it ("apartado 9.1" after "ANEXO I"); else the solvency heading of its group."""
    refs = references(req.get("text") or "")

    def walk(i: int, pos: int) -> list[dict]:
        if i == len(refs):
            return []
        kind, num = refs[i]
        kinds = _KINDS[kind]
        cands = [h for h in doc.headings if h["kind"] in kinds and h["num"] == num and h["start"] >= pos]
        cands.sort(key=lambda h: (not _SOLVENCY_ANY.search(h["title"]), kinds.index(h["kind"]), h["start"]))
        best = []
        for h in cands[:6]:
            path = [h] + walk(i + 1, h["start"])
            if len(path) > len(best):
                best = path
            if len(best) == len(refs) - i:
                break
        return best or walk(i + 1, pos)

    path = walk(0, 0)
    if path:
        return [(path[-1]["start"], path[-1]["end"])]
    rx = _SOLVENCY.get(req.get("group") or "")
    hits = [h for h in doc.headings if rx and rx.search(h["title"])]
    return [(h["start"], h["end"]) for h in hits[:2]]


def find_regex(doc: Doc, rx: re.Pattern, accept=lambda m: True) -> list[tuple[int, int]]:
    return [m.span() for m in rx.finditer(doc.text) if accept(m)]


def find_name(doc: Doc, name: str | None, nif: str | None, aliases: list[str] = ()) -> list[tuple[int, int]]:
    out = []
    if nif:
        n = G.norm_nif(nif)
        out += [m.span() for m in _NIF.finditer(doc.text) if G.norm_nif(m.group(1)) == n]
    for nm in [name, *aliases]:
        norm = G.norm_name(nm)
        if len(norm.split()) < 2:
            continue
        want = set(terms(norm))
        for start, line in doc.lines:
            if norm in G.norm_name(line) or norm in fold(line):
                out.append(cluster(line, start, want, len(nm or "") + 20))
    return sorted(set(out))


def targets(eid: str, e, t: dict) -> list[dict]:
    """The feed nodes to look for, with how to find each: built exactly as the graph builds them."""
    from placsp_pilot.entities import _anchors, divided
    fg, sk = _anchors(eid, e, t)
    out = []
    auth = fg.nodes[sk["auth"]]
    # The feed often names the body that signs ("Alcaldía", "la Directora General de…"); the
    # documents, the organization it belongs to, which the feed gives as its hierarchy.
    out.append({"id": auth["id"], "type": "CONTRACTING_AUTHORITY", "name": auth.get("name"), "how": "name", "nif": auth.get("nif"),
                "aliases": [h for h in auth.get("hierarchy") or [] if isinstance(h, str)]})
    is_divided = divided(t)
    for n in fg.nodes.values():
        lab = n["label"]
        if lab == "AwardCriterion":
            out.append({"id": n["id"], "type": "AWARD_CRITERION", "name": n.get("name"), "how": "criterion", "points": n.get("points"),
                        "pointer": n.get("formula")})
        elif lab == "Requirement":
            ref = reference_only(n.get("text"), n.get("amount"))
            out.append({"id": n["id"], "type": "REQUIREMENT", "name": n.get("name"), "how": "clause" if ref else "text",
                        "text": n.get("text"), "group": n.get("group")})
        elif lab == "Lot" and is_divided:
            out.append({"id": n["id"], "type": "LOT", "name": f"Lote {n['number']}", "how": "lot", "number": str(n["number"])})
        elif lab == "Guarantee":
            code = n["id"].split(":")[2]
            if code in _GUARANTEE:
                out.append({"id": n["id"], "type": "GUARANTEE", "name": n.get("name"), "how": "guarantee", "code": code})
        elif lab == "Organization" and n["id"] != auth["id"]:
            out.append({"id": n["id"], "type": "COMPANY", "name": n.get("name"), "how": "name", "nif": n.get("nif")})
    return out


def find(doc: Doc, tgt: dict, role: str | None) -> list[tuple[int, int]]:
    """Where the document names the feed entity, outside the page furniture (a letterhead names the
    authority on every page; that is not a mention)."""
    return [sp for sp in _find(doc, tgt, role) if not doc.in_furniture(sp[0])]


def _find(doc: Doc, tgt: dict, role: str | None) -> list[tuple[int, int]]:
    how = tgt["how"]
    if how == "criterion":
        hits = find_criterion(doc, tgt["name"], tgt.get("points"))
        # The feed's detail may only point at the pliego ("Ver apartado 21 del Anexo I").
        if not hits and role in PCAP_ROLES and references(tgt.get("pointer") or ""):
            hits = find_clause(doc, {"text": tgt["pointer"]})
        return hits
    if how == "clause":
        return find_clause(doc, tgt) if role in PCAP_ROLES else []
    if how == "text":
        # Written out, and maybe also pointing at its clause ("…, según Apartado 13 del Anexo I").
        hits = find_text(doc, tgt.get("text"))
        if role in PCAP_ROLES and references(tgt.get("text") or ""):
            hits += find_clause(doc, {"text": tgt["text"]})
        return hits
    if how == "lot":
        return find_regex(doc, _LOT, lambda m: m.group(1).lstrip("0") == tgt["number"].lstrip("0"))
    if how == "guarantee":
        return find_regex(doc, _GUARANTEE[tgt["code"]])
    if how == "name":
        return find_name(doc, tgt.get("name"), tgt.get("nif"), tgt.get("aliases") or [])
    return []


def locate(cfg, store) -> dict:
    """Rebuild the `feed` mentions of every expediente. Returns, per entity type, how many feed
    entities there are and how many were found (in any document and in the PCAP)."""
    from placsp_pilot.entities import schema
    schema(store)
    docs: dict[str, Doc] = {}
    rows, stats = [], {}
    for e in store.q("SELECT * FROM expediente ORDER BY id"):
        eid = e["id"]
        t = json.loads(e["tender_json"])
        refs = store.q("SELECT d.sha, MIN(d.role) role, b.text_path, b.chunker FROM docref d JOIN blob b ON b.sha=d.sha"
                       " WHERE d.exp_id=? AND d.status='fetched' AND b.text_status='ok' GROUP BY d.sha", (eid,))
        refs = [r for r in refs if r["role"] not in SKIP_ROLES and r["text_path"]]
        for tgt in targets(eid, e, t):
            st = stats.setdefault(tgt["type"] + ("" if tgt["how"] != "clause" else " (points at the pliego)"),
                                  {"feed": 0, "found": 0, "in_pcap": 0, "mentions": 0})
            st["feed"] += 1
            found = in_pcap = False
            for r in refs:
                if r["sha"] not in docs:
                    docs[r["sha"]] = Doc(Path(r["text_path"]).read_text(encoding="utf-8"), cfg.chunk_words, r["chunker"],
                                         r["text_path"], load_layout(r["text_path"]))
                doc = docs[r["sha"]]
                for k, (s, en) in enumerate(find(doc, tgt, r["role"])[:MAX_PER_DOC]):
                    loc = doc.to_chunk(s, en)
                    if not loc:
                        continue
                    idx, cs, ce = loc
                    chunk = doc.chunks[idx]
                    page = _page(chunk, cs, doc.pages[idx][0])
                    quote = chunk[cs:ce]
                    rows.append((f"{r['sha']}:{idx}:f:{eid}:{tgt['id']}:{k}", r["sha"], idx, k, tgt["type"], None,
                                 tgt.get("name") or quote[:120], quote[:200], "{}", doc.line_at(s, en)[:600], 1.0,
                                 cs, ce, page, 1, cs, ce, tgt["id"]))
                    found = True
                    in_pcap = in_pcap or r["role"] in PCAP_ROLES
                    st["mentions"] += 1
            st["found"] += found
            st["in_pcap"] += in_pcap
    with store.tx() as c:
        c.execute("DELETE FROM mention WHERE kind='feed'")
        c.executemany("INSERT OR REPLACE INTO mention (id, sha, idx, k, type, subtype, name, surface, attributes, evidence,"
                      " confidence, char_start, char_end, page, located, name_start, name_end, target, kind)"
                      " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,'feed')", rows)
    log(f"locate: {len(rows)} feed mentions; " + "; ".join(
        f"{k} {v['found']}/{v['feed']}" for k, v in sorted(stats.items())))
    return stats


def _page(chunk: str, offset: int, chunk_page):
    from placsp_pilot.entities import page_at
    return page_at(chunk, offset, chunk_page)


# The sections of a pliego administrativo where what NER still looks for in it is written:
# penalties, qualifications, and the requirements and criteria the feed does not give.
PCAP_SECTIONS = re.compile(r"penalidad|penalizaci|incumplimiento|demora|solvencia|clasificaci|aptitud|criterio|"
                           r"adjudicaci|valoraci|baremo|puntuaci|garant[ií]a|adscripci|medios|subcontrat|"
                           r"condiciones especiales|cuadro (de )?(caracter|resumen)|car[aá]tula|anexo i\b", re.I)
MIN_HEADINGS = 8         # fewer: the document is not structured enough to choose by section
# Words that, in a chunk outside those sections, still say it holds one of the types.
TYPE_CUES = {
    "PENALTY": r"penalidad|penalizaci",
    "QUALIFICATION": r"\biso\b|\bens\b|une-?en|titulaci|titulad|ingenier|licenciad|graduad|colegiad|habilitaci|subgrupo|carne profesional",
    "AWARD_CRITERION": r"puntos|puntuaci|ponderaci|criterio",
    "REQUIREMENT": r"solvencia|volumen anual|seguro de responsabilidad|trabajos (realizados|similares)|clasificaci",
    "GUARANTEE": r"garant[ií]a (provisional|definitiva|complementaria)",
}


def relevant_chunks(text: str, chunk_words: int, types: set[str] = frozenset(), rx: re.Pattern = PCAP_SECTIONS,
                    chunker: str | None = None, text_path: str | None = None) -> set[int] | None:
    """The chunks in a section whose heading (or a parent's) matches `rx`, plus those whose own words
    cue one of `types`. None when the document has too few headings to tell: then every chunk counts."""
    layout = load_layout(text_path) if text_path else None
    doc = Doc(text, chunk_words, chunker, text_path, layout)
    if len(doc.headings) < MIN_HEADINGS:
        return None
    cues = [re.compile(TYPE_CUES[t], re.I) for t in types if t in TYPE_CUES]
    out = {i for i, c in enumerate(doc.chunks) if any(cue.search(fold(c)) for cue in cues)}
    if chunker == "sections" and text_path:
        paths = document(str(text_path), chunk_words, chunker)[1]
        return out | {i for i, path in enumerate(paths) if any(rx.search(p) for p in path)}
    current = False
    marks = [(doc.to_chunk(h["start"], h["end"]) or (None,))[0] for h in doc.headings]
    by_chunk: dict[int, list[dict]] = {}
    for h, idx in zip(doc.headings, marks):
        if idx is not None:
            by_chunk.setdefault(idx, []).append(h)
    for idx in range(len(doc.chunks)):
        hs = by_chunk.get(idx, [])
        if current or any(rx.search(h["title"]) or rx.search(h["kind"] + " " + h["num"]) for h in hs):
            out.add(idx)
        if hs:
            current = bool(rx.search(hs[-1]["title"]))
    return out
