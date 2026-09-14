"""Environment-driven configuration for the atlas pipeline.

Everything that changes what the map looks like lives here and nowhere
else, so a run is described by its config plus the database it read. Every
value that influences geometry or clustering is written into the output
MANIFEST, which is what makes a given map reproducible rather than merely
repeatable.
"""
import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

ROOT = Path(__file__).resolve().parent.parent


def _int(name: str, default: int) -> int:
    return int(os.getenv(name, default))


def _float(name: str, default: float) -> float:
    return float(os.getenv(name, default))


class Config:
    # --- paths ---
    DB_PATH = Path(os.getenv("ATLAS_DB_PATH", ROOT / "structured-data" / "lexikon.db"))
    FRONTEND_DIR = ROOT / "viz"
    EXPORT_DIR = Path(os.getenv("ATLAS_EXPORT_DIR", ROOT / "export" / "viz"))
    CACHE_DIR = Path(os.getenv("ATLAS_CACHE_DIR", ROOT / ".atlas-cache"))

    # --- graph construction ---
    # Redirects are real entries but carry no prose: they exist only to
    # forward a name to an article, and resolve_xrefs.py already chases
    # through them, so as nodes they would be 367 content-free leaves.
    # They stay in the data and stay findable through the lemma index.
    EXCLUDE_REDIRECTS = os.getenv("ATLAS_EXCLUDE_REDIRECTS", "true").lower() in ("true", "1", "yes")
    # Only references that actually landed on an entry become edges.
    # Ambiguous and unresolved ones are still carried into the entry
    # shards -- the resolver never guessed, and the interface should not
    # look like it did either.
    EDGE_STATUSES = ("same_volume", "cross_volume", "deinflected", "slash_half")

    # --- community detection (Leiden) ---
    # Resolution is the one knob that decides how many regions the map
    # has. Tuned for ~15-25 communities: beyond that the hues stop being
    # tellable apart and the colour channel stops carrying information.
    # Measured on this corpus: 0.55 -> 4 regions, 1.0 -> 8, 1.5 -> 13,
    # 2.0 -> 20, 3.0 -> 39. Modularity peaks near 1.0 and decays slowly,
    # so 2.0 buys legible structure for little cost (0.451 -> 0.395).
    LEIDEN_RESOLUTION = _float("ATLAS_LEIDEN_RESOLUTION", 2.0)
    # Communities past this rank render neutral grey rather than taking a
    # hue that would collide with a larger one.
    PALETTE_SIZE = _int("ATLAS_PALETTE_SIZE", 20)
    # A "community" of three entries is a rounding artifact, not a region.
    MIN_COMMUNITY_SIZE = _int("ATLAS_MIN_COMMUNITY_SIZE", 12)

    # --- layout ---
    # Fruchterman-Reingold, with the intra-community boost below doing
    # the separating. Measured against the alternatives on this corpus
    # (ratio of mean intra-community to mean inter-community distance,
    # lower = more separated):
    #   fr,  boost 1 -> 0.551   one hairball, colours interleaved
    #   fr,  boost 8 -> 0.345   readable regions, articles still distinct
    #   drl, boost 1 -> 0.343   thin filaments around a large void
    #   drl, boost 4 -> 0.024   each community collapses into a blob you
    #                           cannot pick a single article out of
    # The best number is not the lowest one: past about 0.3 the map stops
    # showing the corpus and starts showing only the partition.
    # See analysis.LAYOUTS for the other choices ("drl", "kk", "umap").
    LAYOUT_ALGORITHM = os.getenv("ATLAS_LAYOUT", "fr")
    LAYOUT_ITERATIONS = _int("ATLAS_LAYOUT_ITERATIONS", 500)
    # How much harder an edge pulls when both ends are in the same
    # community. 1.0 disables it. See analysis._boost_intra_community():
    # without it this graph lays out as a hairball with the communities
    # interleaved.
    LAYOUT_COMMUNITY_BOOST = _float("ATLAS_LAYOUT_COMMUNITY_BOOST", 8.0)
    # Coordinates are normalised into [-COORD_RANGE, COORD_RANGE] so the
    # frontend's initial zoom does not depend on the layout's arbitrary
    # output scale.
    COORD_RANGE = _float("ATLAS_COORD_RANGE", 1000.0)
    # Force layouts fling disconnected components to arbitrary distances.
    # The small components and singletons are placed deliberately instead,
    # on an outer ring at this multiple of the main map's radius.
    ISOLATE_RING_FACTOR = _float("ATLAS_ISOLATE_RING_FACTOR", 1.28)

    # --- node sizing ---
    # Radius tracks sqrt(in-degree): in-degree runs 0..269 with a median
    # of 3, so a linear scale would collapse everything that is not a hub,
    # and 1,715 entries have no incoming references at all and need a
    # visible floor rather than a zero.
    RADIUS_MIN = _float("ATLAS_RADIUS_MIN", 1.6)
    RADIUS_MAX = _float("ATLAS_RADIUS_MAX", 11.0)

    # --- determinism ---
    SEED = _int("ATLAS_SEED", 20260908)

    SCHEMA_VERSION = "1.0"
