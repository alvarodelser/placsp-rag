import os
from dataclasses import dataclass, field
from pathlib import Path

_PILOT = Path(__file__).resolve().parents[1]
_REPO = _PILOT.parent


def _env(k: str, d: str) -> str:
    return os.getenv(k, d)


# Default sample: the latest entries of each channel, mixed.
DEFAULT_QUOTAS = {
    "placsp_mayores": 50,
    "externos_mayores": 20,
    "placsp_menores": 15,
    "propios": 15,
}


@dataclass
class PilotConfig:
    run_dir: Path
    codelist_dir: Path
    ontology_path: Path
    # Services that exist on the server; the pilot runs no model of its own.
    nlp_url: str            # nlp_service: /summarize, /ner, /resolve
    ocr_url: str            # OCR service: /services/ocr
    vectorizer_url: str     # BGE-M3: /embed
    # Our stack's stores. The pilot keeps to its own namespace in each: pilot_* collections in
    # Qdrant, nodes labelled `Pilot` (+ Pilot<Type>) in Neo4j.
    qdrant_url: str
    qdrant_api_key: str
    collection_prefix: str
    neo4j_url: str
    neo4j_user: str
    neo4j_password: str
    neo4j_label_prefix: str
    embed_batch: int
    service_timeout: float
    fetch_workers: int
    nlp_workers: int
    max_file_mb: int
    # Keep each downloaded file after its text is extracted (default: delete it; the viewer shows
    # the original from its PLACSP link). Files waiting for OCR or that failed are always kept.
    keep_files: bool
    # NER chunk size in words, as nlp_service's relation pipeline (RELATIONS_CHUNK_TOKENS).
    chunk_words: int
    # Max NER chunks per document (0 = all). Over the cap, the chunks with the most procurement
    # vocabulary are kept; the report counts the skipped ones so full cost can be extrapolated.
    ner_max_chunks: int
    describe_relations: bool
    describe_feed: str      # template (feed entities described from their fields) | model
    staging_dir: str        # level 1 data dir (src/placsp/staging): companies' NIFs by name, `select --staging`
    ner_skip_roles: str     # comma-separated document roles to leave out of NER (default: none)
    # Seconds one /ner call may take before the stage stops: catches Ollama running on the CPU.
    ner_preflight_s: float
    # NER reads a PCAP only in the sections whose headings hold penalties, solvency, criteria
    # (locate.relevant_chunks); off: every chunk, up to ner_max_chunks.
    ner_by_section: bool
    # Text extraction: roles whose PDFs get the layout pass (pymupdf4llm: Markdown headings, tables
    # as rows, page headers and footers marked), "*" for all; and how new texts are chunked.
    layout_roles: str
    chunker: str            # sections | words
    coref: bool             # link references ("la empresa"...) to their entities; one call per passage with them
    ocr_min_chars_per_page: int
    quotas: dict = field(default_factory=lambda: dict(DEFAULT_QUOTAS))

    @property
    def db_path(self) -> Path:
        return self.run_dir / "pilot.db"

    @property
    def files_dir(self) -> Path:
        return self.run_dir / "files"

    @property
    def text_dir(self) -> Path:
        return self.run_dir / "text"

    @property
    def raw_dir(self) -> Path:
        return self.run_dir / "raw"

    @property
    def out_dir(self) -> Path:
        return self.run_dir / "out"


def load_config(run_dir: str | None = None) -> PilotConfig:
    cfg = PilotConfig(
        run_dir=Path(run_dir or _env("PILOT_RUN_DIR", "./pilot_runs/default")).resolve(),
        codelist_dir=Path(_env("PILOT_CODELIST_DIR", str(_REPO / "codelists"))),
        ontology_path=Path(_env("PILOT_ONTOLOGY", str(_PILOT / "ontology" / "placsp_procurement.yaml"))),
        nlp_url=_env("NLP_SERVICE_URL", "").rstrip("/"),
        ocr_url=_env("OCR_URL", "").rstrip("/"),
        vectorizer_url=_env("VECTORIZER_URL", "").rstrip("/"),
        qdrant_url=_env("QDRANT_URL", "http://localhost:6343").rstrip("/"),
        qdrant_api_key=_env("QDRANT_API_KEY", ""),
        collection_prefix=_env("PILOT_COLLECTION_PREFIX", "pilot_"),
        neo4j_url=_env("NEO4J_URL", "bolt://localhost:7687"),
        neo4j_user=_env("NEO4J_USER", "neo4j"),
        neo4j_password=_env("NEO4J_PASSWORD", ""),
        neo4j_label_prefix=_env("PILOT_NEO4J_LABEL_PREFIX", "Pilot"),
        embed_batch=int(_env("PILOT_EMBED_BATCH", "32")),
        service_timeout=float(_env("PILOT_SERVICE_TIMEOUT", "600")),
        fetch_workers=int(_env("PILOT_FETCH_WORKERS", "4")),
        nlp_workers=int(_env("PILOT_NLP_WORKERS", "2")),
        max_file_mb=int(_env("PILOT_MAX_FILE_MB", "200")),
        keep_files=_env("PILOT_KEEP_FILES", "0") not in ("0", "false", "no"),
        chunk_words=int(_env("PILOT_CHUNK_WORDS", "512")),
        ner_max_chunks=int(_env("PILOT_NER_MAX_CHUNKS", "60")),
        describe_relations=_env("PILOT_DESCRIBE_RELATIONS", "1") not in ("0", "false", "no"),
        describe_feed=_env("PILOT_DESCRIBE_FEED", "template"),
        staging_dir=_env("PILOT_STAGING_DIR", ""),
        ner_skip_roles=_env("PILOT_NER_SKIP_ROLES", ""),
        ner_preflight_s=float(_env("PILOT_NER_PREFLIGHT_S", "60")),
        ner_by_section=_env("PILOT_NER_BY_SECTION", "1") not in ("0", "false", "no"),
        layout_roles=_env("PILOT_LAYOUT_ROLES", "PCAP,PPT,PCAP+PPT,BoardMinutes,ValuationReport,AbnormalBidReport,"
                                                "AwardProposal,AwardResolution,ContractDocument,ModificationDocument,"
                                                "Clarification,AppealDocument,TenderNotice"),
        chunker=_env("PILOT_CHUNKER", "sections"),
        coref=_env("PILOT_COREF", "1") not in ("0", "false", "no"),
        ocr_min_chars_per_page=int(_env("PILOT_OCR_MIN_CHARS_PER_PAGE", "80")),
    )
    for d in (cfg.run_dir, cfg.files_dir, cfg.text_dir, cfg.raw_dir, cfg.out_dir):
        d.mkdir(parents=True, exist_ok=True)
    return cfg
