import os
from dataclasses import dataclass

def _env(k, d): return os.getenv(k, d)

@dataclass
class Config:
    vectorizer_url: str
    weaviate_url: str
    weaviate_api_key: str
    weaviate_class: str
    work_dir: str
    codelist_dir: str
    embed_batch_size: int
    max_in_flight: int
    offpeak_start: int
    offpeak_end: int
    request_timeout: float

def load_config() -> Config:
    return Config(
        vectorizer_url=_env("VECTORIZER_URL", "http://vectorizer:8089"),
        weaviate_url=_env("WEAVIATE_URL", "http://iarag-vectorstore:8086"),
        weaviate_api_key=_env("WEAVIATE_API_KEY", ""),
        weaviate_class=_env("PLACSP_CLASS", "Placsp_licitaciones"),
        work_dir=_env("PLACSP_WORK_DIR", "./work"),
        codelist_dir=_env("PLACSP_CODELIST_DIR", "./codelists"),
        embed_batch_size=int(_env("PLACSP_EMBED_BATCH", "48")),
        max_in_flight=int(_env("PLACSP_MAX_IN_FLIGHT", "1")),
        offpeak_start=int(_env("PLACSP_OFFPEAK_START", "22")),
        offpeak_end=int(_env("PLACSP_OFFPEAK_END", "7")),
        request_timeout=float(_env("PLACSP_TIMEOUT", "600")),
    )
