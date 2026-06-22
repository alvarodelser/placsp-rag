# PLACSP Ingestion — Follow-ups (production hardening)

The pipeline is feature-complete for the **"validate on one feed first"** milestone
(spec §3.8). The final whole-branch review surfaced production-hardening items that were
intentionally deferred past that milestone. Triage these before enabling the full backfill
+ unattended daily cron.

## Fixed before merge (final review)
- **C1 — daily `updated` guard:** `process_files(..., merge_stored=True)` now skips records
  not newer than the stored object. (daily/reconcile only)
- **C2 — `status_history` merge:** stored history is GET-merged with the batch before upsert,
  deduped by `(code, date)`. `get_stored()` is now used.
- **n_bids** tolerant numeric parse; **watermark** failure now logs.

## Deferred — verify/fix during or right after one-feed validation

1. **I3 / N3 — batch upsert is "silently optimistic" + date typing (HIGHEST PRIORITY at validation).**
   Weaviate `POST /v1/batch/objects` returns HTTP 200 even when individual objects fail
   (e.g. a `date`-typed property receiving a non-RFC3339 string). `Upserter.upsert` does not
   inspect per-object results, so failures are counted as success. **During validation, do not
   trust the returned count — query Weaviate for the actual object count** and compare. Fix:
   parse the batch response array, log/retry per-object errors, and normalize
   `publication_date`/`award_date`/`submission_deadline`/`updated` to RFC3339 (or relax those
   schema props to `text` if normalization is unreliable across sources/years).

2. **I2 — watermark aggregate on a `date` field.** Confirm `Aggregate { ... { updated { maximum } } }`
   actually returns a value on Weaviate 1.28.3 for a date property. If not, the daily walk loses
   its stop condition and re-walks up to 1000 pages. Fallback: store/query `updated` as `text`,
   or track the watermark in a tiny state file.

3. **I4 — HTTP retry/backoff** on the embedder, upserter, fetcher, and watermark clients
   (spec §8). A transient vectorizer/Weaviate blip currently aborts a feed.

4. **I5 — backfill checkpoint/resumability** (spec §7). Re-running is idempotent (safe) but not
   skip-finished; add a per-unit `(category, year, file)` checkpoint so an interrupted multi-day
   backfill resumes instead of restarting.

5. **I1 — timestamp comparison** uses ISO **string** compare in `collapse` and the watermark.
   PLACSP feeds are same-offset (Europe/Madrid) so this is chronological in practice; parse to
   `datetime` to be correct across mixed offsets.

6. **N1 — `render()` runs twice per record** (pipeline for embed text, upserter for properties).
   Render once and pass props through to avoid wasted work and latent divergence.

7. **N2 — `verify=False`** is hardcoded in `fetcher.download` and `scripts/fetch_codelists.py`
   (PLACSP chains to a Spanish CA). Make it a config knob; prefer trusting the FNMT CA on the
   host and defaulting to `verify=True`.

8. **N4 — daily temp files** use predictable names in the shared temp dir; fine for a single
   cron, but use unique names if runs could overlap.

## Minor code cleanups (cosmetic)
- `Lot` import sits inside `extract()`; move to module top.
- `adjudicatario` (absolute xpath) vs `adjudicatario_nif` (`.//`) style inconsistency.
- `_merge_history` computes its key before the `status_code` truthiness guard.
