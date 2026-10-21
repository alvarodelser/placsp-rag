# Staging the PLACSP archives — what the feed gives us, and what still needs the documents

Date: 2026-10-21. Branch: `feat/pliegos-analysis-consolidation`.

This report covers the first phase of the historical platform: download PLACSP's yearly archives,
turn them into tables, and extract everything that is already structured in them — without
reading any PDF or calling any model. It then compares that against what the search app and
the document pilot use today, to answer one question: **what do we still need the second,
document-level stage for?**

All numbers come from real archives downloaded on 2026-10-21 (listed in section 3).

---

## 1. Summary

- **The feed is much richer than the current app uses.** For the major contracts channel it
  carries, per tender: award criteria with their weights (and, in recent years, whether each is
  scored by formula or by judgement), solvency requirements, guarantees, special execution
  conditions, subcontracting terms, lots with their own terms, every award per lot with the
  winner's tax ID, the number of bids received (and how many from SMEs, from the EU, from
  outside the EU), the lowest and highest bid, the signed contract's ID and date, contract
  modifications, and a link to every published document with its checksum.
- **The other three channels are thin.** Regional platforms, minor contracts and in-house
  commissions publish identity, money, dates, winner and bid counts — but no criteria and no
  requirements.
- **Half of the requirement texts are pointers, not content.** About 50% of the financial and
  technical solvency texts in the feed say only "see clause X of the PCAP" or similar. The real
  thresholds are in the PDF.
- **So the second stage is needed for:** the content behind those pointers; everything about
  the competition that the feed never publishes (who else bid, their prices and scores);
  the details of the technical specifications (deliverables, team profiles, technologies, service
  levels); penalties; scoring formulas in full; and every criterion and requirement for the
  three thin channels — where those channels publish documents at all.
- **The pilot can stop extracting with NER what the feed already gives** — award criteria and
  their weights, guarantees, winners, contracts, modifications — and use NER only to fill in
  what is missing or only referenced.
- **One bug found in the current app:** it deletes from search and from the graph every tender
  the feed marks as "closed", and those are mostly tenders that were awarded. A historical and
  transparency tool must keep them. Staging keeps them.

---

## 2. What was built

Three commands, in `src/placsp/staging/`, run as `python -m placsp stage <step>`:

| Step | What it does | Output |
|---|---|---|
| `download` | Downloads every archive that is not on disk yet. Past years come as one ZIP per year. The current year comes as one ZIP per finished month (PLACSP's yearly ZIP for the current year is rebuilt every day and is already 1.9 GB, so it is not used). The month in progress is only in the live feed, which the daily job keeps reading. A download goes to a `.part` file and is renamed when complete, so a cut download never looks finished; it retries three times. | `data/zips/<channel>/<file>.zip` plus a `.json` with what the server reported |
| `extract` | Reads the ATOM files straight from inside each ZIP (nothing is unpacked to disk) and writes every published version of every tender as rows in Parquet tables. Each ZIP is one unit of work: when it finishes, a marker file records it, so a rerun skips it and an interrupted run resumes where it stopped. Several ZIPs are processed in parallel. | `data/versions/<table>/<zip>.parquet` |
| `build` | Uses DuckDB to read all versions of all years at once and produce one row per tender in its latest state, the full status history, and tables of authorities and companies. | `data/current/<table>.parquet` |

`scripts/survey_feed.py` lists every XML field present in an archive and how often it appears.
It is how the coverage below was measured, and how to check a new year before trusting it.

### Why tables of *versions* first

PLACSP republishes a tender every time it changes, and the change often lands in a different
year's archive (published in November, awarded in February). The current app processes one
year at a time, so the later year overwrites the earlier one and the earlier statuses are lost.
Keeping every version and merging them all in one pass fixes that, and gives us the full history
of each tender: when it was published, evaluated, awarded and formalised.

### The tables

One row per published version in `versions/`; one row per tender (latest version) in `current/`.
Codes are stored as published; their Spanish labels are in the `codelist` table.

| Table | One row per | Main contents |
|---|---|---|
| `tender` | tender | identity, status, title, contract type, procedure, budget and estimated value, CPV codes, place, duration, deadlines, the contracting authority (name, tax ID, DIR3 code, address, email, phone, every parent body up to the top), funding, legislation, subcontracting, number of appeals, how many versions were seen, when it left the feed and why |
| `status_history` | tender × status | when the tender was first and last seen in each status |
| `lot` | lot | name, CPV, budget, place |
| `criterion` | award criterion | name, formula or judgement, subtype (price, quality…), weight, note; per tender or per lot |
| `requirement` | solvency or admission requirement | kind (financial, technical, declaration, classification, minimum employees, minimum years of operation…), type code, text, threshold amount |
| `guarantee` | guarantee | provisional / definitive / complementary, percentage, amount |
| `condition` | special execution condition | type (social, environmental…), name, text |
| `result` | award (per lot or for the whole tender) | result (awarded, deserted…), dates, bids received, SME / EU / non-EU bids, lowest and highest bid, abnormally low bids excluded, amount awarded, contract ID and signing date, subcontracting declared |
| `winner` | winning company per award | name, tax ID, location |
| `modification` | contract modification | change in amount and duration, final amount |
| `notice` | published notice | type (call for tenders, award, formalisation…), where it was published (BOE, EU journal, buyer profile), dates |
| `document` | document link | kind (PCAP, PPT, annex, general document, notice document), file name, URL, checksum |
| `authority` | contracting authority | merged across tenders by DIR3 code, else tax ID, else name; every name variant seen |
| `company` | winning company | merged by normalised tax ID; every name variant seen; whether it is a joint venture (UTE) |
| `codelist` | code | Spanish label of every code |

---

## 3. What is in the archives

Archives used (all downloaded 2026-10-21):

| Archive | ZIP size | Versions | Distinct tenders | Extract time |
|---|---|---|---|---|
| Major contracts (PLACSP), 2013 | 20 MB | 23,452 | 13,620 | 20 s |
| Major contracts (PLACSP), 2019 | 466 MB | 235,168 | 111,187 | 170 s |
| Major contracts (PLACSP), Sept 2026 | 303 MB | 95,910 | 42,213 | 82 s |
| Regional platforms, 2016 (first year) | 4 MB | 11,154 | 11,154 | 6 s |
| Regional platforms, 2023 | 88 MB | 239,202 | 79,715 | 66 s |
| Minor contracts, 2018 (first year) | 50 MB | 164,000 | 160,305 | 92 s |
| Minor contracts, 2023 | 251 MB | 512,227 | 496,545 | 202 s |
| In-house commissions, 2023 | 2 MB | 3,470 | 3,345 | 1 s |

(Extract times are for one archive on one core. With four in parallel on the development Mac,
all eight — 1.28 million versions — took 6 minutes, and the build 6 seconds.)

- The Parquet version tables take about **55% of the ZIP size** (1.1 GB of ZIPs → 616 MB); the
  current tables about 30% (917,985 tenders → 315 MB).
- Extraction runs at roughly 1,400 entries per second per core for major contracts (the richest
  entries) and 2,500–4,700 for the others.
- A major contract is published about **2.1 times** on average within one year; a regional
  platform tender about **3 times**; a minor contract about **once** (it is published already
  awarded).
- Each archive also contains **deletion markers**. Their stated reason is either `ANULADA` (the
  publication was annulled) or `CERRADA` (the tender is closed and leaves the feed). In the
  regional platforms archive of 2023 there were 14,039, all `CERRADA`, and the tenders they point
  to are mostly resolved or awarded.

### Coverage: share of tenders that have each item

| | Major 2019 | Major 2026 | Regional 2023 | Minor 2023 | In-house 2023 |
|---|---|---|---|---|---|
| Award criteria | 72% | 92% | — | — | — |
| … with formula/judgement type | 0% | 90% | — | — | — |
| Solvency / admission requirements | 84% | 84% | — | — | — |
| Guarantees | 50% | 50% | — | — | — |
| Special execution conditions | 0% | 50% | — | — | — |
| Link to the PCAP (administrative specifications) | 88% | 88% | 46% | 2% | — |
| Winner with tax ID | 82% | 55%* | 79% | 99.8% | 100% |
| Number of bids received | 88% | 59%* | 84% | 100% | — |
| Lowest and highest bid | 41% | 37% | — | — | — |
| Contract modifications | 3% | — | — | — | — |

\* Many tenders from September 2026 are not yet awarded.

How the feed changed over time (2019 vs 2026, major contracts): 2026 adds the formula/judgement
type and subtype of each criterion, criteria and requirements per lot, threshold amounts on
solvency requirements, special execution conditions, the winner's address and nationality, SME
/ EU / non-EU bid counts, and the number of appeals. 2013, 2016 and 2018 are checked in the
subset test (section 9).

### How much of the requirement text is real content

A requirement text counts as a *pointer* when it says "ver", "véase", "cláusula", "PCAP",
"pliego", "anexo", "cuadro" or "apartado".

| Kind | Rows | Pointers |
|---|---|---|
| Declarations (capacity to contract, no prohibition…) | 323,509 | 0% — these are standard statements |
| Technical solvency | 131,399 | 50% |
| Financial solvency | 106,412 | 53% |
| General description | 13,595 | 82% |
| Business classification (group, subgroup, category) | 11,533 | 0% — a code, fully structured |
| Personal situation | 9,552 | 22% |

---

## 4. What the search app uses, and where it now comes from

Every field the search app reads (search, filters, facet counts and the result card) is in
staging, so the search app can be fed entirely from the `current` tables:

| Search app field | Staging source |
|---|---|
| title, content summary | `tender.name`, plus authority, CPV labels, place |
| status, result | `tender.status_code`, `result.result_code` |
| contract type, procedure | `tender.contract_type_code`, `tender.procedure_code` |
| CPV, NUTS region | `tender.cpv`, `tender.nuts` (and per lot in `lot`) |
| budget, estimated value, awarded amount | `tender.budget_tax_excl`, `tender.value_estimated`, `result.amount_tax_excl` |
| publication date, deadline, award date | `notice.dates`, `tender.deadline_date`, `result.award_date` |
| contracting authority, top-level body | `tender.auth_name`, `tender.auth_parent_names` |
| winner, winner tax ID, SME winner, number of bids | `winner.name`, `winner.nif`, `result.sme_awarded`, `result.bids_received` |
| status history | `status_history` (now across years; today it is lost between years) |
| per-lot winners and bid statistics (graph) | `result` + `winner`, joined on lot |

What staging adds that the search app does not use yet: the authority hierarchy with
identifiers, award criteria and requirements, guarantees, execution conditions, SME / EU /
non-EU bid counts, lowest and highest bids, contract IDs and dates, modifications, appeals,
document links and checksums.

---

## 5. What the old web-page scraper got, and whether the feed has it

The current ingestion downloads each tender's web page on PLACSP and scrapes it
(`parsers/pliego_html_parser.py`, "Tier 1"). Against the feed:

| Scraped from the web page | In the feed? |
|---|---|
| Award criteria (name, subtype, weight) | **Yes** — `criterion` |
| Definitive / complementary guarantee % | **Yes** — `guarantee` |
| Business classification required | **Yes** — `requirement` kind `classification` |
| Admission conditions | **Yes** — `requirement` kind `declaration` |
| Exclusion grounds | Partly — `requirement` kind `personal_situation` |
| Minimum employees | **Yes** where published — `requirement` kind `employees` (rare) |
| Execution period | **Yes** — `tender.duration`, `period_start`, `period_end` |
| Special execution conditions | **Yes** (recent years) — `condition` |
| Subcontracting | **Yes** — `tender.subcontract_*`, `result.subcontract_*` |
| Harmonised (EU-threshold) contract, applicable directive | **Yes** — `tender.over_threshold`, `tender.eu_legislation` |
| Links to the PDFs | **Yes** — `document` |
| Envelopes (sobres) | **No** |
| Offer validity period | **No** |
| Date and place of bid opening | **No** |

So the per-tender web-page scraping can be removed from ingestion. The three items the feed
lacks are minor, and they are in the PCAP anyway, so the document stage can read them when it
needs them.

---

## 6. What the pilot uses, and where it now comes from

The pilot has three sources: the feed entry, the tender's web page, and the documents.

### 6.1 The feed entry

The pilot already parses the feed in full (`pilot/placsp_pilot/codice.py`). Staging reads
everything that parser reads, plus: the authority's contact details, every identifier and the
identifiers of its parent bodies, the body that publishes on its behalf, deadlines for
participation requests, shortlist limits in restricted procedures, how many lots one bidder may
bid for and win, where bids are submitted, EU-journal send dates and times, minimum employees and
years of operation, the winner's nationality and subcontracting declared at award. (Checked
field by field in the subset test, section 9: no difference with the pilot's parser.)

**The pilot can read its tender data from staging instead of parsing feeds itself.**

### 6.2 The web page

The pilot visits each tender's page to list the documents: notices (offered as HTML, PDF and
XML) and "other documents" (memoria justificativa, minutes, reports, resolutions). On 40 random
tenders (section 9.4), 89% of the page's other documents are in the feed under the same name,
the rest are most likely later additions, and the notices are renderings of data the feed
already has. The page visit is only needed for external platforms whose feed entries carry no
links.

### 6.3 The documents (NER)

The pilot's ontology (`pilot/ontology/placsp_procurement.yaml`) against the feed:

| What the pilot extracts with NER | In the feed, structured | Needs the documents for |
|---|---|---|
| Contracting authority | **Yes**, complete with hierarchy and IDs | nothing |
| Company (winner) | **Yes**, with tax ID | other companies named in the documents |
| Joint venture (UTE) | Detected from the tax ID / name | the member companies and their shares |
| Lot | **Yes**, with budget and CPV | nothing (major contracts); names in thin channels |
| Award criterion with points | **Yes** for major contracts (92% in 2026) | the full formula, the envelope, sub-criteria; criteria for the thin channels |
| Requirement (turnover, insurance, similar work, team, credentials) | Partly: type and, in recent years, threshold amount | the content when the feed only points to the PCAP (~50%); years, number of people, accepted credentials |
| Classification (group, subgroup, category) | **Yes**, as a code | nothing |
| Qualification (degree, certification) | No | everything |
| Guarantee | **Yes** (type, percentage) | amounts when only a formula is given |
| Bid (other bidders, price, scores, rank, exclusion) | **No** — only counts and lowest/highest | everything: this is the main gap |
| Contract | **Yes** (ID, signing date, amount) | start and end dates when not in the feed |
| Modification | **Yes** where published (3%) | reasons, and those only in resolutions |
| Penalty | No | everything |
| Deliverable, team profile, technical requirement, service level | No | everything (technical specifications) |
| Other organisation (appeals tribunal…) | Only the number of appeals | which body, outcome |

---

## 7. What the second stage is for

From sections 3–6, the document stage is needed for:

1. **The competition.** Who else bid, at what price, with what scores, who was excluded and why.
   The feed publishes only the number of bids and the lowest and highest. These are in the
   evaluation and award documents (minutes of the evaluation board, award resolution).
2. **Requirement content behind pointers.** About half of the solvency requirements say "see the
   PCAP". The thresholds, years of experience, team sizes and accepted credentials are in the PCAP.
3. **The technical specifications (PPT).** Deliverables, team profiles, technologies, service levels.
   Nothing of this is in the feed. This is what profile matching will need most.
4. **Penalties, full scoring formulas, envelopes, offer validity, bid opening.**
5. **The three thin channels.** Regional platforms (only 46% have a PCAP link), minor contracts
   and in-house commissions publish no criteria or requirements at all. Minor contracts and
   in-house commissions rarely publish documents either, so for them the feed is essentially all
   there is.

What it is **not** needed for: anything about identity, money, dates, status, the authority,
the winner, lots, award criteria and weights in major contracts, guarantees, classification,
contracts and modifications. Those come from staging, for every tender, at no model cost.

This also defines how to prioritise the document stage: major contracts first (they have the
documents and the money), and within a tender, the PCAP only where the feed's requirements are
pointers, the PPT always, and the award documents whenever bids > 1.

---

## 8. Problems found in the current ingestion

| Problem | Where | Effect | Fix |
|---|---|---|---|
| Closed tenders are deleted | `Upserter.apply_tombstones`, `GraphSink.apply_tombstones` | Every tender the feed marks `CERRADA` — mostly awarded ones — is removed from search and from the graph | Keep them; staging records `removed_at` and `removed_reason` |
| Status history lost between years | `Pipeline.run_backfill` + `collapse` | A tender published in one year's archive and awarded in the next keeps only the later status | Staging merges every version of every year |
| Current year downloaded as the cumulative yearly ZIP | `core/catalog.py` | 1.9 GB downloaded again for each run, rebuilt daily by PLACSP | Finished months as monthly ZIPs, the current month from the live feed |
| Whole ZIP held in memory | `ingestion/fetcher.download` (`r.content`) | A 1.9 GB file is held in RAM | Streamed to disk |
| A web page fetched per tender during ingestion | `Pipeline.process_files` (Tier 1) | Millions of serial requests to PLACSP; nearly all of it is in the feed | Remove; read from staging |
| Requirements read from a scraped page | `pliego_html_parser.py` | Fragile, and the page layout changes over the years | Read `requirement` from staging |

---

## 9. Subset test — results

Run on the eight archives of section 3, which include the first year of each channel (major
contracts 2013, regional platforms 2016, minor contracts 2018) so that format changes over time
are covered. Rerun with `python scripts/check_staging.py data/zips/*/*.zip --every 3 --max 10000`.

### 9.1 No field is missed — passed

For every third entry (up to 10,000 per archive; 62,691 entries in total), the check records
every XML element the staging parser reads, then lists every element that carries a value but
was never read. The first run found these, all now read:

| Field | What it is | Fixed by |
|---|---|---|
| Times of the participation deadline, document availability and EU-journal sending | Only the dates were kept | new columns `participation_deadline_time`, `doc_availability_end_time`, `notice.sent_times` |
| Both texts of contract extensions | Only one of two was kept | `extension_validity` and `extension_options` |
| Where bids are submitted (`TenderRecipientParty`) | Not read | `tender_recipient` |
| Street address of the place of execution | Not read | `street` on tender and lot |
| Several activity codes, several funding codes | Only the first was kept | `auth_activity_codes`, `funding_codes` (lists) |
| Text on the required years of operation | Wrong element name in the parser | fixed |

After the fixes: **0 unread fields in all eight archives.** Five fields are skipped on purpose:
country names (the country code is kept) and the authority's fax number.

### 9.2 Nothing is lost relative to today — passed

On the same entries, the current app's extractor (`parsers/codice_extractor.py`) and the
pilot's parser (`pilot/placsp_pilot/codice.py`) were run next to staging's, and every value
they produce was looked up in staging's rows: 28 fields of the app (including per-lot winners and
bid statistics) and 12 groups of the pilot (criteria, requirements, guarantees, conditions,
results, winners, modifications, notices, documents, lots, authority hierarchy, subcontracting).

The first run found two differences, both in the regional platforms channel, neither a loss:
feeds there end the authority hierarchy with an empty parent (staging stored it as an empty
name; now skipped), and they identify authorities with their own scheme `ID_OC_PLAT` (staging
kept only NIF, DIR3 and the PLACSP ID; it now keeps every identifier with its scheme, in
`auth_ids`, and uses it to merge authorities). After the fixes: **0 differences.**

### 9.3 Versions merge correctly — passed, to be confirmed on the full run

- One row per tender: 917,985 rows, 917,985 distinct tenders.
- For every tender that appears in more than one archive (99 in this sample), the row kept is
  the latest version.
- A unit test (`tests/test_staging.py`) checks the case that matters: a tender published in
  one year's archive and awarded in the next keeps both statuses in its history, and a tender
  with a `CERRADA` marker is kept.

The sample archives are not consecutive years, so few tenders span two of them. The full run
(consecutive years) is the real test: the build will report how many tenders span archives
and how many have a history with more than one status.

Also from the build: 13,286 authorities (27% have no identifier at all and are merged by name
only), and 205,526 winning companies, 31% of which appear under more than one spelling of
their name, and 4,593 joint ventures (UTE).

### 9.4 The web page adds little — passed, with one caveat

For 40 random major-contract tenders, the tender's web page on PLACSP was compared with the
feed's documents. Links cannot be compared directly: the page gives every document a
session-specific encrypted link, so not one URL matched, even for the same document. By name:

- **Other documents** (memoria justificativa, minutes, reports, resolutions): 207 on the pages,
  185 of them (89%) also in the feed with the same name. The 22 that are only on the pages
  belong almost all to one or two 2019 tenders and are about a later modification and extension
  of the contract — published after the 2019 archive was cut, so they should be in a later
  archive. The full run will confirm it.
- **Notices** (call for tenders, award, formalisation, corrections…): the page offers each as
  HTML, XML and PDF. They are the platform's rendering of the same data the feed carries in
  structured form (164 notices on the pages, 138 in the sample's feed versions; the difference is
  again later notices). Their text adds nothing structured; the document stage can skip them.
- The feed's links (`DocumentIdParam=…`) are stable; the page's are not. **Staging's document
  table is the better source for the pilot's downloads.**

Conclusion: the web-page visit can go, from ingestion and from the pilot, except for external
platforms whose feed entries carry no document links (46% of regional-platform tenders have a
PCAP link in the feed).

---

## 10. The old ingestion, replaced

Ingestion now runs entirely through staging. `./scripts/placsp backfill | daily | reconcile` are:

| Command | Steps |
|---|---|
| `backfill`, `reconcile` | download missing archives → extract → build → load |
| `daily` | save the live feed since the latest staged update as an archive → extract → build → load |

**Load** (`src/placsp/staging/load.py`) turns each tender of the `current` tables into the
record the search index has always held (same properties, same summary text, same object id),
embeds it and writes it to Weaviate and to the company graph. It also writes the
`Placsp_pliego_criteria` object read by the pliegos modal and by the profile match, now built
from the feed's structured terms instead of the scraped web page, with more in it (solvency
requirements with thresholds, minimum years of operation, criteria per lot with their type).
The LLM extraction cached on that object (`pcap_json`, `ppt_json`) is carried over on reload. Only
tenders that changed since the last load are loaded again (`data/loaded.duckdb`).

The analysis endpoint (`placsp.api`) reads the pliego links from that criteria object instead of
fetching the web page again.

Removed: `ingestion/` (pipeline, `collapse`, page scraping, fetcher), `parsers/atom_parser.py`,
`parsers/codice_extractor.py`, `parsers/pliego_html_parser.py`, `core/catalog.py`,
`scripts/process_pliego.py`, the tombstone deletes in the upserter and the graph sink, and their
tests.

**Checked against the old extractor** (restored from git) on 8,449 entries of the eight
archives, comparing every property written to Weaviate. Differences, all intended:

| Property | Entries | Why |
|---|---|---|
| `contract_type`, `procedure`, `result_label`, `nuts_label`, and the summary text `content` that uses them | up to 4,147 | The old extractor looked codelists up by the versioned file name in the feed and often missed, storing the code (summaries said "Contrato de 1: …"). Staging matches on the name without the version and finds the label ("Contrato de Suministros: …"). Filters use the codes, which are unchanged. |
| `cpv` | 592 | The old one repeated a code once per lot; now each code once. |
| `submission_deadline` | 2 | In restricted procedures, the participation-request deadline when there is no tender deadline. |

New property: `removed_reason` (`ANULADA` or `CERRADA`, else empty), so the app can decide what to
show; nothing is deleted.

**Speed**: the loader handles about 3,000 tenders per second (1 GB of memory) with Weaviate and
the vectorizer mocked, so on the server the embedding model sets the pace. Tests: 38 pass.

## 11. Running it on the server

1. Deploy the branch; `./scripts/placsp init-schema` (adds `removed_reason` to the class in place).
2. `./scripts/placsp backfill`. Every step resumes if interrupted: rerun the same command.
   - Download: total size unknown until it runs (20 MB for 2013, 466 MB for 2019); the server gave
     0.6–15 MB/s.
   - Extract: about 3,400 entries per second with four workers on the development Mac.
   - Load: every tender is embedded once. All summaries changed (labels), so nothing from the
     current index can be reused. Tenders deleted by the old ingestion come back.
3. Then cron: `daily` every day, `reconcile` on the 2nd of each month (the month just finished).
4. Watch-outs:
   - The build is a full rebuild each run (6 s for 0.9 M tenders here); check its time on the full data.
   - The graph is written with batched `MERGE`; if the first load is too slow, a one-off bulk import
     (`neo4j-admin database import` from the Parquet tables) is the fallback.
   - If Weaviate is emptied, delete `data/loaded.duckdb` so the next load writes everything again.
   - Live archives (`zips/<channel>/live_*.zip`) accumulate; they are small and their versions are
     superseded by the monthly archives, but they are not pruned yet.

## 12. Then

Adapt the web app and integrate the pilot on top of the staged data.

### A note on search: keyword search with facet counts

The search app asks Weaviate for two things at once: results ranked by keyword or meaning, and
counts per category (how many results per region, status, procedure…) for the same query.
Weaviate is built for the first; its counts (`Aggregate`) cannot use the hybrid ranking, so the
app computes them as a separate exact-match query, and counting over millions of rows is not what
it is optimised for.

Two options for the web-app phase:

- **A search engine built around counts**, such as OpenSearch (or Elasticsearch). Counting per
  category for any query is its core feature, it has Spanish text analysis, and it also does
  vector search, so one engine could serve keyword, meaning and counts together. This is the
  recommendation, to be confirmed with a benchmark on the full data.
- **Keep a vector store for meaning, and answer counts from DuckDB over the staged tables.**
  No new server, and counts over the full table are fast, but every query then touches two
  systems and their results must be combined.
