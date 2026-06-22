# PLACSP Weaviate configuration

Environment variable reference for the dedicated Weaviate container (separate from the
legacy `iarag-vectorstore` — its own volume and API key).

## Deploy

Weaviate is managed by the **root `docker-compose.yml`**:

```bash
# from repo root
cp .env.example .env
# edit .env: set WEAVIATE_API_KEY (openssl rand -hex 32)
docker compose up -d placsp-weaviate
```

## Verify

```bash
curl -s http://localhost:${WEAVIATE_HTTP_PORT:-8087}/v1/.well-known/ready && echo READY
curl -s -H "Authorization: Bearer $WEAVIATE_API_KEY" http://localhost:8087/v1/schema
```

## Environment variables (see root `.env.example`)

| Variable | Default | Description |
|---|---|---|
| `WEAVIATE_API_KEY` | *(required)* | Shared between Weaviate and the search-api |
| `WEAVIATE_HTTP_PORT` | `8087` | Host port for the HTTP API |
| `WEAVIATE_GRPC_PORT` | `50052` | Host port for the gRPC API |
| `WEAVIATE_GOMEMLIMIT` | `4GiB` | Soft memory ceiling |

## Data / teardown

State lives in the named Docker volume `placsp_weaviate_data`.

```bash
docker compose stop placsp-weaviate          # stop, keep data
docker compose down -v                        # stop and DELETE all indexed data
```
