from typing import Iterator, Union
from lxml import etree
from placsp.core.models import RawEntry, Tombstone

ATOM = "{http://www.w3.org/2005/Atom}"
TOMB = "{http://purl.org/atompub/tombstones/1.0}"
CFS = "{urn:dgpe:names:draft:codice-place-ext:schema:xsd:CommonAggregateComponents-2}ContractFolderStatus"

def _local(tag) -> str:
    return tag.rsplit("}", 1)[-1] if isinstance(tag, str) else ""

def _id_int(url: str) -> str:
    return (url or "").rstrip("/").rsplit("/", 1)[-1]

def parse_feed(path: str, category: str) -> Iterator[Union[RawEntry, Tombstone]]:
    for _, el in etree.iterparse(path, events=("end",)):
        ln = _local(el.tag)
        if ln == "entry":
            eid = el.findtext(f"{ATOM}id") or ""
            updated = el.findtext(f"{ATOM}updated")
            link_el = el.find(f"{ATOM}link")
            link = link_el.get("href") if link_el is not None else None
            cfs = el.find(CFS)
            yield RawEntry(_id_int(eid), updated, link, cfs, category)
            el.clear()
        elif ln == "deleted-entry":
            ref = el.get("ref") or ""
            when = el.get("when")
            comment = el.find(f"{TOMB}comment")
            reason = comment.get("type") if comment is not None else None
            yield Tombstone(_id_int(ref), when, reason, category)
            el.clear()
