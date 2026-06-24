# PLACSP Search UI (React)

A minimal React + Vite app for searching the PLACSP index. It calls the `search-api`
backend (`/api/search`) and renders licitaciones — title, órgano, importes, estado, CPV,
adjudicatario — with hybrid / semantic / keyword modes. You deploy this however you like.

## Develop

```bash
npm install
npm run dev   # http://localhost:5173/placsprag/
              # Vite proxies /placsprag/api/* → localhost:8092 automatically
              # requires: docker compose up -d  (search-api must be running)
```

## Build & deploy (host nginx)

```bash
# Build — do NOT set VITE_API_BASE; the default (/placsprag) is correct.
# nginx will proxy /placsprag/api/* → localhost:8092 server-side.
npm run build

# Copy output to the server (adjust path if needed):
cp -r dist/* /var/www/placsp/

# Install the nginx config:
cp nginx.conf /etc/nginx/sites-available/placsp
ln -s /etc/nginx/sites-available/placsp /etc/nginx/sites-enabled/placsp
nginx -t && systemctl reload nginx
```

The `nginx.conf` in this directory handles everything:
- Proxies `/placsprag/api/*` → `http://127.0.0.1:8092` (search-api, localhost-only — never exposed publicly)
- Serves the SPA from `/var/www/placsp/` with React Router fallback
- Sets immutable cache on hashed JS/CSS bundles

## Structure

- `src/api.js` — single `search(q, mode, k)` call to the backend.
- `src/App.jsx` — search box, mode selector, result list, loading/error states.
- `src/components/ResultCard.jsx` — one licitación card.
- `src/format.js` — EUR formatting. `src/styles.css` — styles.
