"""Column definitions of the staging tables.

Every table but `tombstone` carries `vkey`, the key of one published version of one entry
(<zip>/<atom file>#<position>), which `entry` defines. A version is a full snapshot of the
tender as PLACSP published it at `updated`; `build` keeps the latest one per `entry_id`.
Codes are stored as published; their labels come from the `codelist` table.
"""
import pyarrow as pa

S, F, I, B = pa.string(), pa.float64(), pa.int64(), pa.bool_()
LS = pa.list_(pa.string())

TABLES: dict[str, list[tuple[str, pa.DataType]]] = {
    "entry": [
        ("vkey", S), ("entry_id", S), ("channel", S), ("src_zip", S), ("src_file", S), ("updated", S),
        ("link", S), ("atom_title", S), ("atom_summary", S),
        ("folder_id", S), ("status_code", S), ("uuid", S),
        # contracting authority
        ("auth_name", S), ("auth_nif", S), ("auth_dir3", S), ("auth_platform_id", S), ("auth_ids", LS),
        ("auth_type_code", S), ("auth_activity_codes", LS), ("auth_website", S), ("auth_buyer_profile", S), ("auth_address", S),
        ("auth_city", S), ("auth_postal_code", S), ("auth_country", S),
        ("auth_contact_name", S), ("auth_email", S), ("auth_phone", S),
        ("auth_parent_names", LS), ("auth_parent_ids", LS),      # nearest parent first; id "" when none
        ("agent_name", S), ("agent_id", S),                     # body that publishes on the authority's behalf
        # the tender (ProcurementProject + TenderingProcess + TenderingTerms)
        ("name", S), ("contract_type_code", S), ("subtype_code", S), ("mixed", B),
        ("value_estimated", F), ("budget_tax_excl", F), ("budget_total", F), ("cpv", LS),
        ("nuts", S), ("region", S), ("street", S), ("city", S), ("postal_code", S), ("country", S),
        ("duration", F), ("duration_unit", S), ("period_start", S), ("period_end", S), ("extension_validity", S),
        ("extension_options", S),
        ("procedure_code", S), ("urgency_code", S), ("contracting_system_code", S), ("submission_method_code", S),
        ("over_threshold", B), ("deadline_date", S), ("deadline_time", S), ("participation_deadline_date", S),
        ("participation_deadline_time", S), ("participation_deadline_note", S), ("doc_availability_end", S),
        ("doc_availability_end_time", S), ("tender_recipient", S),
        ("deadline_note", S), ("auction", B), ("part_presentation_code", S), ("max_lots_tender", I), ("max_lots_award", I),
        ("lots_combination", S), ("shortlist_min", I), ("shortlist_max", I), ("shortlist_expected", I), ("shortlist_criteria", S),
        ("funding_codes", LS), ("funding_text", S), ("national_legislation_code", S), ("eu_legislation", LS),
        ("variants_allowed", B), ("curricula_required", B), ("price_revision", S),
        ("subcontract_text", S), ("subcontract_rate", F), ("appeals_received", F), ("language", S),
    ],
    "lot": [
        ("vkey", S), ("lot_id", S), ("name", S), ("cpv", LS), ("value_estimated", F),
        ("budget_tax_excl", F), ("budget_total", F), ("nuts", S), ("region", S), ("city", S), ("street", S),
    ],
    "result": [
        ("vkey", S), ("result_idx", I), ("lot_ids", LS), ("result_code", S), ("description", S),
        ("award_date", S), ("start_date", S), ("bids_received", F), ("sme_bids", F), ("eu_bids", F),
        ("non_eu_bids", F), ("electronic_bids", F), ("lowest_bid", F), ("highest_bid", F),
        ("abnormally_low_excluded", B), ("sme_awarded", B), ("winner_nationality", S),
        ("subcontract_rate", F), ("subcontract_text", S), ("amount_tax_excl", F), ("amount_payable", F),
        ("contract_ids", LS), ("contract_dates", LS),
    ],
    "winner": [
        ("vkey", S), ("result_idx", I), ("winner_idx", I), ("name", S), ("nif", S), ("id_scheme", S),
        ("nuts", S), ("city", S), ("postal_code", S), ("country", S),
    ],
    "criterion": [
        ("vkey", S), ("lot_id", S), ("idx", I), ("type_code", S), ("subtype_code", S), ("description", S),
        ("weight", F), ("note", S),
    ],
    "requirement": [
        ("vkey", S), ("lot_id", S), ("idx", I), ("kind", S), ("type_code", S), ("description", S),
        ("threshold", F), ("classification", S),
    ],
    "guarantee": [
        ("vkey", S), ("lot_id", S), ("type_code", S), ("amount", F), ("rate_pct", F), ("duration", F),
    ],
    "condition": [
        ("vkey", S), ("lot_id", S), ("type_code", S), ("name", S), ("description", S),
    ],
    "notice": [
        ("vkey", S), ("notice_idx", I), ("type_code", S), ("media", LS), ("dates", LS), ("sent_to", LS), ("sent_dates", LS), ("sent_times", LS),
    ],
    "document": [
        ("vkey", S), ("source", S), ("notice_idx", I), ("doc_id", S), ("type_code", S), ("filename", S),
        ("url", S), ("hash", S),
    ],
    "modification": [
        ("vkey", S), ("mod_id", S), ("contract_id", S), ("note", S), ("duration_change", F),
        ("final_duration", F), ("amount_change", F), ("final_amount", F),
    ],
    "tombstone": [
        ("entry_id", S), ("channel", S), ("src_zip", S), ("src_file", S), ("when", S), ("reason", S),
    ],
}

for _t, _cols in TABLES.items():          # position of the row within its entry, as published
    if _t not in ("entry", "tombstone"):
        _cols.insert(1, ("pos", I))

SCHEMAS = {t: pa.schema(cols) for t, cols in TABLES.items()}
