import os, zipfile, glob
import httpx
from lxml import etree

ATOM = "{http://www.w3.org/2005/Atom}"
HOST = "https://contrataciondelsectorpublico.gob.es"

def unzip(zip_path: str, dest_dir: str) -> list[str]:
    os.makedirs(dest_dir, exist_ok=True)
    with zipfile.ZipFile(zip_path) as zf:
        zf.extractall(dest_dir)
    return sorted(glob.glob(os.path.join(dest_dir, "**", "*.atom"), recursive=True))

def feed_next_link(atom_path: str) -> str | None:
    # only the feed-level <link>; stop at first <entry>
    for _, el in etree.iterparse(atom_path, events=("end",)):
        ln = el.tag.rsplit("}", 1)[-1]
        if ln == "link" and el.get("rel") == "next":
            href = el.get("href") or ""
            # feeds reference contrataciondelestado.es; normalize to the canonical sync host
            return href.replace("https://contrataciondelestado.es", HOST)
        if ln == "entry":
            break
    return None

def download(url: str, dest: str, transport=None, timeout=600) -> str:
    os.makedirs(os.path.dirname(dest) or ".", exist_ok=True)
    with httpx.Client(timeout=timeout, transport=transport, verify=False,
                      headers={"User-Agent": "placsp-ingest"}) as c:
        r = c.get(url, follow_redirects=True)
        r.raise_for_status()
        with open(dest, "wb") as f:
            f.write(r.content)
    return dest
