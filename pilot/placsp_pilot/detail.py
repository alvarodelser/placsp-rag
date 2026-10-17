"""Scrape document links from tender detail pages.

PLACSP detail pages list:
- notices (anuncio, rectificación, pliego, adjudicación, formalización and the
  annulled ones), each offered as html, xml and pdf: one is downloaded;
- "otros documentos": memoria justificativa, actas, informes, resoluciones...

External platforms (externos_mayores) have their own pages. A generic link
scraper covers the server-rendered ones (Madrid, Navarra...); single-page apps
(Catalunya) return nothing, but their feed entries carry the PCAP/PPT links.
"""
import re
from urllib.parse import urljoin

from bs4 import BeautifulSoup

PLACSP_DOC = re.compile(r"GetDocumentByIdServlet|GetDocumentsById|/FileSystem/")
EXTERNAL_DOC = re.compile(
    r"\.(pdf|docx?|odt|zip|xlsx?|rtf)(\?|$)|/download|descarga|descarrega|downloadDokusi|mtoGenera|GetDocument|"
    r"verDocumento|documento\.do", re.I)
DATE = re.compile(r"(\d{2})/(\d{2})/(\d{4})")
_FMT_PREF = {"html": 0, "pdf": 1, "xml": 2}
MAX_EXTERNAL_LINKS = 80


def _clean(s: str) -> str:
    return re.sub(r"\s+", " ", s or "").strip()


def _iso(s: str) -> str | None:
    m = DATE.search(s or "")
    return f"{m.group(3)}-{m.group(2)}-{m.group(1)}" if m else None


def is_placsp_detail(url: str | None) -> bool:
    return bool(url) and "contrataciondelestado.es/wps/" in url


def parse_detail(html: str) -> list[dict]:
    soup = BeautifulSoup(html, "html.parser")
    out, seen = [], set()
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if not PLACSP_DOC.search(href) or href in seen:
            continue
        seen.add(href)
        row = a.find_parent("tr")
        cells = row.find_all("td", recursive=False) if row else []
        img = a.find("img")
        m = re.search(r"Documento\s+(\w+)", (img.get("alt") or "") if img is not None else "")
        fmt = m.group(1).lower() if m else None
        type_cell = row.find("td", class_="tipoDocumento") if row else None
        if type_cell is not None:
            label = _clean(type_cell.get_text(" "))
        elif len(cells) > 1:
            label = _clean(cells[1].get_text(" "))
        else:
            label = _clean(a.get_text(" "))
        out.append({
            # A link offered as html/xml/pdf is a notice; plain links are other documents.
            "source": "detail_notice" if fmt else "detail_other",
            "label": label or None,
            "url": href,
            "published": _iso(cells[0].get_text(" ")) if cells else None,
            "fmt": fmt,
        })
    return out


def parse_external(html: str, base_url: str) -> list[dict]:
    soup = BeautifulSoup(html, "html.parser")
    out, seen = [], set()
    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        if href.startswith(("javascript:", "mailto:", "#")) or not EXTERNAL_DOC.search(href):
            continue
        url = urljoin(base_url, href)
        if url in seen:
            continue
        seen.add(url)
        label = _clean(a.get_text(" ")) or _clean(a.get("title") or "")
        row = a.find_parent(["tr", "li"])
        if (not label or label.lower() in ("descargar", "download", "ver", "imprimir")) and row is not None:
            label = _clean(row.get_text(" "))[:200]
        out.append({"source": "detail_external", "label": label or url.rsplit("/", 1)[-1], "url": url,
                    "published": _iso(row.get_text(" ")) if row is not None else None, "fmt": None})
        if len(out) >= MAX_EXTERNAL_LINKS:
            break
    return out


def preferred_formats(refs: list[dict]) -> set[str]:
    """For each notice offered in several formats, the URL to download (html > pdf > xml)."""
    best: dict[tuple, tuple[int, str]] = {}
    for r in refs:
        if r["source"] != "detail_notice":
            continue
        key = (r["label"], r["published"])
        rank = _FMT_PREF.get(r.get("fmt") or "", 9)
        if key not in best or rank < best[key][0]:
            best[key] = (rank, r["url"])
    return {u for _, u in best.values()}
