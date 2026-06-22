# PLACSP Search API

FastAPI backend for PLACSP search. Embeds the query (BGE-M3 vectorizer) and runs a
vector / hybrid / BM25 search over the `Placsp_licitaciones` Weaviate class. Holds the
Weaviate API key server-side; the React UI (`../search-ui`) only calls `/api/search`.

## Deploy (recommended)

Use the root `docker-compose.yml` — it brings up Weaviate, the search-api, and the UI
together with the correct networking and health-check ordering:

```bash
# from repo root
cp .env.example .env   # edit: set WEAVIATE_API_KEY and VITE_API_BASE
docker compose up -d
```

## Run standalone (dev)

```bash
pip install -r requirements.txt
export WEAVIATE_URL=http://localhost:8087
export WEAVIATE_API_KEY=<same key as in .env>
export VECTORIZER_URL=http://localhost:8089
uvicorn search_api:app --host 0.0.0.0 --port 8092 --reload
```

## Endpoints

- `GET /api/search?q=<text>&mode=hybrid|vector|keyword&k=15&alpha=0.5` → JSON results
- `GET /api/health` — reports configured upstream URLs and reachability

`CORS_ORIGINS` defaults to `*`; set it to your UI's public origin in production.
