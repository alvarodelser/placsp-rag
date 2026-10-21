import argparse
from placsp.config import load_config
from placsp.storage.weaviate_schema import ensure_class
from placsp.storage.graph_sink import GraphSink

def _graph_sink(cfg):
    if not cfg.neo4j_url:
        return None
    return GraphSink(cfg.neo4j_url, cfg.neo4j_user, cfg.neo4j_password)

def _loader(cfg):
    from placsp.ai.embedder import Embedder
    from placsp.storage.upserter import Upserter
    from placsp.staging.load import Loader
    return Loader(cfg.data_dir,
                  Embedder(cfg.vectorizer_url, cfg.embed_batch_size, cfg.request_timeout, workers=cfg.embed_workers),
                  Upserter(cfg.weaviate_url, cfg.weaviate_api_key, cfg.weaviate_class, cfg.request_timeout,
                           batch_size=cfg.upsert_batch_size),
                  graph_sink=_graph_sink(cfg))

def _stage(cfg, steps, channels=None, years=None, workers=2, memory="4GB"):
    """Run staging steps in order: live, download, extract, build, load."""
    from placsp.staging import sources, extract, build, live
    if "live" in steps:
        print(live.fetch_live(cfg.data_dir, channels))
    if "download" in steps:
        print(sources.download_missing(cfg.data_dir, sources.archives(channels, years)))
    if "extract" in steps:
        print(f"extracted {len(extract.extract_all(cfg.data_dir, workers))} archives")
    if "build" in steps:
        print(build.build(cfg.data_dir, cfg.codelist_dir, memory))
    if "load" in steps:
        print(_loader(cfg).load())

# backfill: every archive not on disk yet, then everything that changed into search and graph.
# reconcile: the same; run monthly it picks up the month that just finished.
# daily: the live feed since the latest staged update.
RUNS = {"backfill": ("download", "extract", "build", "load"),
        "reconcile": ("download", "extract", "build", "load"),
        "daily": ("live", "extract", "build", "load")}

def main(argv=None):
    parser = argparse.ArgumentParser(prog="placsp")
    sub = parser.add_subparsers(dest="cmd", required=True)
    for name in ("init-schema", "init-graph", "backfill", "daily", "reconcile"):
        sub.add_parser(name)
    stage = sub.add_parser("stage", help="run one staging step (or all of the backfill ones)")
    stage.add_argument("step", choices=["live", "download", "extract", "build", "load", "all"])
    stage.add_argument("--channel", action="append", help="limit live/download to these channels")
    stage.add_argument("--year", action="append", type=int, help="limit download to these years")
    stage.add_argument("--workers", type=int, default=2, help="archives extracted in parallel")
    stage.add_argument("--memory", default="4GB", help="DuckDB memory limit for build")
    args = parser.parse_args(argv)
    cfg = load_config()
    if args.cmd == "stage":
        steps = RUNS["backfill"] if args.step == "all" else (args.step,)
        _stage(cfg, steps, args.channel, args.year, args.workers, args.memory)
        return
    if args.cmd == "init-schema":
        from placsp.storage.weaviate_schema import CLASS_DEF, PLIEGO_CRITERIA_CLASS_DEF
        for name, d in ((cfg.weaviate_class, CLASS_DEF), ("Placsp_pliego_criteria", PLIEGO_CRITERIA_CLASS_DEF)):
            created = ensure_class(cfg.weaviate_url, cfg.weaviate_api_key, name, class_def=d, timeout=cfg.request_timeout)
            print(name, "created" if created else "exists")
        return
    if args.cmd == "init-graph":
        gs = _graph_sink(cfg)
        if gs is None:
            print("neo4j not configured"); return
        gs.ensure_constraints(); gs.close()
        print("constraints ensured")
        return
    _stage(cfg, RUNS[args.cmd], workers=cfg.extract_workers, memory=cfg.build_memory)

if __name__ == "__main__":
    main()
