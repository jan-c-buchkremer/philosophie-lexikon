"""Build story.json, the numbers behind viz/geschichte.html.

Thin CLI over pipeline/story_analysis.py. Reads the atlas that
build_atlas.py already wrote (graph.json fixes node order, communities and
colours) plus structured-data/lexikon.db, and writes story.json beside
graph.json so the essay and the map can never disagree.

  uv run python scripts/build_story.py          # -> export/viz/data/story.json
  uv run python scripts/build_story.py --dev    # -> viz/data/story.json

Run build_atlas.py with the same --dev flag first, and extract_lifedates.py
before that. Then: uv run python scripts/check_story.py
"""
import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from pipeline import graph_data, story_analysis as sa  # noqa: E402
from pipeline.atlas_builder import configure_logging  # noqa: E402
from pipeline.config import Config  # noqa: E402


def build(dev: bool) -> Path:
    out_dir = Config.FRONTEND_DIR if dev else Config.EXPORT_DIR
    data_dir = out_dir / "data"
    graph = sa.load_graph(data_dir)
    conn = graph_data.connect(Config.DB_PATH)
    columns = {r[1] for r in conn.execute("PRAGMA table_info(entries)")}
    if "lifedates_extracted" not in columns:
        raise SystemExit("entries has no life dates. Run: uv run python scripts/extract_lifedates.py")

    person = sa.person_flags(conn, graph)
    story = {
        "schema_version": Config.SCHEMA_VERSION,
        "generated_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "corpus": sa.corpus_counts(conn, graph),
        "person": person,
        "hub_ranking": sa.hub_ranking(graph, person, Config.STORY_HUB_TOP_N),
        "community_graph": {
            "communities": sa.load_labels(Config.COMMUNITY_LABELS, graph),
            **sa.community_matrix(graph),
        },
        "volume_community_heatmap": sa.volume_community_heatmap(graph),
        "hub_bridge_scatter": {"betweenness": sa.betweenness(graph)},
        "lifedates": sa.lifedates(conn, graph),
        "ambiguity": sa.ambiguity(conn, graph, Config.STORY_AMBIGUITY_TOP_N),
        "aliases": sa.redirect_aliases(conn, graph, Config.STORY_ALIAS_TOP_N),
    }
    conn.close()

    path = data_dir / "story.json"
    path.write_text(json.dumps(story, ensure_ascii=False, separators=(",", ":")),
                    encoding="utf-8")
    return path


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dev", action="store_true", help="write into viz/data/ instead of export/viz/data/")
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args()

    configure_logging(verbose=not args.quiet)
    path = build(dev=args.dev)
    story = json.loads(path.read_text(encoding="utf-8"))
    hubs = story["hub_ranking"]
    dates = story["lifedates"]["coverage"]
    amb = story["ambiguity"]
    heat = story["volume_community_heatmap"]
    print(f"[story] {story['corpus']['nodes']} nodes, {sum(story['person'])} persons, "
          f"{hubs['persons_in_top']} of the top {hubs['n']} hubs are persons")
    print(f"[story] {dates['dated_total']} entries dated "
          f"({dates['dated_biographies']}/{dates['total_biographies']} biographies)")
    print(f"[story] volume x community: chi2={heat['chi2']:.1f}, dof={heat['dof']}, "
          f"Cramér's V={heat['cramers_v']:.3f}")
    print(f"[story] {amb['total_ambiguous']} ambiguous references over "
          f"{amb['distinct_terms']} terms, {len(amb['homonyms'])} shared names")
    print(f"[story] {path.stat().st_size / 1024:.0f} KB -> {path}")


if __name__ == "__main__":
    main()
