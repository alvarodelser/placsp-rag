# PLACSP Search UI (React)

A minimal React + Vite app for searching the PLACSP index. It calls the `search-api`
backend (`/api/search`) and renders licitaciones — title, órgano, importes, estado, CPV,
adjudicatario — with hybrid / semantic / keyword modes. You deploy this however you like.

## Configure

```bash
cp .env.example .env
# set VITE_API_BASE to where search-api is reachable from the browser, e.g.
#   http://localhost:8092      (local dev)
#   https://search.example.org (prod)
```

The backend's `CORS_ORIGINS` must allow this app's origin.

## Develop

```bash
npm install
npm run dev          # http://localhost:5173
```

## Build & deploy (you own this part)

```bash
npm run build        # outputs static files to dist/
```

Serve `dist/` from any static host (nginx, Netlify, S3+CloudFront, etc.).

Or build a container (API base baked in at build time):

```bash
docker build --build-arg VITE_API_BASE=https://search.example.org -t placsp-search-ui .
docker run --rm -p 8080:80 placsp-search-ui
```

## Structure

- `src/api.js` — single `search(q, mode, k)` call to the backend.
- `src/App.jsx` — search box, mode selector, result list, loading/error states.
- `src/components/ResultCard.jsx` — one licitación card.
- `src/format.js` — EUR formatting. `src/styles.css` — styles.
