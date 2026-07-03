#!/usr/bin/env python3
"""Measure how much of the profile-match's structured input the HTML parser
actually captures.

The match verdict leans on the platform's structured criteria (clasificación,
condiciones de admisión, nº empleados, etc.). Those fields come from brittle
heading-matching in ``pliego_html_parser`` and are often empty. This samples
real ``Placsp_pliego_criteria`` objects from Weaviate and reports the fill-rate
of each gate field, so you can see how often the match is relying on the parsed
criteria vs. having to fall back to the PDFs.

Run with the stack up:  python scripts/check_criteria_coverage.py --limit 500
"""
import sys
import json
import argparse
from collections import Counter

sys.path.append("src")
from placsp.config import load_config
import httpx

# The fields fed into the match prompt (see PliegoExtractor._MATCH_CRITERIA_KEYS).
GATE_FIELDS = [
    "clasificacion_empresarial", "condiciones_admision", "motivos_exclusion",
    "num_empleados_min", "garantia_definitiva_pct", "garantia_complementaria_pct",
    "criterios_adjudicacion",
]


def _is_filled(value) -> bool:
    if value in (None, "", [], {}, 0):
        return False
    return True


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=500)
    args = ap.parse_args()

    cfg = load_config()
    headers = {"Authorization": f"Bearer {cfg.weaviate_api_key}"} if cfg.weaviate_api_key else {}
    gql = f"""{{ Get {{ Placsp_pliego_criteria(limit: {args.limit}) {{ criteria_json }} }} }}"""
    r = httpx.post(f"{cfg.weaviate_url.rstrip('/')}/v1/graphql",
                   json={"query": gql}, headers=headers, timeout=60)
    r.raise_for_status()
    hits = (((r.json().get("data") or {}).get("Get") or {}).get("Placsp_pliego_criteria")) or []

    total = len(hits)
    if not total:
        print("No Placsp_pliego_criteria objects found. Is ingestion populated?")
        return

    filled = Counter()
    for h in hits:
        try:
            crit = json.loads(h.get("criteria_json") or "{}")
        except json.JSONDecodeError:
            continue
        for f in GATE_FIELDS:
            if _is_filled(crit.get(f)):
                filled[f] += 1

    print(f"Sampled {total} licitaciones.\n")
    print(f"{'field':<32} {'filled':>8} {'coverage':>10}")
    print("-" * 52)
    for f in GATE_FIELDS:
        pct = 100 * filled[f] / total
        print(f"{f:<32} {filled[f]:>8} {pct:>9.1f}%")
    print("\nLow coverage on a field = the match must lean on the PDFs for it.")


if __name__ == "__main__":
    main()
