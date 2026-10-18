"""SQLite state for one pilot run.

Every stage is resumable: it only picks up rows not yet done, so a run can be
interrupted and restarted. Timings and volumes are stored next to the data so
the report is computed from this database alone.
"""
import json
import sqlite3
import threading
import time
from contextlib import contextmanager
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS expediente (
    id            TEXT PRIMARY KEY,          -- syndication id
    channel       TEXT NOT NULL,
    updated       TEXT,
    link          TEXT,
    folder_id     TEXT,                      -- ContractFolderID (the expediente number)
    title         TEXT,
    status        TEXT,
    raw_path      TEXT,
    raw_bytes     INTEGER,
    tender_json   TEXT,                      -- full CODICE parse
    analysable    INTEGER,                   -- 0 for menores/encargos: already awarded, no pliegos
    skip_reason   TEXT,
    detail_status TEXT,                      -- ok | failed | n/a
    detail_bytes  INTEGER,
    detail_ms     INTEGER,
    graph_status  TEXT,
    graph_ms      INTEGER
);

-- One row per place a document is referenced. The same file is often
-- referenced from both the feed and the detail page; content dedup happens on blob.sha.
CREATE TABLE IF NOT EXISTS docref (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    exp_id       TEXT NOT NULL,
    url          TEXT,
    source       TEXT NOT NULL,              -- feed_legal | feed_technical | feed_additional | feed_general | feed_notice | detail_notice | detail_other | zip_member
    label        TEXT,                       -- filename or the label the platform shows
    type_code    TEXT,                       -- GeneralDocument / notice DocumentTypeCode
    notice_type  TEXT,                       -- DOC_CN, DOC_CAN_ADJ, ...
    published    TEXT,
    fmt          TEXT,                       -- declared format (pdf/html/xml) when the page says it
    feed_hash    TEXT,                       -- DocumentHash from the feed (SHA-1, base64)
    role         TEXT,                       -- data-model role, see classify.py
    role_source  TEXT,
    parent_id    INTEGER,                    -- zip member -> zip docref
    status       TEXT NOT NULL DEFAULT 'pending',   -- pending | fetched | failed | skipped
    http_status  INTEGER,
    error        TEXT,
    fetch_ms     INTEGER,
    sha          TEXT,
    UNIQUE (exp_id, url, source, label)
);

CREATE TABLE IF NOT EXISTS blob (
    sha           TEXT PRIMARY KEY,          -- sha256 of the content
    bytes         INTEGER,
    mime          TEXT,
    ext           TEXT,
    path          TEXT,
    pages         INTEGER,
    text_status   TEXT,                      -- pending | ok | empty | unsupported | failed | needs_ocr
    text_method   TEXT,
    text_chars    INTEGER,
    text_path     TEXT,
    text_ms       INTEGER,
    ocr_pages     INTEGER,
    ocr_ms        INTEGER,
    error         TEXT,
    summary_status TEXT,                     -- pending | ok | failed | skipped  (nlp /summarize article)
    summary_json  TEXT,
    summary_ms    INTEGER,
    ner_status    TEXT,                      -- pending | ok | partial | failed | skipped
    ner_chunks_total INTEGER,
    ner_chunks_selected INTEGER,
    resolve_status TEXT,                     -- pending | ok | failed | skipped  (nlp /resolve)
    resolve_json  TEXT,
    resolve_ms    INTEGER,
    describe_status TEXT,                    -- pending | ok | partial | skipped
    embed_ms      INTEGER
);

-- NER input unit: a ~512-word chunk of a document's text (nlp /ner).
CREATE TABLE IF NOT EXISTS chunk (
    sha          TEXT NOT NULL,
    idx          INTEGER NOT NULL,
    words        INTEGER,
    chars        INTEGER,
    score        INTEGER,                    -- procurement vocabulary hits, used when capping
    selected     INTEGER,
    status       TEXT,                       -- pending | ok | failed | skipped
    ms           INTEGER,
    entities     INTEGER,
    relations    INTEGER,
    result_json  TEXT,
    PRIMARY KEY (sha, idx)
);

-- GraphRAG descriptions of resolved entities and relations (nlp /summarize entity_desc|relation_desc).
CREATE TABLE IF NOT EXISTS description (
    sha      TEXT NOT NULL,
    kind     TEXT NOT NULL,                  -- entity | relation
    item_id  TEXT NOT NULL,
    status   TEXT,
    ms       INTEGER,
    text     TEXT,
    PRIMARY KEY (sha, kind, item_id)
);

CREATE TABLE IF NOT EXISTS extraction (
    exp_id      TEXT NOT NULL,
    kind        TEXT NOT NULL,               -- tender_description | org_description (nlp /summarize aggregate)
    sha         TEXT NOT NULL,
    status      TEXT,
    result_json TEXT,
    ms          INTEGER,
    PRIMARY KEY (exp_id, kind, sha)
);

CREATE TABLE IF NOT EXISTS service_call (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    service       TEXT,                      -- nlp | vectorizer | ocr
    task          TEXT,                      -- summarize:article, ner, resolve, summarize:entity_desc, ...
    exp_id        TEXT,
    sha           TEXT,
    input_chars   INTEGER,
    output_chars  INTEGER,
    wall_ms       INTEGER,
    ok            INTEGER,
    error         TEXT,
    at            REAL
);

CREATE TABLE IF NOT EXISTS stage_run (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    stage     TEXT,
    started   REAL,
    ended     REAL,
    wall_ms   INTEGER,
    items     INTEGER,
    notes     TEXT
);
"""


class Store:
    def __init__(self, path: Path):
        self.path = Path(path)
        self._local = threading.local()
        self._lock = threading.Lock()
        with self.tx() as c:
            c.executescript(SCHEMA)

    def conn(self) -> sqlite3.Connection:
        c = getattr(self._local, "c", None)
        if c is None:
            c = sqlite3.connect(self.path, timeout=60, check_same_thread=False)
            c.row_factory = sqlite3.Row
            c.execute("PRAGMA journal_mode=WAL")
            c.execute("PRAGMA synchronous=NORMAL")
            self._local.c = c
        return c

    @contextmanager
    def tx(self):
        with self._lock:
            c = self.conn()
            try:
                yield c
                c.commit()
            except Exception:
                c.rollback()
                raise

    def q(self, sql: str, args=()) -> list[sqlite3.Row]:
        return self.conn().execute(sql, args).fetchall()

    def one(self, sql: str, args=()):
        r = self.conn().execute(sql, args).fetchone()
        return r

    def update(self, table: str, key: dict, **fields):
        if not fields:
            return
        sets = ", ".join(f"{k}=?" for k in fields)
        where = " AND ".join(f"{k}=?" for k in key)
        vals = [json.dumps(v, ensure_ascii=False) if isinstance(v, (dict, list)) else v for v in fields.values()]
        with self.tx() as c:
            c.execute(f"UPDATE {table} SET {sets} WHERE {where}", vals + list(key.values()))

    def log_call(self, **row):
        row.setdefault("at", time.time())
        cols = ", ".join(row)
        with self.tx() as c:
            c.execute(f"INSERT INTO service_call ({cols}) VALUES ({', '.join('?' * len(row))})", list(row.values()))

    def reset_failed(self) -> dict:
        """Put every failed item back to pending so the next run retries it."""
        stmts = {
            "docref": "UPDATE docref SET status='pending', error=NULL WHERE status='failed'",
            "summary": "UPDATE blob SET summary_status='pending' WHERE summary_status='failed'",
            "chunk": "UPDATE chunk SET status='pending' WHERE status='failed'",
            "ner": "UPDATE blob SET ner_status='pending' WHERE ner_status IN ('failed','partial')",
            "resolve": "DELETE FROM resolution WHERE status!='ok'",
            "refine": "DELETE FROM refinement WHERE status!='ok'",
            "describe": "DELETE FROM entity_description WHERE status!='ok'",
            "summary": "DELETE FROM extraction WHERE status!='ok'",
        }
        from placsp_pilot.entities import SCHEMA   # the entity tables may not exist yet
        out = {}
        with self.tx() as c:
            c.executescript(SCHEMA)
            for k, sql in stmts.items():
                out[k] = c.execute(sql).rowcount
        return out

    @contextmanager
    def stage(self, name: str):
        """Record the wall time of a whole stage. Yields a dict; set 'items'/'notes' on it."""
        info = {"items": 0, "notes": ""}
        t0 = time.time()
        try:
            yield info
        finally:
            t1 = time.time()
            with self.tx() as c:
                c.execute(
                    "INSERT INTO stage_run (stage, started, ended, wall_ms, items, notes) VALUES (?,?,?,?,?,?)",
                    (name, t0, t1, int((t1 - t0) * 1000), info["items"], info["notes"]),
                )
