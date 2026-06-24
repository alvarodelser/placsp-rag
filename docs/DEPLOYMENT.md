# PLACSP — Deployment Reference

## Services

All services are defined in `docker-compose.yml` and launched with:

```bash
cp .env.example .env   # set WEAVIATE_API_KEY and NEO4J_PASSWORD
docker compose up -d
```

| Container | Role | Port(s) |
|---|---|---|
| `placsp-weaviate` | Vector store (Weaviate 1.28) | `8087` (HTTP), `50052` (gRPC) |
| `placsp-neo4j` | Company graph (Neo4j 5) | `7474` (browser), `7687` (Bolt) — localhost only |
| `placsp-search-api` | Search API (FastAPI/uvicorn) | `8092` — localhost only |
| `placsp-init-schema` | One-shot: creates Weaviate schema | — |
| `placsp-init-graph` | One-shot: creates Neo4j constraints | — |

**Volumes:** `placsp_weaviate_data`, `placsp_neo4j_data`, `placsp_feedback_data` — persisted across restarts, removed only by `docker compose down -v`.

## External dependencies

| Service | Default address | Used by |
|---|---|---|
| BGE-M3 vectorizer (iarag project) | `host.docker.internal:8089` | `placsp-search-api`, ingester |

To reach the vectorizer by container name instead, uncomment the `networks:` block at the bottom of `docker-compose.yml` and set it to the vectorizer's Docker network.

## Startup sequence

On `docker compose up -d`:

1. `placsp-weaviate` and `placsp-neo4j` start.
2. `placsp-init-schema` polls Weaviate until ready, then runs `python -m placsp init-schema` (idempotent).
3. `placsp-init-graph` waits for Neo4j and for `placsp-init-schema` to complete, then runs `python -m placsp init-graph` (idempotent).
4. `placsp-search-api` starts after `placsp-init-schema` completes.

## Ingestion

Ingestion runs on the **host** (not in Docker), talking to published ports.

`scripts/placsp` is the entrypoint — it auto-creates the venv, installs the package, and populates codelists on first run:

```bash
./scripts/placsp <command>
```

| Command | What it does |
|---|---|
| `init-schema` | Creates or verifies the Weaviate schema |
| `daily` | Pages the live feed, upserts new records, applies tombstones |
| `backfill` | Ingests historical data; self-gates to the off-peak window |
| `reconcile` | Monthly full reconcile against the live feed |

Scheduled via cron (example):

```cron
15 3 * * *   cd /opt/placsp && ./scripts/placsp daily     >> /var/log/placsp/daily.log 2>&1
30 4 1 * *   cd /opt/placsp && ./scripts/placsp reconcile  >> /var/log/placsp/reconcile.log 2>&1
```

Codelists are pre-populated automatically on first run. To refresh against a new feed file:

```bash
python scripts/fetch_codelists.py <feed.atom> ./codelists
```

## Environment variables

Loaded from `.env` in the repo root (auto-sourced by `scripts/placsp`).

| Variable | Required | Default | Notes |
|---|---|---|---|
| `WEAVIATE_API_KEY` | ✓ | — | Shared by Weaviate container and ingester |
| `NEO4J_PASSWORD` | ✓ | — | Neo4j auth |
| `WEAVIATE_URL` | | `http://localhost:8087` | Override for Docker-mode ingestion |
| `VECTORIZER_URL` | | `http://localhost:8089` | BGE-M3 vectorizer |
| `WEAVIATE_HTTP_PORT` | | `8087` | Published Weaviate HTTP port |
| `WEAVIATE_GRPC_PORT` | | `50052` | Published Weaviate gRPC port |
| `WEAVIATE_GOMEMLIMIT` | | `4GiB` | Weaviate Go memory limit |
| `NEO4J_HTTP_PORT` | | `7474` | Published Neo4j browser port |
| `NEO4J_BOLT_PORT` | | `7687` | Published Neo4j Bolt port |
| `NEO4J_HEAP` | | `2G` | Neo4j JVM heap |
| `SEARCH_API_PORT` | | `8092` | Published search-api port |
| `CORS_ORIGINS` | | `*` | CORS origins for search-api |
| `PLACSP_CODELIST_DIR` | | `./codelists` | Codelist cache directory |
| `PLACSP_WORK_DIR` | | `./work` | Download/unzip scratch directory |
| `PLACSP_EMBED_BATCH` | | — | Vectorizer batch size |
| `PLACSP_MAX_IN_FLIGHT` | | — | Concurrent embed requests |
| `PLACSP_OFFPEAK_START` | | — | Off-peak window start (host local time) |
| `PLACSP_OFFPEAK_END` | | — | Off-peak window end |

## Rollback

```bash
# Drop indexed data, keep containers:
python -m placsp init-schema   # after manually deleting the Weaviate class

# Wipe everything (data volumes too):
docker compose down -v
```

---

For one-feed end-to-end validation see [RUNBOOK.md](RUNBOOK.md).
For known issues and hardening backlog see [FOLLOWUPS.md](FOLLOWUPS.md).
