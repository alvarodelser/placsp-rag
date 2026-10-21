# PLACSP document pilot

Fully processes a sample of PLACSP expedientes — every document of every expediente — into a
GraphRAG-style graph, and measures how long that takes and how much it weighs.

It runs in its own package and virtualenv and never touches the app's data. Its working state
(downloaded files, extracted text, every timing) lives in one run directory. Its results are
indexed into our stack's stores under a pilot namespace: `pilot_*` collections in Qdrant, and nodes
labelled `Pilot` in Neo4j. It runs no model of its own; all NLP goes through the services already
on the server.

| Service | Used for | Env var |
|---|---|---|
| `nlp_service` | `/nli` document type, `/summarize` gists and descriptions, `/ner`, `/resolve` | `NLP_SERVICE_URL` (required) |
| OCR service | scanned PDFs (`/services/ocr`) | `OCR_URL` (optional; without it scanned PDFs are counted as `needs_ocr`) |
| BGE-M3 vectorizer | embeddings of chunks, tenders and entities (`/embed`) | `VECTORIZER_URL` (required for `index`) |
| Qdrant (`placsp-qdrant`, docker-compose) | `pilot_tenders`, `pilot_chunks`, `pilot_entities` | `QDRANT_URL`, `QDRANT_API_KEY` |
| Neo4j (`placsp-neo4j`, docker-compose) | the pilot graph | `NEO4J_URL`, `NEO4J_USER`, `NEO4J_PASSWORD` |

Both stores are reached through their official clients, `qdrant-client` and the `neo4j` driver.

## What it does

```
select       latest expedientes per channel from the live ATOM feeds (default 50 mayores,
             20 externos, 15 menores, 15 encargos)
discover     detail pages: PLACSP notices (html/xml/pdf, one kept) and "otros documentos";
             external platforms (Madrid, Navarra...) through a generic link scraper
fetch        every document referenced by the feed (PCAP, PPT, anexos, documentos generales,
             actas and contratos attached to notices) and by the detail pages; deduplicated by SHA-256
text         pdf, html, doc/docx/odt, xls/xlsx, pptx, bc3, rtf, zip (members become documents);
             OCR for PDFs without a text layer. PDFs of the roles where structure matters (pliegos,
             actas, reports, resolutions, contracts…) get the layout pass: Markdown with headings,
             tables as rows and reading order, and where the page headers, footers, headings and
             tables are (<sha>.layout.json beside the text)
classify     /nli for documents the rules could not label
summarize    /summarize article: one gist per document
ner          /ner on ~512-word chunks, with the schema of the document's role (ontology `profiles`):
             only what the feed does not give. Every document is chunked and stored; NER reads
             the roles a profile lists, a PCAP only in its relevant sections, up to
             PILOT_NER_MAX_CHUNKS per document
mentions     every NER item becomes a mention, located in its chunk (offsets, page); then
             locate.py finds the feed's own entities in the text without the model (see "Entities")
resolve      per expediente: feed anchors, keys, near-identical names, then /resolve type by
             type over all documents -> one entity per real thing (see "Entities" below)
coref        /coref/links on the passages that carry references ("la empresa", "la adjudicataria",
             "dicha entidad"...): each becomes a mention of the entity it points at, with offsets
refine       /ner with a narrow schema per requirement and award criterion: thresholds, units,
             periods, accreditation; a criterion's scoring method (proportional to the lowest
             price, linear on the discount, per unit, tiers, yes/no...), what is offered, its
             direction, saturation threshold, abnormally-low rule, minimum score, sub-criteria
formulas     /summarize criterion_formula: each criterion scored by a rule, as an expression
describe     /summarize once per entity (requirement_desc, criterion_desc, else entity_desc)
             from all its passages and fields, and once per relation
summary      /summarize aggregate: one description per expediente, from its document
             summaries in lifecycle order, each headed by position, role and date
graph        out/nodes.jsonl, out/edges.jsonl, out/expedientes/<id>.json
index        Qdrant + Neo4j (rebuilds the pilot namespace; embeddings cached in pilot.db)
validate     every expediente from feed to stores -> validation table, out/validation.csv
report       out/report.md, out/metrics.json
```

`nlp_service` splits entity resolution into three scopes: coreference inside the text (not
exposed over HTTP, so skipped), `/resolve` within one document, and a cross-document merge
(`/dedup/corpus`, its relation pipeline's Phase B). The corpus dedup reads Weaviate, so the
pilot does the cross-document step itself, per expediente, and uses `/resolve` (stateless)
for the doubtful merges.

## Entities

**What NER looks for.** The ontology marks each type `source: feed` (authority, lots, criteria and
points, solvency, guarantees, contracts: CODICE gives them structured) or `source: documents`
(bids and their scores, UTEs, penalties, deliverables, team profiles, technical requirements,
qualifications, modifications' reasons, appeals). `/ner` gets one schema per document role
(`profiles`): actas, valuation reports and award resolutions are read for bids and per-criterion
scores; the PCAP for penalties and qualifications; the PPT for deliverables, team profiles and
technical requirements; notices, annexes, project and preparatory documents not at all. A feed
type is asked for only where the expediente's feed lacks it (`fallback`: an external platform
without criteria, solvency that only says "según cláusula 8ª PCAP"). Document types point at the
feed's entities by key attributes, not relations: a bid's `lot`, `bidder` and `bidder_nif`, a
score's `bidder` and `criterion`. The bidder becomes a company mention with `SUBMITTED_BY`, a score
hangs from its bid (`HAS_SCORE`) and its criterion (`FOR_CRITERION`), without the model.

**Feed entities in the text** (`locate.py`). The feed's entities are found where the documents name
them, so they carry the same provenance as an NER mention and refine, describe and the summary
read their passages: criteria by their words on a short line (a one-word name only beside its
points), lots by "Lote 2" / "lote nº 3", the authority and winners by NIF and name, guarantees
by type, and a requirement that only points at the pliego at that clause's heading ("CLÁUSULA
OCTAVA", "9.1" inside "ANEXO I", "X. C)"), table-of-contents lines excluded. Each find is a
mention of kind `feed` with the feed node as `target`. On 50 recent mayores and externos: 195 of
197 criteria, 64 of 66 lots, 26 of 28 guarantees, and 25 of 28 pointing requirements found.

**Structure** (`sections.py`). The text is never changed. Page furniture (letterheads, "Página 3
de 18", "Cód. Validación…", signature stamps, running titles) is detected, from the layout's
header and footer boxes when they recur or are short, and from lines that recur at the top or
bottom of most pages: the reader keeps it to place pages, while headings, NER, embeddings and the
locator skip it (about 7% of the words of a pliego or an acta). Headings are numbered lines
("CLÁUSULA OCTAVA", "9.1", "ANEXO I", "B)"), Markdown headings, the layout's section headers and
paragraphs that open with a bold or underlined numbered run; never an index line, a table row, a
bidder line or furniture. Their levels make each document's section tree. New texts are chunked
at sections (`PILOT_CHUNKER=sections`): a chunk starts at a top-level section once the current one
holds half the budget, keeps sub-sections whole, cuts a longer section at paragraphs and a table
at rows, and carries its section path (chunk.section, the Qdrant payload, and the head of what NER
reads). Texts extracted before keep the word chunker, so their stored NER results stay valid.

What NER finds in each chunk is a **mention**. Resolution turns the mentions of all of an
expediente's documents into **one entity per real thing**:

1. **Feed anchors.** A mention of a lot, criterion, requirement, guarantee, the authority (and
   its own bodies, such as the Mesa de Contratación), a winner or the contract joins the feed's
   node. A criterion is matched by name and points (an acta's score of 0 is not a weight).
2. **Keys.** NIF, lot number, guarantee type, normalised name (accents, punctuation and legal
   forms removed).
3. **Near-identical names.** Same words up to typos (`SESRVICIOS` = `SERVICIOS`); names that
   differ in a code (ENI-03 / ENI-04) never merge.
4. **The model.** What is left goes to `/resolve`, one call per type, with every document's
   candidates; two feed nodes are never merged, nor criteria with different points.

Organizations (by NIF, else normalised name) and qualifications are shared across expedientes;
everything else belongs to one. When the feed only points at the pliego ("según cláusula 8ª
PCAP"), the PCAP's requirements are linked to that line with `DETAILED_BY`. Values that
disagree between sources (the feed says *fórmula*, the PCAP *juicio de valor*) are kept as
`conflicts`, never silently overwritten; feed values win.

**References.** An entity is named a few times and referred to many more: "la empresa", "la
adjudicataria", "dicha entidad", "el mismo". The `coref` stage sends the passages that contain
such expressions, with the expediente's known organizations, lots and contracts, to
`nlp_service`'s `/coref/links`, which quotes each reference and the entity it points at (generic
uses, such as "el contratista" in a pliego, are left alone). Each reference becomes a mention of
kind `coref`, located like any other, so it is evidence too: descriptions and the expediente
summary read it. It costs one call per passage with references (39 of 61 in the smoke run).

**Provenance.** Every mention keeps its chunk, character offsets of its quote and of the name
inside it, and page. In Neo4j:
`(entity)-[:MENTIONED_IN {quote, char_start, char_end, page}]->(Chunk)<-[:HAS_CHUNK]-(Document)`;
in Qdrant, each chunk lists its mentions and each entity its provenance. Requirements and
criteria are refined from their passages and described with `requirement_desc` /
`criterion_desc`, which keep every figure, unit and standard literally (they are in
`nlp_service`; with an older `nlp_service` the pilot falls back to `entity_desc`).

`ontology/placsp_procurement.yaml` is in `nlp_service`'s ontology format. It can be copied to
`nlp_service/config/ontologies/` and run by the relation pipeline unchanged.

## Data model, adjusted to what is published

The feed (CODICE) provides the skeleton: authority, tender, lots, notices, criteria and points,
solvency requirements, guarantees, execution conditions, results with winners, contracts and
modifications. The documents add a Document node each (role, gist) plus the entities and relations
NER finds in them, attached to that skeleton:

- `LOT` entities map onto the feed's lots (by number, name, or the only lot).
- Companies merge by NIF across the whole run (or by normalised name when there is no NIF).
- Other entities merge by name within an expediente.
- Document criteria are linked `SAME_AS` to the feed criteria they repeat.

The following changes were made to the given model:
- **Added:** Notice, Guarantee, ExecutionCondition, Modification, Penalty, Deliverable, TeamProfile, TechnicalRequirement, CriterionScore (what a bidder offered and scored in one criterion, losing bidders included) and Appeal. Document roles go beyond the model's list too: preparatory documents, valuation and abnormal-bid reports, appeals, project and technical annexes, notices.
- **Not extracted:** envelopes' contents, bid teams (Person) and good-execution certificates. They are not published.
- **Derived, not stored:** roles (client, awarded, partner, competitor), as the model says.
- **Not applicable to menores and encargos:** they are published already awarded, with no pliegos. They are still processed, and marked `analysable: false` with the reason.

## What gets indexed

There is one unified object per tender, not one object per document type. Every document of
an expediente is kept, ordered and linked, but the metadata lives in a single place.

**Qdrant**
- **`pilot_tenders`** has one point per expediente: the unified Tender. Its payload holds:
  - the feed's facts;
  - `lots[]`, each with `award_criteria`, `requirements` (and their qualifications), `scope`,
    `bids` (with bidders), `result` (with winners), `awarded_to` and `contracts`;
  - `guarantees`, `execution_conditions`, `modifications`, `notices` and a merged `timeline`;
  - `companies[]` with their roles, plus `company_nifs` and `winner_nifs`;
  - `documents[]` in order. Each has a `seq`, effective date, role, title, summary, `sha256`,
    source URL and the stored file's path. The files themselves stay in the run directory, so
    they can always be retrieved.

  Vector: the tender's description. Indexed for filtering: channel, status, type, procedure,
  CPV, NUTS, `published_at`, value, authority NIF, company and winner NIFs, document roles.
- **`pilot_chunks`** holds every ~512-word chunk of every document. Each payload has the tender,
  `doc_sha256`, `doc_seq`, `doc_role`, `chunk_idx`, `page_from`/`page_to` and `entity_ids` (the
  graph nodes the chunk mentions), plus the text. Vector: the text.
- **`pilot_entities`** holds the graph entities with their descriptions and `tender_ids`.
  Vector: name plus description.

Point IDs are deterministic (UUIDv5), so re-indexing overwrites instead of duplicating.

**Neo4j:** the same graph, with every node labelled `Pilot` and `Pilot<Type>` so it can't
collide with the app's `Company`/`Lot`/`Contract` constraints. Uniqueness is enforced on
`(:Pilot {id})`. The relationships are:

```
(PilotOrganization)-[:PUBLISHED]->(PilotTender)-[:HAS_LOT]->(PilotLot)-[:HAS_CRITERION|REQUIRES|INCLUDES|HAS_RESULT|RECEIVED_BID]->...
(PilotTender)-[:HAS_DOCUMENT {seq, effective_date, stage, role}]->(PilotDocument)-[:NEXT_DOCUMENT {tender}]->(PilotDocument)
(PilotDocument)-[:CONCERNS]->(PilotLot|PilotResult|PilotContract|PilotModification)
(PilotDocument)-[:HAS_CHUNK]->(PilotChunk)-[:NEXT]->(PilotChunk)-[:MENTIONS]->(entity)
(entity)-[:EXTRACTED_FROM]->(PilotDocument); NER relations (BID_FOR, SUBMITTED_BY, AWARDED_TO, ...) between entities
```

Chunk text is stored only in Qdrant; each Chunk node carries its `qdrant_id`.

**Document order.** Each document's effective date is its own publication date, else the date of
the notice it came with, else the date of its lifecycle stage. Documents are sorted by that date,
then by stage (preparation → notices → pliegos → clarifications → evaluation → award →
formalisation → execution), then by role within the stage (PCAP before PPT before annexes).

**Validation.** Every expediente gets about 40 checks, recorded in the `validation` table and in
`out/validation.csv`:
- the feed's required fields;
- every reference downloaded, and the SHA-1 checked against the feed's `DocumentHash`;
- text extracted, documents ordered;
- every NLP output present: one summary per document, every selected chunk through NER, the
  tender description;
- entities: every mention placed on an entity and located in its chunk, no duplicates (same
  type and name) and no near-duplicates left, every entity and relation described, every
  requirement and criterion refined, requirements whose passages state a figure carry it,
  disagreements between sources listed;
- the counts in Qdrant and Neo4j: documents in order, the chain, lots, chunks, winners, one
  `MENTIONED_IN` edge per mention.

`fail` means the pilot did not do its job. `warn` means the published data is incomplete: a
missing pliego, criteria that don't add up to 100, or the source returning HTTP 500.

## Levels

The pilot is levels 1.5 and 2 of `docs/PIPELINE_LEVELS.md`; level 1 is the staging tables.
- `python -m placsp_pilot rules --staging <data dir> …`: stage 1.5, no model. Select from the
  staging tables (any year; `--themes`, `--quota`, `--years`, `--awarded`, `--ids`), discover,
  fetch, extract text (layout pass, sections), plan the chunks NER will read, summarise notices
  from the feed, and locate the feed's entities. It prints what it leaves for the model.
- `python -m placsp_pilot nlp`: stage 2 on the same files. It skips what the feed settles: the
  actas of tenders where every lot had one bid, descriptions of feed entities (written from
  their fields), notices' summaries; bidders' NIFs come from the staging `company` table first.

## Run on the server

```bash
cd placsp/pilot
python3.11 -m venv .venv && .venv/bin/pip install -e .     # or: uv venv && uv pip install -e .
apt-get install -y antiword                                 # optional: legacy .doc files

export NLP_SERVICE_URL=http://localhost:4200    # nlp_service (NLP_PORT); http://nlp-service:8000 inside b4c-net
export OCR_URL=http://localhost:8084            # OCR service
export VECTORIZER_URL=http://localhost:8089     # BGE-M3
export QDRANT_URL=http://localhost:6343 QDRANT_API_KEY=...       # placsp-qdrant (docker compose up -d placsp-qdrant)
export NEO4J_URL=bolt://localhost:7689 NEO4J_PASSWORD=...        # placsp-neo4j (NEO4J_BOLT_PORT=7689: 7687 is taken on the server)
export PILOT_RUN_DIR=/opt/placsp/pilot_runs/$(date +%F)

# 0. nlp_service's Ollama must run on the GPU with thinking off (see "Before running" below).
# 1. Calibrate on 10 expedientes, read out/report.md.
.venv/bin/python -m placsp_pilot run --quota placsp_mayores=5,externos_mayores=2,placsp_menores=2,propios=1
# 2. Top up to the full sample in the same run dir (selection only adds the missing ones).
nohup .venv/bin/python -m placsp_pilot run > $PILOT_RUN_DIR/run.log 2>&1 &
```

**Growing the sample.** `./add.sh [N]` (default 20) selects N more expedientes with `run --add N`:
spread evenly over the themes plus `otros` (an entry in no theme) and, within each theme, over
contract types, counting what the run already has, then processes them under `nohup`. It reads the
exports above from `~/.placsp_pilot.env` and the run dir from `PILOT_RUN_DIR` (default
`~/pilot_runs/themes`). `./add.sh 0` finishes an interrupted run without adding any.

**Before running.** Check that `nlp_service`'s Ollama has the GPU and that thinking is off.
On the server, `ollama_high` once lost its GPU after a host `systemctl daemon-reload`
(`docker exec ollama_high nvidia-smi` gave `Failed to initialize NVML`), and gemma4:31b ran on
the CPU: 3.5 min per call against about 1 s on the L40. `docker restart ollama_high` brings the
GPU back. `docker exec ollama_high ollama ps` must show `100% GPU`, and `nlp-service` must run
with `OLLAMA_THINK=false`. The `ner` stage stops by itself if two calls in a row take longer
than `PILOT_NER_PREFLIGHT_S`.

Every stage is resumable: rerun the same command after an interruption. `--retry-failed` puts
failed downloads and service calls back to pending. Single stages run with
`python -m placsp_pilot <stage>`.

Tuning (environment):

| Variable | Default | Meaning |
|---|---|---|
| `PILOT_NER_MAX_CHUNKS` | 60 | NER chunks per document (0 = all). Over it, the chunks richest in procurement vocabulary are kept; the report says how many were left out and how long they would take. |
| `PILOT_CHUNK_WORDS` | 512 | Words per NER chunk (same as `RELATIONS_CHUNK_TOKENS`). |
| `PILOT_NER_SKIP_ROLES` | (none) | Roles to leave out of NER, besides those no profile lists. |
| `PILOT_LAYOUT_ROLES` | pliegos, actas, reports, resolutions, contracts, modifications, clarifications, appeals, notices | Roles whose PDFs get the layout pass (`*`: all). About 0.3 CPU-seconds per page. |
| `PILOT_STAGING_DIR` | (none) | Level 1 data dir: bidders' NIFs by name from its `company` table (`--staging` sets it too). |
| `PILOT_DESCRIBE_FEED` | template | `template`: feed entities and rule-drawn links described from their fields; `model`: by `/summarize`. |
| `PILOT_CHUNKER` | sections | How new texts are chunked: `sections`, or `words` (nlp_service's chunker). |
| `PILOT_NER_BY_SECTION` | 1 | Read a PCAP only under the headings that hold penalties, solvency, criteria, guarantees, and in chunks whose words cue a type asked for. 0: every chunk. |
| `PILOT_NER_PREFLIGHT_S` | 60 | The `ner` stage stops if its first two calls each take longer (Ollama on the CPU, thinking on). |
| `PILOT_DESCRIBE_RELATIONS` | 1 | Describe relations as well as entities. |
| `PILOT_COREF` | 1 | Link references ("la empresa", "la adjudicataria") to their entities: one call per NER'd passage that has them. |
| `PILOT_NLP_WORKERS` | 2 | Concurrent calls to nlp_service. |
| `PILOT_FETCH_WORKERS` | 4 | Concurrent downloads and text extraction. |
| `PILOT_MAX_FILE_MB` | 200 | Larger files are recorded but not downloaded. |

## Dry run on this machine (2026-10-17)

This ran against the real `placsp-qdrant` and `placsp-neo4j` containers from our compose file.
Indexing 100 tenders, 29,197 chunk points, 3,313 entities and 33,700 Neo4j nodes took 44 s.
Validation ran 2,902 checks: 0 fail and 32 warn. The warnings are 5 documents PLACSP answers
with HTTP 500, 5 expedientes with no published PCAP, 4 with criteria that don't add up to 100,
and a few files with no text layer or of an unsupported type.

**What this dry run does not show:** whether the extraction is right. All NLP output here
(summaries, NER entities, descriptions) came from `tests/fake_nlp.py`, which returns placeholder
text and regex matches. The `nlp.*` checks only show that every expected output exists in the
right number. The feed, document, order and index checks ran on real data and real stores.
Extraction quality can only be measured on the server, against the real `nlp_service`.

Download and text figures are real; NLP times are not.

- 1,586 document references, 888 unique files: 1.36 GB, 20,930 PDF pages, 90 M characters.
- Download plus text extraction took 6 minutes.
- Largest expediente: 647 MB and 33 M characters (an obra with one project PDF per site).
- 29,000 NER chunks in total; 10,770 with the cap of 60 per document. PCAP: 2,851 of 3,470.
- NER is the cost to watch: at `t` seconds per `/ner` call, the capped sample is about
  `10,770 × t / PILOT_NLP_WORKERS` seconds. The calibration run gives `t`.

## Viewer

The pilot has its own screens in the search UI, at `#/pilot` (user menu → *Piloto documental*).
They read only `/api/pilot` (`search-api/pilot_api.py`), which reads only the pilot namespace.

- **Expedientes:** semantic search over the tenders, then the unified tender: summary,
  lots with criteria (feed and document side by side), solvency, results, documents in
  lifecycle order with their summaries and files, and the tender's graph.
- **Grafo:** a force-directed canvas after `Projects/company_dataset`'s (what a thing is part of is
  a short, stiff spring; bids are company–lot links; documents hang only from their tender), or
  lanes (documents | expediente | pliegos | result). Clicking a node shows its description,
  refined fields, discrepancies and every mention with its passage.
- **Documento:** a document as the pipeline read it, chunk by chunk, with every mention
  highlighted (named: filled; reference such as "la empresa": underlined) and page links to the
  stored PDF. Every mention in a panel opens here at its place.
- **Explorar:** the whole pilot as one graph: tenders, authorities, companies (by role),
  qualifications, CPV sectors. Double-click a tender to unfold its own graph in place.
- **Empresa:** every tender a company or authority appears in, with its role, the companies
  it competes with and the authorities it works for.
- **Preguntar:** GraphRAG retrieval without generation: the closest chunks, the closest
  entities, and each entity's neighbourhood in the graph.

`/api/pilot/health` checks Qdrant, Neo4j and the vectorizer one by one; the home page shows any
that fails (without the vectorizer there is no search by meaning and no Preguntar).

On the server, `placsp-search-api` reads the pilot collections in `placsp-qdrant` with
`QDRANT_API_KEY`. The originals are not served: the viewer shows each one from its PLACSP link,
in a frame. Then rebuild: `docker compose up -d --build placsp-search-api`, and the UI.

## Tests

```bash
.venv/bin/python -m pytest -q        # unit tests + full NLP flow against tests/fake_nlp.py
# also index + validate against real stores (uses pilottest_* / PilotTest and cleans up):
PILOT_TEST_QDRANT_URL=http://localhost:6343 PILOT_TEST_QDRANT_API_KEY=... PILOT_TEST_NEO4J_PASSWORD=... .venv/bin/python -m pytest -q
```
