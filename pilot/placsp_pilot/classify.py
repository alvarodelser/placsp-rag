"""Map each referenced document to a role in the pilot data model.

Rules run first (feed source, type codes, notice type, filename keywords in
Spanish, Catalan and Basque). Anything left as OTHER can be re-labelled by the
LLM during summarisation.
"""
import re

# Roles. The first block is the data model as given; the rest are the
# documents PLACSP actually publishes that the model did not name.
PCAP = "PCAP"
PPT = "PPT"
PCAP_PPT = "PCAP+PPT"                    # one combined pliego file
TENDER_NOTICE = "TenderNotice"
CLARIFICATION = "Clarification"          # rectificaciones, aclaraciones, preguntas y respuestas
BOARD_MINUTES = "BoardMinutes"           # actas de la mesa / órgano de asistencia
AWARD_RESOLUTION = "AwardResolution"
CONTRACT_DOCUMENT = "ContractDocument"   # contrato / documento de formalización
ANNEX = "Annex"                          # DEUC, modelos de oferta, anexos a rellenar
VALUATION_REPORT = "ValuationReport"     # informe de valoración (juicio de valor)
ABNORMAL_BID_REPORT = "AbnormalBidReport"
AWARD_PROPOSAL = "AwardProposal"
AWARD_NOTICE = "AwardNotice"
FORMALIZATION_NOTICE = "FormalizationNotice"
MODIFICATION = "ModificationDocument"    # modificación, prórroga
MODIFICATION_NOTICE = "ModificationNotice"
CANCELLATION = "CancellationDocument"    # renuncia, desistimiento, anulación, desierto
PREPARATORY = "PreparatoryDocument"      # memoria justificativa, acuerdo de inicio, aprobación, insuficiencia de medios
APPEAL = "AppealDocument"                # recursos, resoluciones de tribunales (TACRC...)
PROJECT = "ProjectDocument"              # proyecto de obra, planos, presupuesto, mediciones
TECHNICAL_ANNEX = "TechnicalAnnex"       # inventarios, listados, datos técnicos, planos sueltos
PRIOR_NOTICE = "PriorNotice"             # anuncio previo, consulta preliminar
OTHER = "Other"

ROLES = [PCAP, PPT, PCAP_PPT, TENDER_NOTICE, PRIOR_NOTICE, CLARIFICATION, ANNEX, PROJECT, TECHNICAL_ANNEX, PREPARATORY,
         BOARD_MINUTES, VALUATION_REPORT, ABNORMAL_BID_REPORT, AWARD_PROPOSAL, AWARD_RESOLUTION,
         AWARD_NOTICE, CONTRACT_DOCUMENT, FORMALIZATION_NOTICE, MODIFICATION, MODIFICATION_NOTICE,
         CANCELLATION, APPEAL, OTHER]

# Which structured extraction each role feeds (see extract.py).
EXTRACTION_KIND = {
    PCAP: ["pcap"], PPT: ["ppt"], PCAP_PPT: ["pcap", "ppt"],
    BOARD_MINUTES: ["bids"], VALUATION_REPORT: ["bids"], ABNORMAL_BID_REPORT: ["bids"],
    AWARD_PROPOSAL: ["bids"], AWARD_RESOLUTION: ["bids"],
    CONTRACT_DOCUMENT: ["contract"],
    MODIFICATION: ["modification"],
    CLARIFICATION: ["clarification"],
}

# GeneralContractDocuments codelist (placsp_mayores).
_GENERAL_CODE = {
    "1": BOARD_MINUTES,      # actos públicos informativos / apertura de ofertas
    "2": BOARD_MINUTES,      # composición del jurado
    "3": BOARD_MINUTES,      # composición del comité de expertos
    "4": APPEAL,             # suspensión del procedimiento
    "5": APPEAL,             # levantamiento de la suspensión
    "6": APPEAL,             # mantenimiento de efectos
    "7": APPEAL,             # declaración de invalidez
    "8": PREPARATORY,        # acuerdo de iniciación
    "9": PREPARATORY,        # memoria justificativa
    "10": PREPARATORY,       # informe de insuficiencia de medios
    "11": PREPARATORY,       # aprobación del expediente
    "12": BOARD_MINUTES,     # acta del órgano de asistencia
    "13": VALUATION_REPORT,  # informe de valoración juicio de valor
    "14": ABNORMAL_BID_REPORT,
    "15": BOARD_MINUTES,     # jurado del concurso de proyectos
}
# Encargos a medios propios (propios channel) use a different list.
_ENCARGO_CODE = {"1": CONTRACT_DOCUMENT, "2": PREPARATORY, "3": PREPARATORY, "4": MODIFICATION}

_NOTICE_CODE = {
    "DOC_CN": TENDER_NOTICE, "DOC_CD": TENDER_NOTICE, "DOC_DD": TENDER_NOTICE,
    "DOC_PIN": PRIOR_NOTICE, "DOC_PIN_RTL": PRIOR_NOTICE, "DOC_CON": PRIOR_NOTICE,
    "DOC_CAN_ADJ": AWARD_NOTICE, "DOC_CAN_PROV": AWARD_NOTICE, "DOC_CAN_DEF": AWARD_NOTICE,
    "DOC_FORM": FORMALIZATION_NOTICE, "DOC_FORM_ENC": FORMALIZATION_NOTICE, "PRO_FORM_ENC": MODIFICATION_NOTICE,
    "DOC_MOD": MODIFICATION_NOTICE, "DOC_CCN": OTHER,
    "RENUNCIA": CANCELLATION, "DESISTIMIENTO": CANCELLATION,
}
_NOTICE_DOC_CODE = {"ACTA_ADJ": AWARD_RESOLUTION, "ACTA_FORM": CONTRACT_DOCUMENT}

# Row labels of the detail page's notice table.
_NOTICE_LABEL: list[tuple[str, str]] = [
    (r"renuncia|desistimiento|anulaci", CANCELLATION),
    (r"rectifica|correcci", CLARIFICATION),
    (r"previo|consulta preliminar", PRIOR_NOTICE),
    (r"modificaci|pr[oó]rroga", MODIFICATION_NOTICE),
    (r"formalizaci", FORMALIZATION_NOTICE),
    (r"adjudicaci", AWARD_NOTICE),
    (r"finalizaci", OTHER),
]

# Ordered: the first match wins, so specific patterns come before generic ones.
_KEYWORDS: list[tuple[str, str]] = [
    (r"recurso|tacrc|tribunal administrativo|tacp\b|oarc|reclamaci[oó]n", APPEAL),
    (r"rectifica|correcci[oó]n de errores|aclaraci|preguntas|respuestas|consultas|zuzen", CLARIFICATION),
    (r"renuncia|desistimiento|anulaci[oó]n|desiert|deserta", CANCELLATION),
    (r"modificaci[oó]n del contrato|modificat|pr[oó]rroga|prorroga|luzapen|aldaketa", MODIFICATION),
    (r"anormal|temerari|desproporcionad", ABNORMAL_BID_REPORT),
    (r"informe.*(valoraci|t[eé]cnic)|valoraci[oó]n.*(oferta|criterio|sobre)|juicio de valor|judici de valor", VALUATION_REPORT),
    (r"propuesta de adjudicaci|proposta d.adjudicaci", AWARD_PROPOSAL),
    (r"\bacta|actes?\b|mesa de contrataci|apertura|sobre ?[abc123]\b|akta", BOARD_MINUTES),
    (r"resoluci[oó]n.*adjudica|adjudicaci[oó]n|resoluci[oó] d.adjudicaci|adjudicaci[oó]|esleipen", AWARD_RESOLUTION),
    (r"\bdeuc\b|anexo|annex|modelo|model d|proposici[oó]n econ|oferta econ|declaraci[oó]n responsable|eranskin", ANNEX),
    (r"formalizaci|contrato firmado|\bcontrato\b|contracte|kontratu", CONTRACT_DOCUMENT),
    (r"proyecto|projecte|plano|planos|mediciones|presupuesto|amidament|pressupost|\.bc3|estudio de seguridad|eiss|ess\b", PROJECT),
    (r"memoria justificativa|informe de necesidad|necesidad|acuerdo de inicio|iniciaci[oó]n|aprobaci[oó]n del expediente|insuficiencia", PREPARATORY),
    (r"anuncio|anunci\b|iragarki", TENDER_NOTICE),
]
_PCAP_RE = re.compile(r"pcap|cl[aá]usulas? ?administrativ|administrativ|advas|clàusules administratives|administratiboa|pca\b|pcp\b|pliego.*particular", re.I)
_PPT_RE = re.compile(r"\bppt|\bptt|prescripciones t[eé]cnicas|t[eé]cnic|prescripcions t[eè]cniques|teknikoa|pt\b|pptp", re.I)


def classify(ref: dict, channel: str) -> tuple[str, str]:
    """Return (role, rule) for one docref dict."""
    src = ref.get("source")
    label = (ref.get("label") or "").lower()
    code = ref.get("type_code")
    if src == "feed_legal":
        return (PCAP_PPT, "feed_legal+technical") if ref.get("also_technical") else (PCAP, "feed_legal")
    if src == "feed_technical":
        return PPT, "feed_technical"
    if src == "feed_notice" and code in _NOTICE_DOC_CODE:
        return _NOTICE_DOC_CODE[code], f"notice_doc:{code}"
    if src == "feed_general" and code:
        table = _ENCARGO_CODE if channel == "propios" else _GENERAL_CODE
        if code in table:
            return table[code], f"general_code:{code}"
    if src == "detail_notice":
        for pat, role in _NOTICE_LABEL:
            if re.search(pat, label):
                return role, "detail_notice:label"
        return TENDER_NOTICE, "detail_notice:default"
    if src in ("feed_additional", "detail_external", "zip_member") and not re.search(r"anexo|annex|eranskin|modelo", label):
        has_pcap, has_ppt = bool(_PCAP_RE.search(label)), bool(_PPT_RE.search(label))
        if has_pcap and has_ppt and re.search(r"pliego|plec|plegu", label):
            return PCAP_PPT, f"{src}:kw"
        if has_pcap and not has_ppt:
            return PCAP, f"{src}:kw"
        if has_ppt and not has_pcap and re.search(r"pliego|plec|plegu|prescripci|ppt|ptt", label):
            return PPT, f"{src}:kw"
    for pat, role in _KEYWORDS:
        if re.search(pat, label):
            return role, "kw"
    if src == "feed_additional":
        return ANNEX, "additional:default"
    return OTHER, "default"


# Roles the rules could only guess; the classify stage asks nlp_service /nli about these.
WEAK_SOURCES = ("default", "additional:default")

# NLI hypotheses ("Este documento es {}.") for zero-shot classification of unlabelled documents.
NLI_HYPOTHESES = {
    PCAP: "un pliego de cláusulas administrativas particulares",
    PPT: "un pliego de prescripciones técnicas",
    PROJECT: "un proyecto de obra con memoria, planos, mediciones o presupuesto",
    TECHNICAL_ANNEX: "un inventario, listado o tabla de datos técnicos",
    ANNEX: "un modelo o formulario que deben rellenar los licitadores",
    PREPARATORY: "una memoria justificativa, informe de necesidad o acuerdo de inicio del expediente",
    BOARD_MINUTES: "un acta de la mesa de contratación",
    VALUATION_REPORT: "un informe de valoración de ofertas",
    AWARD_RESOLUTION: "una resolución de adjudicación",
    CONTRACT_DOCUMENT: "un contrato firmado o documento de formalización",
    MODIFICATION: "una modificación o prórroga de un contrato",
    CLARIFICATION: "una aclaración, respuesta a preguntas o rectificación",
    APPEAL: "una resolución de un recurso",
}

