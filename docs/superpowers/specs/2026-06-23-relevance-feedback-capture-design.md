# Relevance Feedback Capture — Design

**Date:** 2026-06-23
**Branch:** `feat/search-ui-revamp`
**Status:** Approved (pending spec review)

## Goal

Let users mark individual search results as **relevant** so we accumulate a
relevance-judgment dataset for evaluating retrieval quality over time. Each
judgment is tied to the query, the full result set as shown, and the running
backend version (git commit), so we can later ask: *"for query X under commit Y,
which of the shown results were marked relevant, and at what rank?"*

This is for **offline evaluation**, not live re-ranking.

## Research basis

Survey of relevance-feedback UX (see sources at end) converges on:

- **Explicit feedback** (a button) is a clean, unambiguous signal but low-volume —
  users rarely do extra work. **Implicit feedback** (clicks, dwell) is cheap and
  high-volume but noisy.
- The pattern that works: a **low-friction, always-visible binary control** on
  every result, zero extra clicks to find.

Chosen mechanism (validated with user): a **positive-only "Relevante" toggle** per
result — the highest-value, lowest-friction signal for building an eval dataset.
Absence of a mark is treated as "not marked", not as an explicit negative.

## Decisions (validated)

| Decision | Choice |
|---|---|
| Feedback control | Positive-only "Relevante" toggle (👍), one per result, toggleable |
| Storage | Local SQLite file, path via `FEEDBACK_DB` env |
| Identity | Anonymous + random `session_id` persisted in `localStorage` |
| Version source | Backend-stamped: `APP_VERSION` env → `git rev-parse --short HEAD` → `"unknown"` |
| Result snapshot | Full shown set (`id`, `rank`, `score`) saved once per search, lazily on first like |

## Data model (SQLite)

Two tables in a single file (default `feedback.db`, override with `FEEDBACK_DB`).

```sql
CREATE TABLE IF NOT EXISTS searches (
  search_id    TEXT PRIMARY KEY,   -- client-generated uuid per executed search
  session_id   TEXT,               -- random browser id (localStorage)
  ts           TEXT,               -- ISO timestamp, set when search row first written
  query        TEXT,
  mode         TEXT,               -- hybrid|vector|keyword|browse
  filters_json TEXT,               -- serialized filter object
  results_json TEXT,               -- [{id, rank, score}, ...] as shown
  app_version  TEXT                -- backend git commit at time of first like
);

CREATE TABLE IF NOT EXISTS feedback (
  id           INTEGER PRIMARY KEY AUTOINCREMENT,
  search_id    TEXT REFERENCES searches(search_id),
  session_id   TEXT,
  ts           TEXT,
  result_id    TEXT,               -- the liked result id (_id / syndication_id)
  result_rank  INTEGER,            -- position in the shown list (0-based)
  result_score REAL,
  UNIQUE(search_id, result_id)     -- one like per (search, result); toggle off deletes the row
);
```

The `searches` row is written **lazily** — only on the *first* like within that
search — so idle searches that never receive feedback are not logged.

## Backend (`search-api`)

- **Version resolution at startup:** `APP_VERSION` env, else `git rev-parse --short
  HEAD` (best-effort; failures fall back to `"unknown"`). Resolved once and reused.
- **New module `feedback.py`:**
  - `init_db(path)` — create tables if absent.
  - `upsert_search(...)` — insert the search row if not present (idempotent on
    `search_id`); stamps `app_version` and `ts` on first write.
  - `add_like(...)` — insert a feedback row; idempotent via the unique constraint
    (re-liking the same result is a no-op).
  - `remove_like(search_id, result_id)` — delete the matching feedback row.
- **New routes** (CORS/methods expanded to allow `POST` and `DELETE`):
  - `POST /api/feedback` — body:
    `{search_id, session_id, query, mode, filters, results:[{id,rank,score}], result_id}`.
    Upserts the search row, inserts the like, stamps `app_version` server-side.
    Returns `{ok: true, app_version}`.
  - `DELETE /api/feedback` — body: `{search_id, result_id}`. Removes the like.

The Weaviate-backed `/api/search` route is unchanged.

## Frontend (`search-ui`)

- **`session_id`:** generated once and persisted in `localStorage`.
- **`search_id`:** a fresh uuid generated each time a *new* query is executed
  (`run(0)`), not on "Cargar más". Held in `App` state alongside the current
  result snapshot.
- **`api.js`:** add `sendFeedback(...)` and `removeFeedback(...)` mirroring the
  existing fetch helpers (POST/DELETE with JSON body).
- **State:** the set of liked `result_id`s for the *current* search is lifted to
  `App` (a `Set`). Likes reset when a new search runs.
- **`ResultCard`:** add a "Relevante" toggle (👍, filled/active when liked).
  On click: optimistic toggle, call the API; on failure, revert and show a subtle
  inline error. The card receives `liked` + an `onToggleLike` callback as props.

## Testing

- **Backend:** pytest for `feedback.py` (init, `upsert_search` idempotency,
  `add_like`/`remove_like`, unique-constraint behavior) and the new routes via
  FastAPI `TestClient` (POST creates search + like; DELETE removes; re-POST is
  idempotent). Use a temp DB path per test.
- **Frontend:** a test for `sendFeedback`/`removeFeedback` URL + body shaping,
  mirroring `src/api.test.js`.

## Out of scope (YAGNI)

- Negative / graded feedback and reason pickers.
- Live re-ranking from feedback.
- User authentication / named identity.
- Implicit-signal capture (clicks, dwell).

## Sources

- [Click data as implicit relevance feedback — ScienceDirect](https://www.sciencedirect.com/science/article/abs/pii/S0306457306001002)
- [Relevance feedback — Wikipedia](https://en.wikipedia.org/wiki/Relevance_feedback)
- [Mining Implicit Relevance Feedback from User Behavior — arXiv](https://arxiv.org/pdf/2006.07581)
- [Explicit In Situ User Feedback for Web Search Results — Microsoft Research](https://www.microsoft.com/en-us/research/publication/explicit-situ-user-feedback-web-search-results/)
- [New Choice — Daniel Tunkelang](https://dtunkelang.medium.com/new-choice-a5594ee7418a)
