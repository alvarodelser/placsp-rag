"""Turn a downloaded file into plain text.

Formats seen in the feeds: pdf (most), html (notices), doc/docx/odt, xls/xlsx/ods,
pptx, zip, bc3 (FIEBDC budgets), dwg/kmz (drawings and maps, not text).
Scanned PDFs go to the OCR service when OCR_URL is set; otherwise they are
marked needs_ocr so the report can count them.
"""
import io
import re
import shutil
import subprocess
import tempfile
import time
import zipfile
from dataclasses import dataclass, field
from pathlib import Path

import httpx
from lxml import etree

TEXT_EXTS = {"txt", "csv", "bc3", "md", "kml"}
UNSUPPORTED = {"dwg", "dxf", "kmz", "shp", "dgn", "pzh", "rar", "7z", "jpg", "jpeg", "png", "tif", "tiff",
               "gif", "bmp", "mp4", "p7s", "xsig", "exe", "gml"}


@dataclass
class TextResult:
    status: str                 # ok | empty | unsupported | failed | needs_ocr | archive
    method: str = ""
    text: str = ""
    pages: int | None = None
    ocr_pages: int = 0
    ocr_ms: int = 0
    error: str = ""
    members: list = field(default_factory=list)   # for archives: [(name, bytes)]
    # The layout pass's boxes as character spans of `text`: furniture (page headers and footers),
    # headings and tables (sections.py reads them). None for a plain extraction.
    layout: dict | None = None


def sniff(data: bytes, filename: str | None, mime: str | None) -> str:
    """Best guess of the file extension from magic bytes, then mime, then name."""
    head = data[:8]
    name_ext = (filename or "").rsplit(".", 1)[-1].lower() if filename and "." in filename else ""
    if head.startswith(b"%PDF"):
        return "pdf"
    if head.startswith(b"PK\x03\x04"):
        if name_ext in {"docx", "xlsx", "pptx", "odt", "ods", "odp", "kmz", "zip"}:
            return name_ext
        try:
            names = zipfile.ZipFile(io.BytesIO(data)).namelist()
        except zipfile.BadZipFile:
            return "zip"
        if "word/document.xml" in names:
            return "docx"
        if "xl/workbook.xml" in names:
            return "xlsx"
        if "ppt/presentation.xml" in names:
            return "pptx"
        if "content.xml" in names:
            return "odt"
        return "zip"
    if head.startswith(b"\xd0\xcf\x11\xe0"):
        return name_ext if name_ext in {"doc", "xls", "ppt", "msg"} else "doc"
    if head.startswith(b"{\\rtf"):
        return "rtf"
    if head.startswith(b"Rar!"):
        return "rar"
    if head.startswith(b"7z\xbc\xaf"):
        return "7z"
    if head[:4] in (b"\x89PNG", b"GIF8") or head[:3] == b"\xff\xd8\xff":
        return "png" if head[:4] == b"\x89PNG" else ("gif" if head[:4] == b"GIF8" else "jpg")
    m = (mime or "").lower()
    if "html" in m or data[:600].lstrip().lower().startswith((b"<!doctype html", b"<html")):
        return "html"
    if "xml" in m or data[:100].lstrip().startswith(b"<?xml"):
        return "xml"
    return name_ext or "bin"


def _decode(data: bytes) -> str:
    for enc in ("utf-8", "cp1252", "latin-1"):
        try:
            return data.decode(enc)
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", "replace")


_NORM_STEPS = [(re.compile("\x00"), ""), (re.compile(r"[ \t\u00a0]+"), " "), (re.compile(r"\n\s*\n\s*\n+"), "\n\n")]


def _norm(text: str) -> str:
    for rx, repl in _NORM_STEPS:
        text = rx.sub(repl, text)
    return text.strip()


def _norm_spans(text: str, spans: dict) -> tuple[str, dict]:
    """_norm, carrying character spans from the raw text to the normalised one."""
    from bisect import bisect_right
    points = sorted({x for v in spans.values() for ab in v for x in ab})
    where = {x: x for x in points}                # raw offset -> offset in the current text
    for rx, repl in _NORM_STEPS:
        starts, ends, shift, total = [], [], [], 0
        for m in rx.finditer(text):
            starts.append(m.start())
            ends.append(m.end())
            total += (m.end() - m.start()) - len(repl)
            shift.append(total)                    # characters removed up to the end of this match
        for x in points:
            cur = where[x]
            k = bisect_right(starts, cur) - 1
            if k < 0:
                continue
            if cur < ends[k]:                      # inside a match: where its replacement starts
                where[x] = starts[k] - (shift[k - 1] if k else 0)
            else:
                where[x] = cur - shift[k]
        text = rx.sub(repl, text)
    lead = len(text) - len(text.lstrip())
    text = text.strip()
    fix = lambda x: min(max(0, where[x] - lead), len(text))
    return text, {k: [[fix(a), fix(b)] for a, b in v] for k, v in spans.items()}


def _xml_text(xml: bytes, para_tags: tuple[str, ...]) -> str:
    root = etree.fromstring(xml, parser=etree.XMLParser(recover=True, huge_tree=True))
    if root is None:
        return ""
    out = []
    for el in root.iter():
        if not isinstance(el.tag, str):
            continue
        ln = el.tag.rsplit("}", 1)[-1]
        if ln in para_tags:
            t = "".join(el.itertext()).strip()
            if t:
                out.append(t)
    return "\n".join(out)


def _office(data: bytes, ext: str) -> str:
    z = zipfile.ZipFile(io.BytesIO(data))
    if ext == "docx":
        parts = [n for n in z.namelist() if re.match(r"word/(document|header\d*|footer\d*|footnotes)\.xml$", n)]
        return "\n".join(_xml_text(z.read(n), ("p",)) for n in sorted(parts, key=lambda n: n != "word/document.xml"))
    if ext == "pptx":
        slides = sorted((n for n in z.namelist() if re.match(r"ppt/slides/slide\d+\.xml$", n)),
                        key=lambda n: int(re.findall(r"\d+", n)[-1]))
        return "\n\n".join(f"[Diapositiva {i + 1}]\n" + _xml_text(z.read(n), ("p",)) for i, n in enumerate(slides))
    if ext in {"odt", "ods", "odp"}:
        return _xml_text(z.read("content.xml"), ("p", "h"))
    raise ValueError(ext)


def _xlsx(data: bytes) -> str:
    import openpyxl
    wb = openpyxl.load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    out = []
    for ws in wb.worksheets:
        out.append(f"[Hoja {ws.title}]")
        for row in ws.iter_rows(values_only=True):
            cells = [str(c) for c in row if c not in (None, "")]
            if cells:
                out.append(" | ".join(cells))
    return "\n".join(out)


def _legacy_office(data: bytes, ext: str) -> tuple[str, str]:
    """Old binary .doc/.xls/.ppt: use whatever converter the host has."""
    with tempfile.TemporaryDirectory() as td:
        src = Path(td) / f"in.{ext}"
        src.write_bytes(data)
        if ext == "doc" and shutil.which("antiword"):
            r = subprocess.run(["antiword", str(src)], capture_output=True, timeout=120)
            if r.returncode == 0:
                return _decode(r.stdout), "antiword"
        if ext == "doc" and shutil.which("catdoc"):
            r = subprocess.run(["catdoc", "-d", "utf-8", str(src)], capture_output=True, timeout=120)
            if r.returncode == 0:
                return _decode(r.stdout), "catdoc"
        if ext == "doc" and shutil.which("textutil"):
            r = subprocess.run(["textutil", "-convert", "txt", "-stdout", str(src)], capture_output=True, timeout=120)
            if r.returncode == 0:
                return _decode(r.stdout), "textutil"
        office = shutil.which("soffice") or shutil.which("libreoffice")
        if office:
            r = subprocess.run([office, "--headless", "--convert-to", "txt:Text", "--outdir", td, str(src)],
                               capture_output=True, timeout=300)
            out = Path(td) / "in.txt"
            if out.exists():
                return _decode(out.read_bytes()), "soffice"
    raise RuntimeError(f"no converter for .{ext} (install antiword or libreoffice)")


def _html(data: bytes) -> str:
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(_decode(data), "html.parser")
    for t in soup(["script", "style", "noscript"]):
        t.decompose()
    return soup.get_text("\n")


def _ocr(data: bytes, ocr_url: str, timeout: float = 1800) -> str:
    r = httpx.post(f"{ocr_url}/services/ocr", data={"type_name": "pdf"},
                   files={"file": ("doc.pdf", data, "application/pdf")}, timeout=timeout)
    r.raise_for_status()
    return r.json().get("content_parsed") or ""


_FURNITURE_BOXES = {"page-header", "page-footer"}
_HEADING_BOXES = {"section-header", "title"}


_GLUED = re.compile(r"[^\W\d_]{8,}")


def _unglue(body: str, plain: str, boxes: list) -> str:
    """Words the layout pass ran together in a table cell ("JOGOSAOBRASYSERVICIOS"), spaced as the
    plain text of the same page has them; the boxes' positions move with the edits."""
    words = [w.strip(".,;:()«»\"'") for w in plain.split()]
    spaced = {}
    for i in range(len(words)):
        for n in range(2, 7):
            run = words[i:i + n]
            if len(run) == n and all(run) and all(w.isalpha() for w in run):
                spaced.setdefault("".join(run), " ".join(run))
    edits = [(m.start(), m.end(), spaced[m.group()]) for m in _GLUED.finditer(body) if m.group() in spaced]
    if not edits:
        return body
    out, last, shifts = [], 0, []
    for a, b, new in edits:
        out += [body[last:a], new]
        shifts.append((b, len(new) - (b - a)))
        last = b
    out.append(body[last:])
    moved = lambda x: x + sum(d for end, d in shifts if end <= x)
    for box in boxes:
        if box.get("pos"):
            box["pos"] = (moved(box["pos"][0]), moved(box["pos"][1]))
    return "".join(out)


def _layout_markdown(doc, plain: list[str]) -> tuple[str, dict]:
    """The PDF as Markdown (headings, tables as rows, lists, reading order), page by page with the
    same "[Página N]" markers, and where its layout model put furniture, headings and tables."""
    import pymupdf4llm
    pages = pymupdf4llm.to_markdown(doc, page_chunks=True, use_ocr=False, show_progress=False)
    parts, spans, pos = [], {"furniture": [], "headings": [], "tables": []}, 0
    for i, page in enumerate(pages):
        body = page.get("text") or ""
        if not body.strip():
            continue
        body = _unglue(body, plain[i] if i < len(plain) else "", page.get("page_boxes") or [])
        if parts:
            pos += 2                                   # the "\n\n" that joins pages
        head = f"[Página {i + 1}]\n"
        base = pos + len(head)
        for box in page.get("page_boxes") or []:
            a, b = box.get("pos") or (None, None)
            if a is None:
                continue
            kind = ("furniture" if box["class"] in _FURNITURE_BOXES else "headings" if box["class"] in _HEADING_BOXES
                    else "tables" if box["class"] == "table" else None)
            if kind:
                spans[kind].append([base + a, base + b])
        parts.append(head + body)
        pos += len(head) + len(body)
    return "\n\n".join(parts), spans


def _pdf(data: bytes, ocr_url: str, min_chars_per_page: int, layout: bool = False) -> TextResult:
    import pymupdf
    doc = pymupdf.open(stream=data, filetype="pdf")
    pages = doc.page_count
    texts = [p.get_text("text") for p in doc]
    text = "\n\n".join(f"[Página {i + 1}]\n{t.strip()}" for i, t in enumerate(texts) if t.strip())
    low = sum(1 for t in texts if len(t.strip()) < min_chars_per_page)
    scanned = pages > 0 and low / pages > 0.5
    if not scanned and layout:
        try:
            md, spans = _layout_markdown(doc, texts)
            if len(md.split()) >= 0.8 * len(text.split()):     # the layout pass lost no text
                doc.close()
                return TextResult("ok", "pymupdf4llm", md, pages, layout=spans)
        except Exception:        # a PDF the layout model cannot read: the plain text is still good
            pass
    doc.close()
    if not scanned:
        return TextResult("ok", "pymupdf", text, pages)
    if not ocr_url:
        return TextResult("needs_ocr", "pymupdf", text, pages, error=f"{low}/{pages} pages without a text layer")
    t0 = time.time()
    ocr_text = _ocr(data, ocr_url)
    return TextResult("ok", "ocr", ocr_text, pages, ocr_pages=pages, ocr_ms=int((time.time() - t0) * 1000))


def extract(data: bytes, ext: str, ocr_url: str = "", min_chars_per_page: int = 80, layout: bool = False) -> TextResult:
    try:
        if ext == "pdf":
            res = _pdf(data, ocr_url, min_chars_per_page, layout)
        elif ext == "zip":
            z = zipfile.ZipFile(io.BytesIO(data))
            members = [(i.filename, z.read(i)) for i in z.infolist()
                       if not i.is_dir() and not i.filename.startswith("__MACOSX") and i.file_size < 300 * 2**20]
            return TextResult("archive", "zip", members=members)
        elif ext in {"docx", "pptx", "odt", "ods", "odp"}:
            res = TextResult("ok", ext, _office(data, ext))
        elif ext == "xlsx":
            res = TextResult("ok", "openpyxl", _xlsx(data))
        elif ext in {"doc", "xls", "ppt"}:
            text, method = _legacy_office(data, ext)
            res = TextResult("ok", method, text)
        elif ext == "rtf":
            res = TextResult("ok", "rtf-strip", re.sub(r"\\[a-z]+-?\d* ?|[{}]", "", _decode(data)))
        elif ext == "html":
            res = TextResult("ok", "html", _html(data))
        elif ext == "xml":
            root = etree.fromstring(data, parser=etree.XMLParser(recover=True, huge_tree=True))
            res = TextResult("ok", "xml", "\n".join(t.strip() for t in root.itertext() if t.strip()) if root is not None else "")
        elif ext in TEXT_EXTS:
            res = TextResult("ok", "plain", _decode(data))
        elif ext in UNSUPPORTED:
            return TextResult("unsupported", ext)
        else:
            return TextResult("unsupported", ext or "bin")
    except Exception as e:  # noqa: BLE001 - a bad file must not stop the run
        return TextResult("failed", ext, error=f"{type(e).__name__}: {e}"[:500])
    if res.layout:
        res.text, res.layout = _norm_spans(res.text, res.layout)
    else:
        res.text = _norm(res.text)
    if res.status == "ok" and len(res.text) < 20:
        res.status = "empty"
    return res
