"""Load the ontology YAML (nlp_service format) and project the inline ExtractionSchema for /ner.

Mirrors nlp_service/pipelines/relations/ontology.py so the same file works in both places.
"""
import re
from pathlib import Path

import yaml

_DT = {"string", "number", "boolean"}
_NAME_RE = re.compile(r"^[A-Z][A-Z0-9_]*$")


def load(path: Path) -> dict:
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    entity_names = set()
    for e in data.get("entity_types", []):
        if not _NAME_RE.match(e["name"]):
            raise ValueError(f"entity type name must be SCREAMING_SNAKE_CASE: {e['name']!r}")
        entity_names.add(e["name"])
        for k, v in (e.get("attributes") or {}).items():
            if v.get("type") not in _DT:
                raise ValueError(f"entity {e['name']} attribute {k!r} has invalid datatype")
    for r in data.get("relation_types", []):
        for t in [*r["head_types"], *r["tail_types"]]:
            if t not in entity_names:
                raise ValueError(f"relation {r['name']!r} references undeclared entity type {t!r}")
    return data


def _attrs(d: dict) -> list[dict]:
    return [{"name": k, "datatype": v["type"], "description": v.get("description", "")}
            for k, v in (d.get("attributes") or {}).items()]


def _subtypes(d: dict) -> list[dict]:
    return [{"name": s["name"], "description": s.get("description", "")} for s in d.get("subtypes", [])]


def extraction_schema(data: dict) -> dict:
    """The JSON body of the `schema` field of POST /ner."""
    return {
        "entity_types": [{"name": e["name"], "description": e.get("description", ""),
                          "subtypes": _subtypes(e), "attributes": _attrs(e)} for e in data["entity_types"]],
        "relation_types": [{"name": r["name"], "description": r.get("description", ""),
                            "subtypes": _subtypes(r), "attributes": _attrs(r),
                            "head_types": r["head_types"], "tail_types": r["tail_types"]}
                           for r in data["relation_types"]],
    }


def ner_types(data: dict, role: str | None, feed_lacks: set[str] = frozenset()) -> set[str]:
    """The entity types /ner asks for in a document of this role: its profiles' types, plus the feed
    types this expediente's feed lacks (`fallback`). Empty when NER does not read the role.
    `feed_lacks` also carries what the feed settles (`single_bid`): a profile `unless` it is skipped."""
    types = {t for p in (data.get("profiles") or {}).values()
             if role in p["roles"] and not set(p.get("unless") or []) & set(feed_lacks) for t in p["entity_types"]}
    types |= {t for t, fb in (data.get("fallback") or {}).items() if t in feed_lacks and role in fb["roles"]}
    return types


def extraction_schema_for(data: dict, types: set[str]) -> dict:
    """The ExtractionSchema restricted to these entity types and the relations between them."""
    full = extraction_schema(data)
    rels = []
    for r in full["relation_types"]:
        heads, tails = [t for t in r["head_types"] if t in types], [t for t in r["tail_types"] if t in types]
        if heads and tails:
            rels.append({**r, "head_types": heads, "tail_types": tails})
    return {"entity_types": [e for e in full["entity_types"] if e["name"] in types], "relation_types": rels}
