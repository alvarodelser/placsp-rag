# PLACSP pipeline: what each level gives

Three levels, each building on the one before. Stage 1.5 needs no model; stage 2 reads only what 1.5 leaves, on the files 1.5 downloaded:

| Level | What it reads | Where | Cost | Scope |
|---|---|---|---|---|
| **1. Feed (staging)** | The CODICE XML of every ATOM entry, every archive since 2012 | `src/placsp/staging` → `data/current/*.parquet` | CPU only, minutes per archive | **Every tender** (733k in the local build: mayores 2018–2026, the other channels 2022–2023) |
| **2. Documents** | Detail pages, every published file: text, layout, structure; feed entities located without a model | `python -m placsp_pilot rules`: `select` · `discover` · `fetch` · `text` · `plan` · `feed_summaries` · `mentions`→`locate` | Network, plus about 0.3 CPU-s per page (layout pass) | Selected tenders (`select --staging`) |
| **3. NLP** | The documents' chunks, through `nlp_service`: NER, entity resolution, coreference, refine, formulas, descriptions, summaries | `python -m placsp_pilot nlp`: `classify` · `summarize` · `ner` → `summary` | GPU, the dominant cost | Selected tenders, selected chunks |

Level 1 is described in full, with its field coverage per channel and year, in
[STAGING_REPORT.md](STAGING_REPORT.md). Level 1.5 and 2 take their feed facts from it
(`pilot/placsp_pilot/staging.py`): a tender's
staging rows become the record the pilot's own parser gave. Their equivalence is a test
(`pilot/tests/test_staging_record.py`, all four channels).

Coverage figures for level 1 are from the local staging build (733,950 tenders). Figures for
level 1.5 are from 50 recent mayores and externos processed without OCR (2026-10-21). Level 2 has
only been measured on one tender against the real `nlp_service`, and before the changes below.

## By entity and attribute

✔ the level gives it · ◐ partly or for some tenders · — not at this level

### Tender, authority, lots

| Item | Level 1: feed (staging table.column) | Level 1.5: documents | Level 2: NLP |
|---|---|---|---|
| Identity, title, status, status history | ✔ `tender` (folder_id, name, status_code), `status_history` | — | Tender summary and short title (`summary`, `titles`) |
| Authority | ✔ `tender.auth_*` (name, NIF, DIR3, platform id, every id scheme, type, activity, address, contact, parents), `authority` | Found in the text by NIF, name and hierarchy names, outside furniture: 48 of 50 | Coreference ("el órgano de contratación") |
| Contract type, procedure, urgency, system, submission | ✔ `tender.*_code` | — | — |
| Budget, estimated value, CPV, NUTS, place | ✔ `tender`, `lot` | — | — |
| Duration, period, extensions | ✔ `tender.duration*`, `period_*`, `extension_*` | — | — |
| Deadlines (tenders, participation, documents) | ✔ `tender.deadline_*`, `participation_deadline_*`, `doc_availability_end*` | — | — |
| Lots | ✔ `lot` (id, name, CPV, budget, place) | "Lote 2", "lote nº 3" found: 64 of 66 | — (NER no longer looks for lots) |
| Lots rules (max per bidder, combinations) | ✔ `tender.max_lots_*`, `lots_combination` | — | — |
| Funding (EU, PRTR…), legislation | ✔ `tender.funding_codes`, `national_legislation_code`, `eu_legislation` | — | — |

### Award criteria

| Item | Level 1 | Level 1.5 | Level 2 |
|---|---|---|---|
| Criterion, judgement or formula, points | ✔ `criterion` (description, type_code, subtype_code, weight): 375,939 rows in 118,374 tenders | Found in the text: 196 of 197; also when the feed only points ("Ver apartado 21 del Anexo I") | NER only when the feed has none (13 of 50 tenders: external platforms) |
| How it is scored | ◐ `criterion.note` (free text, in 60,634 rows) | The passage, its section path, tables as rows | `refine`: method (proportional to the lowest price, linear on the discount, linear between budget and lowest, relative to the average, proportional to the best, per unit, tiers, yes/no, ranking, judgement), variable, unit, direction, saturation threshold, abnormally-low rule and %, VAT basis, judgement scale, minimum score, sub-criteria, rounding |
| Formula as an expression | — | — | `formulas`: expression, every symbol, its range (rendered and evaluated by the viewer) |

### Solvency and other requirements

| Item | Level 1 | Level 1.5 | Level 2 |
|---|---|---|---|
| Requirement and its kind (financial, technical, declaration, classification, personal situation, general) | ✔ `requirement` (kind, type_code, description): 596,000 rows in 128,382 tenders | — | NER in the PCAP when the feed only points at it (31 of 50 tenders) |
| Threshold | ◐ `requirement.threshold`: 4.3% of financial rows, 3.0% of technical | The clause it points at ("según cláusula 8ª", "apartado 9.1 del anexo I", "X. C)"): 23 of 28 found; written-out ones: 60 of 61 | `refine`: amount, unit, period, reference base, accreditation, standard, lots, mandatory |
| Business classification (group, subgroup, category) | ✔ `requirement` kind classification (scheme, code value) | — | — |
| Guarantees | ✔ `guarantee` (type, amount, %, period): 91,431 rows in 77,190 tenders | Found by type: 26 of 28 | NER in the PCAP when the feed has none (29 of 50) |
| Special execution conditions | ✔ `condition` (type, name, description): 33,561 rows | — | — |
| Subcontracting limit | ✔ `tender.subcontract_*`, `result.subcontract_*` | — | Named subcontractors (contract documents) |
| Penalties | — | Chunks selected by heading and keywords | NER (PCAP): type, amount, %, per what, cap, condition |
| Deliverables, team profiles, technical requirements, SLAs | — | — | NER (PPT): deadline, count, years, dedication, metric, threshold, unit |
| Qualifications (ISO, ENS, degrees) | — | — | NER (PCAP, PPT), shared across tenders |

### Bids, results, contracts

| Item | Level 1 | Level 1.5 | Level 2 |
|---|---|---|---|
| Result per lot (awarded, void, withdrawn), award date | ✔ `result`: 814,154 rows | — | — |
| Number of bids (SME, EU, non-EU, electronic), lowest and highest bid | ✔ `result.*_bids`, `lowest_bid`, `highest_bid` | — | — |
| Winner (name, NIF, place), awarded amount | ✔ `winner`: 784,853 rows in 676,660 tenders; `company` | Found by NIF and name: 26 of 26 | — |
| **Every bidder, winners and losers** | — (counts only) | The actas, valuation reports and resolutions, tables as rows (1,513 rows in 51 actas, 606 in 22 resolutions) | NER: `BID` (bidder, NIF, lot, outcome, exclusion reason, price, discount, abnormally low, scores, rank) |
| **What each bidder offered and scored per criterion** | — | Same | NER: `CRITERION_SCORE` (bidder, criterion, points, what was offered, figure, unit), linked to the bid and to the feed's criterion |
| UTE members | ◐ `company.is_ute` | — | NER: `JOINT_VENTURE`, `MEMBER_OF` |
| Contract (id, date) | ✔ `result.contract_ids`, `contract_dates` | — | — |
| Modifications (amounts, durations) | ✔ `modification` | — | Reason (`MODIFICATION` in modification documents) |
| Appeals | ◐ `tender.appeals_received` (count) | — | NER: `APPEAL` (who, tribunal, act, outcome, date) |

### Documents

| Item | Level 1 | Level 1.5 | Level 2 |
|---|---|---|---|
| References to the feed's documents (PCAP, PPT, notices, general) | ✔ `document`: 1,593,022 in 276,159 tenders | Downloaded, hash-checked | — |
| Documents only on the detail page (actas, reports, resolutions) | — | ✔ `discover` | — |
| Text | — | ✔ PyMuPDF; pliegos, actas and reports through the layout pass (Markdown: headings, tables as rows, reading order); spaces lost in table cells restored from the plain text | — |
| Page furniture (letterheads, "Página 3 de 18", validation codes, signatures) | — | ✔ Detected, kept in the text, skipped by NER, embeddings and the locator: 7.4% of the words | — |
| Section tree and chunking by sections | — | ✔ Numbered and layout headings (7,921 against 5,391 before); each chunk carries its section path | Section path heads what NER reads |
| Scanned PDFs | — | ◐ OCR service (MinerU) when set; 2 of 37 PCAPs in the sample needed it | — |
| Document summary | — | — | `summarize` |

## What the feed settles, so the model is not asked

| Step | Level 1 has | Rule | Measured |
|---|---|---|---|
| Bids and scores from the actas | `result.bids_received` | Every lot received one bid → its bidder is the feed's winner; the actas are not read for bids (`unless: single_bid` in the ontology's award profile) | 74,021 of 220,701 mayores results (34%) had one bid |
| Descriptions of feed entities | Every feed entity's fields | Criteria, requirements, guarantees, contracts, modifications, the authority and the winners are described from their fields and refined details (`PILOT_DESCRIBE_FEED=template`); bidder, score and criterion links too. The model describes only what the documents alone give | The describe step was 13 GPU-min per tender |
| Summaries of notices | The record they render | Notices (tender, prior, award, formalisation, modification) are summarised from the feed, with Spanish codelist names (`feed_summaries`) | 112 of 789 documents (14%) |
| Companies named without NIF | `company`: 205,526 companies, 395k names | A bidder's name a winner was published under gives its NIF before any `/resolve` (`PILOT_STAGING_DIR`, or `--staging`) | 31% of the bidders in the sample's actas, by exact name |

`python -m placsp_pilot rules` ends with what it settled and what it leaves for stage 2: the
chunks NER will read, the documents still to summarise, the scanned files.

## Where NER now spends its time

Before: every chunk of every document, with all 16 entity types, about 13,100 characters of schema per call.

Now:
- Only the types the feed lacks, one schema per document role (about 2,700 characters):
  - **actas, reports, resolutions:** bids, scores, companies, UTEs;
  - **PCAP:** penalties, qualifications, plus the fallback types;
  - **PPT:** deliverables, team profiles, technical requirements;
  - **contracts, modifications, appeals:** their own types.
- Notices, annexes, project and preparatory documents are not read by NER.
- PCAPs are read in their relevant sections only.
- On the 50 tenders: 5,209 chunks before, about 2,410 now, with 9% fewer words, since furniture is left out.

## Gaps to close next

- **Level 1 → level 2 only via documents:** losing bidders and their offers are never in the feed. They need actas (level 1.5) and NER (level 2).
- **Level 1.5 misses:** most are a missing or scanned PCAP (6 of the 13 misses). Run OCR for scanned ones, and report "nothing published" as a warning.
- **Level 2 quality:** the new schemas, the section header and the Markdown tables have not yet been run through the real `nlp_service`. Next: about 10 tenders, compared with the old full-schema output.
