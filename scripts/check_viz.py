"""Regression checks for the atlas artifacts.

Same discipline as check_dataset.py: assert the properties that, if they
silently stopped holding, would put a wrong map in front of a reader. The
frontend trusts these files completely -- it does no validation of its own
-- so anything wrong here shows up as a link to the wrong article or a
node in the wrong place, both of which look like data rather than like a
bug.

Run via uv:
  uv run python scripts/check_viz.py [--data viz/data] [--db-path ...]
"""
import argparse
import json
import math
import re
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from parse_entries import volume_config  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DB_PATH = ROOT / "structured-data" / "lexikon.db"
DEFAULT_DATA = ROOT / "viz" / "data"

results = []


def check(name, ok, detail=""):
    results.append((name, ok, detail))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--db-path", default=str(DEFAULT_DB_PATH))
    ap.add_argument("--data", default=str(DEFAULT_DATA))
    args = ap.parse_args()

    data = Path(args.data)
    if not (data / "graph.json").exists():
        print(f"no atlas at {data}. Run: uv run python scripts/build_atlas.py --dev")
        return 1

    conn = sqlite3.connect(args.db_path)
    conn.row_factory = sqlite3.Row

    graph = json.loads((data / "graph.json").read_text(encoding="utf-8"))
    search = json.loads((data / "search-index.json").read_text(encoding="utf-8"))["rows"]
    manifest = json.loads((data / "MANIFEST.json").read_text(encoding="utf-8"))
    shards = {p.stem: json.loads(p.read_text(encoding="utf-8"))
              for p in sorted((data / "entries").glob("*.json"))
              if not p.name.endswith(".bib.json")}
    bibs = {p.name[:-len(".bib.json")]: json.loads(p.read_text(encoding="utf-8"))
            for p in sorted((data / "entries").glob("*.bib.json"))}

    ids = graph["ids"]
    n = len(ids)

    _check_nodes(conn, graph, ids, n)
    _check_edges(conn, graph, n)
    _check_layout(graph, n, manifest)
    _check_communities(graph, n)
    _check_shards(graph, ids, shards, bibs)
    _check_search(graph, search, conn)
    _check_inline_marks(shards)
    _check_manifest(graph, search, manifest)

    passed = sum(1 for _, ok, _ in results if ok)
    for name, ok, detail in results:
        print(("PASS  " if ok else "FAIL  ") + name + ("" if ok else f":\n        - {detail}"))
    print(f"\n{passed}/{len(results)} checks passed")
    return 0 if passed == len(results) else 1


def _check_nodes(conn, graph, ids, n):
    db_types = dict(conn.execute("SELECT id, entry_type FROM entries"))

    missing = [i for i in ids if i not in db_types]
    check("every node is a real entry", not missing,
          f"{len(missing)} unknown ids, e.g. {missing[:3]}")

    check("node ids are unique", len(set(ids)) == n,
          f"{n - len(set(ids))} duplicates")

    # Redirects carry no prose and resolve_xrefs already chases through
    # them; one on the map would be an unopenable dot.
    redirects = [i for i in ids if db_types.get(i) == "redirect"]
    check("no redirect is a node", not redirects,
          f"{len(redirects)} redirects present, e.g. {redirects[:3]}")

    expected = conn.execute(
        "SELECT COUNT(*) FROM entries WHERE entry_type != 'redirect'").fetchone()[0]
    check("every non-redirect entry is on the map", n == expected,
          f"{n} nodes vs {expected} eligible entries")

    parallel = {k: len(graph[k]) for k in
                ("headwords", "volumes", "types", "x", "y", "r", "in_degree", "community")}
    bad = {k: v for k, v in parallel.items() if v != n}
    # The frontend indexes every one of these by node number; a short array
    # would silently read `undefined` rather than raising.
    check("parallel arrays all have one entry per node", not bad, str(bad))

    blank = sum(1 for h in graph["headwords"] if not h or not h.strip())
    check("every node has a headword", blank == 0, f"{blank} blank")


def _check_edges(conn, graph, n):
    src, dst, weight = (graph["edges"][k] for k in ("source", "target", "weight"))

    check("edge arrays are the same length",
          len(src) == len(dst) == len(weight),
          f"{len(src)}/{len(dst)}/{len(weight)}")

    out_of_range = [i for i in range(len(src))
                    if not (0 <= src[i] < n and 0 <= dst[i] < n)]
    check("every edge endpoint is a valid node index", not out_of_range,
          f"{len(out_of_range)} out of range")

    loops = sum(1 for a, b in zip(src, dst) if a == b)
    check("no self loops", loops == 0, f"{loops} found")

    check("all weights are positive", all(w >= 1 for w in weight),
          f"{sum(1 for w in weight if w < 1)} non-positive")

    check("no duplicate directed pairs", len(set(zip(src, dst))) == len(src),
          f"{len(src) - len(set(zip(src, dst)))} duplicates")

    # in_degree must be the weighted in-degree of exactly these edges --
    # it is what node radius is computed from, so a mismatch is a map that
    # sizes entries by a number nothing else in the file agrees with.
    recomputed = [0] * n
    for t, w in zip(dst, weight):
        recomputed[t] += w
    check("in_degree matches the edge list", recomputed == graph["in_degree"],
          f"{sum(1 for a, b in zip(recomputed, graph['in_degree']) if a != b)} nodes differ")

    # Every edge must be a reference the resolver actually reported.
    stated = {(r[0], r[1]) for r in conn.execute("""
        SELECT entry_id, resolved_entry_id FROM resolved_cross_references
        WHERE resolved_entry_id IS NOT NULL
          AND status IN ('same_volume','cross_volume','deinflected','slash_half')
    """)}
    ids = graph["ids"]
    invented = [(ids[a], ids[b]) for a, b in zip(src, dst)
                if (ids[a], ids[b]) not in stated]
    check("every edge is a resolved reference in the database", not invented,
          f"{len(invented)} edges with no source row, e.g. {invented[:2]}")


def _check_layout(graph, n, manifest):
    xs, ys = graph["x"], graph["y"]
    finite = all(isinstance(v, (int, float)) and math.isfinite(v) for v in xs + ys)
    check("all coordinates are finite", finite)

    limit = manifest["parameters"]["coord_range"] * manifest["parameters"].get(
        "isolate_ring_factor", 1.3) + 1
    outside = sum(1 for x, y in zip(xs, ys) if abs(x) > limit or abs(y) > limit)
    check("all coordinates are inside the normalised box", outside == 0,
          f"{outside} nodes beyond +/-{limit:.0f}")

    # Every node at the origin would mean the layout stage silently did
    # nothing; a handful is fine, all of them is not.
    at_origin = sum(1 for x, y in zip(xs, ys) if x == 0 and y == 0)
    check("the layout actually ran", at_origin < n * 0.01,
          f"{at_origin}/{n} nodes at the origin")

    # Size is the map's only quantitative encoding, so it has to be
    # strictly ordered by the quantity it claims to show.
    radii, degrees = graph["r"], graph["in_degree"]
    ordered = sorted(range(n), key=lambda i: degrees[i])
    breaks = sum(1 for a, b in zip(ordered, ordered[1:]) if radii[a] > radii[b] + 1e-9)
    check("radius is monotonic in in-degree", breaks == 0,
          f"{breaks} pairs where a less-cited entry is drawn larger")


def _check_communities(graph, n):
    assigned = graph["community"]
    known = {c["id"] for c in graph["communities"]}

    bad = [c for c in set(assigned) if c != -1 and c not in known]
    check("every community assignment has metadata", not bad, f"unknown ids {bad}")

    check("community ids are ranked by size",
          [c["size"] for c in graph["communities"]] ==
          sorted((c["size"] for c in graph["communities"]), reverse=True),
          "communities are not ordered largest-first")

    sizes = {c["id"]: c["size"] for c in graph["communities"]}
    actual = {cid: assigned.count(cid) for cid in sizes}
    mismatched = {k: (sizes[k], actual[k]) for k in sizes if sizes[k] != actual[k]}
    check("declared community sizes match the assignments", not mismatched,
          str(mismatched))

    anchors = [c["anchor"] for c in graph["communities"]]
    check("every community anchor is one of its own members",
          all(assigned[a] == c["id"] for a, c in zip(anchors, graph["communities"])),
          "an anchor belongs to a different community")

    check("every community has a label",
          all(c["label"].strip() for c in graph["communities"]))


def _check_shards(graph, ids, shards, bibs):
    covered = {}
    for name, entries in shards.items():
        for entry_id in entries:
            covered.setdefault(entry_id, []).append(name)

    duplicated = {k: v for k, v in covered.items() if len(v) > 1}
    check("no entry appears in two shards", not duplicated, str(list(duplicated)[:3]))

    missing = [i for i in ids if i not in covered]
    check("every node has an article payload", not missing,
          f"{len(missing)} missing, e.g. {missing[:3]}")

    extra = [k for k in covered if k not in set(ids)]
    check("no shard carries an entry that is not a node", not extra,
          f"{len(extra)} extra, e.g. {extra[:3]}")

    # The frontend derives the shard name from the entry id; if a payload
    # ever sat in another volume's file it would 404 on click.
    misfiled = [k for k, v in covered.items() if v[0] != k.split(":")[0]]
    check("every entry sits in the shard its id names", not misfiled,
          f"{len(misfiled)} misfiled, e.g. {misfiled[:3]}")

    n = len(ids)
    bad_ref = []
    for entries in shards.values():
        for entry_id, payload in entries.items():
            for ref in payload["refs"]:
                if ref["n"] is not None and not (0 <= ref["n"] < n):
                    bad_ref.append(entry_id)
    check("every reference target is a valid node index", not bad_ref,
          f"{len(bad_ref)} entries affected")

    # has_bib drives whether the frontend fetches the bibliography shard
    # at all, so a false positive is a fetch that renders "no data".
    wrong = []
    for entries in shards.values():
        for entry_id, payload in entries.items():
            volume = entry_id.split(":")[0]
            present = entry_id in bibs.get(volume, {})
            if payload["has_bib"] != present:
                wrong.append(entry_id)
    check("has_bib agrees with the bibliography shards", not wrong,
          f"{len(wrong)} disagree, e.g. {wrong[:3]}")

    # The article shards must not carry the bibliography too -- that split
    # is the whole reason opening an entry costs 3 MB and not 5.
    leaked = [k for entries in shards.values() for k, v in entries.items()
              if "werke" in v or "literatur" in v or "_werke" in v]
    check("bibliography text is not duplicated into the article shards",
          not leaked, f"{len(leaked)} entries carry it twice")

    # Build scaffolding: the pre-reflow text and its offset map would
    # roughly double every shard if they ever shipped.
    scaffolding = sorted({k for entries in shards.values() for v in entries.values()
                          for k in v if k.startswith("_")})
    check("no build-time keys reach the browser", not scaffolding, str(scaffolding))

    # The printed edition's column breaks land mid-sentence; the reflow
    # closes them and keeps only breaks that follow a sentence. A break
    # after a word like "einer" means the reflow stopped working.
    stranded = []
    for entries in shards.values():
        for entry_id, payload in entries.items():
            for m in re.finditer(r"\n+", payload["body"]):
                before = payload["body"][:m.start()].rstrip().rstrip("»«\"'›‹)]}")
                after = payload["body"][m.end():].lstrip()
                if before and after and before[-1] not in ".!?:;":
                    stranded.append(entry_id)
                    break
    check("no article breaks mid-sentence", not stranded,
          f"{len(stranded)} entries, e.g. {stranded[:3]}")

    bib_breaks = [k for entries in bibs.values() for k, v in entries.items()
                  if any("\n" in (v[f] or "") for f in ("werke", "literatur"))]
    check("no line breaks inside the bibliography", not bib_breaks,
          f"{len(bib_breaks)} entries, e.g. {bib_breaks[:3]}")


def _check_search(graph, search, conn):
    n = len(graph["ids"])

    check("every search row points at a valid node",
          all(0 <= r["n"] < n for r in search),
          "a row indexes a node that does not exist")

    check("search keys are already folded",
          all(r["k"] == r["k"].lower() for r in search),
          "a lemma_key is not casefolded")

    # Redirects are left off the map, so the only thing standing between
    # "anima" and the article Seele is this index. What has to hold is
    # that every name a redirect forwards stays LOOKUPABLE -- not that a
    # particular row survives. Two aliases legitimately have no
    # redirect_alias row of their own ("Inkompatibilismus", "präskriptiv"):
    # their redirect points at a slash-compound article, and that
    # article's own slash_half row already carries the spelling.
    reachable = {r["k"] for r in search}
    lost = [k for (k,) in conn.execute(
        "SELECT DISTINCT lemma_key FROM lemmas WHERE variant_type = 'redirect_alias'")
        if k not in reachable]
    check("every redirect name is still findable", not lost,
          f"{len(lost)} unreachable, e.g. {lost[:3]}")

    # Every mapped entry must be findable by its own name.
    primaries = {r["n"] for r in search if r["v"] == "primary"}
    check("every node is findable by its primary lemma",
          len(primaries) == n, f"{n - len(primaries)} nodes have no primary row")


def _check_inline_marks(shards):
    """The inline links are the one place the build re-derives something.

    Every emitted span must start on the volume's own arrow glyph and end
    on a word boundary, and its reference index must exist. A mark that
    drifted by even one character would underline the wrong word and link
    it to an unrelated article.
    """
    bad_glyph, bad_index, bad_order, linkified = [], [], [], 0

    for entries in shards.values():
        for entry_id, payload in entries.items():
            marks = payload.get("marks")
            if not marks:
                continue
            linkified += 1
            body = payload["body"]
            arrow = volume_config(payload["volume"])["xref_arrow"]
            last = -1
            for start, end, ref_index in marks:
                if not (0 <= start < end <= len(body)) or body[start] != arrow:
                    bad_glyph.append(entry_id)
                    break
                if not (0 <= ref_index < len(payload["refs"])):
                    bad_index.append(entry_id)
                    break
                if start < last:
                    bad_order.append(entry_id)
                    break
                last = end

    check("every inline mark starts on the volume's arrow glyph", not bad_glyph,
          f"{len(bad_glyph)} entries, e.g. {bad_glyph[:3]}")
    check("every inline mark names a real reference", not bad_index,
          f"{len(bad_index)} entries, e.g. {bad_index[:3]}")
    check("inline marks are ordered and non-overlapping", not bad_order,
          f"{len(bad_order)} entries, e.g. {bad_order[:3]}")
    check("inline linkification covered most entries", linkified > 0,
          "no entry got inline links at all")


def _check_manifest(graph, search, manifest):
    counts = manifest["counts"]
    check("manifest node count matches graph.json",
          counts["nodes"] == len(graph["ids"]),
          f"{counts['nodes']} vs {len(graph['ids'])}")
    check("manifest edge count matches graph.json",
          counts["directed_edges"] == len(graph["edges"]["source"]),
          f"{counts['directed_edges']} vs {len(graph['edges']['source'])}")
    check("manifest community count matches graph.json",
          counts["communities"] == len(graph["communities"]),
          f"{counts['communities']} vs {len(graph['communities'])}")
    check("manifest lemma count matches the search index",
          counts["lemmas"] == len(search),
          f"{counts['lemmas']} vs {len(search)}")
    check("manifest records the parameters the map was built with",
          {"seed", "leiden_resolution", "layout_algorithm"} <= set(manifest["parameters"]))


if __name__ == "__main__":
    sys.exit(main())
