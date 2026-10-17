"""CLI: python -m placsp_pilot <stage> [--run-dir DIR] [--quota channel=n,...]

Stages run in this order; `run` does them all. Each is resumable.
  select       pick the latest expedientes per channel from the live feeds
  discover     scrape detail pages (PLACSP and external platforms) for more documents
  fetch        download every referenced document
  text         extract text (OCR service for scanned PDFs), unpack zips
  classify     nlp_service /nli: zero-shot role for documents the rules could not label
  summarize    nlp_service /summarize (article): one gist per document
  ner          nlp_service /ner per chunk with the procurement ontology
  resolve      nlp_service /resolve per document
  describe     nlp_service /summarize entity_desc / relation_desc
  consolidate  nlp_service /summarize aggregate: expediente and company descriptions
  graph        nodes/edges and one JSON per expediente (out/)
  index        Qdrant pilot_tenders / pilot_chunks / pilot_entities + Neo4j Pilot graph
               (BGE-M3 embeddings through the vectorizer)
  validate     every expediente, every field and count, feed -> documents -> NLP -> stores
  report       times and volumes -> out/report.md, out/metrics.json
"""
import argparse
import sys
import warnings

from placsp_pilot import graph, index, nlpstages, report, stages, validate
from placsp_pilot.config import DEFAULT_QUOTAS, load_config
from placsp_pilot.store import Store

ORDER = ["select", "discover", "fetch", "text", "classify", "summarize", "ner", "resolve", "describe", "consolidate",
         "graph", "index", "validate", "report"]


def _quotas(s: str | None) -> dict:
    if not s:
        return dict(DEFAULT_QUOTAS)
    out = {}
    for part in s.split(","):
        k, v = part.split("=")
        if k not in DEFAULT_QUOTAS:
            raise SystemExit(f"unknown channel {k}; use one of {', '.join(DEFAULT_QUOTAS)}")
        out[k] = int(v)
    return out


def main(argv=None):
    warnings.filterwarnings("ignore", message="Unverified HTTPS request")
    ap = argparse.ArgumentParser(prog="placsp_pilot", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("stage", choices=ORDER + ["run"])
    ap.add_argument("--run-dir", help="output directory (default $PILOT_RUN_DIR or ./pilot_runs/default)")
    ap.add_argument("--quota", help="per-channel sample size, e.g. placsp_mayores=50,externos_mayores=20,placsp_menores=15,propios=15")
    ap.add_argument("--max-doc-chars", type=int, default=400_000,
                    help="characters of a document sent to /summarize (the service reduces it further)")
    ap.add_argument("--retry-failed", action="store_true", help="put failed downloads and service calls back to pending first")
    args = ap.parse_args(argv)

    cfg = load_config(args.run_dir)
    store = Store(cfg.db_path)
    print(f"run dir {cfg.run_dir}; nlp_service {cfg.nlp_url or '(unset)'}; OCR {cfg.ocr_url or 'off'}; "
          f"vectorizer {cfg.vectorizer_url or 'off'}", flush=True)
    if args.retry_failed:
        print("retry: " + ", ".join(f"{k} {v}" for k, v in store.reset_failed().items() if v), flush=True)

    steps = {
        "select": lambda: stages.select(cfg, store, _quotas(args.quota)),
        "discover": lambda: stages.discover(cfg, store),
        "fetch": lambda: stages.fetch(cfg, store),
        "text": lambda: stages.text(cfg, store),
        "classify": lambda: nlpstages.classify(cfg, store),
        "summarize": lambda: nlpstages.summarize(cfg, store, args.max_doc_chars),
        "ner": lambda: nlpstages.ner(cfg, store),
        "resolve": lambda: nlpstages.resolve(cfg, store),
        "describe": lambda: nlpstages.describe(cfg, store),
        "consolidate": lambda: nlpstages.consolidate(cfg, store),
        "graph": lambda: graph.build(cfg, store),
        "index": lambda: index.index(cfg, store),
        "validate": lambda: validate.validate(cfg, store),
        "report": lambda: print(f"report: {report.write(cfg, store)}"),
    }
    for s in (ORDER if args.stage == "run" else [args.stage]):
        steps[s]()
    return 0


if __name__ == "__main__":
    sys.exit(main())
