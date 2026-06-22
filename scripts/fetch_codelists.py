"""Scan a sample feed for every distinct listURI and download each .gc into the cache dir."""
import os, sys
from lxml import etree
import httpx

def main(sample_atom: str, cache_dir: str):
    os.makedirs(cache_dir, exist_ok=True)
    uris = set()
    for _, el in etree.iterparse(sample_atom, events=("end",)):
        u = el.get("listURI") or el.get("listURIID")
        if u:
            uris.add(u.replace("http://", "https://"))
        el.clear()
    with httpx.Client(verify=False, timeout=120, headers={"User-Agent": "placsp"}) as c:
        for u in sorted(uris):
            fn = u.rstrip("/").rsplit("/", 1)[-1]
            try:
                r = c.get(u, follow_redirects=True)
                if r.status_code == 200:
                    open(os.path.join(cache_dir, fn), "wb").write(r.content)
                    print("ok", fn)
                else:
                    print("skip", fn, r.status_code)
            except Exception as e:
                print("err", fn, e)

if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
