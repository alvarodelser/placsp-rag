# PLACSP Ingestion — Server Deploy & Test Task List

A step-by-step checklist to deploy the pipeline on the server, validate it on one feed,
prove the daily path, then schedule it and run the historical backfill.

**Conventions**
- Target interpreter: **`python3.11`**.
- Two ways the ingester can reach the services — pick one and keep it consistent:
  - **Host mode** (ingester runs via cron/systemd on the host): use published ports —
    `WEAVIATE_URL=http://localhost:8087`, `VECTORIZER_URL=http://localhost:8089`.
    (Requires the vectorizer to publish 8089 to the host.)
  - **Docker mode** (ingester runs as a container on the vectorizer's network): use service
    names — `WEAVIATE_URL=http://placsp-weaviate:8080`, `VECTORIZER_URL=http://vectorizer:8089`.
- The same `WEAVIATE_API_KEY` value is shared by `deploy/weaviate/.env` and the ingester env.

---

## Phase 0 — Provision the dedicated Weaviate

- [ ] **0.1** Clone/pull this repo onto the server; `cd` into it.
- [ ] **0.2** Configure the instance:
  ```bash
  cd deploy/weaviate
  cp .env.example .env
  # set WEAVIATE_API_KEY to a strong value:
  sed -i "s/^WEAVIATE_API_KEY=.*/WEAVIATE_API_KEY=$(openssl rand -hex 32)/" .env
  ```
- [ ] **0.3** (Docker mode only) Uncomment the external `networks:` block in
      `docker-compose.yml` and set it to the vectorizer's network
      (`docker inspect -f '{{json .NetworkSettings.Networks}}' vectorizer`).
- [ ] **0.4** Start it: `docker compose up -d`
- [ ] **0.5** Health + auth check:
  ```bash
  curl -s http://localhost:8087/v1/.well-known/ready && echo " READY"
  curl -s -H "Authorization: Bearer $(grep WEAVIATE_API_KEY .env | cut -d= -f2)" \
    http://localhost:8087/v1/schema | head -c 200; echo
  ```
  Expect `READY` and an (empty) schema JSON, not a 401.

## Phase 1 — Install the ingester

- [ ] **1.1** Create a venv and install the package:
  ```bash
  cd <repo-root>
  python3.11 -m venv .venv && . .venv/bin/activate
  pip install -e .
  ```
- [ ] **1.2** Export the runtime env (host mode shown):
  ```bash
  export WEAVIATE_URL=http://localhost:8087
  export WEAVIATE_API_KEY=<same value as deploy/weaviate/.env>
  export VECTORIZER_URL=http://localhost:8089
  export PLACSP_CODELIST_DIR=$PWD/codelists
  export PLACSP_WORK_DIR=$PWD/work
  ```
- [ ] **1.3** Confirm reachability of both services from the ingester:
  ```bash
  curl -s "$VECTORIZER_URL/health"; echo
  curl -s "$WEAVIATE_URL/v1/.well-known/ready" && echo " WV-OK"
  ```

## Phase 2 — Schema + codelists

- [ ] **2.1** Create the schema: `python3.11 -m placsp init-schema` → expect `created`.
- [ ] **2.2** Populate codelists:
      `python3.11 scripts/fetch_codelists.py tests/fixtures/mayores.atom "$PLACSP_CODELIST_DIR"`
      (re-run with a menores/externos sample too, to cover their codelists). Note any `skip`/`err`.

## Phase 3 — One-feed validation

Follow [RUNBOOK.md](RUNBOOK.md) Steps 3–4, then:

- [ ] **3.1** Ingest one feed (RUNBOOK Step 3). Record the returned `{records, upserted, deleted}`.
- [ ] **3.2** **Verify the ACTUAL stored count** matches `upserted` (RUNBOOK Step 3 ⚠️ box /
      FOLLOWUPS #1). A gap = silently-rejected objects → investigate before proceeding.
- [ ] **3.3** Retrieval smoke test (RUNBOOK Step 4): 3 relevant hits, readable Spanish `content`,
      decoded `status_label` (not raw codes).
- [ ] **3.4** Spot-check decoded labels and the three money fields on a few objects.

## Phase 4 — Daily-path validation (the steady state)

- [ ] **4.1** Run the daily walk once: `python3.11 -m placsp daily`.
      Confirm it pages the live feed, upserts new records, and applies tombstones (deletes).
- [ ] **4.2** **Idempotency:** run `python3.11 -m placsp daily` again immediately. The second run
      should upsert ~0 and report `skipped > 0` (the `updated` guard working — FOLLOWUPS C1 fix).
- [ ] **4.3** **status_history merge:** pick one expediente that changed state, and confirm its
      `status_history` array in Weaviate contains *all* prior states, not just the latest
      (the C2 fix; GET-merge on the daily path).
- [ ] **4.4** **Watermark sanity:** confirm the walk stops after a bounded number of pages (not
      ~1000). If it walks the whole feed, the date-aggregate watermark isn't returning a value —
      see FOLLOWUPS #2.

## Phase 5 — Tune throughput & off-peak

- [ ] **5.1** Measure embed throughput during Phase 3/4 (entries/min) without starving the shared
      GPU the iarag project uses. Adjust `PLACSP_EMBED_BATCH` and keep `PLACSP_MAX_IN_FLIGHT` low (1).
- [ ] **5.2** Set the off-peak window for backfill: `PLACSP_OFFPEAK_START` / `PLACSP_OFFPEAK_END`
      (host-local hours). Backfill only does work inside this window.
- [ ] **5.3** Record chosen values in RUNBOOK Step 5 (Observed Metrics).

## Phase 6 — Schedule daily + monthly reconcile

Create an env file the timers source, e.g. `/etc/placsp/placsp.env` with the Phase 1.2 vars.

- [ ] **6.1** Daily (off-peak), e.g. cron `15 3 * * *`:
  ```cron
  15 3 * * *  cd /opt/placsp && . .venv/bin/activate && set -a && . /etc/placsp/placsp.env && python -m placsp daily   >> /var/log/placsp/daily.log 2>&1
  ```
- [ ] **6.2** Monthly reconciliation, e.g. cron `30 4 1 * *`:
  ```cron
  30 4 1 * *  cd /opt/placsp && . .venv/bin/activate && set -a && . /etc/placsp/placsp.env && python -m placsp reconcile >> /var/log/placsp/reconcile.log 2>&1
  ```
  (systemd timer equivalents are fine; `Type=oneshot` services pointing at the same commands.)
- [ ] **6.3** Verify the first scheduled `daily` ran and logged sane counts.

## Phase 7 — Historical backfill

- [ ] **7.1** Launch the resumable backfill (it self-gates to the off-peak window):
      `nohup python3.11 -m placsp backfill >> /var/log/placsp/backfill.log 2>&1 &`
- [ ] **7.2** Monitor: object count climbing, GPU not starving iarag traffic, no error spikes.
      Note: backfill is idempotent (safe to restart) but not yet checkpoint-resuming — FOLLOWUPS #5.
- [ ] **7.3** On completion, confirm per-category counts look plausible vs. expectations.

## Phase 8 — Teardown / rollback

- [ ] Drop indexed data, keep the container: delete + recreate the class
      (`python3.11 -m placsp init-schema` after deleting the class), or `cd deploy/weaviate && docker compose down -v` to wipe everything.
- [ ] Disable the cron/systemd timers to stop ingestion.

---

## Pre-production gate

Before considering this production-ready, review **[FOLLOWUPS.md](FOLLOWUPS.md)** and decide
which hardening items to do now vs. later. The highest-priority ones surfaced by validation are
usually **#1 (silent batch errors / date typing)** and **#2 (watermark aggregate)**.
