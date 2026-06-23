"""Generate static codelist JSON maps for the search UI.

Parses the CODICE .gc codelists into flat {code: spanish_label} JSON files,
committed under search-ui/src/codelists/ and bundled by Vite. The search API
never sees labels; only the UI uses these to decode/search codes.

Usage:
  python scripts/build_codelists_json.py
  python scripts/build_codelists_json.py --codelists-dir codelists --out-dir search-ui/src/codelists
"""
import argparse
import json
import os

from placsp.codelists import parse_gc

# out_name -> .gc filename in the codelists dir
MAPPING = {
    "cpv": "CPV2008-2.04.gc",
    "status": "SyndicationContractFolderStatusCode-2.04.gc",
    "result": "TenderResultCode-2.09.gc",
    "contract_type": "ContractCode-2.08.gc",
    "procedure": "SyndicationTenderingProcessCode-2.07.gc",
    "nuts": "NUTS-2021.gc",
}


def gc_to_json_map(path: str) -> dict[str, str]:
    return parse_gc(path)


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--codelists-dir", default="codelists")
    ap.add_argument("--out-dir", default="search-ui/src/codelists")
    args = ap.parse_args(argv)
    os.makedirs(args.out_dir, exist_ok=True)
    for out_name, gc_file in MAPPING.items():
        src = os.path.join(args.codelists_dir, gc_file)
        m = gc_to_json_map(src)
        dst = os.path.join(args.out_dir, f"{out_name}.json")
        with open(dst, "w", encoding="utf-8") as f:
            json.dump(m, f, ensure_ascii=False, sort_keys=True)
        print(f"{out_name}: {len(m)} codes -> {dst}")


if __name__ == "__main__":
    main()
