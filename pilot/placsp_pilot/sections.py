"""A document's structure: page furniture, headings, the section tree, and chunks cut at sections.

The text is never changed. Furniture (the header and footer repeated on every page: the
authority's letterhead, "Página 3 de 18", "Cód. Validación: …", "Documento firmado
electrónicamente…") is only detected: the reader shows it, to place pages; headings, NER and the
locator skip it. It comes from two sources:
  layout      the PDF's page-header / page-footer boxes (pymupdf4llm's layout model, textract.py),
              saved beside the text as <sha>.layout.json with the headings and tables it found
  repetition  a line in the first or last lines of a page that recurs, numbers aside, on most
              pages; this works for any text with page markers, old runs included

Headings are numbered lines ("CLÁUSULA OCTAVA", "9.1 SOLVENCIA", "ANEXO I", "B) Solvencia…"),
Markdown headings from the layout pass, and the layout's section-header boxes; never a line of a
table of contents, a table row or furniture. Their levels make the section tree, and every chunk
carries the path of the section it starts in ("ANEXO I › 9 › 9.1 SOLVENCIA ECONÓMICA").

Chunking (chunker "sections"): a chunk starts at each top-level section and holds whole
sub-sections up to the word budget; a section over the budget is cut at paragraphs, and a table at
rows. Chunks are consecutive stretches of the text, so their words are the text's words in order,
as with the older "words" chunker (nlp_service's), which blobs extracted before keep.
"""
import json
import re
from functools import lru_cache
from pathlib import Path

from placsp_pilot.lexical import fold

PAGE_LINE = re.compile(r"^\[Página (\d+)\]$")
EDGE_LINES = 5           # lines at the top and the bottom of a page where furniture lives
FURNITURE_SHARE = 0.4    # a line on this share of the pages (and on 3 at least) is furniture
BOX_MAX_WORDS = 12       # a header / footer box line this short counts even if it does not recur
MIN_SHARE = 0.5          # a top-level section starts a new chunk once the current one holds half the budget

_UNITS = ["primer", "segund", "tercer", "cuart", "quint", "sext", "septim", "octav", "noven"]
_TENS = {"decim": 10, "vigesim": 20, "trigesim": 30}
_SPECIAL = {"undecim": 11, "duodecim": 12}
ORDINAL_RE = r"(?:(?:decim|vigesim|trigesim)[oa]?\s*)?(?:primer|segund|tercer|cuart|quint|sext|septim|octav|noven|undecim|duodecim|decim|vigesim|trigesim)[oa]?"
_ROMAN = {"I": 1, "V": 5, "X": 10, "L": 50, "C": 100}

TOC = re.compile(r"(\.{4,}|…{2,}|_{4,}|·{4,}).{0,8}$")
HEADINGS = [
    ("clause", re.compile(rf"^(?:cl[aá]usula|cláusula)\s+(?P<num>\d{{1,2}}(?:\.\d{{1,2}}){{0,3}}|{ORDINAL_RE})\b[ªº]?\s*[.:\-–]?\s*(?P<title>.*)", re.I)),
    ("annex", re.compile(r"^anexo\s+(?P<num>[IVXLC]+|\d{1,2})\b\.?\s*[.:\-–]?\s*(?P<title>.*)", re.I)),
    ("section", re.compile(r"^apartado\s+(?P<num>[A-Z0-9](?:[\w.]{0,6}))\s*[.:\-–)]?\s*(?P<title>.*)", re.I)),
    ("number", re.compile(r"^(?P<num>\d{1,2}(?:\.\d{1,2}){0,3}|[IVXL]{1,6}(?=\.))\.?(?:\s*[-–.)])?\s+(?P<title>[A-ZÁÉÍÓÚÑ].{2,})")),
    ("letter", re.compile(r"^(?P<num>[A-Z])\s?[).\-–]\s+(?P<title>[A-ZÁÉÍÓÚÑ].{2,})")),
]
_MD_HEADING = re.compile(r"^(#{1,6})\s+(.*)$")
_NIF_IN = re.compile(r"\b[A-HJ-NP-SUVW]-?\d{7}-?[0-9A-J]\b")
_MARKUP = re.compile(r"[*_`#]+|</?(br|u|b|i|em|strong|sup|sub)\s*/?>", re.I)
# A paragraph that opens with an emphasised run is headed by it: "**13.- Solvencia.** Los
# licitadores…", "<u>13.- Los licitadores deberán incluir en el SOBRE</u> -archivo…". The layout
# pass joins wrapped lines, so such a heading is the start of a long line, not a line of its own.
_LEAD = re.compile(r"^(?:[-*]\s+)?(?P<pre>\d{1,2}(?:\.\d{1,2}){0,3}\.?-?\s*)?(?:\*\*|<u>|<b>|<strong>)(?P<run>.+?)(?:\*\*|</u>|</b>|</strong>)", re.I)
_PAGE_NUMBER = re.compile(r"^[-–\s]*(p[aá]g(ina)?\.?\s*)?([ivxlc]+|\d+)(\s*(de|/)\s*\d+)?[-–\s]*$", re.I)


def ordinal(word: str) -> int | None:
    """"octava" -> 8, "decimotercera" / "décima tercera" -> 13, "vigésimo primera" -> 21."""
    w = re.sub(r"\s+", "", fold(word))
    for k, v in _SPECIAL.items():
        if w.startswith(k):
            return v
    base = 0
    for k, v in _TENS.items():
        if w.startswith(k):
            base, w = v, re.sub(r"^[oa]", "", w[len(k):])
            break
    for i, u in enumerate(_UNITS, 1):
        if w.startswith(u):
            return base + i
    return base or None


def roman(s: str) -> int | None:
    if not s or any(c not in _ROMAN for c in s.upper()):
        return None
    vals = [_ROMAN[c] for c in s.upper()]
    return sum(-v if i + 1 < len(vals) and v < vals[i + 1] else v for i, v in enumerate(vals))


def norm_num(kind: str, num: str) -> str:
    """Clause and section numbers compared as written in figures: "octava", "VIII" and "8" are 8."""
    num = num.strip().rstrip(".").upper()
    if kind in ("clause", "number") and not num[0].isdigit():
        n = roman(num) or (ordinal(num) if kind == "clause" else None)
        return str(n) if n else num
    return num


def heading_like(title: str) -> bool:
    """A numbered line is a heading when it reads like a title (upper case, or a few words), not
    like an item of a list in running text ("2. Acreditar los requisitos de solvencia, …")."""
    letters = [c for c in title if c.isalpha()]
    upper = sum(c.isupper() for c in letters) / len(letters) if letters else 0
    return upper >= 0.6 or (len(title.split()) <= 8 and not title.rstrip().endswith((",", ";")))


def _numbered_heading(line: str) -> bool:
    plain = _MARKUP.sub("", line).strip()
    md = _MD_HEADING.match(plain)
    plain = md.group(2) if md else plain
    return any(kind in ("clause", "annex", "section") and rx.match(plain) for kind, rx in HEADINGS)


def line_key(line: str) -> str:
    """A line as furniture is compared: no markup, no accents or case, numbers as #."""
    s = fold(_MARKUP.sub(" ", line))
    return re.sub(r"\s+", " ", re.sub(r"\d+", "#", s)).strip(" |-–")


def load_layout(text_path: str | Path) -> dict | None:
    p = Path(text_path).with_suffix(".layout.json")
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None


class Structure:
    """Lines, furniture, headings and sections of one text."""

    def __init__(self, text: str, layout: dict | None = None):
        self.text = text
        self.lines: list[tuple[int, str]] = []
        pos = 0
        for line in text.split("\n"):
            self.lines.append((pos, line))
            pos += len(line) + 1
        self.starts = [s for s, _ in self.lines]
        self.layout = layout or {}
        self.furniture = self._furniture()
        self.furniture_keys = {line_key(self.lines[i][1]) for i in self.furniture} - {""}
        self.headings = self._headings()

    def line_of(self, offset: int) -> int:
        from bisect import bisect_right
        return max(0, bisect_right(self.starts, offset) - 1)

    def _spans_to_lines(self, spans) -> set[int]:
        out = set()
        for a, b in spans or []:
            out.update(range(self.line_of(a), self.line_of(max(a, b - 1)) + 1))
        return out

    def _furniture(self) -> set[int]:
        # The layout model sometimes calls the last paragraph of a page its footer: a boxed line
        # counts when it recurs (numbers aside) or is short, as headers and footers are.
        boxed = self._spans_to_lines(self.layout.get("furniture"))
        recurs = {}
        for i in boxed:
            recurs.setdefault(line_key(self.lines[i][1]), set()).add(i)
        out = {i for i in boxed if len(recurs[line_key(self.lines[i][1])]) > 1 or len(self.lines[i][1].split()) <= BOX_MAX_WORDS}
        pages, cur = [], []
        for i, (_, line) in enumerate(self.lines):
            if PAGE_LINE.match(line.strip()):
                if cur:
                    pages.append(cur)
                cur = []
            elif line.strip():
                cur.append(i)
        if cur:
            pages.append(cur)
        if len(pages) < 3:
            return out
        edges = [p[:EDGE_LINES] + p[-EDGE_LINES:] for p in pages]
        seen: dict[str, set[int]] = {}
        for n, edge in enumerate(edges):
            for i in edge:
                k = line_key(self.lines[i][1])
                if len(k) >= 3:
                    seen.setdefault(k, set()).add(n)
        need = max(3, FURNITURE_SHARE * len(pages))
        common = {k for k, ps in seen.items() if len(ps) >= need}
        for edge in edges:
            for i in edge:
                line = self.lines[i][1].strip()
                # A numbered heading that opens every page ("CLÁUSULA 3…") recurs once numbers are
                # hidden, but it is the text's own; only the layout's boxes can call it furniture.
                if _numbered_heading(line):
                    continue
                if line_key(line) in common or _PAGE_NUMBER.match(fold(_MARKUP.sub(" ", line)).strip()):
                    out.add(i)
        return out

    def _headings(self) -> list[dict]:
        tables = self._spans_to_lines(self.layout.get("tables"))
        boxed = self._spans_to_lines(self.layout.get("headings"))
        out, depth = [], 1
        for i, (start, line) in enumerate(self.lines):
            s = line.strip()
            if not s or i in self.furniture or i in tables or s.startswith("|") or len(s) > 220 or TOC.search(s):
                continue
            md = _MD_HEADING.match(s)
            lead = None if md else _LEAD.match(s)
            if lead and len(s) > len(lead.group(0)) + 40:
                plain = _MARKUP.sub("", (lead.group("pre") or "") + lead.group("run")).strip()
            else:
                plain = _MARKUP.sub("", md.group(2) if md else s).strip()
                lead = None
            h = None
            for kind, rx in HEADINGS:
                m = rx.match(plain)
                if m and (kind not in ("number", "letter") or lead or heading_like(m.group("title"))):
                    num = norm_num(kind, m.group("num"))
                    level = 1 if kind in ("clause", "annex") else (num.count(".") + 1 if kind in ("number", "section")
                                                                  else min(depth + 1, 4))
                    h = {"kind": kind, "num": num, "title": m.group("title").strip(), "level": level}
                    break
            if h is None and (md or i in boxed) and len(plain.split()) <= 25:
                h = {"kind": "layout", "num": "", "title": plain, "level": min(len(md.group(1)), 3) if md else 2}
            if h is None or _NIF_IN.search(plain):     # "1.- B13564596 (MARTATOR)": a bidder in a list
                continue
            if h["kind"] != "letter":
                depth = h["level"]
            off = start + line.index(s)
            end = off + (len(lead.group(0)) if lead else len(s))
            out.append({**h, "start": off, "end": end, "line": i, "label": plain})
        self._paths(out)
        return out

    @staticmethod
    def _paths(headings: list[dict]):
        stack: list[dict] = []
        for h in headings:
            while stack and stack[-1]["level"] >= h["level"]:
                stack.pop()
            stack.append(h)
            h["path"] = [x["label"][:80] for x in stack]

    def path_at(self, offset: int) -> list[str]:
        """The section an offset of the text is in."""
        cur = []
        for h in self.headings:
            if h["start"] > offset:
                break
            cur = h["path"]
        return cur


def _split_block(block: str, max_words: int) -> list[str]:
    """A section over the budget: at paragraphs; a paragraph over it (a long table) at lines."""
    from placsp_pilot.nlpstages import split_words
    paras = [p for p in re.split(r"\n\s*\n", block) if p.strip()]
    out, cur, n = [], [], 0
    for p in paras:
        w = len(p.split())
        if w > max_words and "\n" in p.strip():
            if cur:
                out.append("\n\n".join(cur))
                cur, n = [], 0
            rows, rn = [], 0
            for line in p.strip().split("\n"):
                lw = len(line.split())
                if rows and rn + lw > max_words:
                    out.append("\n".join(rows))
                    rows, rn = [], 0
                if lw > max_words:
                    out.extend(split_words(line, max_words))
                    continue
                rows.append(line)
                rn += lw
            if rows:
                out.append("\n".join(rows))
            continue
        if w > max_words:
            if cur:
                out.append("\n\n".join(cur))
                cur, n = [], 0
            out.extend(split_words(p, max_words))
            continue
        if cur and n + w > max_words:
            out.append("\n\n".join(cur))
            cur, n = [], 0
        cur.append(p.strip())
        n += w
    if cur:
        out.append("\n\n".join(cur))
    return [x.strip() for x in out if x.strip()]


def chunk_sections(text: str, max_words: int, layout: dict | None = None) -> list[tuple[str, list[str]]]:
    """Chunks cut at sections, each with the path of the section it starts in, followed by the
    top-level sections that open inside it (a short one shares its chunk with the one before)."""
    st = Structure(text, layout)
    cuts = [h for h in st.headings if h["level"] <= 2]
    bounds = [0] + [h["start"] for h in cuts] + [len(text)]
    blocks = []
    for k in range(len(bounds) - 1):
        a, b = bounds[k], bounds[k + 1]
        body = text[a:b]
        if body.strip():
            blocks.append((body, cuts[k - 1] if k > 0 else None, st.path_at(a)))
    out, cur, cur_words, cur_path, opened = [], [], 0, None, []
    min_words = int(MIN_SHARE * max_words)

    def flush():
        nonlocal cur, cur_words, cur_path, opened
        if cur:
            out.append(("\n\n".join(x.strip("\n") for x in cur).strip(), (cur_path or []) + opened))
        cur, cur_words, cur_path, opened = [], 0, None, []

    for body, head, path in blocks:
        w = len(body.split())
        top = head is not None and head["level"] == 1
        if cur and (cur_words + w > max_words or (top and cur_words >= min_words)):
            flush()
        if cur and top and w <= max_words:
            opened.append(head["label"][:80])
        if w > max_words:
            # Cut at paragraphs; the last piece starts the next chunk, so what follows fills it.
            flush()
            parts = _split_block(body, max_words)
            out.extend((piece, path) for piece in parts[:-1])
            cur, cur_words, cur_path = [parts[-1]], len(parts[-1].split()), path
            continue
        if not cur:
            cur_path = path
        cur.append(body)
        cur_words += w
    flush()
    return [(p, path) for p, path in out if p]


def pieces(text: str, max_words: int, chunker: str | None, layout: dict | None = None) -> list[str]:
    """A document's chunks, by the chunker its text was extracted for."""
    if chunker == "sections":
        return [p for p, _ in chunk_sections(text, max_words, layout)]
    from placsp_pilot.nlpstages import split_words
    return split_words(text, max_words)


@lru_cache(maxsize=64)
def document(text_path: str, max_words: int, chunker: str | None) -> tuple[list[str], list[list[str]], frozenset]:
    """(chunks, section path of each, furniture line keys) of a stored text, cached."""
    text = Path(text_path).read_text(encoding="utf-8")
    layout = load_layout(text_path)
    if chunker == "sections":
        cs = chunk_sections(text, max_words, layout)
        chunks, paths = [p for p, _ in cs], [path for _, path in cs]
    else:
        from placsp_pilot.nlpstages import split_words
        chunks = split_words(text, max_words)
        st = Structure(text, layout)
        paths, pos = [], 0
        for c in chunks:      # where each chunk starts in the text: its first word, searched forward
            first = c.split()[0] if c.split() else ""
            pos = max(pos, text.find(first, pos)) if first else pos
            paths.append(st.path_at(pos))
        return chunks, paths, frozenset(st.furniture_keys)
    return chunks, paths, frozenset(Structure(text, layout).furniture_keys)


def without_furniture(chunk: str, keys: frozenset) -> str:
    """The chunk as NER reads it: the furniture lines out (the stored text keeps them)."""
    if not keys:
        return chunk
    keep = [line for line in chunk.split("\n")
            if line_key(line) not in keys and not _PAGE_NUMBER.match(fold(_MARKUP.sub(" ", line)).strip() or "x")]
    return "\n".join(keep)


def furniture_ranges(chunk: str, keys: frozenset) -> list[list[int]]:
    """[start, end) of the chunk's furniture lines, for the reader to fold."""
    out, at = [], 0
    for line in chunk.split("\n"):
        if line.strip() and (line_key(line) in keys or _PAGE_NUMBER.match(fold(_MARKUP.sub(" ", line)).strip())):
            out.append([at, at + len(line)])
        at += len(line) + 1
    return out
