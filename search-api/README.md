# PLACSP Search API

FastAPI backend for PLACSP search. Embeds the query (BGE-M3 vectorizer) and runs a
vector / hybrid / BM25 search over the `Placsp_licitaciones` Weaviate class. Holds the
Weaviate API key server-side; the React UI (`../search-ui`) only calls `/api/search`.

## Run

```bash
cd search-api
pip install -r requirements.txt
export WEAVIATE_URL=http://localhost:8087
export WEAVIATE_API_KEY=<same key as deploy/weaviate/.env>
export VECTORIZER_URL=http://localhost:8089
export CORS_ORIGINS=http://localhost:5173      # the React dev server (or your deployed UI origin)
uvicorn search_api:app --host 0.0.0.0 --port 8092
```

Docker:

```bash
docker build -t placsp-search-api .
docker run --rm -p 8092:8092 \
  -e WEAVIATE_URL=http://placsp-weaviate:8080 -e WEAVIATE_API_KEY=<key> \
  -e VECTORIZER_URL=http://vectorizer:8089 -e CORS_ORIGINS='*' \
  --network <vectorizer-network> placsp-search-api
```

## Endpoints

- `GET /api/search?q=<text>&mode=hybrid|vector|keyword&k=15&alpha=0.5` → JSON.
  ```json
  { "query": "...", "mode": "hybrid", "count": 15,
    "results": [ { "title": "...", "contracting_authority": "...", "budget_amount": 120000,
                   "status_label": "EN PLAZO", "cpv": ["..."], "source_url": "...",
                   "_id": "...", "_score": 0.87 }, ... ] }
  ```
- `GET /api/health` — configured upstreams.

`CORS_ORIGINS` defaults to `*`; set it to your UI origin(s) in production.
