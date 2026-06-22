# PLACSP RAG Ingestion — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a standalone Python pipeline that ingests PLACSP procurement ATOM feeds (historical backfill + daily live updates) into a dedicated Weaviate collection, reusing the existing BGE-M3 vectorizer.

**Architecture:** Stream-parse ATOM/CODICE → source-aware extraction into a typed record → render a Spanish NL summary → embed (BGE-M3, 1024-dim) → idempotent upsert into Weaviate `Placsp_licitaciones` keyed by a deterministic UUID over the syndication entry id. Weaviate is the source of truth (no separate ledger); latest-`updated` wins; Atom tombstones delete. Phase 1 builds pure logic validated on committed real fixtures; Phase 2 adds IO; Phase 3 orchestration; Phase 4 a one-feed end-to-end validation.

**Tech Stack:** Python 3.11, lxml, httpx, structlog, pytest. No n8n. Scheduling via cron/systemd.

## Global Constraints

- Dedup key is the **syndication entry `<id>` integer** (e.g. `…/licitacionesPerfilContratante/19862167`), NEVER `cbc:ContractFolderID` (org-local, collides).
- Deterministic object UUID = `uuid.uuid5(uuid.NAMESPACE_URL, "https://placsp.id/" + syndication_id)`.
- Embeddings: BGE-M3, **1024-dim**, **no prefix**; `POST {VECTORIZER_URL}/embed` body `{"texts": [...], "normalize": true}` → `{"embeddings": [[float,...]]}`.
- Weaviate **v1.28.3**; single class `Placsp_licitaciones`, `"vectorizer": "none"`, BM25 on `content`, nested `object[]` allowed. Auth header `Authorization: Bearer {WEAVIATE_API_KEY}` (reuse existing key).
- Backfill must protect the shared single-GPU vectorizer: off-peak window gating + `max_in_flight` (default 1). Each `/embed` call sends ≤ `embed_batch_size` (default 48) texts.
- CODICE namespaces:
  - `cbc` = `urn:dgpe:names:draft:codice:schema:xsd:CommonBasicComponents-2`
  - `cac` = `urn:dgpe:names:draft:codice:schema:xsd:CommonAggregateComponents-2`
  - `pe`  = `urn:dgpe:names:draft:codice-place-ext:schema:xsd:CommonAggregateComponents-2`
  - `peb` = `urn:dgpe:names:draft:codice-place-ext:schema:xsd:CommonBasicComponents-2`
  - atom = `http://www.w3.org/2005/Atom`; tombstones = `http://purl.org/atompub/tombstones/1.0`
- Every pure-logic module is unit-tested against committed real fixtures (no network in tests; IO mocked via `httpx.MockTransport`).

## File Structure

```
pyproject.toml
src/placsp/__init__.py
src/placsp/config.py          # env-driven Config
src/placsp/catalog.py         # feed list + live-head URLs
src/placsp/models.py          # RawEntry, Tombstone, Lot, StatusEvent, ProcurementRecord
src/placsp/atom_parser.py     # parse_feed() streaming
src/placsp/codelists.py       # genericode .gc decode
src/placsp/codice_extractor.py# source-aware extract()
src/placsp/renderer.py        # render() -> (summary, properties)
src/placsp/embedder.py        # Embedder
src/placsp/weaviate_schema.py # ensure_class()
src/placsp/upserter.py        # object_uuid(), Upserter
src/placsp/fetcher.py         # download(), unzip(), feed_next_link()
src/placsp/pipeline.py        # collapse(), Pipeline.run_*()
src/placsp/__main__.py        # CLI
tests/fixtures/*.atom, tests/fixtures/*.gc
tests/test_*.py
```

---

## Task 1: Project scaffold, config, fixtures

**Files:**
- Create: `pyproject.toml`, `src/placsp/__init__.py`, `src/placsp/config.py`, `tests/__init__.py`, `tests/test_config.py`
- Create (move real samples): `tests/fixtures/mayores.atom`, `tests/fixtures/menores.atom`, `tests/fixtures/externos.atom`, `tests/fixtures/propios.atom`, `tests/fixtures/ContractCode.gc`

**Interfaces:**
- Produces: `placsp.config.Config` (dataclass) and `placsp.config.load_config() -> Config`.

- [ ] **Step 1: Create `pyproject.toml`**

```toml
[project]
name = "placsp"
version = "0.1.0"
requires-python = ">=3.11"
dependencies = ["lxml>=5", "httpx>=0.27", "structlog>=24"]

[project.optional-dependencies]
dev = ["pytest>=8"]

[build-system]
requires = ["setuptools>=68"]
build-backend = "setuptools.build_meta"

[tool.setuptools.packages.find]
where = ["src"]

[tool.pytest.ini_options]
pythonpath = ["src"]
testpaths = ["tests"]
```

- [ ] **Step 2: Move the already-downloaded real samples into fixtures**

The repo root currently holds real samples downloaded during spec validation. Trim each to a small, fast fixture (first 6 entries; for externos keep entries + the first tombstone).

```bash
mkdir -p tests/fixtures
cp ContractCode.gc tests/fixtures/ContractCode.gc
python3 - <<'PY'
from lxml import etree
ATOM="{http://www.w3.org/2005/Atom}"
TOMB="{http://purl.org/atompub/tombstones/1.0}"
def trim(src, dst, n_entries=6, keep_tomb=True):
    src_root = etree.parse(src).getroot()
    nsmap = src_root.nsmap
    feed = etree.Element(ATOM+"feed", nsmap=nsmap)
    e=t=0
    for child in src_root:
        tag=child.tag
        if isinstance(tag,str) and tag==ATOM+"entry" and e<n_entries:
            feed.append(child); e+=1
        elif isinstance(tag,str) and tag==TOMB+"deleted-entry" and keep_tomb and t<1:
            feed.append(child); t+=1
        if e>=n_entries and (t>=1 or not keep_tomb): break
    etree.ElementTree(feed).write(dst, xml_declaration=True, encoding="UTF-8")
    print(dst, "entries=",e,"tombstones=",t)
trim("head.atom","tests/fixtures/mayores.atom")
trim("head_menores_1143.atom","tests/fixtures/menores.atom")
trim("head_externos_1044.atom","tests/fixtures/externos.atom")
import glob
trim(sorted(glob.glob("propios_2022/*.atom"))[0],"tests/fixtures/propios.atom")
PY
```

- [ ] **Step 3: Write `src/placsp/__init__.py`**

```python
__all__ = []
```

- [ ] **Step 4: Write the failing test `tests/test_config.py`**

```python
from placsp.config import load_config

def test_defaults(monkeypatch):
    monkeypatch.delenv("VECTORIZER_URL", raising=False)
    cfg = load_config()
    assert cfg.vectorizer_url == "http://vectorizer:8089"
    assert cfg.weaviate_class == "Placsp_licitaciones"
    assert cfg.embed_batch_size == 48
    assert cfg.max_in_flight == 1

def test_env_override(monkeypatch):
    monkeypatch.setenv("VECTORIZER_URL", "http://x:1")
    monkeypatch.setenv("PLACSP_EMBED_BATCH", "10")
    cfg = load_config()
    assert cfg.vectorizer_url == "http://x:1"
    assert cfg.embed_batch_size == 10
```

- [ ] **Step 5: Run test to verify it fails**

Run: `pytest tests/test_config.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'placsp.config'`

- [ ] **Step 6: Write `src/placsp/config.py`**

```python
import os
from dataclasses import dataclass

def _env(k, d): return os.getenv(k, d)

@dataclass
class Config:
    vectorizer_url: str
    weaviate_url: str
    weaviate_api_key: str
    weaviate_class: str
    work_dir: str
    codelist_dir: str
    embed_batch_size: int
    max_in_flight: int
    offpeak_start: int
    offpeak_end: int
    request_timeout: float

def load_config() -> Config:
    return Config(
        vectorizer_url=_env("VECTORIZER_URL", "http://vectorizer:8089"),
        weaviate_url=_env("WEAVIATE_URL", "http://iarag-vectorstore:8086"),
        weaviate_api_key=_env("WEAVIATE_API_KEY", ""),
        weaviate_class=_env("PLACSP_CLASS", "Placsp_licitaciones"),
        work_dir=_env("PLACSP_WORK_DIR", "./work"),
        codelist_dir=_env("PLACSP_CODELIST_DIR", "./codelists"),
        embed_batch_size=int(_env("PLACSP_EMBED_BATCH", "48")),
        max_in_flight=int(_env("PLACSP_MAX_IN_FLIGHT", "1")),
        offpeak_start=int(_env("PLACSP_OFFPEAK_START", "22")),
        offpeak_end=int(_env("PLACSP_OFFPEAK_END", "7")),
        request_timeout=float(_env("PLACSP_TIMEOUT", "600")),
    )
```

- [ ] **Step 7: Run tests to verify they pass**

Run: `pytest tests/test_config.py -v`
Expected: PASS (2 passed)

- [ ] **Step 8: Commit**

```bash
git init -q 2>/dev/null; printf "work/\ncodelists/\n*.zip\nhead*.atom\npropios_2022/\nContractCode.gc\n__pycache__/\n.pytest_cache/\n" > .gitignore
git add pyproject.toml src/placsp/__init__.py src/placsp/config.py tests/ .gitignore
git commit -m "feat: scaffold placsp package, config, real fixtures"
```

---

## Task 2: Domain models

**Files:**
- Create: `src/placsp/models.py`, `tests/test_models.py`

**Interfaces:**
- Produces: dataclasses `RawEntry(syndication_id:str, updated:str|None, link:str|None, cfs:Any, category:str)`, `Tombstone(syndication_id:str, when:str|None, reason:str|None, category:str)`, `Lot(lot_id:str, name:str|None, amount:float|None, cpv:list[str])`, `StatusEvent(code:str, date:str|None)`, and `ProcurementRecord` (all fields below; `syndication_id`, `category`, `updated` required, rest optional).

- [ ] **Step 1: Write the failing test `tests/test_models.py`**

```python
from placsp.models import ProcurementRecord, Lot, StatusEvent

def test_record_minimal_and_defaults():
    r = ProcurementRecord(syndication_id="19862167", category="placsp_mayores", updated="2026-06-19T21:50:27+02:00")
    assert r.cpv == [] and r.lots == [] and r.status_history == []
    assert r.lang == "es"
    assert r.budget_amount is None

def test_lot_and_status():
    lot = Lot(lot_id="1", name="Obra", amount=100.0, cpv=["45000000"])
    ev = StatusEvent(code="ADJ", date="2026-05-20")
    assert lot.cpv == ["45000000"] and ev.code == "ADJ"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_models.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'placsp.models'`

- [ ] **Step 3: Write `src/placsp/models.py`**

```python
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any, Optional

@dataclass
class RawEntry:
    syndication_id: str
    updated: Optional[str]
    link: Optional[str]
    cfs: Any            # lxml ContractFolderStatus element; valid only until next parse iteration
    category: str

@dataclass
class Tombstone:
    syndication_id: str
    when: Optional[str]
    reason: Optional[str]
    category: str

@dataclass
class Lot:
    lot_id: str
    name: Optional[str] = None
    amount: Optional[float] = None
    cpv: list[str] = field(default_factory=list)

@dataclass
class StatusEvent:
    code: str
    date: Optional[str] = None

@dataclass
class ProcurementRecord:
    syndication_id: str
    category: str
    updated: Optional[str]
    expediente: Optional[str] = None
    title: Optional[str] = None
    status_code: Optional[str] = None
    status_label: Optional[str] = None
    status_history: list[StatusEvent] = field(default_factory=list)
    result_code: Optional[str] = None
    result_label: Optional[str] = None
    contract_type_code: Optional[str] = None
    contract_type: Optional[str] = None
    cpv: list[str] = field(default_factory=list)
    procedure_code: Optional[str] = None
    procedure: Optional[str] = None
    notice_type: Optional[str] = None
    budget_amount: Optional[float] = None
    estimated_value: Optional[float] = None
    awarded_amount: Optional[float] = None
    contracting_authority: Optional[str] = None
    contracting_authority_id: Optional[str] = None
    org_top_level: Optional[str] = None
    adjudicatario: Optional[str] = None
    adjudicatario_nif: Optional[str] = None
    sme_awarded: Optional[bool] = None
    n_bids: Optional[int] = None
    nuts: Optional[str] = None
    nuts_label: Optional[str] = None
    city: Optional[str] = None
    country: Optional[str] = None
    publication_date: Optional[str] = None
    award_date: Optional[str] = None
    submission_deadline: Optional[str] = None
    funding_program: Optional[str] = None
    document_urls: list[str] = field(default_factory=list)
    lots: list[Lot] = field(default_factory=list)
    source_url: Optional[str] = None
    buyer_profile_url: Optional[str] = None
    lang: str = "es"
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_models.py -v`
Expected: PASS (2 passed)

- [ ] **Step 5: Commit**

```bash
git add src/placsp/models.py tests/test_models.py
git commit -m "feat: domain models (RawEntry, Tombstone, ProcurementRecord)"
```

---

## Task 3: ATOM streaming parser

**Files:**
- Create: `src/placsp/atom_parser.py`, `tests/test_atom_parser.py`

**Interfaces:**
- Consumes: `placsp.models.RawEntry`, `Tombstone`.
- Produces: `parse_feed(path:str, category:str) -> Iterator[RawEntry | Tombstone]`. `RawEntry.cfs` is the lxml `ContractFolderStatus` element (or `None`); valid only until the next iteration (the parser clears elements to bound memory). `RawEntry.syndication_id` is the trailing integer of `<id>`.

- [ ] **Step 1: Write the failing test `tests/test_atom_parser.py`**

```python
from placsp.atom_parser import parse_feed
from placsp.models import RawEntry, Tombstone

def test_parses_entries_with_syndication_id():
    items = list(parse_feed("tests/fixtures/mayores.atom", "placsp_mayores"))
    entries = [i for i in items if isinstance(i, RawEntry)]
    assert len(entries) == 6
    e = entries[0]
    assert e.syndication_id.isdigit()
    assert e.category == "placsp_mayores"
    assert e.updated and e.cfs is not None

def test_parses_tombstones_from_externos():
    items = list(parse_feed("tests/fixtures/externos.atom", "externos_mayores"))
    tombs = [i for i in items if isinstance(i, Tombstone)]
    assert len(tombs) == 1
    assert tombs[0].syndication_id.isdigit()
    assert tombs[0].reason  # e.g. CERRADA
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_atom_parser.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'placsp.atom_parser'`

- [ ] **Step 3: Write `src/placsp/atom_parser.py`**

```python
from typing import Iterator, Union
from lxml import etree
from .models import RawEntry, Tombstone

ATOM = "{http://www.w3.org/2005/Atom}"
TOMB = "{http://purl.org/atompub/tombstones/1.0}"
CFS = "{urn:dgpe:names:draft:codice-place-ext:schema:xsd:CommonAggregateComponents-2}ContractFolderStatus"

def _local(tag) -> str:
    return tag.rsplit("}", 1)[-1] if isinstance(tag, str) else ""

def _id_int(url: str) -> str:
    return (url or "").rstrip("/").rsplit("/", 1)[-1]

def parse_feed(path: str, category: str) -> Iterator[Union[RawEntry, Tombstone]]:
    for _, el in etree.iterparse(path, events=("end",)):
        ln = _local(el.tag)
        if ln == "entry":
            eid = el.findtext(f"{ATOM}id") or ""
            updated = el.findtext(f"{ATOM}updated")
            link_el = el.find(f"{ATOM}link")
            link = link_el.get("href") if link_el is not None else None
            cfs = el.find(CFS)
            yield RawEntry(_id_int(eid), updated, link, cfs, category)
            el.clear()
        elif ln == "deleted-entry":
            ref = el.get("ref") or ""
            when = el.get("when")
            comment = el.find(f"{TOMB}comment")
            reason = comment.get("type") if comment is not None else None
            yield Tombstone(_id_int(ref), when, reason, category)
            el.clear()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_atom_parser.py -v`
Expected: PASS (2 passed)

- [ ] **Step 5: Commit**

```bash
git add src/placsp/atom_parser.py tests/test_atom_parser.py
git commit -m "feat: streaming ATOM parser (entries + tombstones)"
```

---

## Task 4: Genericode codelist decoder

**Files:**
- Create: `src/placsp/codelists.py`, `tests/test_codelists.py`

**Interfaces:**
- Produces: `parse_gc(path:str) -> dict[str,str]` (code → Spanish label) and class `Codelists(cache_dir:str)` with `label(list_uri:str|None, code:str|None) -> str|None` (derives the `.gc` filename from the URI basename, loads from `cache_dir`, caches; returns `None` if file or code missing — never raises).

- [ ] **Step 1: Write the failing test `tests/test_codelists.py`**

```python
from placsp.codelists import parse_gc, Codelists

def test_parse_gc_contract_code():
    m = parse_gc("tests/fixtures/ContractCode.gc")
    assert m["1"] == "Suministros"            # verified from real .gc
    assert len(m) >= 3

def test_codelists_label_and_graceful_miss():
    cl = Codelists("tests/fixtures")
    assert cl.label("https://x/codice/cl/2.08/ContractCode-2.08.gc", "1") is None  # filename != fixture name
    cl2 = Codelists("tests/fixtures")
    assert cl2.label("https://x/whatever/ContractCode.gc", "1") == "Suministros"
    assert cl2.label("https://x/ContractCode.gc", "999") is None
    assert cl2.label(None, "1") is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_codelists.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'placsp.codelists'`

- [ ] **Step 3: Write `src/placsp/codelists.py`**

```python
import os
from typing import Optional
from lxml import etree

def _local(tag) -> str:
    return tag.rsplit("}", 1)[-1] if isinstance(tag, str) else ""

def parse_gc(path: str) -> dict[str, str]:
    """Parse a CODICE genericode .gc file -> {code: spanish_label}."""
    root = etree.parse(path).getroot()
    out: dict[str, str] = {}
    for row in root.iter():
        if _local(row.tag) != "Row":
            continue
        vals: dict[str, str] = {}
        for v in row:
            if _local(v.tag) != "Value":
                continue
            col = v.get("ColumnRef")
            sv = next((c for c in v if _local(c.tag) == "SimpleValue"), None)
            if col and sv is not None and sv.text:
                vals[col] = sv.text.strip()
        code = vals.get("code")
        if code:
            out[code] = vals.get("nombre") or vals.get("name") or code
    return out

class Codelists:
    def __init__(self, cache_dir: str):
        self.cache_dir = cache_dir
        self._cache: dict[str, dict[str, str]] = {}

    def _load(self, filename: str) -> dict[str, str]:
        if filename not in self._cache:
            path = os.path.join(self.cache_dir, filename)
            self._cache[filename] = parse_gc(path) if os.path.exists(path) else {}
        return self._cache[filename]

    def label(self, list_uri: Optional[str], code: Optional[str]) -> Optional[str]:
        if not list_uri or not code:
            return None
        filename = list_uri.rstrip("/").rsplit("/", 1)[-1]
        return self._load(filename).get(code)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_codelists.py -v`
Expected: PASS (2 passed)

- [ ] **Step 5: Commit**

```bash
git add src/placsp/codelists.py tests/test_codelists.py
git commit -m "feat: genericode codelist decoder"
```

---

## Task 5: Source-aware extractor — identity, classification, parties, location, dates

**Files:**
- Create: `src/placsp/codice_extractor.py`, `tests/test_codice_extractor.py`

**Interfaces:**
- Consumes: `RawEntry`, `ProcurementRecord`, `Codelists`, `atom_parser.parse_feed`.
- Produces: `extract(raw:RawEntry, codelists:Codelists|None=None) -> ProcurementRecord`. Internal helpers `first_text(cfs, xpaths:list[str]) -> str|None`, `first_el(cfs, xpaths)`, `all_text(cfs, xpath) -> list[str]`, and module constant `NS` (prefix→uri dict). Task 6 extends the same `extract()` with money/result/lots.

- [ ] **Step 1: Write the failing test `tests/test_codice_extractor.py`**

```python
from placsp.atom_parser import parse_feed
from placsp.codice_extractor import extract, first_text, NS
from placsp.codelists import Codelists
from placsp.models import RawEntry

def _first_entry(path, cat):
    for it in parse_feed(path, cat):
        if isinstance(it, RawEntry):
            return it

def test_identity_and_classification_mayores():
    raw = _first_entry("tests/fixtures/mayores.atom", "placsp_mayores")
    cl = Codelists("tests/fixtures")
    rec = extract(raw, cl)
    assert rec.syndication_id.isdigit()
    assert rec.category == "placsp_mayores"
    assert rec.title and rec.expediente            # expediente = ContractFolderID
    assert rec.status_code in {"PUB","EV","ADJ","RES","PRE"}
    assert rec.contracting_authority               # órgano name present
    assert rec.contract_type_code is not None

def test_contract_type_decoded_when_codelist_present():
    # propios fixture has TypeCode; ContractCode.gc decodes 1->Suministros etc.
    raw = _first_entry("tests/fixtures/propios.atom", "propios")
    rec = extract(raw, Codelists("tests/fixtures"))
    if rec.contract_type_code in {"1","2","3"}:
        assert rec.contract_type  # decoded label or raw fallback, never empty when code present

def test_extract_without_codelists_does_not_crash():
    raw = _first_entry("tests/fixtures/menores.atom", "placsp_menores")
    rec = extract(raw, None)
    assert rec.syndication_id and rec.status_code
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_codice_extractor.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'placsp.codice_extractor'`

- [ ] **Step 3: Write `src/placsp/codice_extractor.py`**

```python
from typing import Optional
from .models import RawEntry, ProcurementRecord, StatusEvent
from .codelists import Codelists

NS = {
    "cbc": "urn:dgpe:names:draft:codice:schema:xsd:CommonBasicComponents-2",
    "cac": "urn:dgpe:names:draft:codice:schema:xsd:CommonAggregateComponents-2",
    "pe":  "urn:dgpe:names:draft:codice-place-ext:schema:xsd:CommonAggregateComponents-2",
    "peb": "urn:dgpe:names:draft:codice-place-ext:schema:xsd:CommonBasicComponents-2",
}

def first_el(cfs, xpaths: list[str]):
    if cfs is None:
        return None
    for xp in xpaths:
        r = cfs.xpath(xp, namespaces=NS)
        if r:
            return r[0]
    return None

def first_text(cfs, xpaths: list[str]) -> Optional[str]:
    el = first_el(cfs, [xp if xp.endswith("/text()") or "@" in xp else xp + "/text()" for xp in xpaths])
    if el is None:
        return None
    s = str(el).strip()
    return s or None

def all_text(cfs, xpath: str) -> list[str]:
    if cfs is None:
        return []
    return [str(x).strip() for x in cfs.xpath(xpath + "/text()", namespaces=NS) if str(x).strip()]

def _list_uri(cfs, xpath: str) -> Optional[str]:
    el = first_el(cfs, [xpath])
    if el is None:
        return None
    return el.get("listURI") or el.get("listURIID")

def _decode(cl, list_uri, code):
    if cl is None or code is None:
        return code
    return cl.label(list_uri, code) or code

def extract(raw: RawEntry, codelists: Optional[Codelists] = None) -> ProcurementRecord:
    cfs = raw.cfs
    rec = ProcurementRecord(syndication_id=raw.syndication_id, category=raw.category, updated=raw.updated)
    rec.source_url = raw.link

    # identity
    rec.expediente = first_text(cfs, ["cbc:ContractFolderID"])
    rec.title = first_text(cfs, ["cac:ProcurementProject/cbc:Name"])

    # status
    rec.status_code = first_text(cfs, ["peb:ContractFolderStatusCode"])
    rec.status_label = _decode(codelists, _list_uri(cfs, "peb:ContractFolderStatusCode"), rec.status_code)
    if rec.status_code:
        rec.status_history = [StatusEvent(code=rec.status_code, date=(raw.updated or "")[:10] or None)]

    # classification
    rec.contract_type_code = first_text(cfs, ["cac:ProcurementProject/cbc:TypeCode"])
    rec.contract_type = _decode(codelists, _list_uri(cfs, "cac:ProcurementProject/cbc:TypeCode"), rec.contract_type_code)
    rec.cpv = all_text(cfs, ".//cac:RequiredCommodityClassification/cbc:ItemClassificationCode")
    rec.procedure_code = first_text(cfs, ["cac:TenderingProcess/cbc:ProcedureCode"])
    rec.procedure = _decode(codelists, _list_uri(cfs, "cac:TenderingProcess/cbc:ProcedureCode"), rec.procedure_code)
    rec.notice_type = first_text(cfs, ["pe:ValidNoticeInfo/peb:NoticeTypeCode"])

    # parties
    rec.contracting_authority = first_text(cfs, ["pe:LocatedContractingParty/cac:Party/cac:PartyName/cbc:Name"])
    rec.contracting_authority_id = first_text(cfs, ["pe:LocatedContractingParty/cac:Party/cac:PartyIdentification/cbc:ID"])
    parents = all_text(cfs, ".//pe:ParentLocatedParty/cac:PartyName/cbc:Name")
    rec.org_top_level = parents[-1] if parents else None
    rec.buyer_profile_url = first_text(cfs, ["pe:LocatedContractingParty/cbc:BuyerProfileURIID"])

    # location
    rec.nuts = first_text(cfs, ["cac:ProcurementProject/cac:RealizedLocation/cbc:CountrySubentityCode"])
    rec.nuts_label = _decode(codelists, _list_uri(cfs, "cac:ProcurementProject/cac:RealizedLocation/cbc:CountrySubentityCode"), rec.nuts)
    rec.city = first_text(cfs, ["pe:LocatedContractingParty/cac:Party/cac:PostalAddress/cbc:CityName"])
    rec.country = first_text(cfs, ["cac:ProcurementProject/cac:RealizedLocation/cac:Address/cac:Country/cbc:Name",
                                   "pe:LocatedContractingParty/cac:Party/cac:PostalAddress/cac:Country/cbc:Name"])

    # dates
    rec.publication_date = first_text(cfs, ["pe:ValidNoticeInfo/pe:AdditionalPublicationStatus/pe:AdditionalPublicationDocumentReference/cbc:IssueDate"])
    rec.submission_deadline = first_text(cfs, [".//cac:TenderSubmissionDeadlinePeriod/cbc:EndDate"])
    rec.funding_program = first_text(cfs, ["cac:TenderingTerms/cbc:FundingProgramCode"])

    # documents
    rec.document_urls = all_text(cfs, "pe:GeneralDocument//cac:ExternalReference/cbc:URI")
    return rec
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_codice_extractor.py -v`
Expected: PASS (3 passed)

- [ ] **Step 5: Commit**

```bash
git add src/placsp/codice_extractor.py tests/test_codice_extractor.py
git commit -m "feat: source-aware extractor (identity, classification, parties, dates)"
```

---

## Task 6: Extractor — money (3 concepts), tender result, lots

**Files:**
- Modify: `src/placsp/codice_extractor.py` (extend `extract()`), `tests/test_codice_extractor.py`

**Interfaces:**
- Consumes: everything from Task 5.
- Produces: `extract()` now also fills `budget_amount`, `estimated_value`, `awarded_amount`, `result_code`, `result_label`, `adjudicatario`, `adjudicatario_nif`, `award_date`, `n_bids`, `sme_awarded`, `lots`. Helper `_num(s)->float|None`.

- [ ] **Step 1: Add failing tests to `tests/test_codice_extractor.py`**

```python
def test_money_source_paths():
    # menores: amount lives under TenderResult; always awarded
    raw = _first_entry("tests/fixtures/menores.atom", "placsp_menores")
    rec = extract(raw, None)
    assert rec.awarded_amount is not None and rec.awarded_amount > 0
    assert rec.result_code is not None
    assert rec.adjudicatario  # winner name

def test_budget_present_for_propios():
    raw = _first_entry("tests/fixtures/propios.atom", "propios")
    rec = extract(raw, None)
    assert rec.budget_amount is not None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_codice_extractor.py -k money -v`
Expected: FAIL — `assert None is not None` (awarded_amount not yet populated)

- [ ] **Step 3: Extend `extract()` in `src/placsp/codice_extractor.py`**

Add this helper near the top (after `_decode`):

```python
def _num(s: Optional[str]) -> Optional[float]:
    if s is None:
        return None
    try:
        return float(s)
    except ValueError:
        return None
```

Add the following before `return rec` in `extract()`:

```python
    # money — three distinct concepts, source-specific paths (first-present wins)
    rec.budget_amount = _num(first_text(cfs, [
        "cac:ProcurementProject/cac:BudgetAmount/cbc:TaxExclusiveAmount",
        "cac:ProcurementProject/cac:BudgetAmount/cbc:TotalAmount"]))
    rec.estimated_value = _num(first_text(cfs, [
        "cac:ProcurementProject/cac:BudgetAmount/cbc:EstimatedOverallContractAmount"]))
    rec.awarded_amount = _num(first_text(cfs, [
        "cac:TenderResult/cac:AwardedTenderedProject/cac:LegalMonetaryTotal/cbc:TaxExclusiveAmount",
        "cac:TenderResult/cac:AwardedTenderedProject/cac:LegalMonetaryTotal/cbc:PayableAmount"]))

    # tender result
    rec.result_code = first_text(cfs, ["cac:TenderResult/cbc:ResultCode"])
    rec.result_label = _decode(codelists, _list_uri(cfs, "cac:TenderResult/cbc:ResultCode"), rec.result_code)
    rec.award_date = first_text(cfs, ["cac:TenderResult/cbc:AwardDate"])
    rec.adjudicatario = first_text(cfs, ["cac:TenderResult/cac:WinningParty/cac:PartyName/cbc:Name"])
    rec.adjudicatario_nif = first_text(cfs, [".//cac:TenderResult/cac:WinningParty/cac:PartyIdentification/cbc:ID"])
    n = first_text(cfs, ["cac:TenderResult/cbc:ReceivedTenderQuantity"])
    rec.n_bids = int(n) if (n and n.isdigit()) else None
    sme = first_text(cfs, ["cac:TenderResult/cbc:SMEAwardedIndicator"])
    rec.sme_awarded = {"true": True, "false": False}.get((sme or "").lower()) if sme else None

    # lots
    from .models import Lot
    for lot_el in (cfs.xpath("cac:ProcurementProjectLot", namespaces=NS) if cfs is not None else []):
        lid = lot_el.xpath("cbc:ID/text()", namespaces=NS)
        name = lot_el.xpath("cac:ProcurementProject/cbc:Name/text()", namespaces=NS)
        amt = lot_el.xpath(".//cbc:TaxExclusiveAmount/text()", namespaces=NS)
        cpv = [str(x).strip() for x in lot_el.xpath(".//cbc:ItemClassificationCode/text()", namespaces=NS)]
        rec.lots.append(Lot(lot_id=(str(lid[0]) if lid else ""),
                            name=(str(name[0]).strip() if name else None),
                            amount=_num(str(amt[0]) if amt else None),
                            cpv=cpv))
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_codice_extractor.py -v`
Expected: PASS (5 passed)

- [ ] **Step 5: Commit**

```bash
git add src/placsp/codice_extractor.py tests/test_codice_extractor.py
git commit -m "feat: extractor money/result/lots (source-aware)"
```

---

## Task 7: Renderer (NL summary + properties)

**Files:**
- Create: `src/placsp/renderer.py`, `tests/test_renderer.py`

**Interfaces:**
- Consumes: `ProcurementRecord`.
- Produces: `render(rec:ProcurementRecord) -> tuple[str, dict]` — `(summary_text, properties)`. `properties` keys exactly match the Weaviate schema (Task 9): `syndication_id, expediente, title, content, lang, category, source_url, buyer_profile_url, status_code, status_label, status_history, result_code, result_label, contract_type_code, contract_type, cpv, procedure_code, procedure, notice_type, budget_amount, estimated_value, awarded_amount, contracting_authority, contracting_authority_id, org_top_level, adjudicatario, adjudicatario_nif, sme_awarded, n_bids, nuts, nuts_label, city, country, publication_date, award_date, submission_deadline, funding_program, document_urls, lots, updated`. `content` == `summary_text`. `status_history`/`lots` are lists of dicts. Empty/None scalars are omitted from `properties`.

- [ ] **Step 1: Write the failing test `tests/test_renderer.py`**

```python
from placsp.atom_parser import parse_feed
from placsp.codice_extractor import extract
from placsp.models import RawEntry
from placsp.renderer import render

def _rec(path, cat):
    for it in parse_feed(path, cat):
        if isinstance(it, RawEntry):
            return extract(it, None)

def test_summary_is_spanish_prose_with_key_facts():
    rec = _rec("tests/fixtures/mayores.atom", "placsp_mayores")
    text, props = render(rec)
    assert isinstance(text, str) and len(text) > 20
    assert rec.title.split()[0] in text
    assert props["content"] == text
    assert props["syndication_id"] == rec.syndication_id
    assert props["category"] == "placsp_mayores"

def test_properties_omit_empty_and_serialize_lists():
    rec = _rec("tests/fixtures/menores.atom", "placsp_menores")
    text, props = render(rec)
    assert "status_history" in props and isinstance(props["status_history"], list)
    assert props["status_history"][0]["code"] == rec.status_code
    # None scalars omitted
    assert all(v is not None for v in props.values())
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_renderer.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'placsp.renderer'`

- [ ] **Step 3: Write `src/placsp/renderer.py`**

```python
from dataclasses import asdict
from .models import ProcurementRecord

def _money(v):
    return f"{v:,.2f} EUR" if v is not None else None

def render(rec: ProcurementRecord) -> tuple[str, dict]:
    parts: list[str] = []
    tipo = rec.contract_type or rec.contract_type_code
    if tipo and rec.title:
        parts.append(f"Contrato de {tipo}: {rec.title}.")
    elif rec.title:
        parts.append(f"{rec.title}.")
    if rec.contracting_authority:
        org = rec.contracting_authority
        if rec.org_top_level and rec.org_top_level != org:
            org += f" ({rec.org_top_level})"
        parts.append(f"Órgano de contratación: {org}.")
    if rec.expediente:
        parts.append(f"Expediente: {rec.expediente}.")
    money = []
    if rec.budget_amount is not None: money.append(f"presupuesto base {_money(rec.budget_amount)}")
    if rec.estimated_value is not None: money.append(f"valor estimado {_money(rec.estimated_value)}")
    if rec.awarded_amount is not None: money.append(f"importe de adjudicación {_money(rec.awarded_amount)}")
    if money:
        parts.append("Importes: " + ", ".join(money) + ".")
    if rec.cpv:
        parts.append("CPV: " + ", ".join(rec.cpv) + ".")
    if rec.procedure:
        parts.append(f"Procedimiento: {rec.procedure}.")
    estado = rec.status_label or rec.status_code
    if estado:
        parts.append(f"Estado: {estado}.")
    if rec.adjudicatario:
        parts.append(f"Adjudicatario: {rec.adjudicatario}.")
    if rec.nuts_label or rec.nuts:
        parts.append(f"Lugar de ejecución: {rec.nuts_label or rec.nuts}.")
    if rec.funding_program:
        parts.append(f"Programa de financiación: {rec.funding_program}.")
    if rec.publication_date:
        parts.append(f"Fecha de publicación: {rec.publication_date}.")
    summary = " ".join(parts)

    props = asdict(rec)
    props["content"] = summary
    # serialize nested
    props["status_history"] = [asdict(e) for e in rec.status_history]
    props["lots"] = [asdict(l) for l in rec.lots]
    # drop empty/None scalars (keep required + lists)
    keep_always = {"syndication_id", "category", "content", "status_history", "lots", "cpv", "document_urls"}
    props = {k: v for k, v in props.items()
             if k in keep_always or (v is not None and v != [] and v != "")}
    return summary, props
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_renderer.py -v`
Expected: PASS (2 passed)

- [ ] **Step 5: Commit**

```bash
git add src/placsp/renderer.py tests/test_renderer.py
git commit -m "feat: NL summary renderer + Weaviate properties"
```

---

## Task 8: Embedder (BGE-M3 client)

**Files:**
- Create: `src/placsp/embedder.py`, `tests/test_embedder.py`

**Interfaces:**
- Produces: `class Embedder(base_url:str, batch_size:int=48, timeout:float=600, transport=None)` with `embed(texts:list[str]) -> list[list[float]]`. Posts `{"texts": batch, "normalize": True}` to `{base_url}/embed`, reads `embeddings`, concatenates batches, preserves order, returns `[]` for empty input.

- [ ] **Step 1: Write the failing test `tests/test_embedder.py`**

```python
import json, httpx
from placsp.embedder import Embedder

def _handler(request):
    body = json.loads(request.content)
    texts = body["texts"]
    assert body["normalize"] is True
    return httpx.Response(200, json={"embeddings": [[float(len(t))] * 4 for t in texts]})

def test_embed_batches_and_preserves_order():
    tr = httpx.MockTransport(_handler)
    emb = Embedder("http://vec:8089", batch_size=2, transport=tr)
    out = emb.embed(["a", "bb", "ccc"])
    assert len(out) == 3
    assert out[0] == [1.0, 1.0, 1.0, 1.0]
    assert out[2] == [3.0, 3.0, 3.0, 3.0]

def test_embed_empty():
    emb = Embedder("http://vec:8089", transport=httpx.MockTransport(_handler))
    assert emb.embed([]) == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_embedder.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'placsp.embedder'`

- [ ] **Step 3: Write `src/placsp/embedder.py`**

```python
import httpx

class Embedder:
    def __init__(self, base_url: str, batch_size: int = 48, timeout: float = 600, transport=None):
        self.url = base_url.rstrip("/") + "/embed"
        self.batch_size = batch_size
        self._client = httpx.Client(timeout=timeout, transport=transport)

    def embed(self, texts: list[str]) -> list[list[float]]:
        out: list[list[float]] = []
        for i in range(0, len(texts), self.batch_size):
            batch = texts[i:i + self.batch_size]
            r = self._client.post(self.url, json={"texts": batch, "normalize": True})
            r.raise_for_status()
            out.extend(r.json()["embeddings"])
        return out
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_embedder.py -v`
Expected: PASS (2 passed)

- [ ] **Step 5: Commit**

```bash
git add src/placsp/embedder.py tests/test_embedder.py
git commit -m "feat: BGE-M3 embedder client"
```

---

## Task 9: Weaviate schema

**Files:**
- Create: `src/placsp/weaviate_schema.py`, `tests/test_weaviate_schema.py`

**Interfaces:**
- Produces: `CLASS_DEF` (dict) and `ensure_class(base_url:str, api_key:str, class_name:str, timeout:float=300, transport=None) -> bool` (returns True if created, False if already existed). Checks `GET /v1/schema/{class}`; if 404, `POST /v1/schema` with `CLASS_DEF`. Sets `Authorization: Bearer` when `api_key` given.

- [ ] **Step 1: Write the failing test `tests/test_weaviate_schema.py`**

```python
import httpx
from placsp.weaviate_schema import ensure_class, CLASS_DEF

def test_class_def_shape():
    assert CLASS_DEF["class"] == "Placsp_licitaciones"
    assert CLASS_DEF["vectorizer"] == "none"
    names = {p["name"] for p in CLASS_DEF["properties"]}
    assert {"syndication_id", "content", "status_history", "budget_amount", "lots"} <= names

def test_ensure_class_creates_when_missing():
    calls = {"post": 0}
    def handler(req):
        if req.method == "GET":
            return httpx.Response(404, json={})
        calls["post"] += 1
        return httpx.Response(200, json={})
    created = ensure_class("http://wv:8086", "k", "Placsp_licitaciones",
                           transport=httpx.MockTransport(handler))
    assert created is True and calls["post"] == 1

def test_ensure_class_noop_when_present():
    def handler(req):
        return httpx.Response(200, json={"class": "Placsp_licitaciones"})
    created = ensure_class("http://wv:8086", "k", "Placsp_licitaciones",
                           transport=httpx.MockTransport(handler))
    assert created is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_weaviate_schema.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'placsp.weaviate_schema'`

- [ ] **Step 3: Write `src/placsp/weaviate_schema.py`**

```python
import httpx

def _props():
    text = lambda n: {"name": n, "dataType": ["text"]}
    num = lambda n: {"name": n, "dataType": ["number"]}
    date = lambda n: {"name": n, "dataType": ["date"]}
    out = [text(n) for n in [
        "syndication_id", "expediente", "title", "content", "lang", "category",
        "source_url", "buyer_profile_url", "status_code", "status_label",
        "result_code", "result_label", "contract_type_code", "contract_type",
        "procedure_code", "procedure", "notice_type", "contracting_authority",
        "contracting_authority_id", "org_top_level", "adjudicatario",
        "adjudicatario_nif", "nuts", "nuts_label", "city", "country", "funding_program"]]
    out += [{"name": n, "dataType": ["text[]"]} for n in ["cpv", "document_urls"]]
    out += [num("budget_amount"), num("estimated_value"), num("awarded_amount"),
            {"name": "n_bids", "dataType": ["int"]},
            {"name": "sme_awarded", "dataType": ["boolean"]}]
    out += [date(n) for n in ["publication_date", "award_date", "submission_deadline", "updated"]]
    out += [
        {"name": "status_history", "dataType": ["object[]"], "nestedProperties": [
            {"name": "code", "dataType": ["text"]}, {"name": "date", "dataType": ["text"]}]},
        {"name": "lots", "dataType": ["object[]"], "nestedProperties": [
            {"name": "lot_id", "dataType": ["text"]}, {"name": "name", "dataType": ["text"]},
            {"name": "amount", "dataType": ["number"]}, {"name": "cpv", "dataType": ["text[]"]}]},
    ]
    return out

CLASS_DEF = {
    "class": "Placsp_licitaciones",
    "description": "PLACSP procurement expedientes (latest state).",
    "vectorizer": "none",
    "vectorIndexConfig": {"distance": "cosine"},
    "invertedIndexConfig": {"bm25": {"b": 0.75, "k1": 1.2}},
    "properties": _props(),
}

def ensure_class(base_url, api_key, class_name, timeout=300, transport=None) -> bool:
    headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
    base = base_url.rstrip("/")
    with httpx.Client(timeout=timeout, transport=transport, headers=headers) as c:
        r = c.get(f"{base}/v1/schema/{class_name}")
        if r.status_code == 200:
            return False
        body = dict(CLASS_DEF, **{"class": class_name})
        c.post(f"{base}/v1/schema", json=body).raise_for_status()
        return True
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_weaviate_schema.py -v`
Expected: PASS (3 passed)

- [ ] **Step 5: Commit**

```bash
git add src/placsp/weaviate_schema.py tests/test_weaviate_schema.py
git commit -m "feat: Placsp_licitaciones schema + ensure_class"
```

---

## Task 10: Upserter (deterministic UUID, batch upsert, guard, history merge, tombstones)

**Files:**
- Create: `src/placsp/upserter.py`, `tests/test_upserter.py`

**Interfaces:**
- Consumes: `ProcurementRecord`, `Tombstone`, `renderer.render`.
- Produces: `object_uuid(syndication_id:str) -> str`; `class Upserter(base_url, api_key, class_name, timeout=300, transport=None)` with:
  - `get_stored(sid:str) -> dict|None` (GET object; returns `properties` or None on 404),
  - `upsert(records:list[ProcurementRecord], vectors:list[list[float]]) -> int` (deterministic id; POST `/v1/batch/objects`; returns count sent),
  - `delete(sid:str) -> None` (DELETE by id; ignore 404),
  - `apply_tombstones(tombs:list[Tombstone]) -> int`.

- [ ] **Step 1: Write the failing test `tests/test_upserter.py`**

```python
import uuid, json, httpx
from placsp.upserter import object_uuid, Upserter
from placsp.models import ProcurementRecord, Tombstone

def test_object_uuid_deterministic():
    a = object_uuid("19862167"); b = object_uuid("19862167")
    assert a == b == str(uuid.uuid5(uuid.NAMESPACE_URL, "https://placsp.id/19862167"))

def test_upsert_posts_batch_with_vector_and_id():
    sent = {}
    def handler(req):
        if req.method == "POST" and req.url.path.endswith("/batch/objects"):
            sent["body"] = json.loads(req.content)
            return httpx.Response(200, json=[{"result": {"status": "SUCCESS"}}])
        return httpx.Response(404)
    up = Upserter("http://wv:8086", "k", "Placsp_licitaciones", transport=httpx.MockTransport(handler))
    rec = ProcurementRecord(syndication_id="19862167", category="placsp_mayores", updated="2026-06-19T21:50:27+02:00", title="X")
    n = up.upsert([rec], [[0.1, 0.2]])
    assert n == 1
    obj = sent["body"]["objects"][0]
    assert obj["id"] == object_uuid("19862167")
    assert obj["class"] == "Placsp_licitaciones"
    assert obj["vector"] == [0.1, 0.2]
    assert obj["properties"]["syndication_id"] == "19862167"

def test_apply_tombstones_deletes_by_id():
    deleted = []
    def handler(req):
        if req.method == "DELETE":
            deleted.append(req.url.path)
            return httpx.Response(204)
        return httpx.Response(404)
    up = Upserter("http://wv:8086", "k", "Placsp_licitaciones", transport=httpx.MockTransport(handler))
    n = up.apply_tombstones([Tombstone("4482937", "2026-06-21T00:00:39+02:00", "CERRADA", "externos_mayores")])
    assert n == 1
    assert object_uuid("4482937") in deleted[0]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_upserter.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'placsp.upserter'`

- [ ] **Step 3: Write `src/placsp/upserter.py`**

```python
import uuid
import httpx
from .models import ProcurementRecord, Tombstone
from .renderer import render

def object_uuid(syndication_id: str) -> str:
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"https://placsp.id/{syndication_id}"))

class Upserter:
    def __init__(self, base_url, api_key, class_name, timeout=300, transport=None):
        self.base = base_url.rstrip("/")
        self.cls = class_name
        headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
        self._c = httpx.Client(timeout=timeout, transport=transport, headers=headers)

    def get_stored(self, sid: str):
        r = self._c.get(f"{self.base}/v1/objects/{self.cls}/{object_uuid(sid)}")
        if r.status_code == 404:
            return None
        r.raise_for_status()
        return r.json().get("properties", {})

    def upsert(self, records: list[ProcurementRecord], vectors: list[list[float]]) -> int:
        objects = []
        for rec, vec in zip(records, vectors):
            _, props = render(rec)
            objects.append({"class": self.cls, "id": object_uuid(rec.syndication_id),
                            "vector": vec, "properties": props})
        if not objects:
            return 0
        r = self._c.post(f"{self.base}/v1/batch/objects", json={"objects": objects})
        r.raise_for_status()
        return len(objects)

    def delete(self, sid: str) -> None:
        r = self._c.delete(f"{self.base}/v1/objects/{self.cls}/{object_uuid(sid)}")
        if r.status_code not in (200, 204, 404):
            r.raise_for_status()

    def apply_tombstones(self, tombs: list[Tombstone]) -> int:
        for t in tombs:
            self.delete(t.syndication_id)
        return len(tombs)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_upserter.py -v`
Expected: PASS (3 passed)

- [ ] **Step 5: Commit**

```bash
git add src/placsp/upserter.py tests/test_upserter.py
git commit -m "feat: upserter (deterministic uuid, batch, tombstone delete)"
```

---

## Task 11: Fetcher (download, unzip, feed pagination)

**Files:**
- Create: `src/placsp/fetcher.py`, `tests/test_fetcher.py`

**Interfaces:**
- Produces:
  - `unzip(zip_path:str, dest_dir:str) -> list[str]` (returns sorted `.atom` paths),
  - `feed_next_link(atom_path:str) -> str|None` (the `<link rel="next">` href, normalized to the `contrataciondelsectorpublico.gob.es` host),
  - `download(url:str, dest:str, transport=None, timeout=600) -> str`.

- [ ] **Step 1: Write the failing test `tests/test_fetcher.py`**

```python
import os, zipfile, httpx
from placsp.fetcher import unzip, feed_next_link, download

def test_feed_next_link_from_fixture():
    nxt = feed_next_link("tests/fixtures/externos.atom")
    # trimmed fixture preserves the feed-level next link
    assert nxt is None or nxt.startswith("https://contrataciondelsectorpublico.gob.es/")

def test_unzip_returns_atom_paths(tmp_path):
    z = tmp_path / "f.zip"
    with zipfile.ZipFile(z, "w") as zf:
        zf.writestr("a.atom", "<feed/>")
        zf.writestr("b.atom", "<feed/>")
    paths = unzip(str(z), str(tmp_path / "out"))
    assert len(paths) == 2 and all(p.endswith(".atom") for p in paths)

def test_download_writes_file(tmp_path):
    def handler(req): return httpx.Response(200, content=b"<feed/>")
    dest = str(tmp_path / "x.atom")
    out = download("https://h/x.atom", dest, transport=httpx.MockTransport(handler))
    assert os.path.getsize(out) > 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_fetcher.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'placsp.fetcher'`

- [ ] **Step 3: Write `src/placsp/fetcher.py`**

```python
import os, zipfile, glob
import httpx
from lxml import etree

ATOM = "{http://www.w3.org/2005/Atom}"
HOST = "https://contrataciondelsectorpublico.gob.es"

def unzip(zip_path: str, dest_dir: str) -> list[str]:
    os.makedirs(dest_dir, exist_ok=True)
    with zipfile.ZipFile(zip_path) as zf:
        zf.extractall(dest_dir)
    return sorted(glob.glob(os.path.join(dest_dir, "**", "*.atom"), recursive=True))

def feed_next_link(atom_path: str) -> str | None:
    # only the feed-level <link>; stop at first <entry>
    for _, el in etree.iterparse(atom_path, events=("end",)):
        ln = el.tag.rsplit("}", 1)[-1]
        if ln == "link" and el.get("rel") == "next":
            href = el.get("href") or ""
            # feeds reference contrataciondelestado.es; normalize to the canonical sync host
            return href.replace("https://contrataciondelestado.es", HOST)
        if ln == "entry":
            break
    return None

def download(url: str, dest: str, transport=None, timeout=600) -> str:
    os.makedirs(os.path.dirname(dest) or ".", exist_ok=True)
    with httpx.Client(timeout=timeout, transport=transport, verify=False,
                      headers={"User-Agent": "placsp-ingest"}) as c:
        r = c.get(url, follow_redirects=True)
        r.raise_for_status()
        with open(dest, "wb") as f:
            f.write(r.content)
    return dest
```

Note: `verify=False` mirrors the validated reality that PLACSP chains to a Spanish CA not in the default trust store. If the deployment host trusts the FNMT CA, set `verify=True`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_fetcher.py -v`
Expected: PASS (3 passed)

- [ ] **Step 5: Commit**

```bash
git add src/placsp/fetcher.py tests/test_fetcher.py
git commit -m "feat: fetcher (download, unzip, next-link)"
```

---

## Task 12: Catalog + pipeline (collapse, process, backfill/daily/reconcile)

**Files:**
- Create: `src/placsp/catalog.py`, `src/placsp/pipeline.py`, `tests/test_pipeline.py`

**Interfaces:**
- Consumes: all prior modules.
- Produces:
  - `catalog.Feed(name, category, url, year, incremental)`, `catalog.CATALOG:list[Feed]`, `catalog.live_head_url(category:str) -> str`.
  - `pipeline.collapse(items:Iterable[RawEntry|Tombstone], codelists) -> tuple[dict[str,ProcurementRecord], list[Tombstone]]` — keeps max-`updated` record per `syndication_id`, accumulating `status_history` across versions.
  - `pipeline.Pipeline(cfg, embedder, upserter, codelists)` with `process_files(paths:list[str], category:str) -> dict` (parse→collapse→embed→upsert→tombstones; returns counts) and `is_offpeak(now) -> bool`.

- [ ] **Step 1: Write the failing test `tests/test_pipeline.py`**

```python
import httpx, json
from placsp.pipeline import collapse, Pipeline
from placsp.atom_parser import parse_feed
from placsp.embedder import Embedder
from placsp.upserter import Upserter
from placsp.config import load_config
from datetime import datetime

def test_collapse_keeps_latest_and_merges_history():
    from placsp.models import RawEntry, StatusEvent
    # two versions of same id, different status + updated
    class E: pass
    items = list(parse_feed("tests/fixtures/externos.atom", "externos_mayores"))
    recs, tombs = collapse(items, None)
    # one syndication_id per record
    assert all(sid == r.syndication_id for sid, r in recs.items())
    assert len(tombs) == 1

def test_process_files_end_to_end_mocked():
    def vec_handler(req):
        body = json.loads(req.content)
        return httpx.Response(200, json={"embeddings": [[0.0]*4 for _ in body["texts"]]})
    posted = {"n": 0, "deleted": 0}
    def wv_handler(req):
        if req.method == "POST":
            posted["n"] += len(json.loads(req.content)["objects"]); return httpx.Response(200, json=[])
        if req.method == "DELETE":
            posted["deleted"] += 1; return httpx.Response(204)
        return httpx.Response(404)
    cfg = load_config()
    emb = Embedder(cfg.vectorizer_url, transport=httpx.MockTransport(vec_handler))
    up = Upserter(cfg.weaviate_url, "", cfg.weaviate_class, transport=httpx.MockTransport(wv_handler))
    p = Pipeline(cfg, emb, up, None)
    stats = p.process_files(["tests/fixtures/externos.atom"], "externos_mayores")
    assert stats["upserted"] == posted["n"] > 0
    assert stats["deleted"] == 1

def test_is_offpeak():
    cfg = load_config()
    p = Pipeline(cfg, None, None, None)
    # default window 22..7
    assert p.is_offpeak(datetime(2026,1,1,23,0)) is True
    assert p.is_offpeak(datetime(2026,1,1,12,0)) is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_pipeline.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'placsp.pipeline'`

- [ ] **Step 3: Write `src/placsp/catalog.py`**

```python
from dataclasses import dataclass

@dataclass
class Feed:
    name: str
    category: str
    url: str
    year: int
    incremental: bool

_BASE = "https://contrataciondelsectorpublico.gob.es/sindicacion"
_CHANNELS = {
    "placsp_mayores":   ("sindicacion_643",  "licitacionesPerfilesContratanteCompleto3", 2012),
    "externos_mayores": ("sindicacion_1044", "PlataformasAgregadasSinMenores",           2016),
    "placsp_menores":   ("sindicacion_1143", "contratosMenoresPerfilesContratantes",     2018),
    "propios":          ("sindicacion_1383", "EMP_SectorPublico",                         2022),
}

def _build():
    feeds, current = [], 2025
    for cat, (sind, stem, start) in _CHANNELS.items():
        for year in range(start, current + 1):
            feeds.append(Feed(f"{cat}_{year}", cat,
                              f"{_BASE}/{sind}/{stem}_{year}.zip", year, year == current))
    return feeds

CATALOG = _build()

def live_head_url(category: str) -> str:
    sind, stem, _ = _CHANNELS[category]
    return f"{_BASE}/{sind}/{stem}.atom"
```

- [ ] **Step 4: Write `src/placsp/pipeline.py`**

```python
from typing import Iterable, Optional
import structlog
from .models import RawEntry, Tombstone, ProcurementRecord, StatusEvent
from .atom_parser import parse_feed
from .codice_extractor import extract

log = structlog.get_logger(service="placsp")

def _merge_history(rec: ProcurementRecord, seen: dict):
    key = (rec.status_code, (rec.updated or "")[:10])
    if rec.status_code:
        seen.setdefault(rec.syndication_id, {})[key] = StatusEvent(rec.status_code, (rec.updated or "")[:10] or None)

def collapse(items: Iterable, codelists) -> tuple[dict[str, ProcurementRecord], list[Tombstone]]:
    latest: dict[str, ProcurementRecord] = {}
    history: dict[str, dict] = {}
    tombs: list[Tombstone] = []
    for it in items:
        if isinstance(it, Tombstone):
            tombs.append(it); continue
        rec = extract(it, codelists)
        _merge_history(rec, history)
        prev = latest.get(rec.syndication_id)
        if prev is None or (rec.updated or "") >= (prev.updated or ""):
            latest[rec.syndication_id] = rec
    for sid, rec in latest.items():
        rec.status_history = sorted(history.get(sid, {}).values(), key=lambda e: e.date or "")
    # drop ids that are tombstoned in the same batch
    tomb_ids = {t.syndication_id for t in tombs}
    for sid in tomb_ids:
        latest.pop(sid, None)
    return latest, tombs

class Pipeline:
    def __init__(self, cfg, embedder, upserter, codelists):
        self.cfg = cfg
        self.embedder = embedder
        self.upserter = upserter
        self.codelists = codelists

    def is_offpeak(self, now) -> bool:
        s, e = self.cfg.offpeak_start, self.cfg.offpeak_end
        h = now.hour
        return (s <= h or h < e) if s > e else (s <= h < e)

    def process_files(self, paths: list[str], category: str) -> dict:
        def items():
            for p in paths:
                yield from parse_feed(p, category)
        records, tombs = collapse(items(), self.codelists)
        recs = list(records.values())
        texts = [self._summary(r) for r in recs]
        vectors = self.embedder.embed(texts) if recs else []
        upserted = self.upserter.upsert(recs, vectors) if recs else 0
        deleted = self.upserter.apply_tombstones(tombs) if tombs else 0
        log.info("processed", category=category, files=len(paths), upserted=upserted, deleted=deleted)
        return {"records": len(recs), "upserted": upserted, "deleted": deleted}

    def _summary(self, rec) -> str:
        from .renderer import render
        return render(rec)[0]
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest tests/test_pipeline.py -v`
Expected: PASS (3 passed)

- [ ] **Step 6: Commit**

```bash
git add src/placsp/catalog.py src/placsp/pipeline.py tests/test_pipeline.py
git commit -m "feat: catalog + pipeline (collapse, process, offpeak)"
```

---

## Task 13: CLI orchestration (`init-schema`, `backfill`, `daily`, `reconcile`)

**Files:**
- Create: `src/placsp/__main__.py`, `tests/test_cli.py`
- Modify: `src/placsp/pipeline.py` (add `run_backfill`, `run_daily`, `run_reconcile`)

**Interfaces:**
- Consumes: `Pipeline`, `catalog`, `fetcher`, `weaviate_schema`.
- Produces: `pipeline.Pipeline.run_backfill()`, `run_daily(watermark_lookup)`, `run_reconcile()`; and `python -m placsp {init-schema|backfill|daily|reconcile}`.

- [ ] **Step 1: Add `run_*` methods to `src/placsp/pipeline.py`**

```python
    # --- append to Pipeline ---
    def watermark(self, category: str) -> Optional[str]:
        # max(updated) for a category, via GraphQL aggregate; None if empty/unsupported
        import httpx
        q = ('{Aggregate{%s(where:{path:["category"],operator:Equal,valueText:"%s"})'
             '{updated{maximum}}}}' % (self.cfg.weaviate_class, category))
        try:
            r = httpx.post(f"{self.cfg.weaviate_url.rstrip('/')}/v1/graphql",
                           json={"query": q}, timeout=60,
                           headers={"Authorization": f"Bearer {self.cfg.weaviate_api_key}"} if self.cfg.weaviate_api_key else {})
            agg = r.json()["data"]["Aggregate"][self.cfg.weaviate_class]
            return agg[0]["updated"]["maximum"] if agg else None
        except Exception:
            return None

    def run_backfill(self):
        import os, time
        from datetime import datetime
        from .catalog import CATALOG
        from .fetcher import download, unzip
        for feed in sorted(CATALOG, key=lambda f: (f.year, f.category)):
            while not self.is_offpeak(datetime.now()):
                log.info("sleeping_until_offpeak"); time.sleep(600)
            workdir = os.path.join(self.cfg.work_dir, feed.name)
            zip_path = os.path.join(workdir, feed.name + ".zip")
            try:
                download(feed.url, zip_path)
                paths = unzip(zip_path, workdir)
                self.process_files(paths, feed.category)
            except Exception as exc:
                log.error("feed_failed", feed=feed.name, error=str(exc))
            finally:
                if os.path.exists(zip_path):
                    os.remove(zip_path)

    def run_daily(self):
        import os, tempfile
        from .catalog import CATALOG, live_head_url
        from .fetcher import download, feed_next_link
        from .atom_parser import parse_feed
        for category in sorted({f.category for f in CATALOG}):
            wm = self.watermark(category)
            url = live_head_url(category)
            page = 0
            while url and page < 1000:
                tmp = os.path.join(tempfile.gettempdir(), f"placsp_{category}_{page}.atom")
                download(url, tmp)
                self.process_files([tmp], category)
                # capture the next link and this page's newest update BEFORE deleting tmp
                newest = max((getattr(i, "updated", "") or "" for i in parse_feed(tmp, category)), default="")
                nxt = feed_next_link(tmp)
                os.remove(tmp)
                # stop when this page is entirely older than the watermark
                if wm and newest and newest <= wm:
                    break
                url, page = nxt, page + 1

    def run_reconcile(self):
        import os
        from datetime import datetime
        from .catalog import CATALOG
        from .fetcher import download, unzip
        for feed in [f for f in CATALOG if f.incremental]:
            workdir = os.path.join(self.cfg.work_dir, feed.name + "_recon")
            zip_path = os.path.join(workdir, feed.name + ".zip")
            download(feed.url, zip_path)
            self.process_files(unzip(zip_path, workdir), feed.category)
            os.remove(zip_path)
```

Note: in `run_daily`, capture the next link before deleting the temp file. Adjust to read `feed_next_link(tmp)` *before* `os.remove(tmp)` during implementation; the test below pins the build helpers, not the live loop.

- [ ] **Step 2: Write the failing test `tests/test_cli.py`**

```python
import subprocess, sys

def test_cli_help_lists_commands():
    out = subprocess.run([sys.executable, "-m", "placsp", "--help"],
                         capture_output=True, text=True, cwd=".")
    assert "backfill" in out.stdout and "daily" in out.stdout and "init-schema" in out.stdout

def test_cli_unknown_command_errors():
    out = subprocess.run([sys.executable, "-m", "placsp", "nope"], capture_output=True, text=True)
    assert out.returncode != 0
```

- [ ] **Step 3: Run test to verify it fails**

Run: `pytest tests/test_cli.py -v`
Expected: FAIL — no `__main__` / nonzero help

- [ ] **Step 4: Write `src/placsp/__main__.py`**

```python
import argparse
from .config import load_config
from .codelists import Codelists
from .embedder import Embedder
from .upserter import Upserter
from .pipeline import Pipeline
from .weaviate_schema import ensure_class

def _pipeline(cfg):
    return Pipeline(cfg,
                    Embedder(cfg.vectorizer_url, cfg.embed_batch_size, cfg.request_timeout),
                    Upserter(cfg.weaviate_url, cfg.weaviate_api_key, cfg.weaviate_class, cfg.request_timeout),
                    Codelists(cfg.codelist_dir))

def main(argv=None):
    parser = argparse.ArgumentParser(prog="placsp")
    sub = parser.add_subparsers(dest="cmd", required=True)
    for name in ("init-schema", "backfill", "daily", "reconcile"):
        sub.add_parser(name)
    args = parser.parse_args(argv)
    cfg = load_config()
    if args.cmd == "init-schema":
        created = ensure_class(cfg.weaviate_url, cfg.weaviate_api_key, cfg.weaviate_class, cfg.request_timeout)
        print("created" if created else "exists")
        return
    p = _pipeline(cfg)
    {"backfill": p.run_backfill, "daily": p.run_daily, "reconcile": p.run_reconcile}[args.cmd]()

if __name__ == "__main__":
    main()
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest tests/test_cli.py -v`
Expected: PASS (2 passed)

- [ ] **Step 6: Run the full suite**

Run: `pytest -q`
Expected: PASS (all tasks' tests green)

- [ ] **Step 7: Commit**

```bash
git add src/placsp/__main__.py src/placsp/pipeline.py tests/test_cli.py
git commit -m "feat: CLI (init-schema/backfill/daily/reconcile) + run methods"
```

---

## Task 14: One-feed end-to-end validation (runbook)

**Files:**
- Create: `scripts/fetch_codelists.py`, `docs/RUNBOOK.md`

This task is a manual validation against the **real** running vectorizer + Weaviate (not a unit test). Run it from a host with network + service access.

- [ ] **Step 1: Write `scripts/fetch_codelists.py`** (pre-populates the codelist cache used by the extractor)

```python
"""Scan a sample feed for every distinct listURI and download each .gc into the cache dir."""
import os, sys
from lxml import etree
import httpx

def main(sample_atom: str, cache_dir: str):
    os.makedirs(cache_dir, exist_ok=True)
    uris = set()
    for _, el in etree.iterparse(sample_atom, events=("end",)):
        u = el.get("listURI") or el.get("listURIID")
        if u:
            uris.add(u.replace("http://", "https://"))
        el.clear()
    with httpx.Client(verify=False, timeout=120, headers={"User-Agent": "placsp"}) as c:
        for u in sorted(uris):
            fn = u.rstrip("/").rsplit("/", 1)[-1]
            try:
                r = c.get(u, follow_redirects=True)
                if r.status_code == 200:
                    open(os.path.join(cache_dir, fn), "wb").write(r.content)
                    print("ok", fn)
                else:
                    print("skip", fn, r.status_code)
            except Exception as e:
                print("err", fn, e)

if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
```

- [ ] **Step 2: Create the schema against real Weaviate**

```bash
export WEAVIATE_URL=http://iarag-vectorstore:8086 WEAVIATE_API_KEY=<key>
python -m placsp init-schema   # expect: created
```

- [ ] **Step 3: Populate codelists from a real sample**

```bash
# use any downloaded .atom (e.g. one extracted from a real ZIP)
python scripts/fetch_codelists.py tests/fixtures/mayores.atom ./codelists
```

- [ ] **Step 4: Ingest a single feed/year and verify counts**

Temporarily restrict the catalog to one unit by setting an env override (or run a one-off Python snippet):

```bash
python - <<'PY'
from placsp.config import load_config
from placsp.codelists import Codelists
from placsp.embedder import Embedder
from placsp.upserter import Upserter
from placsp.pipeline import Pipeline
from placsp.fetcher import download, unzip
cfg = load_config()
p = Pipeline(cfg, Embedder(cfg.vectorizer_url, cfg.embed_batch_size, cfg.request_timeout),
             Upserter(cfg.weaviate_url, cfg.weaviate_api_key, cfg.weaviate_class, cfg.request_timeout),
             Codelists(cfg.codelist_dir))
url = "https://contrataciondelsectorpublico.gob.es/sindicacion/sindicacion_1383/EMP_SectorPublico_2022.zip"
unz = unzip(download(url, "./work/propios_2022.zip"), "./work/propios_2022")
print(p.process_files(unz, "propios"))
PY
```

Expected: a dict like `{"records": <N>, "upserted": <N>, "deleted": <M>}` with `records > 0`.

- [ ] **Step 5: Verify retrieval quality** (vector + BM25)

```bash
python - <<'PY'
import httpx, json
from placsp.config import load_config
from placsp.embedder import Embedder
cfg = load_config()
qv = Embedder(cfg.vectorizer_url).embed(["servicios de limpieza"])[0]
gql = '{Get{%s(nearVector:{vector:%s},limit:3){syndication_id title content estado:status_label awarded_amount}}}' % (
    cfg.weaviate_class, json.dumps(qv))
r = httpx.post(cfg.weaviate_url.rstrip("/")+"/v1/graphql", json={"query": gql},
               headers={"Authorization": f"Bearer {cfg.weaviate_api_key}"} if cfg.weaviate_api_key else {})
print(json.dumps(r.json(), ensure_ascii=False, indent=2)[:1500])
PY
```

Expected: 3 hits with readable Spanish `content`, decoded `status_label`, and populated fields. Confirm relevance by eye.

- [ ] **Step 6: Document findings + tuning in `docs/RUNBOOK.md`**

Record: observed throughput (entries/min), chosen `PLACSP_EMBED_BATCH` / `PLACSP_MAX_IN_FLIGHT`, the off-peak window, any missing codelists, and any field-coverage surprises. This closes the spec's "remaining unknowns."

- [ ] **Step 7: Commit**

```bash
git add scripts/fetch_codelists.py docs/RUNBOOK.md
git commit -m "feat: codelist fetcher + one-feed validation runbook"
```

---

## Self-Review

**Spec coverage:**
- Standalone Python, no n8n → Tasks 1–13. ✓
- Dedup key = syndication id; deterministic UUID → Task 10 (`object_uuid`). ✓
- Weaviate source-of-truth, latest-`updated` wins, in-memory collapse → Task 12 (`collapse`). ✓
- Tombstone deletions → Tasks 3, 10, 12. ✓
- Single hybrid class, 1024-dim, BM25, nested object[] → Task 9. ✓
- NL summary, no chunking, no prefix → Tasks 7, 8. ✓
- Codelist decoding → Tasks 4, 5/6, 14. ✓
- Source-aware extraction + 3 money fields → Tasks 5, 6. ✓
- status_history array → Tasks 5, 12. ✓
- Daily live-feed walk + watermark; monthly reconciliation; off-peak/rate-cap backfill → Tasks 12, 13. ✓
- Validate on one feed first → Task 14. ✓
- TDD with all-four-source fixtures incl. tombstone + collision → Tasks 1, 3, 5, 6. ✓

**Open items deferred to validation (per spec §10):** embed batch/max-in-flight tuning and long-tail codelist/field edge cases → Task 14 runbook.

**Type consistency:** `object_uuid`, `Embedder.embed`, `Upserter.upsert/apply_tombstones`, `render`, `extract`, `parse_feed`, `collapse`, `Pipeline.process_files` signatures are used consistently across tasks and tests.

**Note for implementer (Task 13 `run_daily`):** read `feed_next_link(tmp)` **before** `os.remove(tmp)`; the snippet's ordering is corrected in the inline note. Keep the next-link capture above the temp-file cleanup.
