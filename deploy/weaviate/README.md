# PLACSP Weaviate instance

A dedicated Weaviate container for the PLACSP RAG index — separate from the legacy
`iarag-vectorstore`. Bring-your-own vectors (BGE-M3 supplied at upsert), BM25 built-in,
API-key auth, pinned to **1.28.3** (the version the schema/code was verified against).

## Bring it up

```bash
cd deploy/weaviate
cp .env.example .env
# edit .env: set a strong WEAVIATE_API_KEY (openssl rand -hex 32), adjust ports if needed
docker compose up -d
```

## Verify

```bash
curl -s http://localhost:${WEAVIATE_HTTP_PORT:-8087}/v1/.well-known/ready && echo READY
# auth check (should list schema, empty at first):
curl -s -H "Authorization: Bearer $WEAVIATE_API_KEY" \
  http://localhost:8087/v1/schema
```

## How the ingester reaches it

- **Ingester on the host** (cron/systemd): `WEAVIATE_URL=http://localhost:8087`.
- **Ingester in Docker** on the vectorizer's network: `WEAVIATE_URL=http://placsp-weaviate:8080`
  (uncomment the external `networks:` block in `docker-compose.yml` and set the
  vectorizer's network name).

The **same** `WEAVIATE_API_KEY` value goes in both this `.env` and the ingester's
environment. See `../../docs/DEPLOYMENT.md` for the full deploy + test checklist.

## Data / teardown

State lives in the named volume `placsp_weaviate_data`.

```bash
docker compose down              # stop, keep data
docker compose down -v           # stop and DELETE all indexed data
```
