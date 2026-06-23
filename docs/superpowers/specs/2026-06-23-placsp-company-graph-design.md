# PLACSP Company Graph (SP1) — Design Spec

**Date:** 2026-06-23
**Status:** Approved design, pending spec review

## 1. Goal

Curate a database of companies that win Spanish public contracts, as a **Neo4j
graph** built from the data already flowing through the PLACSP ingestion pipeline.
Each awarded **lot** is linked to the **company** (identified by NIF) that won it,
plus the contract, contracting authority, CPV sector, and location. This graph is
the structural foundation for later GraphRAG-style work.

This is **sub-project #1 (SP1)** of a larger plan. It deliberately builds only the
graph skeleton. It does **not** implement enrichment or summaries.

### Sub-project decomposition (context)

| Sub-project | Delivers | Depends on |
|---|---|---|
| **SP1 (this spec)** | Neo4j graph: lots + awarded companies (NIF identity, UTE modelling), contracts, authorities, CPV, geography. Feed-derived, deterministic. | — |
| **SP2 — Enrichment** | Pluggable enrichers (VIES → BORME/libreBORME → GLEIF → OpenCorporates) attaching attributes + **generating company descriptions/text** for summaries. | SP1 |
| **SP3 — GraphRAG communities** | Leiden/Louvain community detection (Neo4j GDS) + LLM community summaries. | SP1 (SP2 enriches) |
| *(later)* SP4 | Wire community summaries into the chatbot. | SP3 |

**Data-source finding (informs SP2, recorded here):** there is **no complete, free,
downloadable, NIF-keyed Spanish company directory.** The authoritative Registro
Mercantil is gated (paywalled per-query; bulk access restricted to notaries/lawyers/
banks). Genuinely free bulk sources are partial: **BORME** via the BOE open-data API
(free, structured, but name-keyed event data, no reliable NIF), and **GLEIF LEI**
golden-copy files (free, downloadable, unlimited, carry the NIF — but cover mostly
larger/LEI-holding entities). Therefore the **PLACSP feeds themselves are the primary
company directory** (the population we care about = firms that win public money), and
external sources are *opportunistic enrichment* in SP2.

## 2. Scope

**In scope (SP1)**

- A `placsp-neo4j` graph store added to the stack.
- Extend `codice_extractor` to emit a **winner per lot** (name + NIF + amount), not a
  single record-level winner.
- A `graph_sink` (`GraphSink`) that runs inside the existing pipeline alongside the
  Weaviate `Upserter`, populating the graph on backfill / daily / reconcile.
- Company identity by **normalized NIF**, with name **aliases** (counts) and an
  elected `canonical_name`; **UTE** modelling via `MEMBER_OF`.
- Tombstone handling (delete contract + its lots, never the company).
- `init-graph` CLI command creating uniqueness constraints.
- TDD: pure-logic unit tests + live-Neo4j integration tests.

**Out of scope (deferred)**

- Any external enrichment / company descriptions / `profile_text` (→ SP2).
- Community detection and LLM summaries (→ SP3).
- Materialized company aggregates (computed on-demand via Cypher).
- Authority hierarchy as edges (`org_top_level` stays a flat property).
- Non-awarded tenders (only awarded records enter the graph).

## 3. Graph model

```
(:Contract {syndication_id, expediente, title, status_code, result_code,
            contract_type_code, procedure_code, budget_amount, estimated_value,
            award_date, publication_date, category})
(:Lot {lot_key, name, amount, award_date, sme_awarded,
       n_bids, n_sme_bids, lower_tender_amount, higher_tender_amount})   // lot_key = "{syndication_id}:{lot_id}"
(:Company {nif, canonical_name, is_ute})
(:Name {raw})
(:Authority {id, name, org_top_level})
(:Cpv {code})
(:Nuts {code})

(:Contract) -[:HAS_LOT]->                  (:Lot)
(:Company)  -[:WON {amount, award_date}]-> (:Lot)
(:Company)  -[:MEMBER_OF]->                (:Company)   // member → UTE
(:Company)  -[:HAS_NAME {count, last_seen}]-> (:Name)
(:Lot)      -[:CLASSIFIED_AS]->            (:Cpv)
(:Authority)-[:TENDERED]->                 (:Contract)
(:Contract) -[:LOCATED_IN]->               (:Nuts)
```

### Design notes

- **Awarded-only.** Only records carrying at least one lot winner (NIF present) enter
  the graph. A record with no parseable winner NIF is skipped from the graph and
  logged (it still lands in Weaviate via the existing path).
- **Lot is the award unit.** A non-divided contract is modelled as **one implicit
  lot** (`lot_id = "0"`). A divided contract gets one `Lot` per lot, each with its own
  `WON` edge (possibly to different companies) and its own `CLASSIFIED_AS` CPV.
- **CPV / NUTS are code-only.** Labels stay in the client-side codelist JSON already
  built for the search UI — single source of truth, no label duplication in the graph.
- **No materialized company aggregates.** "Top winners", totals, and date spans are
  derived on demand via Cypher (`MATCH (c:Company)-[:WON]->(:Lot) …`), keeping
  upserts simple and idempotent.
- **Bid statistics, not bidder rosters.** PLACSP names only the **winner** of each
  lot. It does publish per-result bid *statistics* — `ReceivedTenderQuantity`
  (`n_bids`), `SMEsReceivedTenderQuantity` (`n_sme_bids`), and the offer range
  `LowerTenderAmount`/`HigherTenderAmount` — which are stored on the `Lot` node
  (competitiveness / price-spread signal). It does **not** publish the identities of
  losing bidders (the `cac:Tenderer…` elements are `TendererQualificationRequest`
  qualification criteria, not a roster). Therefore a competitive
  `(:Company)-[:BID_ON]->(:Lot)` graph is **not buildable from these feeds** — only
  the `WON` edge exists. A full bidder roster would require a paid/richer data source
  and is out of scope (noted for a future SP).

## 4. Company identity & resolution

- **Identity key = normalized NIF** (uppercase, strip spaces/dots/hyphens).
  `MERGE (:Company {nif})` → idempotent.
- **Names are never identity.** Each distinct winner name string seen for a NIF is
  recorded as `(:Company)-[:HAS_NAME {count, last_seen}]->(:Name {raw})`, incrementing
  `count`. `canonical_name` on the Company is materialized as the **highest-count**
  name (tie-break: most recent `last_seen`).
- **Name normalization** (strip legal suffixes `S.L./S.A./S.L.U./S.C.…`, collapse
  punctuation/whitespace) is used **only** to group alias variants for counting, never
  to key identity — so it cannot cause false company merges.
- **UTE (temporary joint venture):** when the winner is a UTE (own NIF, or `is_ute`
  heuristic on the name, e.g. leading `UTE`), it is a `Company {is_ute:true}`. Member
  companies link via `(:Company)-[:MEMBER_OF]->(:Company{is_ute})` **when their member
  NIFs are parseable** from the source; otherwise the UTE node stands alone.

## 5. Extractor change — winner per lot

Today `codice_extractor.extract()` reads a single record-level winner from
`cac:TenderResult/cac:WinningParty/...`. PLACSP CODICE expresses per-lot results as
**multiple `cac:TenderResult` blocks**, each tied to its lot via
`cac:AwardedTenderedProject/cbc:ProcurementProjectLotID` (**verified against the
`mayores` fixture** — 4 `TenderResult`s, each with a `ProcurementProjectLotID` and its
own `WinningParty`).

- Extend the extractor to emit a list of per-lot results, each carrying:
  `lot_id` (← `AwardedTenderedProject/ProcurementProjectLotID`), winner `name`
  (`WinningParty/PartyName/Name`), winner `nif` (`WinningParty/PartyIdentification/ID`),
  awarded `amount` (`AwardedTenderedProject/LegalMonetaryTotal/TaxExclusiveAmount`),
  `award_date`, `sme_awarded`, and the bid stats `n_bids`
  (`ReceivedTenderQuantity`), `n_sme_bids` (`SMEsReceivedTenderQuantity`),
  `lower_tender_amount`/`higher_tender_amount`.
- The existing `Lot` dataclass (`lot_id, name, amount, cpv`) gains winner + bid-stat
  fields (or a parallel `LotResult`); the record-level
  `adjudicatario`/`adjudicatario_nif`/`n_bids` remain for the Weaviate summary and are
  sourced from the first/only lot result for backwards compatibility.
- **Single-state / no-lot sources** (e.g. menores) yield exactly one implicit lot
  (`lot_id="0"`) carrying the record-level winner. (Verified: `menores`/`propios`
  fixtures carry `TenderResult` + `WinningParty` with no `ProcurementProjectLot`.)
- **Plan-time check:** confirm `externos` multi-lot shape (the fixture had no
  `TenderResult`); capture a fresh multi-lot `externos` sample if needed.

## 6. Build, sync & idempotency

- **New module** `src/placsp/graph_sink.py`:
  - Pure function `record_to_graph_ops(rec) -> list[GraphOp]` turning a
    `ProcurementRecord` (with per-lot winners) into MERGE/SET operations. This is the
    **unit-test seam** — no DB required (mirrors `build_where` in the search work).
  - `GraphSink` class (Neo4j Python driver / Bolt) executing those ops in a write
    transaction; `upsert(records)` and `apply_tombstones(tombs)`.
- **Pipeline wiring:** `Pipeline.__init__` gains an optional `graph_sink`;
  `process_files` calls `graph_sink.upsert(recs)` after the Weaviate upsert and
  `graph_sink.apply_tombstones(tombs)`. When `graph_sink` is `None`, behaviour is
  unchanged (graph is additive, never blocks the existing path). Backfill / daily /
  reconcile populate the graph automatically — no separate scheduler.
- **Idempotency:** every write is `MERGE` on a key + `SET` properties (last-write-wins,
  same philosophy as the deterministic-UUID Weaviate upsert). Re-running a feed is safe.
  `HAS_NAME.count` uses `ON CREATE SET count = 1 / ON MATCH SET count = count + 1`; note
  re-processing the *same* record would double-count — guarded by only counting per
  distinct `(syndication_id, lot_id)` award contribution, or accepted as a known
  approximation (decided at plan time; see §9).
- **Tombstones:** `at:deleted-entry` → `MATCH (c:Contract {syndication_id})` then
  `DETACH DELETE` the contract and its lots (and their `WON`/`CLASSIFIED_AS`/`TENDERED`/
  `LOCATED_IN` edges). **Company, Authority, Cpv, Nuts nodes are never deleted** — a
  firm is not removed because one contract was withdrawn. Orphaned `Name` nodes are
  left as-is (harmless) or swept by `init-graph`/a maintenance query.

## 7. Infrastructure

- **`placsp-neo4j` service** in `docker-compose.yml`:
  - Neo4j 5.x with the **GDS (Graph Data Science) plugin enabled now**, so SP3's Leiden
    needs no infra change.
  - Bolt + HTTP ports bound to localhost; a named volume for persistence.
  - Auth via `NEO4J_AUTH`; credentials from env.
- **Config** (`src/placsp/config.py`): `NEO4J_URL` (bolt), `NEO4J_USER`,
  `NEO4J_PASSWORD`. `GraphSink` is constructed only when these are set.
- **`init-graph` CLI command** (mirrors `init-schema`): creates uniqueness constraints
  on `Company.nif`, `Contract.syndication_id`, `Lot.lot_key`, `Authority.id`,
  `Cpv.code`, `Nuts.code`, and an index on `Name.raw`. Idempotent.
- A one-shot `placsp-init-graph` compose service (like `placsp-init-schema`) waits for
  Neo4j readiness and runs `init-graph`.

## 8. Testing strategy (TDD)

- **Unit (no DB)** — `record_to_graph_ops`:
  - single-lot award → Company/Lot/Contract/WON/authority/cpv/nuts ops;
  - **multi-lot, multi-winner** contract → distinct `Lot`s and `WON` edges;
  - award with **no parseable winner NIF** → record skipped from graph, logged;
  - **UTE** with parseable member NIFs → `MEMBER_OF` ops; UTE without → standalone;
  - multi-CPV lot; missing NUTS / missing amount;
  - NIF normalization; canonical-name election from competing aliases with counts.
- **Integration (live Neo4j** — compose service or testcontainer):
  - MERGE idempotency: ingest a fixture twice → identical node/edge counts;
  - tombstone `DETACH DELETE` removes contract + lots, leaves Company intact;
  - `MEMBER_OF` wiring; `HAS_NAME` count + canonical election across versions.
- **Extractor tests** assert per-lot winner extraction against the (verified) multi-lot
  fixture and the single-implicit-lot path for menores.
- Reuse existing four-source ATOM fixtures; add a multi-lot fixture if absent.

## 9. Open decisions (to resolve at plan time)

- **`externos` multi-lot shape** — verify against a fresh sample (§5); the `mayores`
  lot↔`TenderResult` linkage is already confirmed.
- **`HAS_NAME` count semantics** — exact per-award increment vs. idempotent
  approximation on re-ingest (§6). Pick the simplest correct option once the upsert
  transaction shape is settled.
- **Neo4j driver batching** — per-record transaction vs. batched UNWIND for backfill
  throughput. Default to batched UNWIND; tune during validation.
- **UTE detection heuristic** — confirm how UTEs present across the four sources (own
  NIF vs. composite name) during fixture review.

## 10. Validation milestone

Mirror the ingestion project's "validate on one feed first": run the graph sink over a
single `placsp_mayores` year, then verify in Neo4j that lot/company/award counts and a
few hand-checked multi-lot, UTE, and repeat-winner cases are correct before enabling the
sink on the full backfill.
