# PLACSP Company Graph (SP1) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a feed-derived Neo4j graph of awarded lots and their winning companies (NIF identity, bid statistics), populated by a `graph_sink` running inside the existing PLACSP ingestion pipeline.

**Architecture:** Extend `codice_extractor` to emit a winner-per-lot list on each `ProcurementRecord`. A pure function `record_to_graph_ops` projects a record into a `GraphBatch` (plain node/edge dicts) — the unit-test seam, no DB. A `GraphSink` translates batches into idempotent Cypher `MERGE` (via `UNWIND`) against Neo4j, and applies tombstones as `DETACH DELETE`. The sink is wired into `Pipeline.process_files` as an optional, additive step alongside the existing Weaviate upsert, so backfill/daily/reconcile populate both stores in one pass.

**Tech Stack:** Python 3.11+, `neo4j` Python driver (Bolt), Neo4j 5.x + GDS plugin (Docker), `lxml`, `structlog`, `pytest`.

## Global Constraints

- Python `requires-python = ">=3.11"`; keep dependencies minimal (add only `neo4j>=5`).
- The graph path is **additive and non-blocking**: when Neo4j is not configured (`NEO4J_URL` empty), `Pipeline` behaves exactly as today. Never let a graph error abort the Weaviate path.
- **Idempotency:** every graph write is `MERGE` on a stable key + `SET` (last-write-wins), mirroring the deterministic-UUID Weaviate upsert. Re-running any feed must not duplicate nodes/edges.
- **Awarded-only:** only records carrying at least one lot winner with a parseable NIF enter the graph. No-NIF awards are skipped (and logged), never guessed.
- **Do not alter the existing Weaviate path:** the current `rec.lots`, `rec.adjudicatario`, `rec.adjudicatario_nif`, and `render()` output must stay byte-for-byte unchanged. The graph consumes a **new** `rec.lot_results` field.
- Follow existing module style: small functions, `structlog` logger `log = structlog.get_logger(service="placsp")`, dataclasses in `models.py`, first-present-wins XPath helpers in `codice_extractor.py`.
- Run tests with `PYTHONPATH=src pytest` (configured via `pyproject.toml` `pythonpath`).

## Plan-time resolutions of spec §9 open decisions

- **`HAS_NAME` count semantics → resolved by dropping the `Name` node.** The winner name is stored **on the `WON` edge** (`name_norm`, `name_display`); `Company.canonical_name` is **derived** by aggregating `WON` edges (most frequent normalized name → its display). This is fully idempotent (re-ingest MERGEs the same `WON` by `lot_key`, no double-count) and removes the `(:Name)`/`HAS_NAME` structures from the spec's §3 model. Aliases remain queryable as `DISTINCT r.name_display`.
- **`MEMBER_OF` → deferred.** Verified against fixtures: PLACSP syndication names only the winning party, not UTE members. SP1 sets `Company.is_ute` (winner NIF starts with `U`, or name starts with `UTE`) but creates **no** `MEMBER_OF` edges; member linkage waits for a source that exposes members (SP2). The `U04800001` in fixtures is a DIR3 *authority* code, so `is_ute` is applied to **winner** NIFs only.
- **Lot↔`TenderResult` XPath → confirmed** (`cac:AwardedTenderedProject/cbc:ProcurementProjectLotID`); `externos` multi-lot shape remains a manual spot-check in Task 1.
- **Neo4j batching → `UNWIND` per element type** in one write transaction per `process_files` call.

## File Structure

- Create `src/placsp/graph_ops.py` — pure projection: `GraphBatch` dataclass, `record_to_graph_ops(rec) -> GraphBatch`, `merge_batches(...)`, and helpers `normalize_nif`, `normalize_name`, `is_ute_winner`.
- Create `src/placsp/graph_sink.py` — `GraphSink` (Bolt driver): `ensure_constraints`, `upsert(records)`, `apply_tombstones(tombs)`, `close`; the Cypher `UNWIND` statements.
- Modify `src/placsp/models.py` — add `LotResult` dataclass and `ProcurementRecord.lot_results` field.
- Modify `src/placsp/codice_extractor.py` — populate `rec.lot_results` from `cac:TenderResult` joined with `cac:ProcurementProjectLot`.
- Modify `src/placsp/config.py` — add `neo4j_url`, `neo4j_user`, `neo4j_password`.
- Modify `src/placsp/pipeline.py` — optional `graph_sink` arg; call it in `process_files`.
- Modify `src/placsp/__main__.py` — construct `GraphSink` when configured; add `init-graph` command.
- Modify `docker-compose.yml` — `placsp-neo4j` + one-shot `placsp-init-graph` services.
- Modify `pyproject.toml` — add `neo4j>=5`.
- Tests: extend `tests/test_codice_extractor.py`; create `tests/test_graph_ops.py` (pure), `tests/test_pipeline_graph.py` (stub), `tests/test_graph_sink_integration.py` (live Neo4j, marked).

---

## Task 1: Per-lot winner extraction

**Files:**
- Modify: `src/placsp/models.py`
- Modify: `src/placsp/codice_extractor.py:114-143`
- Test: `tests/test_codice_extractor.py`

**Interfaces:**
- Produces: `LotResult` dataclass and `ProcurementRecord.lot_results: list[LotResult]`. Each `LotResult` has: `lot_id: str`, `winner_name: Optional[str]`, `winner_nif: Optional[str]`, `amount: Optional[float]`, `award_date: Optional[str]`, `sme_awarded: Optional[bool]`, `n_bids: Optional[int]`, `n_sme_bids: Optional[int]`, `lower_tender_amount: Optional[float]`, `higher_tender_amount: Optional[float]`, `name: Optional[str]`, `cpv: list[str]`.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_codice_extractor.py`:

```python
def test_lot_results_multilot_mayores():
    # mayores sid 17200541 has 3 TenderResults, one per ProcurementProjectLot,
    # all won by HERMANOS OLIVA BAHIA SLL (B72318934)
    cl = Codelists("tests/fixtures")
    rec = None
    for it in parse_feed("tests/fixtures/mayores.atom", "placsp_mayores"):
        if isinstance(it, RawEntry) and it.syndication_id == "17200541":
            rec = extract(it, cl); break
    assert rec is not None
    assert len(rec.lot_results) == 3
    lot_ids = sorted(lr.lot_id for lr in rec.lot_results)
    assert lot_ids == ["1", "2", "3"]
    for lr in rec.lot_results:
        assert lr.winner_nif == "B72318934"
        assert lr.winner_name == "HERMANOS OLIVA BAHIA SLL"
        assert lr.amount is not None and lr.amount > 0

def test_lot_results_bid_stats_present_mayores():
    cl = Codelists("tests/fixtures")
    rec = next(extract(it, cl) for it in parse_feed("tests/fixtures/mayores.atom", "placsp_mayores")
               if isinstance(it, RawEntry) and it.syndication_id == "17200541")
    lr = rec.lot_results[0]
    assert lr.n_bids is not None and lr.n_bids >= 1
    # mayores carries SMEsReceivedTenderQuantity + Lower/HigherTenderAmount
    assert lr.lower_tender_amount is not None
    assert lr.higher_tender_amount is not None

def test_lot_results_implicit_single_lot_menores():
    # menores have a TenderResult + WinningParty but no ProcurementProjectLot
    rec = next(extract(it, None) for it in parse_feed("tests/fixtures/menores.atom", "placsp_menores")
               if isinstance(it, RawEntry))
    assert len(rec.lot_results) == 1
    lr = rec.lot_results[0]
    assert lr.lot_id == "0"
    assert lr.winner_name  # winner present
    assert lr.amount is not None and lr.amount > 0

def test_existing_weaviate_fields_unchanged_menores():
    # Regression: the existing record-level fields the Weaviate path uses must remain
    rec = next(extract(it, None) for it in parse_feed("tests/fixtures/menores.atom", "placsp_menores")
               if isinstance(it, RawEntry))
    assert rec.adjudicatario and rec.adjudicatario_nif
    assert rec.awarded_amount is not None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `PYTHONPATH=src pytest tests/test_codice_extractor.py -k "lot_results" -v`
Expected: FAIL — `AttributeError: 'ProcurementRecord' object has no attribute 'lot_results'`.

- [ ] **Step 3: Add the `LotResult` dataclass and record field**

In `src/placsp/models.py`, add after the `Lot` dataclass (around line 26):

```python
@dataclass
class LotResult:
    lot_id: str
    winner_name: Optional[str] = None
    winner_nif: Optional[str] = None
    amount: Optional[float] = None
    award_date: Optional[str] = None
    sme_awarded: Optional[bool] = None
    n_bids: Optional[int] = None
    n_sme_bids: Optional[int] = None
    lower_tender_amount: Optional[float] = None
    higher_tender_amount: Optional[float] = None
    name: Optional[str] = None
    cpv: list[str] = field(default_factory=list)
```

In `ProcurementRecord`, add a field next to `lots` (around line 69):

```python
    lot_results: list[LotResult] = field(default_factory=list)
```

- [ ] **Step 4: Populate `lot_results` in the extractor**

In `src/placsp/codice_extractor.py`, update the import at line 2 and add the population logic. Replace the `# lots` block (lines 131-141) with the existing lots loop **plus** the new `lot_results` build below it. First, change line 132 `from .models import Lot` to:

```python
    from .models import Lot, LotResult
```

Then, **after** the existing `for lot_el in (...)` loop that appends to `rec.lots` (keep that loop unchanged), append:

```python
    # per-lot winners for the graph (separate from rec.lots / Weaviate path)
    def _int(s):
        try:
            return int(float(s)) if s is not None else None
        except (TypeError, ValueError):
            return None

    lot_meta = {}  # lot_id -> (name, cpv[])
    for lot_el in (cfs.xpath("cac:ProcurementProjectLot", namespaces=NS) if cfs is not None else []):
        lid = lot_el.xpath("cbc:ID/text()", namespaces=NS)
        nm = lot_el.xpath("cac:ProcurementProject/cbc:Name/text()", namespaces=NS)
        cpv = [str(x).strip() for x in lot_el.xpath(".//cbc:ItemClassificationCode/text()", namespaces=NS)]
        if lid:
            lot_meta[str(lid[0]).strip()] = (str(nm[0]).strip() if nm else None, cpv)

    for tr in (cfs.xpath("cac:TenderResult", namespaces=NS) if cfs is not None else []):
        lid = tr.xpath("cac:AwardedTenderedProject/cbc:ProcurementProjectLotID/text()", namespaces=NS)
        lot_id = str(lid[0]).strip() if lid else "0"
        nm = tr.xpath("cac:WinningParty/cac:PartyName/cbc:Name/text()", namespaces=NS)
        nif = tr.xpath("cac:WinningParty/cac:PartyIdentification/cbc:ID/text()", namespaces=NS)
        amt = tr.xpath("cac:AwardedTenderedProject/cac:LegalMonetaryTotal/cbc:TaxExclusiveAmount/text()",
                       namespaces=NS) or \
              tr.xpath("cac:AwardedTenderedProject/cac:LegalMonetaryTotal/cbc:PayableAmount/text()", namespaces=NS)
        adate = tr.xpath("cbc:AwardDate/text()", namespaces=NS)
        sme = tr.xpath("cbc:SMEAwardedIndicator/text()", namespaces=NS)
        nbids = tr.xpath("cbc:ReceivedTenderQuantity/text()", namespaces=NS)
        nsme = tr.xpath("cbc:SMEsReceivedTenderQuantity/text()", namespaces=NS)
        low = tr.xpath("cbc:LowerTenderAmount/text()", namespaces=NS)
        high = tr.xpath("cbc:HigherTenderAmount/text()", namespaces=NS)
        meta = lot_meta.get(lot_id, (None, []))
        rec.lot_results.append(LotResult(
            lot_id=lot_id,
            winner_name=(str(nm[0]).strip() if nm else None),
            winner_nif=(str(nif[0]).strip() if nif else None),
            amount=_num(str(amt[0]) if amt else None),
            award_date=(str(adate[0]).strip() if adate else None),
            sme_awarded={"true": True, "false": False}.get((str(sme[0]).lower() if sme else "")),
            n_bids=_int(str(nbids[0]) if nbids else None),
            n_sme_bids=_int(str(nsme[0]) if nsme else None),
            lower_tender_amount=_num(str(low[0]) if low else None),
            higher_tender_amount=_num(str(high[0]) if high else None),
            name=meta[0],
            cpv=meta[1],
        ))
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `PYTHONPATH=src pytest tests/test_codice_extractor.py -v`
Expected: PASS (all new tests plus the pre-existing extractor tests).

- [ ] **Step 6: Manual spot-check of `externos`**

Run: `PYTHONPATH=src python3 -c "from placsp.atom_parser import parse_feed; from placsp.models import RawEntry; from placsp.codice_extractor import extract; print([len(extract(it,None).lot_results) for it in parse_feed('tests/fixtures/externos.atom','externos_mayores') if isinstance(it,RawEntry)][:10])"`
Expected: a list of integers (0 for non-awarded externos entries — the fixture had no `TenderResult`). If a future externos sample shows multi-lot results, no code change is needed; the same `TenderResult` path handles it. Note the result in the commit message if non-zero.

- [ ] **Step 7: Commit**

```bash
git add src/placsp/models.py src/placsp/codice_extractor.py tests/test_codice_extractor.py
git commit -m "feat: extract per-lot winners and bid stats into lot_results"
```

---

## Task 2: `record_to_graph_ops` projection (pure, no DB)

**Files:**
- Create: `src/placsp/graph_ops.py`
- Test: `tests/test_graph_ops.py`

**Interfaces:**
- Consumes: `ProcurementRecord` with `lot_results` (Task 1), plus existing fields `syndication_id`, `expediente`, `title`, `status_code`, `result_code`, `contract_type_code`, `procedure_code`, `budget_amount`, `estimated_value`, `award_date`, `publication_date`, `category`, `contracting_authority`, `contracting_authority_id`, `org_top_level`, `nuts`.
- Produces:
  - `normalize_nif(s: Optional[str]) -> Optional[str]` — uppercase, strip spaces/dots/hyphens; `None`/empty → `None`.
  - `normalize_name(s: Optional[str]) -> str` — uppercase, drop legal-suffix tokens, collapse non-alphanumerics to single spaces, trim.
  - `is_ute_winner(name, nif) -> bool`.
  - `GraphBatch` dataclass with list fields: `companies`, `contracts`, `lots`, `won`, `authorities`, `tendered`, `classified`, `located`, `affected_nifs`.
  - `record_to_graph_ops(rec) -> GraphBatch`.
  - `merge_batches(batches: list[GraphBatch]) -> GraphBatch`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_graph_ops.py`:

```python
from placsp.models import ProcurementRecord, LotResult
from placsp.graph_ops import (
    normalize_nif, normalize_name, is_ute_winner,
    record_to_graph_ops, merge_batches, GraphBatch,
)

def _rec(**kw):
    base = dict(syndication_id="100", category="placsp_mayores", updated="2025-01-01")
    base.update(kw)
    return ProcurementRecord(**base)

def test_normalize_nif():
    assert normalize_nif(" b-72.318.934 ") == "B72318934"
    assert normalize_nif("") is None
    assert normalize_nif(None) is None

def test_normalize_name_strips_legal_suffix():
    assert normalize_name("Hermanos Oliva Bahia, S.L.L.") == normalize_name("HERMANOS OLIVA BAHIA SLL")
    assert normalize_name("Acme S.A.") == "ACME"

def test_is_ute_winner():
    assert is_ute_winner("UTE LIMPIEZA 2025", "U12345678") is True
    assert is_ute_winner("UTE Algo", "B12345678") is True
    assert is_ute_winner("Acme SL", "B12345678") is False

def test_single_lot_award_produces_company_contract_lot_won():
    rec = _rec(title="Servicio X", contracting_authority="Ayto Z",
               contracting_authority_id="L01", nuts="ES61",
               lot_results=[LotResult(lot_id="0", winner_name="Acme SL",
                                      winner_nif="B12345678", amount=1000.0,
                                      award_date="2025-03-01", cpv=["45110000"])])
    b = record_to_graph_ops(rec)
    assert b.companies == [{"nif": "B12345678", "is_ute": False}]
    assert b.contracts[0]["syndication_id"] == "100"
    assert b.lots[0]["lot_key"] == "100:0"
    assert b.won[0] == {"nif": "B12345678", "lot_key": "100:0", "amount": 1000.0,
                        "award_date": "2025-03-01",
                        "name_norm": normalize_name("Acme SL"), "name_display": "Acme SL"}
    assert {"authority_id": "L01", "syndication_id": "100"} in b.tendered
    assert {"lot_key": "100:0", "cpv": "45110000"} in b.classified
    assert {"syndication_id": "100", "nuts": "ES61"} in b.located
    assert b.affected_nifs == ["B12345678"]

def test_multilot_multiwinner_distinct_won_edges():
    rec = _rec(syndication_id="200", lot_results=[
        LotResult(lot_id="1", winner_name="A SL", winner_nif="B1", amount=10.0),
        LotResult(lot_id="2", winner_name="B SL", winner_nif="B2", amount=20.0),
    ])
    b = record_to_graph_ops(rec)
    assert {c["nif"] for c in b.companies} == {"B1", "B2"}
    assert sorted(w["lot_key"] for w in b.won) == ["200:1", "200:2"]

def test_no_nif_award_skipped():
    rec = _rec(lot_results=[LotResult(lot_id="0", winner_name="Anon", winner_nif=None, amount=5.0)])
    b = record_to_graph_ops(rec)
    assert b.companies == []
    assert b.won == []
    # contract with no graphable winner is not emitted either
    assert b.contracts == []

def test_lot_bid_stats_on_lot_dict():
    rec = _rec(lot_results=[LotResult(lot_id="0", winner_name="A", winner_nif="B1",
                                      n_bids=3, n_sme_bids=1,
                                      lower_tender_amount=9.0, higher_tender_amount=11.0)])
    b = record_to_graph_ops(rec)
    lot = b.lots[0]
    assert lot["n_bids"] == 3 and lot["n_sme_bids"] == 1
    assert lot["lower_tender_amount"] == 9.0 and lot["higher_tender_amount"] == 11.0

def test_ute_company_flagged():
    rec = _rec(lot_results=[LotResult(lot_id="0", winner_name="UTE X", winner_nif="U99999999", amount=1.0)])
    b = record_to_graph_ops(rec)
    assert b.companies == [{"nif": "U99999999", "is_ute": True}]

def test_merge_batches_concatenates():
    r1 = record_to_graph_ops(_rec(syndication_id="1",
            lot_results=[LotResult(lot_id="0", winner_nif="B1", winner_name="A", amount=1.0)]))
    r2 = record_to_graph_ops(_rec(syndication_id="2",
            lot_results=[LotResult(lot_id="0", winner_nif="B2", winner_name="C", amount=2.0)]))
    m = merge_batches([r1, r2])
    assert len(m.won) == 2
    assert {c["nif"] for c in m.companies} == {"B1", "B2"}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `PYTHONPATH=src pytest tests/test_graph_ops.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'placsp.graph_ops'`.

- [ ] **Step 3: Implement `graph_ops.py`**

Create `src/placsp/graph_ops.py`:

```python
from __future__ import annotations
import re
from dataclasses import dataclass, field
from typing import Optional
from .models import ProcurementRecord

_LEGAL_SUFFIXES = {
    "SL", "SLU", "SLL", "SA", "SAU", "SCA", "SC", "SLP", "SLNE",
    "SCOOP", "COOP", "SRL", "SAL", "AIE", "UTE",
}

def normalize_nif(s: Optional[str]) -> Optional[str]:
    if not s:
        return None
    out = re.sub(r"[\s.\-]", "", s).upper()
    return out or None

def normalize_name(s: Optional[str]) -> str:
    if not s:
        return ""
    tokens = re.sub(r"[^0-9A-Za-zÁÉÍÓÚÜÑáéíóúüñ]+", " ", s).upper().split()
    kept = [t for t in tokens if t not in _LEGAL_SUFFIXES]
    return " ".join(kept or tokens).strip()

def is_ute_winner(name: Optional[str], nif: Optional[str]) -> bool:
    n = normalize_nif(nif)
    if n and n.startswith("U"):
        return True
    return bool(name and name.strip().upper().startswith("UTE"))

@dataclass
class GraphBatch:
    companies: list[dict] = field(default_factory=list)
    contracts: list[dict] = field(default_factory=list)
    lots: list[dict] = field(default_factory=list)
    won: list[dict] = field(default_factory=list)
    authorities: list[dict] = field(default_factory=list)
    tendered: list[dict] = field(default_factory=list)
    classified: list[dict] = field(default_factory=list)
    located: list[dict] = field(default_factory=list)
    affected_nifs: list[str] = field(default_factory=list)

def record_to_graph_ops(rec: ProcurementRecord) -> GraphBatch:
    b = GraphBatch()
    winners = [lr for lr in rec.lot_results if normalize_nif(lr.winner_nif)]
    if not winners:
        return b  # awarded-only: no graphable winner → emit nothing

    sid = rec.syndication_id
    b.contracts.append({
        "syndication_id": sid,
        "props": {
            "expediente": rec.expediente, "title": rec.title,
            "status_code": rec.status_code, "result_code": rec.result_code,
            "contract_type_code": rec.contract_type_code,
            "procedure_code": rec.procedure_code,
            "budget_amount": rec.budget_amount, "estimated_value": rec.estimated_value,
            "award_date": rec.award_date, "publication_date": rec.publication_date,
            "category": rec.category,
        },
    })
    if rec.contracting_authority_id:
        b.authorities.append({"id": rec.contracting_authority_id,
                              "name": rec.contracting_authority,
                              "org_top_level": rec.org_top_level})
        b.tendered.append({"authority_id": rec.contracting_authority_id, "syndication_id": sid})
    if rec.nuts:
        b.located.append({"syndication_id": sid, "nuts": rec.nuts})

    seen_nifs = set()
    for lr in winners:
        nif = normalize_nif(lr.winner_nif)
        lot_key = f"{sid}:{lr.lot_id}"
        if nif not in seen_nifs:
            b.companies.append({"nif": nif, "is_ute": is_ute_winner(lr.winner_name, lr.winner_nif)})
            b.affected_nifs.append(nif)
            seen_nifs.add(nif)
        b.lots.append({
            "lot_key": lot_key, "syndication_id": sid,
            "props": {
                "name": lr.name, "amount": lr.amount, "award_date": lr.award_date,
                "sme_awarded": lr.sme_awarded, "n_bids": lr.n_bids, "n_sme_bids": lr.n_sme_bids,
                "lower_tender_amount": lr.lower_tender_amount,
                "higher_tender_amount": lr.higher_tender_amount,
            },
        })
        b.won.append({"nif": nif, "lot_key": lot_key, "amount": lr.amount,
                      "award_date": lr.award_date,
                      "name_norm": normalize_name(lr.winner_name),
                      "name_display": lr.winner_name})
        for code in lr.cpv:
            if code:
                b.classified.append({"lot_key": lot_key, "cpv": code})
    return b

def merge_batches(batches: list[GraphBatch]) -> GraphBatch:
    out = GraphBatch()
    for b in batches:
        out.companies += b.companies
        out.contracts += b.contracts
        out.lots += b.lots
        out.won += b.won
        out.authorities += b.authorities
        out.tendered += b.tendered
        out.classified += b.classified
        out.located += b.located
        out.affected_nifs += b.affected_nifs
    return out
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `PYTHONPATH=src pytest tests/test_graph_ops.py -v`
Expected: PASS (all 9 tests).

- [ ] **Step 5: Commit**

```bash
git add src/placsp/graph_ops.py tests/test_graph_ops.py
git commit -m "feat: pure record_to_graph_ops projection into GraphBatch"
```

---

## Task 3: `GraphSink` (Neo4j writes + constraints + tombstones)

**Files:**
- Modify: `pyproject.toml:5`
- Create: `src/placsp/graph_sink.py`
- Test: `tests/test_graph_sink_integration.py`

**Interfaces:**
- Consumes: `record_to_graph_ops`, `merge_batches`, `GraphBatch` (Task 2); `ProcurementRecord` (Task 1); `Tombstone` (existing, has `.syndication_id`).
- Produces: `GraphSink(uri, user, password)` with methods `ensure_constraints() -> None`, `upsert(records: list[ProcurementRecord]) -> int` (returns number of `WON` edges written), `apply_tombstones(tombs: list[Tombstone]) -> int`, `close() -> None`.

- [ ] **Step 1: Add the driver dependency**

In `pyproject.toml`, change line 5 to:

```toml
dependencies = ["lxml>=5", "httpx>=0.27", "structlog>=24", "neo4j>=5"]
```

Run: `pip install -e .` (or `pip install 'neo4j>=5'`).
Expected: `neo4j` installed; `python -c "import neo4j"` exits 0.

- [ ] **Step 2: Write the failing integration test**

Create `tests/test_graph_sink_integration.py`. These tests require a live Neo4j; they self-skip when `NEO4J_TEST_URL` is unset.

```python
import os
import pytest
from placsp.models import ProcurementRecord, LotResult, Tombstone
from placsp.graph_sink import GraphSink

URI = os.getenv("NEO4J_TEST_URL")
USER = os.getenv("NEO4J_TEST_USER", "neo4j")
PWD = os.getenv("NEO4J_TEST_PASSWORD", "testpassword")

pytestmark = pytest.mark.skipif(not URI, reason="NEO4J_TEST_URL not set")

def _rec(sid, lot_results, **kw):
    base = dict(syndication_id=sid, category="placsp_mayores", updated="2025-01-01",
                title="T", contracting_authority="Auth", contracting_authority_id="L1",
                nuts="ES61", lot_results=lot_results)
    base.update(kw)
    return ProcurementRecord(**base)

@pytest.fixture
def sink():
    s = GraphSink(URI, USER, PWD)
    s.ensure_constraints()
    with s._driver.session() as ses:
        ses.run("MATCH (n) DETACH DELETE n")
    yield s
    s.close()

def _count(sink, cypher):
    with sink._driver.session() as ses:
        return ses.run(cypher).single()[0]

def test_upsert_creates_nodes_and_is_idempotent(sink):
    rec = _rec("100", [LotResult(lot_id="1", winner_name="Acme SL", winner_nif="B1",
                                 amount=10.0, cpv=["45110000"])])
    sink.upsert([rec])
    sink.upsert([rec])  # second run must not duplicate
    assert _count(sink, "MATCH (c:Company) RETURN count(c)") == 1
    assert _count(sink, "MATCH (:Company)-[w:WON]->(:Lot) RETURN count(w)") == 1
    assert _count(sink, "MATCH (:Contract)-[h:HAS_LOT]->(:Lot) RETURN count(h)") == 1
    assert _count(sink, "MATCH (:Lot)-[r:CLASSIFIED_AS]->(:Cpv) RETURN count(r)") == 1

def test_canonical_name_is_most_frequent(sink):
    # Same NIF wins two lots as "Acme SL" and one as "ACME, S.L." → display of the
    # most frequent NORMALIZED form wins.
    sink.upsert([_rec("1", [LotResult(lot_id="0", winner_name="Acme SL", winner_nif="B9", amount=1.0)])])
    sink.upsert([_rec("2", [LotResult(lot_id="0", winner_name="Acme SL", winner_nif="B9", amount=1.0)])])
    sink.upsert([_rec("3", [LotResult(lot_id="0", winner_name="OTHERNAME SA", winner_nif="B9", amount=1.0)])])
    name = _count(sink, "MATCH (c:Company {nif:'B9'}) RETURN c.canonical_name")
    assert name == "Acme SL"

def test_tombstone_deletes_contract_and_lots_keeps_company(sink):
    sink.upsert([_rec("500", [LotResult(lot_id="1", winner_name="Acme", winner_nif="B1", amount=5.0)])])
    sink.apply_tombstones([Tombstone(syndication_id="500", when=None, reason="CERRADA",
                                     category="placsp_mayores")])
    assert _count(sink, "MATCH (c:Contract {syndication_id:'500'}) RETURN count(c)") == 0
    assert _count(sink, "MATCH (l:Lot {lot_key:'500:1'}) RETURN count(l)") == 0
    assert _count(sink, "MATCH (c:Company {nif:'B1'}) RETURN count(c)") == 1
```

- [ ] **Step 3: Run the test to verify it fails**

Run: `PYTHONPATH=src pytest tests/test_graph_sink_integration.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'placsp.graph_sink'` (or SKIP if `NEO4J_TEST_URL` is unset — in that case start a throwaway Neo4j first, see Step 6).

- [ ] **Step 4: Implement `graph_sink.py`**

Create `src/placsp/graph_sink.py`:

```python
import structlog
from neo4j import GraphDatabase
from .models import ProcurementRecord, Tombstone
from .graph_ops import record_to_graph_ops, merge_batches, GraphBatch

log = structlog.get_logger(service="placsp")

_CONSTRAINTS = [
    "CREATE CONSTRAINT company_nif IF NOT EXISTS FOR (c:Company) REQUIRE c.nif IS UNIQUE",
    "CREATE CONSTRAINT contract_sid IF NOT EXISTS FOR (c:Contract) REQUIRE c.syndication_id IS UNIQUE",
    "CREATE CONSTRAINT lot_key IF NOT EXISTS FOR (l:Lot) REQUIRE l.lot_key IS UNIQUE",
    "CREATE CONSTRAINT authority_id IF NOT EXISTS FOR (a:Authority) REQUIRE a.id IS UNIQUE",
    "CREATE CONSTRAINT cpv_code IF NOT EXISTS FOR (c:Cpv) REQUIRE c.code IS UNIQUE",
    "CREATE CONSTRAINT nuts_code IF NOT EXISTS FOR (n:Nuts) REQUIRE n.code IS UNIQUE",
]

_WRITE = [
    ("UNWIND $companies AS c MERGE (co:Company {nif:c.nif}) "
     "ON CREATE SET co.is_ute=c.is_ute ON MATCH SET co.is_ute = co.is_ute OR c.is_ute", "companies"),
    ("UNWIND $contracts AS k MERGE (ct:Contract {syndication_id:k.syndication_id}) SET ct += k.props",
     "contracts"),
    ("UNWIND $lots AS l MERGE (lo:Lot {lot_key:l.lot_key}) SET lo += l.props "
     "WITH l, lo MATCH (ct:Contract {syndication_id:l.syndication_id}) MERGE (ct)-[:HAS_LOT]->(lo)",
     "lots"),
    ("UNWIND $won AS w MATCH (co:Company {nif:w.nif}), (lo:Lot {lot_key:w.lot_key}) "
     "MERGE (co)-[r:WON]->(lo) "
     "SET r.amount=w.amount, r.award_date=w.award_date, r.name_norm=w.name_norm, r.name_display=w.name_display",
     "won"),
    ("UNWIND $authorities AS a MERGE (au:Authority {id:a.id}) SET au.name=a.name, au.org_top_level=a.org_top_level",
     "authorities"),
    ("UNWIND $tendered AS t MATCH (au:Authority {id:t.authority_id}), (ct:Contract {syndication_id:t.syndication_id}) "
     "MERGE (au)-[:TENDERED]->(ct)", "tendered"),
    ("UNWIND $classified AS x MERGE (cp:Cpv {code:x.cpv}) "
     "WITH x, cp MATCH (lo:Lot {lot_key:x.lot_key}) MERGE (lo)-[:CLASSIFIED_AS]->(cp)", "classified"),
    ("UNWIND $located AS n MERGE (nu:Nuts {code:n.nuts}) "
     "WITH n, nu MATCH (ct:Contract {syndication_id:n.syndication_id}) MERGE (ct)-[:LOCATED_IN]->(nu)", "located"),
    ("UNWIND $affected_nifs AS nif MATCH (co:Company {nif:nif})-[r:WON]->(:Lot) "
     "WITH co, r.name_norm AS norm, collect(r.name_display)[0] AS disp, count(*) AS n "
     "ORDER BY n DESC, norm WITH co, collect(disp)[0] AS top SET co.canonical_name = top", "affected_nifs"),
]

class GraphSink:
    def __init__(self, uri, user, password):
        self._driver = GraphDatabase.driver(uri, auth=(user, password))

    def close(self):
        self._driver.close()

    def ensure_constraints(self):
        with self._driver.session() as s:
            for stmt in _CONSTRAINTS:
                s.run(stmt)

    @staticmethod
    def _apply(tx, batch: GraphBatch):
        params = {
            "companies": batch.companies, "contracts": batch.contracts, "lots": batch.lots,
            "won": batch.won, "authorities": batch.authorities, "tendered": batch.tendered,
            "classified": batch.classified, "located": batch.located,
            "affected_nifs": list(dict.fromkeys(batch.affected_nifs)),
        }
        for cypher, key in _WRITE:
            if params.get(key):
                tx.run(cypher, **params)

    def upsert(self, records: list[ProcurementRecord]) -> int:
        batch = merge_batches([record_to_graph_ops(r) for r in records])
        if not batch.won:
            return 0
        with self._driver.session() as s:
            s.execute_write(self._apply, batch)
        log.info("graph_upserted", companies=len(batch.companies), won=len(batch.won))
        return len(batch.won)

    def apply_tombstones(self, tombs: list[Tombstone]) -> int:
        if not tombs:
            return 0
        sids = [t.syndication_id for t in tombs]
        with self._driver.session() as s:
            s.run("UNWIND $sids AS sid MATCH (ct:Contract {syndication_id:sid}) "
                  "OPTIONAL MATCH (ct)-[:HAS_LOT]->(lo:Lot) DETACH DELETE lo, ct", sids=sids)
        return len(tombs)
```

Note: in the `affected_nifs` Cypher, the canonical name is the display of the most frequent normalized name — the inner aggregation groups `WON` edges by `name_norm`, picks each group's first display, then the outermost takes the highest-count group.

- [ ] **Step 5: Start a throwaway Neo4j for the test**

```bash
docker run -d --name placsp-neo4j-test -p 7688:7687 \
  -e NEO4J_AUTH=neo4j/testpassword \
  -e NEO4J_PLUGINS='["graph-data-science"]' neo4j:5
# wait ~15s for startup
```

- [ ] **Step 6: Run the integration tests to verify they pass**

Run:
```bash
NEO4J_TEST_URL=bolt://localhost:7688 NEO4J_TEST_PASSWORD=testpassword \
  PYTHONPATH=src pytest tests/test_graph_sink_integration.py -v
```
Expected: PASS (3 tests). Tear down with `docker rm -f placsp-neo4j-test` when done.

- [ ] **Step 7: Commit**

```bash
git add pyproject.toml src/placsp/graph_sink.py tests/test_graph_sink_integration.py
git commit -m "feat: GraphSink writes GraphBatch to Neo4j with idempotent MERGE + tombstones"
```

---

## Task 4: Config, pipeline wiring, and `init-graph` CLI

**Files:**
- Modify: `src/placsp/config.py`
- Modify: `src/placsp/pipeline.py:35-77`
- Modify: `src/placsp/__main__.py`
- Test: `tests/test_pipeline_graph.py`

**Interfaces:**
- Consumes: `GraphSink` (Task 3); existing `Pipeline`, `Config`, `Upserter`, `Embedder`, `Codelists`.
- Produces: `Pipeline(cfg, embedder, upserter, codelists, graph_sink=None)`; `Config.neo4j_url/neo4j_user/neo4j_password`; CLI command `init-graph`.

- [ ] **Step 1: Write the failing pipeline test**

Create `tests/test_pipeline_graph.py`:

```python
from placsp.pipeline import Pipeline

class _StubUpserter:
    def upsert(self, recs, vectors): return len(recs)
    def apply_tombstones(self, tombs): return len(tombs)
    def get_stored(self, sid): return None

class _StubEmbedder:
    def embed(self, texts): return [[0.0] for _ in texts]

class _StubGraphSink:
    def __init__(self): self.upserted = None; self.tombs = None
    def upsert(self, recs): self.upserted = recs; return len(recs)
    def apply_tombstones(self, tombs): self.tombs = tombs; return len(tombs)

class _Cfg:
    weaviate_class = "X"; weaviate_url = ""; weaviate_api_key = ""
    offpeak_start = 22; offpeak_end = 7

def test_process_files_calls_graph_sink(tmp_path, monkeypatch):
    gs = _StubGraphSink()
    p = Pipeline(_Cfg(), _StubEmbedder(), _StubUpserter(), codelists=None, graph_sink=gs)
    # Drive process_files with a single real fixture file
    out = p.process_files(["tests/fixtures/menores.atom"], "placsp_menores")
    assert gs.upserted is not None  # graph_sink.upsert was called
    assert out["upserted"] >= 0

def test_graph_sink_optional_defaults_none():
    p = Pipeline(_Cfg(), _StubEmbedder(), _StubUpserter(), codelists=None)
    assert p.graph_sink is None
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `PYTHONPATH=src pytest tests/test_pipeline_graph.py -v`
Expected: FAIL — `TypeError: __init__() got an unexpected keyword argument 'graph_sink'`.

- [ ] **Step 3: Add `graph_sink` to `Pipeline`**

In `src/placsp/pipeline.py`, update `__init__` (lines 36-40):

```python
    def __init__(self, cfg, embedder, upserter, codelists, graph_sink=None):
        self.cfg = cfg
        self.embedder = embedder
        self.upserter = upserter
        self.codelists = codelists
        self.graph_sink = graph_sink
```

In `process_files`, after the line `upserted = self.upserter.upsert(...)` and the `deleted = ...` line (around lines 74-75), add the graph calls (non-blocking):

```python
        if self.graph_sink is not None:
            try:
                self.graph_sink.upsert(recs)
                self.graph_sink.apply_tombstones(tombs)
            except Exception as exc:
                log.error("graph_sink_failed", category=category, error=str(exc))
```

- [ ] **Step 4: Run the pipeline test to verify it passes**

Run: `PYTHONPATH=src pytest tests/test_pipeline_graph.py -v`
Expected: PASS (2 tests).

- [ ] **Step 5: Add Neo4j config fields**

In `src/placsp/config.py`, add to the `Config` dataclass (after line 18):

```python
    neo4j_url: str
    neo4j_user: str
    neo4j_password: str
```

And to `load_config()` (inside the `Config(...)` call):

```python
        neo4j_url=_env("NEO4J_URL", ""),
        neo4j_user=_env("NEO4J_USER", "neo4j"),
        neo4j_password=_env("NEO4J_PASSWORD", ""),
```

- [ ] **Step 6: Wire `GraphSink` into the CLI**

In `src/placsp/__main__.py`, add the import and update `_pipeline` + `main`:

```python
from .graph_sink import GraphSink
```

Replace `_pipeline` (lines 9-13):

```python
def _graph_sink(cfg):
    if not cfg.neo4j_url:
        return None
    return GraphSink(cfg.neo4j_url, cfg.neo4j_user, cfg.neo4j_password)

def _pipeline(cfg):
    return Pipeline(cfg,
                    Embedder(cfg.vectorizer_url, cfg.embed_batch_size, cfg.request_timeout),
                    Upserter(cfg.weaviate_url, cfg.weaviate_api_key, cfg.weaviate_class, cfg.request_timeout),
                    Codelists(cfg.codelist_dir),
                    graph_sink=_graph_sink(cfg))
```

In `main`, register the command in the loop (line 18):

```python
    for name in ("init-schema", "init-graph", "backfill", "daily", "reconcile"):
        sub.add_parser(name)
```

And handle it after the `init-schema` block (after line 25):

```python
    if args.cmd == "init-graph":
        gs = _graph_sink(cfg)
        if gs is None:
            print("neo4j not configured"); return
        gs.ensure_constraints(); gs.close()
        print("constraints ensured")
        return
```

- [ ] **Step 7: Verify the CLI parses and the suite is green**

Run: `PYTHONPATH=src python -m placsp init-graph` (with `NEO4J_URL` unset)
Expected: prints `neo4j not configured`, exits 0.

Run: `PYTHONPATH=src pytest -q`
Expected: PASS (whole suite; integration tests SKIP without `NEO4J_TEST_URL`).

- [ ] **Step 8: Commit**

```bash
git add src/placsp/config.py src/placsp/pipeline.py src/placsp/__main__.py tests/test_pipeline_graph.py
git commit -m "feat: wire optional GraphSink into pipeline + init-graph CLI"
```

---

## Task 5: Docker Compose — Neo4j + init-graph services

**Files:**
- Modify: `docker-compose.yml`

**Interfaces:**
- Consumes: `init-graph` CLI (Task 4); the existing `placsp-ingester` image build.

- [ ] **Step 1: Add the Neo4j service**

In `docker-compose.yml`, add under `services:` (after the `placsp-weaviate` block):

```yaml
  # ── Neo4j (company graph) ─────────────────────────────────────────────────
  placsp-neo4j:
    image: neo4j:5
    container_name: placsp-neo4j
    restart: unless-stopped
    ports:
      - "127.0.0.1:${NEO4J_HTTP_PORT:-7474}:7474"
      - "127.0.0.1:${NEO4J_BOLT_PORT:-7687}:7687"
    environment:
      NEO4J_AUTH: "neo4j/${NEO4J_PASSWORD}"
      NEO4J_PLUGINS: '["graph-data-science"]'
      NEO4J_server_memory_heap_max__size: "${NEO4J_HEAP:-2G}"
    volumes:
      - placsp_neo4j_data:/data
```

- [ ] **Step 2: Add the one-shot init-graph service**

Add after `placsp-init-schema`:

```yaml
  # ── Graph init (one-shot, idempotent) ─────────────────────────────────────
  placsp-init-graph:
    image: placsp-ingester
    container_name: placsp-init-graph
    environment:
      NEO4J_URL: "bolt://placsp-neo4j:7687"
      NEO4J_USER: "neo4j"
      NEO4J_PASSWORD: "${NEO4J_PASSWORD}"
    command:
      - sh
      - -c
      - |
        echo 'waiting for neo4j bolt...'
        until python -c "from neo4j import GraphDatabase; GraphDatabase.driver('bolt://placsp-neo4j:7687', auth=('neo4j','${NEO4J_PASSWORD}')).verify_connectivity()" 2>/dev/null; do
          sleep 2
        done
        echo 'neo4j ready; creating constraints'
        python -m placsp init-graph
    depends_on:
      placsp-neo4j:
        condition: service_started
      placsp-init-schema:
        condition: service_completed_successfully
    restart: "no"
```

- [ ] **Step 3: Add the named volume and wire the search-api env (optional consumers)**

In the `volumes:` block at the bottom, add:

```yaml
  placsp_neo4j_data:
    name: placsp_neo4j_data
```

- [ ] **Step 4: Validate compose config**

Run: `NEO4J_PASSWORD=devpassword WEAVIATE_API_KEY=x docker compose config >/dev/null && echo OK`
Expected: prints `OK` (compose file parses with the new services and volume).

- [ ] **Step 5: End-to-end smoke (manual)**

```bash
echo "NEO4J_PASSWORD=devpassword" >> .env   # if not already set
docker compose up -d placsp-neo4j placsp-init-graph
docker logs placsp-init-graph        # expect "constraints ensured"
```
Then run the validation milestone: point the ingester at one `placsp_mayores` year with `NEO4J_URL=bolt://placsp-neo4j:7687` set, run `backfill` for that unit, and in Neo4j Browser (`http://localhost:7474`) confirm:
- `MATCH (c:Company) RETURN count(c)` > 0
- `MATCH (:Company)-[w:WON]->(:Lot) RETURN count(w)` > 0
- spot-check one multi-lot contract: `MATCH (ct:Contract)-[:HAS_LOT]->(l:Lot)<-[:WON]-(co:Company) RETURN ct.syndication_id, l.lot_key, co.canonical_name LIMIT 20`

- [ ] **Step 6: Commit**

```bash
git add docker-compose.yml
git commit -m "feat: add Neo4j + init-graph services to docker-compose"
```

---

## Self-Review notes (spec coverage)

- Spec §3 model → Tasks 2/3 (nodes/edges); `Name`/`HAS_NAME` deliberately replaced by `WON.name_*` + derived `canonical_name` (resolves §9; documented above).
- Spec §4 identity (normalized NIF, aliases, canonical, UTE flag) → Task 2 helpers + Task 3 canonical recompute; `MEMBER_OF` deferred (data not present — documented).
- Spec §3 bid statistics on Lot → Tasks 1/2/3.
- Spec §5 per-lot extraction (verified XPath) → Task 1.
- Spec §6 sink wiring + idempotency + tombstones → Tasks 3/4.
- Spec §7 infra (`placsp-neo4j`, GDS, `init-graph`, constraints) → Tasks 3/5.
- Spec §8 testing (pure unit + live integration) → Tasks 1/2 (unit), 3 (integration), 4 (wiring).
- Spec §10 validation milestone → Task 5 Step 5.
