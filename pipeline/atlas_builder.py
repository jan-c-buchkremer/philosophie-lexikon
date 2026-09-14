"""Stage orchestrator for the atlas build.

Holds the run's state and sequences the stages; the work itself belongs to
`analysis.py` (numerics) and `graph_data.py` (I/O). Stages are resumable:
each caches its result, so re-tuning the layout does not re-run community
detection and re-sharding 17 MB of text does not re-run either.

    load -> communities -> layout -> metrics -> shard -> export
"""
import json
import logging
import pickle
from pathlib import Path

from . import analysis, graph_data
from .config import Config

logger = logging.getLogger(__name__)

STAGES = ("load", "communities", "layout", "metrics", "shard", "export")


class AtlasBuilder:
    def __init__(self, dev: bool = False):
        self.dev = dev
        # The bundle root differs between dev and export, but data always
        # sits at "<root>/data/" so the frontend's fetch paths are
        # identical either way -- otherwise index.html would need to know
        # which mode built it.
        self.out_dir = Config.FRONTEND_DIR if dev else Config.EXPORT_DIR
        self.data_dir = self.out_dir / "data"
        self.state: dict = {}

    # --- stage plumbing ----------------------------------------------------

    def run(self, start_from: str = "load"):
        if start_from not in STAGES:
            raise SystemExit(f"unknown stage {start_from!r}; choose from {', '.join(STAGES)}")

        begin = STAGES.index(start_from)
        if begin > 0:
            self._load_cache(STAGES[begin - 1])

        for stage in STAGES[begin:]:
            logger.info("--- %s ---", stage)
            getattr(self, f"_run_{stage}")()
            if stage != "export":
                self._save_cache(stage)

        logger.info("atlas written to %s", self.out_dir)
        return self.state

    def _cache_path(self, stage: str) -> Path:
        return Config.CACHE_DIR / f"{stage}.pickle"

    def _save_cache(self, stage: str):
        Config.CACHE_DIR.mkdir(parents=True, exist_ok=True)
        # The igraph object does not pickle usefully across versions and is
        # cheap to rebuild from the edge list, so it is never cached.
        payload = {k: v for k, v in self.state.items() if k != "g"}
        self._cache_path(stage).write_bytes(pickle.dumps(payload))

    def _load_cache(self, stage: str):
        path = self._cache_path(stage)
        if not path.exists():
            raise SystemExit(
                f"no cached state for stage {stage!r} at {path}.\n"
                f"Run without --start-from at least once."
            )
        self.state = pickle.loads(path.read_bytes())
        # Rebuild the graph the cached stages were computed against.
        if "nodes" in self.state:
            self.state["g"] = analysis.build_igraph(
                self.state["nodes"], self.state["edges"], self.state["node_index"]
            )
        logger.info("resumed from cached stage %r", stage)

    # --- stages ------------------------------------------------------------

    def _run_load(self):
        conn = graph_data.connect(Config.DB_PATH)
        nodes = graph_data.load_nodes(conn)
        node_index = {n["id"]: i for i, n in enumerate(nodes)}
        edges = graph_data.load_edges(conn, set(node_index))

        logger.info("loaded %d nodes, %d directed edges", len(nodes), len(edges))

        self.state.update({
            "nodes": nodes,
            "node_index": node_index,
            "edges": edges,
            "search": graph_data.load_search_index(conn, node_index),
            "payloads": graph_data.load_entry_payloads(conn, node_index),
        })
        self.state["g"] = analysis.build_igraph(nodes, edges, node_index)
        conn.close()

    def _run_communities(self):
        self.state["communities"] = analysis.detect_communities(self.state["g"])

    def _run_layout(self):
        self.state["coords"] = analysis.compute_layout(
            self.state["g"], self.state["nodes"],
            self.state["communities"]["assignment"],
        )

    def _run_metrics(self):
        s = self.state
        s["in_degree"] = analysis.compute_degrees(s["nodes"], s["edges"], s["node_index"])
        s["radii"] = analysis.compute_radii(s["in_degree"])
        s["communities"] = analysis.describe_communities(
            s["communities"], s["nodes"], s["in_degree"]
        )

    def _run_shard(self):
        # Inline offsets are recovered here rather than at load time
        # because the gate compares against the reference lists, which
        # only exist once the payloads are assembled.
        self.state["inline"] = graph_data.attach_inline_offsets(self.state["payloads"])
        stats = self.state["inline"]
        share = stats["linkified"] / stats["eligible"] if stats["eligible"] else 0.0
        logger.info(
            "inline references: %d/%d entries linkified (%.1f%%), %d marks, %d rejected",
            stats["linkified"], stats["eligible"], share * 100,
            stats["marks"], stats["rejected"],
        )

    def _run_export(self):
        s = self.state
        out = self.data_dir
        out.mkdir(parents=True, exist_ok=True)

        graph_data.write_graph(
            out, s["nodes"], s["edges"], s["communities"], s["coords"],
            s["radii"], s["in_degree"], s["node_index"],
        )
        graph_data.write_search_index(out, s["search"])
        shard_sizes = graph_data.write_shards(out, s["payloads"])

        if not self.dev:
            # export/viz/ is meant to be servable as-is, so the frontend
            # travels with the data.
            graph_data.copy_frontend(Config.FRONTEND_DIR, self.out_dir)

        graph_data.write_manifest(out, self._manifest(shard_sizes))

    def _manifest(self, shard_sizes: dict[str, int]) -> dict:
        s = self.state
        stats = s["inline"]
        return {
            "source": "structured-data/lexikon.db",
            "parameters": {
                "seed": Config.SEED,
                "leiden_resolution": Config.LEIDEN_RESOLUTION,
                "min_community_size": Config.MIN_COMMUNITY_SIZE,
                "palette_size": Config.PALETTE_SIZE,
                "layout_algorithm": Config.LAYOUT_ALGORITHM,
                "layout_iterations": Config.LAYOUT_ITERATIONS,
                "coord_range": Config.COORD_RANGE,
                "isolate_ring_factor": Config.ISOLATE_RING_FACTOR,
                "exclude_redirects": Config.EXCLUDE_REDIRECTS,
                "edge_statuses": list(Config.EDGE_STATUSES),
            },
            "counts": {
                "nodes": len(s["nodes"]),
                "directed_edges": len(s["edges"]),
                "undirected_edges": s["g"].ecount(),
                "communities": s["communities"]["count"],
                "unassigned_nodes": s["communities"]["unassigned"],
                "lemmas": len(s["search"]),
                "shards": len(shard_sizes),
            },
            "modularity": round(s["communities"]["modularity"], 4),
            "in_degree": {
                "max": max(s["in_degree"]),
                "zero": sum(1 for d in s["in_degree"] if d == 0),
            },
            "inline_references": {
                "entries_with_references": stats["eligible"],
                "entries_linkified": stats["linkified"],
                "entries_rejected": stats["rejected"],
                "marks": stats["marks"],
                "coverage": round(stats["linkified"] / stats["eligible"], 4) if stats["eligible"] else 0,
            },
            "shard_bytes": shard_sizes,
            "notes": [
                "Positions come from the citation graph alone -- no text embeddings. "
                "Two entries are near each other because the editors cross-referenced "
                "them, not because their prose is similar.",
                "Redirect entries are not nodes; they are reachable through the search "
                "index as redirect_alias rows.",
                "Ambiguous and unresolved references are carried into the entry shards "
                "and shown in the reading pane, but are not edges.",
                "Inline reference offsets are emitted only for entries where re-running "
                "the parser's own matcher against the cleaned text reproduces the stored "
                "reference list exactly; every other entry renders as plain text.",
            ],
        }


def configure_logging(verbose: bool = True):
    logging.basicConfig(
        level=logging.INFO if verbose else logging.WARNING,
        format="[%(levelname)s] %(message)s",
    )
