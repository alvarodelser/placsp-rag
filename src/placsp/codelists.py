import os
from typing import Optional
from lxml import etree

def _local(tag) -> str:
    return tag.rsplit("}", 1)[-1] if isinstance(tag, str) else ""

def parse_gc(path: str) -> dict[str, str]:
    """Parse a CODICE genericode .gc file -> {code: spanish_label}."""
    root = etree.parse(path).getroot()
    out: dict[str, str] = {}
    for row in root.iter():
        if _local(row.tag) != "Row":
            continue
        vals: dict[str, str] = {}
        for v in row:
            if _local(v.tag) != "Value":
                continue
            col = v.get("ColumnRef")
            sv = next((c for c in v if _local(c.tag) == "SimpleValue"), None)
            if col and sv is not None and sv.text:
                vals[col] = sv.text.strip()
        code = vals.get("code")
        if code:
            out[code] = vals.get("nombre") or vals.get("name") or code
    return out

class Codelists:
    def __init__(self, cache_dir: str):
        self.cache_dir = cache_dir
        self._cache: dict[str, dict[str, str]] = {}

    def _load(self, filename: str) -> dict[str, str]:
        if filename not in self._cache:
            path = os.path.join(self.cache_dir, filename)
            self._cache[filename] = parse_gc(path) if os.path.exists(path) else {}
        return self._cache[filename]

    def label(self, list_uri: Optional[str], code: Optional[str]) -> Optional[str]:
        if not list_uri or not code:
            return None
        filename = list_uri.rstrip("/").rsplit("/", 1)[-1]
        return self._load(filename).get(code)
