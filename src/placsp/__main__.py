import argparse
from .config import load_config
from .codelists import Codelists
from .embedder import Embedder
from .upserter import Upserter
from .pipeline import Pipeline
from .weaviate_schema import ensure_class
from .graph_sink import GraphSink

def _graph_sink(cfg):
    if not cfg.neo4j_url:
        return None
    return GraphSink(cfg.neo4j_url, cfg.neo4j_user, cfg.neo4j_password)

def _pipeline(cfg):
    return Pipeline(cfg,
                    Embedder(cfg.vectorizer_url, cfg.embed_batch_size, cfg.request_timeout),
                    Upserter(cfg.weaviate_url, cfg.weaviate_api_key, cfg.weaviate_class, cfg.request_timeout,
                             batch_size=cfg.upsert_batch_size),
                    Codelists(cfg.codelist_dir),
                    graph_sink=_graph_sink(cfg))

def main(argv=None):
    parser = argparse.ArgumentParser(prog="placsp")
    sub = parser.add_subparsers(dest="cmd", required=True)
    for name in ("init-schema", "init-graph", "backfill", "daily", "reconcile"):
        sub.add_parser(name)
    args = parser.parse_args(argv)
    cfg = load_config()
    if args.cmd == "init-schema":
        from .weaviate_schema import CLASS_DEF, COMPANY_CLASS_DEF, PLIEGO_CRITERIA_CLASS_DEF, PLIEGO_CHUNKS_CLASS_DEF
        created_lic = ensure_class(cfg.weaviate_url, cfg.weaviate_api_key, cfg.weaviate_class, class_def=CLASS_DEF, timeout=cfg.request_timeout)
        created_comp = ensure_class(cfg.weaviate_url, cfg.weaviate_api_key, "Placsp_companies", class_def=COMPANY_CLASS_DEF, timeout=cfg.request_timeout)
        created_pliego_crit = ensure_class(cfg.weaviate_url, cfg.weaviate_api_key, "Placsp_pliego_criteria", class_def=PLIEGO_CRITERIA_CLASS_DEF, timeout=cfg.request_timeout)
        created_pliego_chunk = ensure_class(cfg.weaviate_url, cfg.weaviate_api_key, "Placsp_pliego_chunks", class_def=PLIEGO_CHUNKS_CLASS_DEF, timeout=cfg.request_timeout)
        print("licitaciones:", "created" if created_lic else "exists")
        print("companies:", "created" if created_comp else "exists")
        print("pliego criteria:", "created" if created_pliego_crit else "exists")
        print("pliego chunks:", "created" if created_pliego_chunk else "exists")
        return
    if args.cmd == "init-graph":
        gs = _graph_sink(cfg)
        if gs is None:
            print("neo4j not configured"); return
        gs.ensure_constraints(); gs.close()
        print("constraints ensured")
        return
    p = _pipeline(cfg)
    {"backfill": p.run_backfill, "daily": p.run_daily, "reconcile": p.run_reconcile}[args.cmd]()

if __name__ == "__main__":
    main()
