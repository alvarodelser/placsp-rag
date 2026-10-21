"""Field inventory of PLACSP archives: every element path inside ContractFolderStatus and the
share of entries that carry it. Use it to see what a channel/year publishes before trusting a
field, and to spot paths the staging parser does not read yet.

Usage: python scripts/survey_feed.py <zip> [<zip> ...] [--out DIR]
Writes <DIR>/<zip name>.survey.json: {entries, distinct_ids, tombstones, paths: {path: [n, pct, sample]}}
"""
import argparse, collections, json, os, zipfile
from lxml import etree

ATOM = "{http://www.w3.org/2005/Atom}"


def _local(tag):
    return tag.rsplit("}", 1)[-1] if isinstance(tag, str) else ""


def survey(zpath: str) -> dict:
    counts, sample, ids = collections.Counter(), {}, set()
    entries = tombs = 0
    with zipfile.ZipFile(zpath) as zf:
        for name in sorted(n for n in zf.namelist() if n.endswith(".atom")):
            with zf.open(name) as fh:
                for _, el in etree.iterparse(fh, events=("end",), huge_tree=True):
                    ln = _local(el.tag)
                    if ln not in ("entry", "deleted-entry"):
                        continue
                    if ln == "deleted-entry":
                        tombs += 1
                    else:
                        entries += 1
                        ids.add((el.findtext(f"{ATOM}id") or "").rsplit("/", 1)[-1])
                        cfs = next((c for c in el if _local(c.tag) == "ContractFolderStatus"), None)
                        here = set()
                        for d in (cfs.iter() if cfs is not None else ()):
                            if d is cfs or not isinstance(d.tag, str):
                                continue
                            parts, p = [], d
                            while p is not cfs:
                                parts.append(_local(p.tag))
                                p = p.getparent()
                            path = "/".join(reversed(parts))
                            here.add(path)
                            t = (d.text or "").strip()
                            if t and path not in sample:
                                sample[path] = t[:80]
                        counts.update(here)
                    el.clear()
                    while el.getprevious() is not None:
                        del el.getparent()[0]
    return {"zip": os.path.basename(zpath), "entries": entries, "distinct_ids": len(ids), "tombstones": tombs,
            "paths": {p: [n, round(100 * n / max(entries, 1), 1), sample.get(p)] for p, n in counts.most_common()}}


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("zips", nargs="+")
    ap.add_argument("--out", default=".")
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)
    for z in a.zips:
        r = survey(z)
        out = os.path.join(a.out, r["zip"].replace(".zip", ".survey.json"))
        with open(out, "w") as f:
            json.dump(r, f, ensure_ascii=False, indent=1)
        print(r["zip"], "entries", r["entries"], "distinct", r["distinct_ids"], "tombstones", r["tombstones"],
              "paths", len(r["paths"]), "->", out)
