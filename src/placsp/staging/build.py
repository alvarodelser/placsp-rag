"""versions/ -> current/: one row per tender in its latest published state, across every archive.

A tender is republished each time it changes, often in another year's archive, so its state is
only known once every archive is read: the latest version wins, every version contributes to
the status history. Child tables (lots, results, criteria...) are taken from the latest version
only, since each version is a full snapshot.

Feeds also carry deletion markers (atompub tombstones) with a reason: ANULADA (the publication
was annulled) or CERRADA (the tender is closed and leaves the feed; mostly resolved or awarded
tenders). Neither removes the tender here: `removed_at` / `removed_reason` record the marker
when it is not older than the latest version.
"""
import glob
import os
import shutil
import time

import duckdb
import structlog

from placsp.core.codelists import parse_gc
from placsp.staging.tables import TABLES

log = structlog.get_logger(service="placsp")

CHILDREN = [t for t in TABLES if t not in ("entry", "tombstone")]
_VERSION = "-[0-9]+(\\.[0-9]+)*$"


def _src(data_dir: str, table: str) -> str:
    return f"read_parquet('{os.path.join(data_dir, 'versions', table, '*.parquet')}', union_by_name=true)"


def _copy(con, sql: str, path: str):
    con.execute(f"COPY ({sql}) TO '{path}' (FORMAT parquet, COMPRESSION zstd)")


def build(data_dir: str, codelist_dir: str, memory_limit: str = "4GB") -> dict:
    t0 = time.time()
    final_dir = os.path.join(data_dir, "current")
    out_dir = final_dir + ".tmp"            # swapped in at the end: readers never see a half-built set
    shutil.rmtree(out_dir, ignore_errors=True)
    os.makedirs(out_dir)
    con = duckdb.connect()
    con.execute(f"SET memory_limit='{memory_limit}'")
    con.execute(f"SET temp_directory='{os.path.join(data_dir, 'tmp')}'")
    con.execute("SET preserve_insertion_order=false")

    # The latest version of each tender, picked on narrow columns before touching the wide rows.
    con.execute(f"""
        CREATE TEMP TABLE pick AS
        SELECT entry_id, arg_max(vkey, (ts, src_zip, src_file, vkey)) AS vkey,
               count(*) AS n_versions, min(ts) AS first_seen, max(ts) AS last_updated
        FROM (SELECT entry_id, vkey, src_zip, src_file, try_cast(updated AS TIMESTAMPTZ) AS ts
              FROM {_src(data_dir, 'entry')})
        GROUP BY entry_id""")
    con.execute(f"""
        CREATE TEMP TABLE gone AS
        SELECT entry_id, max(try_cast("when" AS TIMESTAMPTZ)) AS removed_at, arg_max(reason, "when") AS removed_reason
        FROM {_src(data_dir, 'tombstone')} GROUP BY entry_id""")

    _copy(con, f"""
        SELECT e.* EXCLUDE (vkey, src_file), p.n_versions, p.first_seen, p.last_updated,
               CASE WHEN g.removed_at >= p.last_updated THEN g.removed_at END AS removed_at,
               CASE WHEN g.removed_at >= p.last_updated THEN g.removed_reason END AS removed_reason
        FROM {_src(data_dir, 'entry')} e JOIN pick p USING (vkey)
        LEFT JOIN gone g ON g.entry_id = p.entry_id
        ORDER BY e.entry_id""", os.path.join(out_dir, "tender.parquet"))

    # Every status a tender went through, with when it was first and last published in it.
    _copy(con, f"""
        SELECT entry_id, status_code, min(try_cast(updated AS TIMESTAMPTZ)) AS first_seen,
               max(try_cast(updated AS TIMESTAMPTZ)) AS last_seen, count(*) AS versions
        FROM {_src(data_dir, 'entry')} WHERE status_code IS NOT NULL
        GROUP BY ALL ORDER BY entry_id, first_seen""", os.path.join(out_dir, "status_history.parquet"))

    for t in CHILDREN:
        _copy(con, f"SELECT p.entry_id, c.* EXCLUDE (vkey) FROM {_src(data_dir, t)} c JOIN pick p USING (vkey) "
                   "ORDER BY p.entry_id",
              os.path.join(out_dir, f"{t}.parquet"))

    cur = lambda t: f"read_parquet('{os.path.join(out_dir, t + '.parquet')}')"
    # Authorities: one per identifier (DIR3, else NIF, else platform id, else name), with every name seen.
    _copy(con, f"""
        SELECT coalesce('DIR3:' || auth_dir3, 'NIF:' || auth_nif, 'ID_PLATAFORMA:' || auth_platform_id, auth_ids[1],
                        'name:' || lower(trim(auth_name))) AS authority_key,
               any_value(auth_dir3) AS dir3, any_value(auth_nif) AS nif, any_value(auth_platform_id) AS platform_id,
               list_distinct(flatten(list(auth_ids))) AS ids, mode(auth_name) AS name, list_distinct(list(auth_name)) AS names,
               mode(auth_type_code) AS type_code, mode(auth_activity_codes) AS activity_codes,
               mode(auth_city) AS city, mode(auth_postal_code) AS postal_code, mode(auth_website) AS website,
               mode(auth_email) AS email, mode(auth_buyer_profile) AS buyer_profile,
               mode(auth_parent_names) AS parent_names, mode(auth_parent_ids) AS parent_ids,
               count(*) AS tenders, min(first_seen) AS first_seen, max(last_updated) AS last_updated
        FROM {cur('tender')} WHERE auth_name IS NOT NULL OR auth_dir3 IS NOT NULL OR auth_nif IS NOT NULL
        GROUP BY 1""", os.path.join(out_dir, "authority.parquet"))
    # Companies: winners by normalised tax id (letters and digits, upper case), with every name seen.
    _copy(con, f"""
        SELECT upper(regexp_replace(nif, '[^0-9A-Za-z]', '', 'g')) AS nif_norm, mode(name) AS name,
               list_distinct(list(name)) AS names, mode(id_scheme) AS id_scheme,
               upper(regexp_replace(nif, '[^0-9A-Za-z]', '', 'g')) LIKE 'U%' OR bool_or(upper(name) LIKE 'UTE %') AS is_ute,
               mode(nuts) AS nuts, mode(city) AS city, count(DISTINCT entry_id) AS tenders_won, count(*) AS awards
        FROM {cur('winner')} WHERE nif IS NOT NULL AND trim(nif) <> ''
        GROUP BY 1""", os.path.join(out_dir, "company.parquet"))

    rows = [(_stem(f), code, label) for f in sorted(glob.glob(os.path.join(codelist_dir, "*.gc")))
            for code, label in parse_gc(f).items()]
    con.execute("CREATE TEMP TABLE codelist (list VARCHAR, code VARCHAR, label VARCHAR)")
    con.executemany("INSERT INTO codelist VALUES (?, ?, ?)", rows)
    _copy(con, "SELECT * FROM codelist", os.path.join(out_dir, "codelist.parquet"))

    counts = {os.path.basename(p)[:-8]: con.execute(f"SELECT count(*) FROM read_parquet('{p}')").fetchone()[0]
              for p in sorted(glob.glob(os.path.join(out_dir, "*.parquet")))}
    shutil.rmtree(final_dir + ".old", ignore_errors=True)
    if os.path.exists(final_dir):
        os.replace(final_dir, final_dir + ".old")
    os.replace(out_dir, final_dir)
    shutil.rmtree(final_dir + ".old", ignore_errors=True)
    log.info("built", seconds=round(time.time() - t0, 1), **counts)
    return counts


def _stem(path: str) -> str:
    import re
    return re.sub(_VERSION, "", os.path.basename(path)[:-3])
