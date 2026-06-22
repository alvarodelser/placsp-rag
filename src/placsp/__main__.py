import argparse
from .config import load_config
from .codelists import Codelists
from .embedder import Embedder
from .upserter import Upserter
from .pipeline import Pipeline
from .weaviate_schema import ensure_class

def _pipeline(cfg):
    return Pipeline(cfg,
                    Embedder(cfg.vectorizer_url, cfg.embed_batch_size, cfg.request_timeout),
                    Upserter(cfg.weaviate_url, cfg.weaviate_api_key, cfg.weaviate_class, cfg.request_timeout),
                    Codelists(cfg.codelist_dir))

def main(argv=None):
    parser = argparse.ArgumentParser(prog="placsp")
    sub = parser.add_subparsers(dest="cmd", required=True)
    for name in ("init-schema", "backfill", "daily", "reconcile"):
        sub.add_parser(name)
    args = parser.parse_args(argv)
    cfg = load_config()
    if args.cmd == "init-schema":
        created = ensure_class(cfg.weaviate_url, cfg.weaviate_api_key, cfg.weaviate_class, cfg.request_timeout)
        print("created" if created else "exists")
        return
    p = _pipeline(cfg)
    {"backfill": p.run_backfill, "daily": p.run_daily, "reconcile": p.run_reconcile}[args.cmd]()

if __name__ == "__main__":
    main()
