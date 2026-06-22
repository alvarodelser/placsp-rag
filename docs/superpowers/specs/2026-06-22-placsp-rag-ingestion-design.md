# PLACSP RAG Ingestion — Design Spec

**Date:** 2026-06-22
**Status:** Approved design, pending spec review

## 1. Goal

Ingest Spanish public-procurement data from PLACSP syndication feeds into the
existing RAG vector store so it can be retrieved via the existing search stack.
The pipeline must:

- **Backfill** several years of historical data from the yearly aggregate ZIPs.
- **Stay current** with a daily update path.
- **Reuse** the already-deployed shared services: the **vectorizer** (`vectorizer:8089`,
  running **BGE-M3**) and **Weaviate** (`iarag-vectorstore:8086`, **v1.28.3**). The
  chunker is **not** used — BGE-M3 accepts up to 8192 tokens, far beyond any single
  procurement summary.

## 2. Source data

PLACSP publishes four syndication channels, each as yearly aggregate ZIPs and a
rolling "live" ATOM feed:

| category          | sindicacion | content                          |
|-------------------|-------------|----------------------------------|
| `placsp_mayores`  | 643         | major contracts (PLACSP)         |
| `externos_mayores`| 1044        | aggregated external platforms    |
| `placsp_menores`  | 1143        | minor contracts                  |
| `propios`         | 1383        | own public-sector platform       |

(Full URL list is the catalog ported from the existing `Procurement 1` data table,
years ~2012–2025; current year flagged `incremental`.)

Each yearly ZIP unzips into **many paginated `.atom` files** (a few hundred entries
each, ~2–5 MB). Each `.atom` file is an Atom `<feed>` of `<entry>` elements. Each entry
wraps a CODICE/UBL `ContractFolderStatus` block (`cac:`/`cbc:`/`pe:`/`peb:` namespaces),
and carries an `<id>`, an `<updated>` timestamp, and a `<summary>` (estado).

**Identity / dedup key (verified against real data):** the stable per-expediente key
is the **syndication entry `<id>` integer** (e.g. `…/licitacionesPerfilContratante/19862167`)
— it stays constant across lifecycle versions (verified: externos `19817649` PUB→EV) and
re-publishes. **`cbc:ContractFolderID` is NOT usable as a key** — it is org-local and
free-form (`1100`, `2025/SP03032003/00002230E`, …) and collides across bodies (verified
in propios). `ContractFolderID` is kept only as a display field. A single expediente
recurs as many entries across its lifecycle (PUB → EV → ADJ → RES …); the yearly ZIP for
a year contains every version active that year.

**Deletions via Atom tombstones (verified):** feeds publish
`<at:deleted-entry ref="…/<id>" when="…"><at:comment type="CERRADA"/></at:deleted-entry>`
for removed records. Externos churns heavily (140 tombstones in one live head); propios a
few; mayores/menores ~none in samples. These are **real deletions** and must remove the
object from the index.

**Cross-source field variance (verified — see §5):** the four channels expose different
CODICE subsets. Notably: **menores are single-state (`RES` only)**, always carry an
awarded amount, and lack budget lifecycle/procedure/lots; **propios lack CPV (only ~48%),
procedure, lots, estimated value**; **externos** carry estimated value + procedure + lots
+ heavy tombstones; **mayores** are the richest (full lifecycle, lots ~28%). Money appears
as **three distinct concepts** at source-specific paths: budget base, estimated value,
awarded amount.

## 3. Decisions

1. **Document model:** one RAG document per **expediente** (keyed by syndication id),
   **latest state wins**. (Menores are effectively single-state — `RES` only.)
2. **Tool:** a single **standalone Python** codebase owns all procurement logic
   (fetch → parse → extract → dedup → render → embed → upsert). **No n8n involvement
   at all.** Daily and monthly-reconciliation runs are launched by a **cron/systemd
   timer**; the historical backfill is launched manually as a one-off resumable run.
3. **State / dedup:** **Weaviate is the source of truth** — no separate ledger.
   Achieved via:
   - **Deterministic object UUID** = `uuid5(NAMESPACE, f"placsp:{syndication_id}")`,
     keyed on the entry `<id>` integer (NOT `ContractFolderID`), so re-upserting an
     expediente overwrites the prior object (last write wins).
   - **In-memory collapse per run:** all versions of a `syndication_id` seen in a run are
     reduced to the one with the max `updated`.
   - **Chronological order** in backfill (oldest year → newest).
   - **`updated` guard:** stored as a property; the daily path skips an incoming
     record whose `updated` is not newer than what Weaviate already holds.
   - **Tombstones = deletions:** `<at:deleted-entry ref="…/<id>">` removes the object
     `uuid5("placsp:<id>")` from the index (and reason is recorded). Processed by the
     daily and reconciliation paths.
4. **Vector store schema:** a dedicated, single **`Placsp_licitaciones`** hybrid class
   (vector + BM25), bring-your-own vectors (`vectorizer: none`). No separate full-text
   class — a procurement record ≈ one chunk, so the Synergyos chunk/full-text split is
   unnecessary. Single logical tenant; `category` is a filter property.
5. **Document text:** each expediente is rendered to a **templated Spanish NL summary**
   (objeto, órgano, importes, CPV decodificado, procedimiento, estado, fechas, lotes,
   adjudicatario) embedded as **one 1024-dim BGE-M3 vector**, no prefix (the vectorizer
   strips `query:` and BGE-M3 needs none). Structured fields are also stored as
   filterable properties and feed BM25. **No chunking** — the summary always fits
   BGE-M3's 8192-token window; a hard truncation safeguard covers any pathological case.
   **Coded values are decoded to Spanish labels** (TypeCode, ProcedureCode, StatusCode,
   ResultCode, NUTS, FundingProgram, …) via the CODICE `.gc` codelists so the summary and
   filters are human-readable, not raw codes.
6. **Status history:** keep a compact **`status_history`** array on the single doc
   (`[{code, date}]`, nested `object[]` — supported by Weaviate 1.28.3). Backfill builds
   it free from the year's ZIP in one pass; the daily path does one GET-by-UUID merge per
   changed expediente before upsert. (Trivial for menores — single state.)
7. **Daily updates (hybrid):**
   - **Daily:** once per day, off-peak, walk the live rolling ATOM feed (follow
     `<link rel="next">`) until all entries on a page are older than the per-category
     **watermark** = `max(updated) where category=X` queried from Weaviate. Upsert
     new/newer expedientes only; **apply tombstones** (delete removed objects).
   - **Reconciliation:** **monthly**, re-process the current-year ZIP as a backstop,
     via the same ingest path.
8. **Build scope:** build the full path but **validate end-to-end on one feed/year**
   (e.g. one `placsp_mayores` year) — confirm extraction coverage, summary quality,
   schema, and retrieval — before scaling to full backfill + enabling daily.

## 4. Architecture

Single Python package. Each module has one purpose and is independently testable.

```
catalog → fetcher → atom_parser → codice_extractor (+ codelists)
   → collapse (max `updated` per syndication_id, in-memory) + tombstones
   → renderer → embedder → upserter → Weaviate
```

### Modules

- **`catalog`** — the feed list (categories × years × URLs, `incremental` flag). Static
  config replacing the n8n data table.
- **`fetcher`** — downloads + unzips a yearly ZIP to a working dir; also the live
  rolling-feed HTTP walker (pagination + watermark) for the daily path. Streams.
- **`atom_parser`** — `lxml.iterparse` streaming over each `.atom` file; yields raw
  entries (`syndication_id` from `<id>`, `updated`, the embedded `ContractFolderStatus`)
  **and tombstones** (`at:deleted-entry` → ref id + reason). Namespace-aware,
  memory-bounded.
- **`codelists`** — loads + caches the CODICE `.gc` codelists (from each value's
  `listURI`) and decodes codes → Spanish labels (TypeCode, ProcedureCode, StatusCode,
  ResultCode, NUTS-2021, FundingProgram, NoticeType, …). Versioned; cached on disk.
- **`codice_extractor`** — **source-aware** mapping of UBL/CODICE into a typed
  `ProcurementRecord`. Each logical field has an ordered list of candidate XPaths
  (first-present wins) to absorb per-source path differences (see §5). Extracts:
  `syndication_id`, `expediente` (display), objeto, tipo (decoded), CPV[], the three
  money fields (budget base / estimated value / awarded), procedimiento (decoded), órgano
  (+id) and parent hierarchy, NUTS/location/país, estado, result code, fechas (publicación,
  award, deadline), adjudicatario (+NIF), n_bids, SME, funding, lotes[], pliego doc URLs.
- **`renderer`** — `ProcurementRecord` → (a) Spanish NL summary text (decoded labels),
  (b) properties dict for filters + BM25.
- **`embedder`** — batched calls to `vectorizer:8089/embed`.
- **`schema`** — creates `Placsp_licitaciones` if absent.
- **`upserter`** — batched `weaviate /v1/batch/objects` with deterministic UUIDs, the
  `updated` guard, `status_history` merge (GET-before-upsert on the daily path), and
  **tombstone deletes**.
- **`pipeline`** — orchestration: `backfill` (chronological, per-unit in-memory collapse),
  `daily` (live feed + watermark + tombstones), `reconcile`.
- **`cli`** — entrypoints: `init-schema`, `backfill`, `daily`, `reconcile`.
- **`config`**, structured logging, tests.

## 5. Weaviate schema — `Placsp_licitaciones`

Single class, `vectorizer: none` (1024-dim vectors supplied at upsert from BGE-M3),
BM25 enabled on `content`. Weaviate 1.28.3 supports nested `object[]`, so `status_history`
is stored as a real `[{code, date}]` array.

Properties (field set grounded in the cross-source inventory; coverage % noted where it
varies by source):

**Identity & content**
- `syndication_id` (text) — stable dedup key (entry `<id>` integer)
- `expediente` (text) — `ContractFolderID`, display only (org-local, non-unique)
- `title` (text), `content` (text, the NL summary; vectorized + BM25), `lang` (text)
- `category` (text) — placsp_mayores / placsp_menores / externos_mayores / propios
- `source_url` (text) — entry `<link>` deeplink, `buyer_profile_url` (text)

**Status & lifecycle**
- `status_code` (text) + `status_label` (text, decoded)
- `status_history` (object[] `{code, date}`)
- `result_code` (text) + `result_label` (text, decoded; nullable) — adjudicada/desierta/…

**Subject & classification**
- `contract_type_code` / `contract_type` (decoded: obras/servicios/suministros)
- `cpv` (text[]) — *propios ~48%, else ~100%*
- `procedure_code` / `procedure` (decoded) — *absent in propios*
- `notice_type` (text)

**Money (three distinct concepts, source-dependent paths)**
- `budget_amount` (number) — presupuesto base (tax-excl)
- `estimated_value` (number, nullable) — valor estimado *(absent in propios)*
- `awarded_amount` (number, nullable) — importe de adjudicación *(present once awarded;
  menores always)*

**Parties**
- `contracting_authority` (text) + `contracting_authority_id` (text, DIR3/NIF)
- `org_top_level` (text) — top `ParentLocatedParty` (for entity filtering)
- `adjudicatario` (text, nullable) + `adjudicatario_nif` (text, nullable)
- `sme_awarded` (boolean, nullable), `n_bids` (int, nullable)

**Location, dates, funding, docs**
- `nuts` (text), `nuts_label` (text, decoded), `city` (text), `country` (text)
- `publication_date` (date), `award_date` (date, nullable),
  `submission_deadline` (date, nullable ~85–89%)
- `funding_program` (text, nullable) — EU / Next-Gen flag
- `document_urls` (text[]) — pliego/document links *(mayores ~79%, propios ~97%)*
- `lots` (object[] `{id, name, amount, cpv}`, nullable) — *mayores ~28%, externos ~21%*
- `updated` (date) — dedup guard / watermark source

### Source-path variance (extractor candidate paths, first-present wins)

| logical field | candidate CODICE paths |
|---|---|
| budget base | `ProcurementProject/BudgetAmount/{TaxExclusiveAmount,TotalAmount}` |
| estimated value | `ProcurementProject/BudgetAmount/EstimatedOverallContractAmount` |
| awarded amount | `TenderResult/AwardedTenderedProject/LegalMonetaryTotal/{TaxExclusiveAmount,PayableAmount}` |
| cpv | `.//RequiredCommodityClassification/ItemClassificationCode` |
| procedure | `TenderingProcess/ProcedureCode` |
| deadline | `.//TenderSubmissionDeadlinePeriod/EndDate` |
| adjudicatario | `TenderResult/WinningParty/PartyName/Name` (+ `PartyIdentification/ID`) |

## 6. Idempotency & dedup details

- Deterministic UUID makes every upsert idempotent; reprocessing the same feed is safe.
- Backfill processes years oldest → newest and collapses per-year in memory (bounded
  RAM ≈ one year of distinct expedientes). An expediente updated across two years may be
  embedded twice; the newer year's upsert overwrites — accepted, documented; can be
  optimized later (knob).
- Daily: collapse the live-feed delta in memory, then for each candidate compare its
  `updated` against the stored object (or rely on the watermark) and upsert only if newer;
  merge `status_history`.
- **Deletions:** Atom tombstones (`at:deleted-entry`) delete `uuid5("placsp:<ref-id>")`
  from the index. (Status changes like annulment that arrive as a normal entry remain
  ordinary status updates; only tombstones delete.)

## 7. Operational model

Both backfill and live share the same `extract → render → embed → upsert` core; they
differ only in source, dedup scope, and resource profile.

### Backfill — one-off, resumable, throttled
- A single `backfill` command loops all `(category, year)` units **oldest → newest**.
- **Off-peak gating:** processing is confined to a configured off-peak window; outside
  it the run sleeps and resumes. A multi-hour/day backfill therefore never contends with
  the iarag/Synergy project's live traffic during business hours.
- **Concurrency / rate cap:** the vectorizer is a **single shared GPU** (internal batch
  size 12). Backfill keeps **max-in-flight low (1–2)** so it doesn't monopolize the GPU
  the iarag project also uses; each `/embed` call sends a modest `texts[]` batch
  (~12–60). Both are configurable and tuned during validation.
- **Resumable:** idempotent deterministic-UUID upserts + a per-unit checkpoint (last
  completed `(category, year)` and `.atom` file) let an interrupted run relaunch and skip
  finished work.
- In-memory collapse is per `(category, year)` unit (bounded RAM).

### Daily — scheduled, light
- A **cron/systemd timer** runs `python -m placsp daily` once per day, off-peak.
- Per category: walk the live rolling feed (`rel=next`) until entries fall at/under the
  per-category watermark; collapse the delta; upsert new/newer only; merge
  `status_history`. No throttling needed.

### Reconciliation — scheduled, monthly
- A **cron/systemd timer** runs `python -m placsp reconcile` monthly: re-process the
  current-year ZIP through the same path as a backstop for entries the live feed missed.
  Idempotent.

### Configuration knobs
Off-peak window; max-in-flight / rate cap; embed batch size; embedding prefix;
vectorizer + Weaviate URLs and auth; the feed catalog.

## 8. Error handling

- Per-`.atom`-file isolation: a parse failure on one file logs and continues; the run
  reports counts (files ok/failed, entries parsed, docs upserted, skipped-stale).
- HTTP calls (vectorizer, weaviate) retried with backoff; batch upsert failures are
  re-tried per-object so one bad object doesn't fail a batch.
- Backfill is resumable: because upserts are idempotent and Weaviate is source of truth,
  re-running a year is safe; processing is logged at file granularity.

## 9. Testing strategy

- **TDD** on the pure-logic modules using real ATOM fixtures captured from the live site /
  a sample ZIP: `atom_parser`, `codice_extractor`, `codelists`, `renderer`.
- Fixtures must cover **all four sources** (their differing field sets), multiple lifecycle
  versions of one `syndication_id` (collapse + `status_history`), a `ContractFolderID`
  collision (proves syndication-id keying), **tombstones**, multi-lot contracts, and
  missing/optional fields.
- `codice_extractor` tests assert the source-path fallbacks (e.g. awarded amount under
  `TenderResult` for menores vs `BudgetAmount` for propios).
- Integration test of `upserter` against a Weaviate instance (deterministic UUID overwrite,
  `updated` guard, history merge, tombstone delete).
- Golden-file test for the rendered NL summary (with decoded labels).

## 10. Resolved facts & remaining unknowns

**Resolved against the running stack:**

- **Embedding model:** BGE-M3 (`BAAI/bge-m3`), dense **1024-dim**, **no prefix** (the
  service strips a leading `query:`; BGE-M3 needs none), **8192-token** window → no
  chunking. Multilingual — good for Spanish + co-official languages.
- **Vectorizer contract:** `POST /embed` with `texts[]` + `normalize` (default `true`,
  L2) → `{embeddings: [[float]]}`. Internal batch size 12 on a single GPU.
- **Weaviate:** v1.28.3 — supports nested `object[]` (for `status_history`); reuse the
  existing `Weaviate API Key` header credential for auth.

**Resolved against real PLACSP data (this analysis):**

- **Dedup key** = syndication entry `<id>` integer (stable across status transitions);
  `ContractFolderID` is org-local and collides.
- **Tombstones** (`at:deleted-entry`) are real deletions — handled.
- **Live feed** paginates backward via `<link rel="next">` to timestamped `.atom` files;
  watermark walk is viable. Heads confirmed reachable per channel.
- **Cross-source field matrix** and **source-specific paths** captured in §2/§5.
- **Codelists:** ~25 coded fields decode via versioned CODICE `.gc` files (referenced by
  each value's `listURI`).

**Remaining unknowns (configurable, tuned during one-feed validation):**

- **Embed batch size + max-in-flight:** tune against observed GPU throughput while
  respecting the shared iarag workload.
- **Long-tail field edge cases:** rare statuses (e.g. `ANUL`, `DES`) and codelist version
  drift across years — confirm during validation/backfill.

## 11. Out of scope (this iteration)

- Full multi-year backfill execution (built for, but first validated on one feed).
- Event-level analytics (`Placsp_status_events` separate class) — not needed; the
  `status_history` array covers per-expediente history.
- Changes to the retrieval/search endpoints (a dedicated PLACSP retrieval query may be
  added later, but is not part of ingestion).
