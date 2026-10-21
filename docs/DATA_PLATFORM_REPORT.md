# PLACSP Data Platform — Data & AI Processing Report

An exhaustive reference-scale walkthrough of where every piece of data enters the system, how it is transformed, and where it lands. 

- **Part 1** covers raw data collection: feeds, parsing, transformation, storage.
- **Part 2** covers AI processing: embeddings, pliego extraction, profile matching, company graph.
- **Part 3** is forward-looking: external data sources for company enrichment and further documents/data you could gather.

---

## PART 1 — DATA COLLECTION

### 1.1 Where the data comes from

**Single primary source: PLACSP** — *Plataforma de Contratación del Sector Público*, the Spanish government's official public-procurement portal. Everything the platform knows originates from its **ATOM syndication feeds** at `https://contrataciondelsectorpublico.gob.es/sindicacion`.

Each ATOM `<entry>` embeds a **CODICE XML** document (`ContractFolderStatus`, "CFS") — CODICE is Spain's UBL-derived procurement schema (namespaces `cbc`/`cac` from CODICE + `pe`/`peb` from the CODICE-PLACE extension). This is the atomic unit of a tender ("expediente").

Four feed **channels** are ingested (`src/placsp/core/catalog.py`):

| Category | Syndication | Content | From year |
|---|---|---|---|
| `placsp_mayores` | 643 | Major contracts, PLACSP contracting profiles | 2012 |
| `externos_mayores` | 1044 | Aggregated *external* platforms, majors (no minors) | 2016 |
| `placsp_menores` | 1143 | Minor contracts (contratos menores) | 2018 |
| `propios` | 1383 | Sector-público own contracts | 2022 |

For each channel the catalog generates one **per-year ZIP** URL (`{stem}_{year}.zip`) from its start year to the current year, plus a live **`.atom` head feed** for the current year (`live_head_url`). The current year is flagged `incremental=True`.

**Secondary source (derived, not a feed):** the PLACSP **detail HTML pages** at `contrataciondelestado.es/wps/portal/...`, reached via each record's `source_url`. These are scraped for tender criteria and links to the actual PDF pliegos (Part 2).

**Reference data: CODICE codelists** — 28 genericode `.gc` files in `codelists/` (CPV2008, NUTS-2021, procedure/status/result/contract-type codes, etc.), fetched from the `listURI` attributes referenced in the feeds (`scripts/fetch_codelists.py`). These translate raw codes into Spanish labels.

### 1.2 How it's fetched

**Location:** ingestion runs **on the host via cron** (not in Docker), entrypoint `scripts/placsp`.

Three modes:

- **`daily`** — walks the live `.atom` head feed, following feed-level `rel="next"` links up to 1000 pages. Stops early once a page is entirely older than the **watermark** (max `updated` timestamp already stored for that category, queried via Weaviate GraphQL aggregate). Uses `merge_stored=True`.
- **`backfill`** — downloads the historical per-year ZIPs; self-gates to an off-peak window (default 22:00–07:00 host-local).
- **`reconcile`** — monthly full re-pull of the incremental feeds, `merge_stored=True`.

**Fetch mechanics** (`src/placsp/ingestion/fetcher.py`):
- httpx with `verify=False` (PLACSP chains to a Spanish FNMT CA — flagged as a hardening follow-up).
- `User-Agent: placsp-ingest`, 600 s timeout, follow redirects.
- ZIPs unzipped to scratch `work/` dir and globbed for `*.atom`.

### 1.3 What fields are parsed

**Stage A — ATOM parse** (`parsers/atom_parser.py`, streaming `iterparse`):
- `<entry>` → `RawEntry(syndication_id, updated, link, cfs, category)`. The `syndication_id` is the last path segment of the `atom:id` URL.
- `<deleted-entry>` (atompub tombstones) → `Tombstone(syndication_id, when, reason, category)`.

**Stage B — CODICE extraction** (`parsers/codice_extractor.py`) maps the CFS XML into a `ProcurementRecord` dataclass (`core/models.py`). Full field inventory:

| Group | Fields | XPath / notes |
|---|---|---|
| **Identity** | `syndication_id`, `expediente`, `title`, `source_url`, `category`, `lang="es"` | `ContractFolderID`, `ProcurementProject/Name` |
| **Status** | `status_code`, `status_label`, `status_history[]` | `ContractFolderStatusCode` (decoded), list of `StatusEvent(code, date)` |
| **Classification** | `contract_type_code`, `contract_type`, `cpv[]`, `procedure_code`, `procedure`, `notice_type` | `TypeCode`, `ItemClassificationCode`, `ProcedureCode`, `NoticeTypeCode` |
| **Parties** | `contracting_authority`, `contracting_authority_id`, `org_top_level`, `buyer_profile_url` | `PartyIdentification/ID`, top `ParentLocatedParty` |
| **Location** | `nuts`, `nuts_label`, `city`, `country` | `CountrySubentityCode` |
| **Money** | `budget_amount`, `estimated_value`, `awarded_amount` | `BudgetAmount/TaxExclusive|Total`, `EstimatedOverallContractAmount`, `TenderResult/LegalMonetaryTotal` |
| **Dates** | `publication_date`, `submission_deadline`, `award_date`, `updated` | `AdditionalPublicationDocumentReference/IssueDate`, `TenderSubmissionDeadlinePeriod/EndDate`, from ATOM |
| **Tender result** | `result_code`, `result_label`, `adjudicatario`, `adjudicatario_nif`, `n_bids`, `sme_awarded` | `TenderResult/ResultCode`, winner name/NIF, `ReceivedTenderQuantity`, `SMEAwardedIndicator` |
| **Funding / docs** | `funding_program`, `document_urls[]` | `FundingProgramCode`, `GeneralDocument/ExternalReference/URI` |
| **Lots** | `lots[]` = `Lot(lot_id, name, amount, cpv[])` | `ProcurementProjectLot` structure |
| **Per-lot winners** | `lot_results[]` = `LotResult(lot_id, winner_name, winner_nif, amount, award_date, sme_awarded, n_bids, n_sme_bids, lower_tender_amount, higher_tender_amount, name, cpv[])` | Multi-`cac:TenderResult` linked via `AwardedTenderedProject/ProcurementProjectLotID` |

Codes are decoded to labels via `Codelists.label(list_uri, code)` (`core/codelists.py`), which parses the `.gc` files into `{code: spanish_label}` maps.

**Important structural fact:** `mayores` feeds carry multiple `cac:TenderResult` blocks linked to lots; `menores`/`propios` are single implicit lots. **Losing-bidder identities are NOT in the feeds** — only bid *counts* and low/high amounts — so no competitive "who-else-bid" graph is possible from this source.

### 1.4 Processing / transformation

**`collapse()`** (`pipeline.py`):
- Dedupes a batch by `syndication_id`, keeping the record with the latest `updated`.
- Merges `status_history` across all entries for the same id (dedup by `(code, date)`).
- Drops any id that is tombstoned in the same batch.

**`merge_stored` path** (daily/reconcile):
- GETs the stored Weaviate object.
- **Skips** the record if its `updated` is not newer than what's stored.
- Otherwise merges stored + new status history before upsert.

**`render()`** (`parsers/renderer.py`) — the key transformation:
- Produces a **natural-language Spanish `content` summary**: "Contrato de servicios: … Órgano de contratación: … Importes: presupuesto base … Estado: … Adjudicatario: …"
  - This string is what gets embedded into the vector space.
- Derives facet fields:
  - `budget_bucket` (15 log-space buckets, 1k–100M €).
  - `pub_month`, `deadline_month`.
- Date normalization to **RFC3339** for Weaviate `date` props:
  - Date-only values get `T00:00:00Z`.
  - Unparseable → dropped.
- Empty scalars stripped (required fields + list fields always kept).

### 1.5 Where it's stored

Three persistence layers:

**1. Weaviate (vector DB)** — `docker-compose`, class `Placsp_licitaciones` (`storage/weaviate_schema.py`).
- Schema: `vectorizer: none` (vectors supplied externally), cosine distance, BM25 (`b=0.75, k1=1.2`).
- Object UUID = `uuid5(NAMESPACE_URL, "https://placsp.id/{syndication_id}")` → idempotent upserts.
- Every `ProcurementRecord` field is a typed property; `status_history` and `lots` are nested `object[]`.
- Batched upserts of 100 (`storage/upserter.py`); tombstones → object deletes.
- Three sibling classes also exist: `Placsp_companies`, `Placsp_pliego_criteria`, `Placsp_pliego_chunks` (Part 2).

**2. Neo4j graph (optional)** — runs as a second sink if `NEO4J_URL` is set (`storage/graph_sink.py` + `graph_ops.py`).
- **Nodes:** `Company{nif}`, `Contract{syndication_id}`, `Lot{lot_key}`, `Authority{id}`, `Cpv{code}`, `Nuts{code}`.
- **Relationships:** 
  - `(Authority)-[:TENDERED]->(Contract)`
  - `(Contract)-[:HAS_LOT]->(Lot)`
  - `(Company)-[:WON]->(Lot)`
  - `(Lot)-[:CLASSIFIED_AS]->(Cpv)`
  - `(Contract)-[:LOCATED_IN]->(Nuts)`
- **Only contracts with a resolvable winner NIF are graphed.**
- Company identity is cleaned:
  - `normalize_nif` (strip punctuation, uppercase).
  - `normalize_name` (drop legal suffixes SL/SA/UTE…).
  - `is_ute_winner` detection (NIF starts "U" or name starts "UTE").
  - `canonical_name` derived from most-frequent display name.

**3. SQLite `users.db`** (search-api, `search-api/users.py`) — application state, not procurement data:
- `users`, `refresh_tokens`, `saved_items`, `user_events`, `user_profiles`, `saved_items_analysis`.

**Vectorizer:** external **BGE-M3** service (`ai/embedder.py`, `VECTORIZER_URL/embed`, `normalize=True`).
- Dense multilingual embeddings, computed once at ingestion and stored on the Weaviate object.

---

## PART 2 — AI PROCESSING

### 2.1 Semantic embeddings (the always-on layer)

- **Source:** the `render()` summary string for each licitación.
- **Processing:** BGE-M3 dense embedding at ingestion (`Embedder.embed`, batched 48).
- **Storage:** the vector on the `Placsp_licitaciones` object.
- **Use:** `/api/search` supports `keyword` (BM25), `vector` (nearVector), and `hybrid` (alpha-weighted) modes, plus faceted filters (CPV, NUTS, status, result, type, procedure, date ranges, budget) computed by `facets.py` over pre-bucketed fields.

### 2.2 Pliego (tender-document) analysis — three tiers

This is the heavier AI pipeline, layered from cheap-always-on to expensive-on-demand.

#### Tier 1 — HTML criteria scrape (at ingestion, shared across all users)

`ingestion/pliego_pipeline.py::process_tier1`, run inside `process_files` for any record whose `source_url` points at `contrataciondelestado.es/wps/portal`:

1. Fetches the detail HTML; `parsers/pliego_html_parser.py` (BeautifulSoup) scrapes a rich `PliegoCriteria` structure:
   - `criterios_adjudicacion` (name/subtipo/ponderación)
   - `garantia_definitiva_pct`, `garantia_complementaria_pct`
   - `clasificacion_empresarial`, `condiciones_admision`, `motivos_exclusion`
   - `num_empleados_min`
   - `plazo_ejecucion`, `condiciones_especiales`, `subcontratacion`
   - `sobres`, `plazo_validez_oferta`
   - `apertura_fecha`, `apertura_lugar`
   - `regulacion_armonizada`, `directiva_aplicacion`
   - **`pdf_links`** (the actual pliego PDFs)

2. **Stored** as `criteria_json` on a `Placsp_pliego_criteria` object (UUID = `uuid5("criteria_{syndication_id}")`).

#### Tier 2 — LLM extraction + profile match (on-demand, user-triggered)

Entry: `search_api` `/api/pliegos/{id}/analyze` → ingester `api.py` `/internal/analyze` (FastAPI `BackgroundTask`) → `ai/nlp_pipeline.py::run_pipeline`:

1. Re-fetch HTML, re-parse criteria to get `pdf_links`.
2. `_classify_pdf_links` picks the **PCAP** (administrative — "administrativ"/"pcap") and **PPT** (technical — "técnic"/"ppt") documents, with a generic-"pliego" fallback and combined-document handling.
3. `_get_pdf_text`: download PDF → **PyMuPDF** text extraction; if < 200 chars (scanned/image PDF), **fall back to OCR service** (`ocr_url/services/ocr`).
4. `_extractive_search`: paragraph-level keyword scoring (distinct `_PCAP_KEYWORDS` / `_PPT_KEYWORDS` lists) selects the densest ~8000 chars to fit LLM context.
5. **LLM extraction** (`ai/extractor.py`, **Ollama**, model `gemma4:31b` default, `format: json`):
   - **PCAP** → `penalidades, forma_pago, modificaciones_contrato, subcontratacion, seguros, cesion, resolucion` (via `PLIEGO_PCAP_EXTRACTION_PROMPT`).
   - **PPT** → `entregables_clave, sla_acuerdos_nivel_servicio, perfiles_profesionales, certificaciones_tecnicas, tecnologias_obligatorias, lugar_ejecucion` (via `PLIEGO_PPT_EXTRACTION_PROMPT`).
6. **Extraction is cached** (`pcap_json`, `ppt_json`, `pliegos_extracted_at`) on the shared `Placsp_pliego_criteria` object → computed **once per tender**, reused for every user.
7. **Profile match** (`match_profile`, `PLIEGO_MATCH_PROMPT`):
   - LLM is given:
     - The **user profile**
     - The **structured platform criteria** (treated as most-reliable qualification gates: `clasificacion_empresarial`, `condiciones_admision`, `motivos_exclusion`, `num_empleados_min`, guarantees, award criteria)
     - PCAP extraction + PPT extraction
   - Returns: **`veredicto` (YES/NO/MAYBE)**, `razonamiento_general`, per-requirement `requisitos_evaluados[]`.
8. **Stored** per-user in SQLite `saved_items_analysis` (`veredicto`, `razonamiento`, `requisitos_evaluados`, `status`).

#### Tier 3 — full-document chunk RAG (scaffolded)

`Placsp_pliego_chunks` class + `process_pliego` (OCR → chunker service → embed each chunk → store `chunk_text` + vector + `pliego_type`/`chunk_index`/`source_pdf_url`). This is the RAG substrate for document-level Q&A; the extraction path above is the currently-wired product surface.

### 2.3 The user profile

Stored as `profile_json` in `user_profiles` (SQLite), edited in `search-ui/src/components/UserProfile.jsx`:

```json
{
  "company_name": "string",
  "description": "free text — activity, turnover, years",
  "cpvs": "comma-separated CPV codes",
  "certifications": "ISO 9001, ENS…",
  "tech_stack": "React, Node.js, AWS…",
  "employees": [
    { "name": "string", "profile_desc": "Senior Java, 10 años" }
  ]
}
```

**Important limitation:** entirely **self-declared** — users manually type this. See Part 3 for how to derive it from real company data.

### 2.4 The company graph as an analytical product

`search-api/graph_api.py` exposes the Neo4j graph:
- `/api/graph/company/{nif}` — aggregate stats (contracts/lots won, total awarded €, unique CPVs/authorities).
- `/api/graph/company/{nif}/contracts` — list contracts won, paginated.
- `/api/graph/contract/{id}` — contract neighbourhood (parties, lots, winners, CPVs, location).
- `/api/graph/similar/companies/{nif}` — shared-CPV similarity.

This is the **SP1 foundation** of the GraphRAG company-curation effort; **SP2 enrichment and SP3 community summaries are not yet built** — the exact seam Part 3 fills.

---

## PART 3 — FURTHER DATA WORTH GATHERING

Two tracks: **(A) company data** and **(B) more licitation documents/data**. These are grounded against what the pipeline already has and prior research (see `PLACSP company graph plan` and `Spanish company data sources` in project memory).

### 3.A — Company data (enrichment of the `Company` node)

Today a `Company` node has only what awards reveal: `nif`, `canonical_name`, `is_ute`, and won-lot aggregates. There is **no** sector, size, location, financials, or corporate structure.

**Constraint:** there is **no free, complete, downloadable, NIF-keyed Spanish company directory.** Enrichment is opportunistic, tiered by cost/coverage:

#### Free / bulk — do these first (highest ROI):

**1. GLEIF LEI golden-copy** — free, daily unlimited download
- Carries the **NIF** in the registration-authority field + canonical legal name, HQ + legal address.
- Relationship files include **parent/ultimate-parent links** → real `SUBSIDIARY_OF`/`PARENT_OF` edges in Neo4j.
- Coverage skews to larger/LEI-holding entities, but it's the single best free NIF-keyed spine.
- *Adds:* `legal_name`, `address`, `country`, corporate-ownership edges.

**2. BORME via BOE open-data API** — free structured JSON/XML
- Registry *events*: incorporations, director appointments/removals, dissolutions, capital changes.
- **Name-keyed, no reliable NIF** (degrades at peak hours). Basis of libreBORME/OpenMercantil.
- Requires a name-matching bridge to your NIF spine.
- *Adds:* incorporation date (→ company age), director/administrator names (→ people graph, UTE-member resolution, conflict-of-interest signals), status (active/dissolved).

**3. VIES (EU VAT)** — per-NIF API
- Validates VAT registration, returns canonical name/address.
- Rate-limited, VAT-registered only.
- **Best use:** NIF validation / canonical-name normalization pass, not bulk enrichment.

**4. CPV → sector inference (internal, zero external data)**
- Roll up per-lot CPVs per company into a sector fingerprint (dominant CPV divisions).
- Free, immediate `primary_sectors` attribute.
- Better `/similar/companies` signal than current shared-CPV count.

#### Paid / gated — only if the product justifies it:

**5. Registro Mercantil** — authoritative, NIF-keyed, SME-inclusive
- Paywalled per-query; bulk gated to notaries/lawyers/banks.
- The complete answer, but not bulk-accessible.

**6. Commercial aggregators** — (Informa D&B, eInforma, Axesor)
- Comprehensive (financials, employees, CNAE, ratings), but paid.
- Free repackagers (EmpreciF, DatosCif, Infonif) allow *lookups* only, not bulk.
- **Realistic use:** on-demand enrichment of the handful of companies a user inspects, cached — not a mass backfill.

#### Derivable from PLACSP itself (free, no new source):

**7. Win-rate / competitive stats**
- You have `n_bids` and low/high tender amounts per lot.
- Per company compute: award frequency, typical discount vs. budget, authority concentration, geographic footprint (NUTS), repeat-authority relationships.
- This is arguably richer than most external data for *procurement-behaviour* analytics.
- **Currently unused** on the `Lot` nodes.

**Recommended sequence:**
1. (4) + (7) internal-only first → quick wins, no new infrastructure.
2. (1) GLEIF spine + ownership edges → free, high-coverage NIF normalization + corporate structure.
3. (2) BORME people/events with a name-bridge → director history, UTE composition, corporate events.
4. (3) VIES as a validation pass → harden `canonical_name`.

### 3.B — More licitation documents & data

Current pipeline captures feed metadata + scraped HTML criteria + (on-demand) PCAP/PPT text. Gaps and additions:

#### Documents already reachable but under-exploited:

**1. `document_urls[]` and `pdf_links[]` beyond PCAP/PPT**
- Feeds and detail pages reference anexos, cuadros de características, modelos de proposición, correction notices.
- Tier 2 currently ignores these (only classifies PCAP/PPT).
- Ingesting these into `Placsp_pliego_chunks` broadens the RAG corpus.

**2. Full-document RAG activation**
- Tier 3 (`process_pliego` → chunks) is scaffolded but not wired into a user-facing endpoint.
- Activating it turns "does my profile match?" into "answer any question about this pliego" — materially bigger product.

**3. Award/formalization documents**
- "Acta de adjudicación" / "documento de formalización" PDFs contain the *actual* scoring breakdown and losing-bidder context.
- Worth targeting specifically.

#### New PLACSP-adjacent structured sources:

**4. PLACSP full "Documento CODICE" per expediente**
- Detail pages expose a complete CODICE XML richer than the syndication summary.
- Full award criteria weightings, all lots, all publication events.
- Fetching per-expediente CODICE would close feed-vs-detail gaps without HTML scraping fragility.

**5. DOUE / TED (Tenders Electronic Daily)**
- EU-level procurement feed.
- Spanish above-threshold ("regulación armonizada") tenders are cross-published to TED with **standardized eForms** (machine-readable, multilingual, includes award/competition data).
- TED bulk data is free and open — a cleaner structured mirror for the major-contract subset.
- Carries pan-EU context.

**6. BOE / regional boletines (BOCM, DOGC, BOJA…)**
- Award and formalization announcements published as open data.
- Cross-fill missing `award_date`/`adjudicatario`.
- Catch corrections and updates.

#### Enrichment / derivation on documents you already have:

**7. Deadline & calendar extraction**
- `submission_deadline`, `apertura_fecha` exist as raw strings.
- Normalizing them enables an "expiring soon" alerting product on saved items.

**8. Requirement taxonomy normalization**
- LLM currently emits free-form `certificaciones_tecnicas`, `clasificacion_empresarial`, etc.
- Mapping to controlled vocabulary (official *clasificación empresarial* grupos/subgrupos, ISO registry) would make profile-match deterministic.
- Reduces the "MAYBE" rate that stems from string-mismatch vs. genuine ambiguity.

**Recommended sequence:**
1. (4) per-expediente CODICE to harden metadata → low-friction, high-value.
2. (1)+(2) broaden and activate the chunk RAG → user-visible feature.
3. (5) TED eForms for the majors subset → validation + EU context.
4. (8) requirement normalization to sharpen matching → ML/data quality win.

---

## Cross-cutting observations

**Cheap wins (immediate):**
- The **`lot_results` bid statistics** (`n_bids`, `n_sme_bids`, low/high tender amounts) are extracted and stored on graph `Lot` nodes but **not surfaced anywhere** in the API/UI. Exposing these is the quickest analytical win.
- CPV-derived `primary_sectors` (Part 3.A.4) adds immediate company-comparison signal with zero external dependencies.

**Structural improvements:**
- The self-declared **user profile** is the weakest input to the whole match pipeline. Linking a user's own company to its graph node (win history, real CPVs, real awarded amounts) would let you *derive* much of the profile instead of trusting free text.
- **Current Tier 2 limitation:** "MAYBE" verdicts stem partly from fuzzy string matching (LLM extracting free-form text). Mapping to controlled vocabularies (Part 3.B.8) would harden this.

---

**Generated:** 2026-07-08  
**Report scope:** PLACSP data + AI ingestion pipeline end-to-end, from ATOM feeds through Neo4j + user profiles + Tier 2/3 LLM analysis.
