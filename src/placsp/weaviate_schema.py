import httpx

def _props():
    text = lambda n: {"name": n, "dataType": ["text"]}
    num = lambda n: {"name": n, "dataType": ["number"]}
    date = lambda n: {"name": n, "dataType": ["date"]}
    out = [text(n) for n in [
        "syndication_id", "expediente", "title", "content", "lang", "category",
        "source_url", "buyer_profile_url", "status_code", "status_label",
        "result_code", "result_label", "contract_type_code", "contract_type",
        "procedure_code", "procedure", "notice_type", "contracting_authority",
        "contracting_authority_id", "org_top_level", "adjudicatario",
        "adjudicatario_nif", "nuts", "nuts_label", "city", "country", "funding_program"]]
    out += [{"name": n, "dataType": ["text[]"]} for n in ["cpv", "document_urls"]]
    out += [num("budget_amount"), num("estimated_value"), num("awarded_amount"),
            {"name": "n_bids", "dataType": ["int"]},
            {"name": "sme_awarded", "dataType": ["boolean"]}]
    out += [date(n) for n in ["publication_date", "award_date", "submission_deadline", "updated"]]
    out += [
        {"name": "status_history", "dataType": ["object[]"], "nestedProperties": [
            {"name": "code", "dataType": ["text"]}, {"name": "date", "dataType": ["text"]}]},
        {"name": "lots", "dataType": ["object[]"], "nestedProperties": [
            {"name": "lot_id", "dataType": ["text"]}, {"name": "name", "dataType": ["text"]},
            {"name": "amount", "dataType": ["number"]}, {"name": "cpv", "dataType": ["text[]"]}]},
    ]
    return out

CLASS_DEF = {
    "class": "Placsp_licitaciones",
    "description": "PLACSP procurement expedientes (latest state).",
    "vectorizer": "none",
    "vectorIndexConfig": {"distance": "cosine"},
    "invertedIndexConfig": {"bm25": {"b": 0.75, "k1": 1.2}},
    "properties": _props(),
}

COMPANY_CLASS_DEF = {
    "class": "Placsp_companies",
    "description": "Companies involved in public procurement.",
    "vectorizer": "none",
    "vectorIndexConfig": {"distance": "cosine"},
    "invertedIndexConfig": {"bm25": {"b": 0.75, "k1": 1.2}},
    "properties": [
        {"name": "nif", "dataType": ["text"]},
        {"name": "name", "dataType": ["text"]},
        {"name": "description", "dataType": ["text"]}
    ],
}

def ensure_class(base_url, api_key, class_name, class_def=CLASS_DEF, timeout=300, transport=None) -> bool:
    headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
    base = base_url.rstrip("/")
    with httpx.Client(timeout=timeout, transport=transport, headers=headers) as c:
        r = c.get(f"{base}/v1/schema/{class_name}")
        if r.status_code == 200:
            return False
        body = dict(class_def, **{"class": class_name})
        c.post(f"{base}/v1/schema", json=body).raise_for_status()
        return True
