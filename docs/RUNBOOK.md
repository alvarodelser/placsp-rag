# PLACSP One-Feed End-to-End Validation Runbook

This runbook validates the PLACSP ingestion pipeline against a real running deployment (Weaviate + Vectorizer). It must be executed from a host with network access to the deployment services.

> **Full server deploy + test checklist:** see [DEPLOYMENT.md](DEPLOYMENT.md). This runbook
> is the focused one-feed validation that DEPLOYMENT.md references.

## Prerequisites

- The **dedicated PLACSP Weaviate** instance running (see `deploy/weaviate/`), plus the
  shared Vectorizer (`vectorizer:8089`, BGE-M3) reachable.
- Environment variables set (host-run commands below assume the published port):
  - `WEAVIATE_URL` — `http://localhost:8087` (host) or `http://placsp-weaviate:8080` (in Docker)
  - `WEAVIATE_API_KEY` — the key configured in `deploy/weaviate/.env` (sent as `Authorization: Bearer`)
  - `VECTORIZER_URL` — `http://localhost:8089` (host) or `http://vectorizer:8089` (in Docker)
  - `PLACSP_CODELIST_DIR` — Directory for cached codelists (e.g., `./codelists`)
  - Optional: `PLACSP_EMBED_BATCH`, `PLACSP_MAX_IN_FLIGHT` for throughput tuning
- Use `python3.11` (the target interpreter); from a source checkout, `pip install -e .`.

## Step 0: Bring up the PLACSP Weaviate (Run on Deployment Host)

```bash
cd deploy/weaviate && cp .env.example .env   # set a strong WEAVIATE_API_KEY in .env
docker compose up -d
curl -s http://localhost:8087/v1/.well-known/ready && echo " READY"
```

## Step 1: Initialize Schema (Run on Deployment Host)

Create the Weaviate schema for the first time (or verify existing schema).

```bash
export WEAVIATE_URL=http://localhost:8087
export WEAVIATE_API_KEY=<same key as deploy/weaviate/.env>
export VECTORIZER_URL=http://localhost:8089
python3.11 -m placsp init-schema
```

**Expected output:** "created" or confirmation that schema exists.

## Step 2: Populate Codelists (Run on Deployment Host)

Download all CODICE `.gc` codelists referenced by a sample feed into the cache directory.

```bash
export PLACSP_CODELIST_DIR=./codelists
python scripts/fetch_codelists.py tests/fixtures/mayores.atom $PLACSP_CODELIST_DIR
```

**Expected behavior:**
- Script scans `mayores.atom` for all `listURI` and `listURIID` attributes
- Downloads each `.gc` codelist to the cache directory
- Prints "ok <filename>" for successful downloads
- Prints "skip <filename> <status_code>" for non-200 responses
- Prints "err <filename> <exception>" for network/parsing errors

**Note:** If codelists are already cached, you may safely re-run this step.

## Step 3: Ingest One Feed/Year (Run on Deployment Host)

Process a single year of procurement data to verify end-to-end ingestion.

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

**Expected output:** A dictionary with keys:
- `records` — number of records parsed from the feed (should be > 0)
- `upserted` — number of records successfully upserted to Weaviate
- `deleted` — number of tombstone deletions applied

Example:
```json
{"records": 1234, "upserted": 1200, "deleted": 5}
```

**Troubleshooting:**
- If `records = 0`, verify the URL is accessible and the feed format is valid
- If `upserted = 0`, check Weaviate and Vectorizer connectivity
- If `deleted > 0`, this indicates tombstone records were processed (normal for incremental feeds)

> ⚠️ **Do not trust `upserted` alone.** Weaviate's batch endpoint returns HTTP 200 even
> when individual objects fail (e.g. a date-typed property rejecting a non-RFC3339 string),
> and the current `Upserter.upsert` does not inspect per-object results (see
> [FOLLOWUPS.md](FOLLOWUPS.md) #1). **Verify the actual stored count:**
>
> ```bash
> python3.11 - <<'PY'
> import httpx
> from placsp.config import load_config
> cfg = load_config()
> q = '{Aggregate{%s{meta{count}}}}' % cfg.weaviate_class
> r = httpx.post(cfg.weaviate_url.rstrip("/")+"/v1/graphql", json={"query": q},
>     headers={"Authorization": f"Bearer {cfg.weaviate_api_key}"} if cfg.weaviate_api_key else {})
> print(r.json())
> PY
> ```
>
> The reported `count` should match `upserted`. A large gap means objects were silently
> rejected — inspect a single object POST response body for per-object `errors`.

## Step 4: Verify Retrieval Quality (Run on Deployment Host)

Test vector search and BM25 hybrid retrieval to confirm data quality.

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

**Expected output:** JSON with 3 search results containing:
- `syndication_id` — unique identifier for the contract
- `title` — Spanish contract title (readable)
- `content` — natural language summary (readable Spanish)
- `estado` (status_label) — decoded status (not raw code)
- `awarded_amount` — numerical contract amount

**Quality checks:**
- All 3 results relate to "cleaning services" (or similar semantic match)
- Status labels are human-readable (e.g., "Formalizado" not "01")
- Content is coherent Spanish text
- No null or empty critical fields

## Step 5: Document Findings

After running the validation steps above, record your observations in the section below:

### Observed Metrics

- **Throughput:** _____ entries/minute
- **Embed batch size (`PLACSP_EMBED_BATCH`):** _____ (recommended)
- **Max in-flight (`PLACSP_MAX_IN_FLIGHT`):** _____ (recommended)
- **Off-peak window:** _____ (e.g., "00:00–06:00 UTC")

### Codelist Coverage

List any missing or unreachable codelists encountered during Step 2:

- \_\_\_\_\_

### Field Coverage & Surprises

Note any fields that were unexpectedly empty, null, or malformed:

- \_\_\_\_\_

### Summary

Confirm here that all 4 steps completed successfully and retrieval quality is acceptable:

- [ ] Schema initialized
- [ ] Codelists downloaded
- [ ] Feed ingested with records > 0
- [ ] Retrieval results show relevant contracts with readable content

---

## Rollback / Cleanup

To clear ingested data for re-testing:

```bash
# Delete all documents from the class (Weaviate GraphQL):
python - <<'PY'
import httpx, json
from placsp.config import load_config

cfg = load_config()
gql = '{Get{%s(limit:1){_additional{id}}}}' % cfg.weaviate_class
r = httpx.post(cfg.weaviate_url.rstrip("/")+"/v1/graphql", json={"query": gql},
               headers={"Authorization": f"Bearer {cfg.weaviate_api_key}"} if cfg.weaviate_api_key else {})
print("Current class has documents; delete via Weaviate console if needed")
PY
```

Or delete the entire class and re-run Step 1.
