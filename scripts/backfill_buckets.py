"""One-off backfill: add budget_bucket, pub_month, deadline_month to existing Weaviate records.

Usage (from repo root):
    python scripts/backfill_buckets.py [--url http://localhost:8180] [--class Placsp_licitaciones]

Reads all objects in cursor-batches of 200, computes the three bucket fields,
and PATCHes only objects where any value differs from what's already stored.
Safe to run multiple times (idempotent).
"""
import argparse
import math
import re
import sys
import time

import httpx

# ── bucket logic (must match renderer.py + facets.py) ────────────────────────
_B_MIN   = 1_000
_B_MAX   = 100_000_000
_B_LMIN  = math.log(_B_MIN)
_B_LSPAN = math.log(_B_MAX) - _B_LMIN
_B_NUM   = 15
_MONTH   = re.compile(r"(\d{4}-\d{2})")


def budget_bucket(amount) -> str | None:
    if amount is None or amount <= 0:
        return None
    if amount < _B_MIN:
        return "b00"
    if amount >= _B_MAX:
        return f"b{_B_NUM - 1:02d}"
    t = (math.log(amount) - _B_LMIN) / _B_LSPAN
    return f"b{min(int(t * _B_NUM), _B_NUM - 1):02d}"


def month(date_str) -> str | None:
    m = _MONTH.search(date_str or "")
    return m.group(1) if m else None


# ── schema: add missing properties ───────────────────────────────────────────
NEW_PROPS = [
    {"name": "budget_bucket",  "dataType": ["text"]},
    {"name": "pub_month",      "dataType": ["text"]},
    {"name": "deadline_month", "dataType": ["text"]},
]


def ensure_properties(base: str, class_name: str, headers: dict, client: httpx.Client):
    r = client.get(f"{base}/v1/schema/{class_name}")
    r.raise_for_status()
    existing = {p["name"] for p in r.json().get("properties", [])}
    for prop in NEW_PROPS:
        if prop["name"] not in existing:
            print(f"  adding property {prop['name']} …")
            client.post(f"{base}/v1/schema/{class_name}/properties",
                        json=prop, headers=headers).raise_for_status()


# ── main ─────────────────────────────────────────────────────────────────────
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--url",   default="http://localhost:8180")
    ap.add_argument("--class", dest="cls", default="Placsp_licitaciones")
    ap.add_argument("--key",   default="", help="Weaviate API key (if any)")
    ap.add_argument("--batch", type=int, default=200)
    args = ap.parse_args()

    base    = args.url.rstrip("/")
    headers = {"Authorization": f"Bearer {args.key}"} if args.key else {}

    with httpx.Client(timeout=60, headers=headers) as c:
        print("Ensuring schema properties exist …")
        ensure_properties(base, args.cls, headers, c)

        total_processed = 0
        total_patched   = 0
        cursor          = None

        print("Scanning objects …")
        while True:
            params = {"class": args.cls, "limit": args.batch,
                      "include": "vector=false",
                      "properties": "budget_amount,publication_date,submission_deadline,"
                                    "budget_bucket,pub_month,deadline_month"}
            if cursor:
                params["after"] = cursor

            r = c.get(f"{base}/v1/objects", params=params)
            r.raise_for_status()
            objects = r.json().get("objects") or []
            if not objects:
                break

            for obj in objects:
                uid   = obj["id"]
                props = obj.get("properties") or {}

                want_bb  = budget_bucket(props.get("budget_amount"))
                want_pm  = month(props.get("publication_date"))
                want_dm  = month(props.get("submission_deadline"))

                patch = {}
                if props.get("budget_bucket")  != want_bb:  patch["budget_bucket"]  = want_bb
                if props.get("pub_month")       != want_pm:  patch["pub_month"]      = want_pm
                if props.get("deadline_month")  != want_dm:  patch["deadline_month"] = want_dm

                if patch:
                    c.patch(f"{base}/v1/objects/{args.cls}/{uid}",
                            json={"properties": patch}).raise_for_status()
                    total_patched += 1

                total_processed += 1
                cursor = uid

            print(f"  {total_processed} processed, {total_patched} patched …", end="\r")
            if len(objects) < args.batch:
                break
            time.sleep(0.05)  # be gentle

    print(f"\nDone. {total_processed} records scanned, {total_patched} updated.")


if __name__ == "__main__":
    main()
