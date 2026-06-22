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

## Build & deploy (host nginx)

```bash
# set VITE_API_BASE to the public URL of the search-api, then build:
VITE_API_BASE=http://<server-ip>:8092 npm run build

# copy the output to your nginx webroot:
cp -r dist/* /var/www/html/placsp/
```

Point your nginx `root` at that directory and you're done.

## Structure

- `src/api.js` — single `search(q, mode, k)` call to the backend.
- `src/App.jsx` — search box, mode selector, result list, loading/error states.
- `src/components/ResultCard.jsx` — one licitación card.
- `src/format.js` — EUR formatting. `src/styles.css` — styles.
