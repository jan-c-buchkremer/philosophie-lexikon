"""The numeric stages of the atlas: communities, layout, node metrics.

Reads plain node/edge lists and returns plain results; all file access
lives in `graph_data.py`. Every function here is seeded, so the same
database and the same Config produce the same map.
"""
import colorsys
import logging
import math
import random
from collections import Counter

import igraph as ig
import leidenalg

from .config import Config

logger = logging.getLogger(__name__)


def build_igraph(nodes: list[dict], edges: list[tuple[str, str, int]],
                 node_index: dict[str, int]) -> ig.Graph:
    """The undirected weighted projection used for clustering and layout.

    Direction matters for reading ("what cites this") but not for
    position: two articles that reference each other belong near each
    other regardless of which way the arrow points. Reciprocal pairs
    (4,691 of them) therefore fold into a single heavier edge.
    """
    g = ig.Graph(n=len(nodes), directed=False)
    combined: Counter = Counter()
    for src, dst, weight in edges:
        a, b = node_index[src], node_index[dst]
        combined[(min(a, b), max(a, b))] += weight
    g.add_edges(list(combined.keys()))
    g.es["weight"] = list(combined.values())
    g.vs["name"] = [n["id"] for n in nodes]
    logger.info("graph: %d nodes, %d undirected edges", g.vcount(), g.ecount())
    return g


def detect_communities(g: ig.Graph) -> dict:
    """Leiden partition, ordered and coloured for display.

    Leiden rather than Louvain: Louvain can return communities that are
    internally disconnected, which on a map means a "region" whose members
    have nothing joining them -- exactly the claim a spatial layout should
    not make by accident. Leiden guarantees connectedness.

    Communities are renumbered by size so community 0 is always the
    largest and the palette assignment is stable between runs.
    """
    partition = leidenalg.find_partition(
        g,
        leidenalg.RBConfigurationVertexPartition,
        weights=g.es["weight"],
        resolution_parameter=Config.LEIDEN_RESOLUTION,
        n_iterations=-1,          # iterate to stability, not a fixed count
        seed=Config.SEED,
    )

    sizes = Counter(partition.membership)
    # Below MIN_COMMUNITY_SIZE a group is a rounding artifact rather than
    # a region of the encyclopedia; those entries fold into the unassigned
    # bucket (-1) and render neutral instead of claiming a colour.
    ranked = [cid for cid, n in sizes.most_common() if n >= Config.MIN_COMMUNITY_SIZE]
    remap = {cid: rank for rank, cid in enumerate(ranked)}
    assignment = [remap.get(cid, -1) for cid in partition.membership]

    logger.info(
        "leiden: resolution=%.2f -> %d communities (%d above the size floor), modularity=%.3f",
        Config.LEIDEN_RESOLUTION, len(sizes), len(ranked), partition.modularity,
    )
    return {
        "assignment": assignment,
        "count": len(ranked),
        "modularity": partition.modularity,
        "meta": [],  # filled by describe_communities()
    }


def describe_communities(communities: dict, nodes: list[dict], in_degree: list[int]) -> dict:
    """Name and colour each community.

    Names come from the three most-cited headwords in the community. With
    no topic model and no LLM in the prototype this is the honest label:
    it says what the region's landmarks are rather than inventing a theme
    for it, and for a cross-referenced encyclopedia the most-cited member
    usually IS the theme.
    """
    members: dict[int, list[int]] = {}
    for idx, cid in enumerate(communities["assignment"]):
        members.setdefault(cid, []).append(idx)

    meta = []
    for cid in sorted(c for c in members if c >= 0):
        group = sorted(members[cid], key=lambda i: -in_degree[i])
        meta.append({
            "id": cid,
            "size": len(group),
            "color": _community_color(cid, communities["count"]),
            "label": " · ".join(nodes[i]["headword"] for i in group[:3]),
            # The single biggest hub, used as the label anchor on the map.
            "anchor": group[0],
        })

    unassigned = len(members.get(-1, []))
    if unassigned:
        logger.info("%d entries below the community size floor -> neutral", unassigned)
    communities["meta"] = meta
    communities["unassigned"] = unassigned
    return communities


def _community_color(rank: int, total: int) -> str:
    """Evenly spaced hues, muted for a dark ground.

    Past PALETTE_SIZE the hues would start colliding with ones already in
    use, so those communities go neutral rather than pretending to a
    distinction the eye cannot make. Saturation and value are held low and
    high respectively: fully saturated hues vibrate against near-black.
    """
    if rank >= Config.PALETTE_SIZE:
        return "#6b7280"
    # The golden-ratio step spreads adjacent ranks far apart on the wheel,
    # so the largest communities -- which sit next to each other in the
    # legend -- never get neighbouring hues.
    hue = (rank * 0.618033988749895) % 1.0
    r, g, b = colorsys.hsv_to_rgb(hue, 0.42, 0.93)
    return "#%02x%02x%02x" % (int(r * 255), int(g * 255), int(b * 255))


def compute_layout(g: ig.Graph, nodes: list[dict],
                   assignment: list[int]) -> list[tuple[float, float]]:
    """2D coordinates for every node.

    The giant component (4,208 of 4,259 nodes) is laid out by force; the
    stragglers are placed deliberately. A force layout has no opinion
    about where a disconnected node belongs, so left to itself it throws
    the 49 singletons and the handful of two-node components to arbitrary
    distances, which reads as data rather than as absence. Putting them on
    a labelled outer ring makes "nothing cites this and it cites nothing"
    a visible fact about the corpus instead of visual noise.
    """
    random.seed(Config.SEED)
    ig.set_random_number_generator(random)

    components = g.connected_components()
    giant_id = max(range(len(components)), key=lambda i: len(components[i]))
    giant_members = components[giant_id]
    outsiders = [i for i in range(g.vcount()) if components.membership[i] != giant_id]

    logger.info("layout: giant component %d nodes, %d outside it",
                len(giant_members), len(outsiders))

    sub = g.subgraph(giant_members)
    sub.es["weight"] = _boost_intra_community(sub, [assignment[i] for i in giant_members])
    raw = _run_layout(sub)

    coords: list[tuple[float, float]] = [(0.0, 0.0)] * g.vcount()
    for local, node in enumerate(giant_members):
        coords[node] = (raw[local][0], raw[local][1])

    _normalise(coords, giant_members)
    _place_outsiders(coords, outsiders, components, giant_id)
    return coords


def _boost_intra_community(sub: ig.Graph, membership: list[int]) -> list[float]:
    """Pull each community together before the force pass runs.

    A plain force layout of this graph is a hairball: it is dense enough
    (50,001 edges over 4,259 nodes) that every community is pinned against
    every other and the colours end up interleaved, which makes the map
    pretty and unreadable. Scaling up the edges that stay inside a
    community lets the same simulation resolve them into separate regions.

    This does not invent structure. The communities were found by Leiden
    on the same edges, so the boost only amplifies a division the graph
    already contains -- what changes is whether the eye can see it.
    """
    boost = Config.LAYOUT_COMMUNITY_BOOST
    if boost <= 1:
        return sub.es["weight"]
    return [
        w * boost if membership[e.source] == membership[e.target] >= 0 else w
        for e, w in zip(sub.es, sub.es["weight"])
    ]


# Only the two layouts that were actually measured on this corpus (see
# docs/atlas.md). igraph 1.0 dropped the short aliases, so they are named
# here rather than assembled from the config string.
LAYOUTS = {
    "drl": lambda g: g.layout_drl(weights=g.es["weight"]),
    "fr": lambda g: g.layout_fruchterman_reingold(
        weights=g.es["weight"], niter=Config.LAYOUT_ITERATIONS),
}


def _run_layout(sub: ig.Graph):
    try:
        algorithm = LAYOUTS[Config.LAYOUT_ALGORITHM]
    except KeyError:
        raise SystemExit(
            f"unknown ATLAS_LAYOUT {Config.LAYOUT_ALGORITHM!r}; "
            f"choose from {', '.join(LAYOUTS)}"
        )
    logger.info("layout: %s over %d nodes", Config.LAYOUT_ALGORITHM, sub.vcount())
    return algorithm(sub)


def _normalise(coords: list[tuple[float, float]], members: list[int]):
    """Centre the main map on the origin and scale it to COORD_RANGE.

    Force layouts return whatever scale they converge to, so without this
    the frontend's opening zoom would depend on the run.
    """
    xs = [coords[i][0] for i in members]
    ys = [coords[i][1] for i in members]
    cx, cy = (min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2
    half = max(max(xs) - min(xs), max(ys) - min(ys)) / 2 or 1.0
    scale = Config.COORD_RANGE / half
    for i in members:
        coords[i] = ((coords[i][0] - cx) * scale, (coords[i][1] - cy) * scale)


def _place_outsiders(coords, outsiders, components, giant_id):
    """Disconnected entries, on a deterministic ring outside the map.

    Grouped by component so the few two- and three-node components sit
    together rather than being scattered among the singletons.
    """
    if not outsiders:
        return
    radius = Config.COORD_RANGE * Config.ISOLATE_RING_FACTOR
    ordered = sorted(outsiders, key=lambda i: (components.membership[i], i))
    for slot, node in enumerate(ordered):
        angle = 2 * math.pi * slot / len(ordered)
        coords[node] = (radius * math.cos(angle), radius * math.sin(angle))


def compute_degrees(nodes: list[dict], edges, node_index) -> list[int]:
    """In-degree: how often the corpus cites each entry."""
    counts = [0] * len(nodes)
    for _, dst, weight in edges:
        counts[node_index[dst]] += weight
    return counts


def compute_radii(in_degree: list[int]) -> list[float]:
    """Node radius from in-degree, on a square-root scale.

    In-degree runs 0 to 269 with a median of 3. Linear sizing would make
    every non-hub the same invisible dot; sqrt keeps the area roughly
    proportional to the count while leaving the middle of the
    distribution legible. RADIUS_MIN is a floor, not a zero: 1,715
    entries are never cited, and they are still articles.
    """
    peak = max(in_degree) or 1
    span = Config.RADIUS_MAX - Config.RADIUS_MIN
    return [Config.RADIUS_MIN + span * math.sqrt(d / peak) for d in in_degree]
