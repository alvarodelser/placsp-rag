"""Genericode (.gc) label lookup, keyed by the codelist name in a listURI.

The feed's listURI may name a different version than the file on disk
(e.g. ContractCode-2.08 vs -2.10), so lookups match on the name without
the version suffix.
"""
import re
from pathlib import Path

from lxml import etree

_VER = re.compile(r"-\d+(\.\d+)*$")


def _stem(name: str) -> str:
    base = name.rsplit("/", 1)[-1]
    base = base[:-3] if base.endswith(".gc") else base
    return _VER.sub("", base)


class Codelists:
    def __init__(self, directory: Path):
        self._maps: dict[str, dict[str, str]] = {}
        d = Path(directory)
        if not d.is_dir():
            return
        for f in sorted(d.glob("*.gc")):
            try:
                tree = etree.parse(str(f))
            except etree.XMLSyntaxError:
                continue
            m: dict[str, str] = {}
            for row in tree.iter("{*}Row", "Row"):
                vals = [v.findtext("{*}SimpleValue") or v.findtext("SimpleValue") for v in row.iter("{*}Value", "Value")]
                if len(vals) >= 2 and vals[0]:
                    m[vals[0].strip()] = (vals[1] or "").strip()
            self._maps[_stem(f.name)] = m

    def label(self, list_uri: str | None, code: str | None) -> str | None:
        if not list_uri or code is None:
            return None
        return self._maps.get(_stem(list_uri), {}).get(code.strip())

    def by_name(self, name: str, code: str | None) -> str | None:
        if code is None:
            return None
        return self._maps.get(name, {}).get(code.strip())
