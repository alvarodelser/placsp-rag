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
             OCR for PDFs without a text layer
classify     /nli for documents the rules could not label
summarize    /summarize article: one gist per document
ner          /ner on ~512-word chunks with ontology/placsp_procurement.yaml
resolve      /resolve per document
describe     /summarize entity_desc and relation_desc
consolidate  /summarize aggregate: one description per expediente, one per company seen in
             several documents
graph        out/nodes.jsonl, out/edges.jsonl, out/expedientes/<id>.json
index        Qdrant + Neo4j (rebuilds the pilot namespace; embeddings cached in pilot.db)
validate     every expediente from feed to stores -> validation table, out/validation.csv
report       out/report.md, out/metrics.json
```

`summarize → ner → resolve → describe` is Phase A of `nlp_service`'s relation pipeline,
called over HTTP. Coreference is skipped, because `nlp_service` doesn't expose it over HTTP.

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
- **Added:** Notice, Guarantee, ExecutionCondition, Modification, Penalty, Deliverable, TeamProfile and TechnicalRequirement. Document roles go beyond the model's list too: preparatory documents, valuation and abnormal-bid reports, appeals, project and technical annexes, notices.
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

**Validation.** Every expediente gets about 29 checks, recorded in the `validation` table and in
`out/validation.csv`:
- the feed's required fields;
- every reference downloaded, and the SHA-1 checked against the feed's `DocumentHash`;
- text extracted, documents ordered;
- every NLP output present: one summary per document, every selected chunk through NER, one
  resolution per document, one description per entity and relation, the tender description;
- the counts in Qdrant and Neo4j: documents in order, the chain, lots, chunks, winners.

`fail` means the pilot did not do its job. `warn` means the published data is incomplete: a
missing pliego, criteria that don't add up to 100, or the source returning HTTP 500.

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
| `PILOT_NER_SKIP_ROLES` | (none) | Roles to leave out of NER, e.g. `Annex,ProjectDocument,TechnicalAnnex`. |
| `PILOT_NER_PREFLIGHT_S` | 60 | The `ner` stage stops if its first two calls each take longer (Ollama on the CPU, thinking on). |
| `PILOT_DESCRIBE_RELATIONS` | 1 | Describe relations as well as entities. |
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

## Tests

```bash
.venv/bin/python -m pytest -q        # unit tests + full NLP flow against tests/fake_nlp.py
# also index + validate against real stores (uses pilottest_* / PilotTest and cleans up):
PILOT_TEST_QDRANT_URL=http://localhost:6343 PILOT_TEST_QDRANT_API_KEY=... PILOT_TEST_NEO4J_PASSWORD=... .venv/bin/python -m pytest -q
```
