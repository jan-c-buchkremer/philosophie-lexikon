"""Regression checks for story.json, the numbers behind viz/geschichte.html.

Same discipline as check_viz.py: every figure the essay states is
recomputed here from graph.json and the database, independently of
pipeline/story_analysis.py, and compared. A number that drifted would
read as a fact about the encyclopedia, not as a bug.

Run via uv:
  uv run python scripts/check_story.py [--data viz/data] [--db-path ...]
"""
import argparse
import json
import sqlite3
import sys
from collections import Counter
from pathlib import Path

import igraph as ig
import numpy as np

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DB_PATH = ROOT / "structured-data" / "lexikon.db"
DEFAULT_DATA = ROOT / "viz" / "data"

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

results = []


def check(name, ok, detail=""):
    results.append((name, ok, detail))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--db-path", default=str(DEFAULT_DB_PATH))
    ap.add_argument("--data", default=str(DEFAULT_DATA))
    args = ap.parse_args()

    data = Path(args.data)
    if not (data / "story.json").exists():
        print(f"no story at {data}. Run: uv run python scripts/build_story.py --dev")
        return 1

    conn = sqlite3.connect(args.db_path)
    graph = json.loads((data / "graph.json").read_text(encoding="utf-8"))
    story = json.loads((data / "story.json").read_text(encoding="utf-8"))
    n = len(graph["ids"])

    _check_persons(conn, graph, story, n)
    _check_hubs(graph, story, n)
    _check_communities(graph, story)
    _check_heatmap(graph, story)
    _check_betweenness(graph, story, n)
    _check_lifedates(conn, graph, story, n)
    _check_ambiguity(conn, graph, story, n)
    _check_corpus(conn, graph, story)

    passed = sum(1 for _, ok, _ in results if ok)
    for name, ok, detail in results:
        print(("PASS  " if ok else "FAIL  ") + name + ("" if ok else f":\n        - {detail}"))
    print(f"\n{passed}/{len(results)} checks passed")
    return 0 if passed == len(results) else 1


def _check_persons(conn, graph, story, n):
    person = story["person"]
    check("person flags cover every node", len(person) == n, f"{len(person)} vs {n}")
    persons = {r[0] for r in conn.execute("""
        SELECT id FROM entries
        WHERE lifedates_extracted = 1
           OR (entry_type = 'biography'
               AND instr(substr(COALESCE(body_clean, body_text), 1, 500), '†') > 0)""")}
    expected = [1 if i in persons else 0 for i in graph["ids"]]
    check("a person is a dated life or a biography with the death sign, nothing else",
          person == expected, f"{sum(1 for a, b in zip(person, expected) if a != b)} nodes differ")


def _check_hubs(graph, story, n):
    hubs = story["hub_ranking"]
    nodes = hubs["nodes"]
    deg = graph["in_degree"]
    check("hub ranking has the declared length", len(nodes) == hubs["n"],
          f"{len(nodes)} vs {hubs['n']}")
    check("every hub is a valid node", all(0 <= i < n for i in nodes))
    check("hubs are unique", len(set(nodes)) == len(nodes))
    check("hubs are ordered by in-degree",
          all(deg[a] >= deg[b] for a, b in zip(nodes, nodes[1:])))
    # Nothing outside the list may outrank its last member.
    floor = deg[nodes[-1]]
    outside = max((deg[i] for i in range(n) if i not in set(nodes)), default=0)
    check("no entry outside the ranking is cited more than its last member",
          outside <= floor, f"{outside} > {floor}")
    person = story["person"]
    check("persons_in_top is the count of persons in the ranking",
          hubs["persons_in_top"] == sum(person[i] for i in nodes))
    check("top_persons are persons ordered by in-degree",
          all(person[i] for i in hubs["top_persons"]) and
          all(deg[a] >= deg[b] for a, b in zip(hubs["top_persons"], hubs["top_persons"][1:])))
    check("uncited count matches the graph",
          hubs["uncited"] == sum(1 for d in deg if d == 0))


def _check_communities(graph, story):
    cg = story["community_graph"]
    k = len(graph["communities"])
    ids = [c["id"] for c in cg["communities"]]
    check("every atlas community has a label row", ids == [c["id"] for c in graph["communities"]])
    check("every community label is non-blank",
          all(c["short_label"].strip() for c in cg["communities"]))
    stale = [c["id"] for c in cg["communities"] if c["label_status"] != "ok"]
    check("every community label was written for the community it names", not stale,
          f"ids {stale} are missing or stale in pipeline/community_labels.json")

    matrix = [[0] * k for _ in range(k)]
    un = {"in": 0, "out": 0, "internal": 0}
    comm = graph["community"]
    e = graph["edges"]
    for s, t, w in zip(e["source"], e["target"], e["weight"]):
        cs, ct = comm[s], comm[t]
        if cs < 0 and ct < 0:
            un["internal"] += w
        elif cs < 0:
            un["out"] += w
        elif ct < 0:
            un["in"] += w
        else:
            matrix[cs][ct] += w
    check("community matrix matches a recount of the edges", matrix == cg["matrix"])
    check("unassigned edge buckets match a recount", un == cg["unassigned"])
    total = sum(map(sum, cg["matrix"])) + sum(cg["unassigned"].values())
    check("every edge weight is accounted for exactly once",
          total == sum(e["weight"]), f"{total} vs {sum(e['weight'])}")


def _check_heatmap(graph, story):
    h = story["volume_community_heatmap"]
    volumes = sorted(set(graph["volumes"]))
    check("heatmap volumes are the atlas volumes", h["volumes"] == volumes)
    k = len(graph["communities"])
    counts = [[0] * k for _ in volumes]
    un = [0] * len(volumes)
    vi = {v: i for i, v in enumerate(volumes)}
    for v, c in zip(graph["volumes"], graph["community"]):
        if c < 0:
            un[vi[v]] += 1
        else:
            counts[vi[v]][c] += 1
    check("heatmap counts match a recount of the nodes", counts == h["counts"])
    check("unassigned-by-volume matches a recount", un == h["unassigned_by_volume"])
    check("heatmap n is the table total", h["n"] == sum(map(sum, counts)))

    t = np.asarray(counts, dtype=float)
    expected = np.outer(t.sum(axis=1), t.sum(axis=0)) / t.sum()
    chi2 = float(((t - expected) ** 2 / expected).sum())
    v = float(np.sqrt(chi2 / (t.sum() * (min(t.shape) - 1))))
    check("chi-square recomputes", abs(chi2 - h["chi2"]) < 1e-6, f"{chi2} vs {h['chi2']}")
    check("Cramér's V recomputes", abs(v - h["cramers_v"]) < 1e-9, f"{v} vs {h['cramers_v']}")
    check("degrees of freedom are (rows-1)(cols-1)",
          h["dof"] == (len(volumes) - 1) * (k - 1))


def _check_betweenness(graph, story, n):
    bt = story["hub_bridge_scatter"]["betweenness"]
    check("betweenness has one value per node", len(bt) == n, f"{len(bt)} vs {n}")
    e = graph["edges"]
    g = ig.Graph(n=n, edges=list(zip(e["source"], e["target"])), directed=True)
    recomputed = g.betweenness(directed=True)
    worst = max(abs(a - b) for a, b in zip(bt, recomputed))
    check("betweenness recomputes on the atlas edge list", worst < 0.01,
          f"largest difference {worst}")
    check("betweenness is non-negative", all(b >= 0 for b in bt))


def _check_lifedates(conn, graph, story, n):
    ld = story["lifedates"]
    entries = ld["entries"]
    check("every dated entry is a valid node", all(0 <= d["node"] < n for d in entries))
    check("every dated entry is a person", all(story["person"][d["node"]] for d in entries))
    check("dated entries are unique nodes", len({d["node"] for d in entries}) == len(entries))
    check("every life runs from birth to death",
          all(d["birth"] < d["death"] for d in entries))
    check("no life is longer than 120 years",
          all(d["death"] - d["birth"] <= 120 for d in entries))

    db = {}
    for i, by, bb, dy, dbc in conn.execute(
            "SELECT id, birth_year, birth_bc, death_year, death_bc FROM entries "
            "WHERE lifedates_extracted = 1"):
        db[i] = (-by if bb else by, -dy if dbc else dy)
    ids = graph["ids"]
    mismatched = [d["node"] for d in entries
                  if db.get(ids[d["node"]]) != (d["birth"], d["death"])]
    check("every dated entry matches the database", not mismatched,
          f"{len(mismatched)} differ, e.g. {mismatched[:3]}")
    on_map = sum(1 for i in db if i in set(ids))
    check("every dated entry on the map is listed", on_map == len(entries),
          f"{on_map} in db vs {len(entries)} listed")

    cov = ld["coverage"]
    total, dated = conn.execute(
        "SELECT COUNT(*), SUM(lifedates_extracted) FROM entries WHERE entry_type = 'biography'"
    ).fetchone()
    check("biography coverage matches the database",
          (cov["total_biographies"], cov["dated_biographies"]) == (total, dated))
    check("era counts sum to the dated entries",
          sum(e["count"] for e in ld["eras"]) == len(entries))


def _check_ambiguity(conn, graph, story, n):
    amb = story["ambiguity"]
    terms = amb["terms"]
    check("ambiguity ranking has at most the declared length", len(terms) <= amb["n"])
    check("ambiguous terms are ordered by citation count",
          all(a["citation_count"] >= b["citation_count"] for a, b in zip(terms, terms[1:])))

    counts = Counter(k for (k,) in conn.execute(
        "SELECT match_key FROM resolved_cross_references WHERE status = 'ambiguous'"))
    check("total ambiguous references match the database",
          amb["total_ambiguous"] == sum(counts.values()))
    check("distinct term count matches the database", amb["distinct_terms"] == len(counts))
    wrong = [t["key"] for t in terms if counts[t["key"]] != t["citation_count"]]
    check("every term's citation count matches the database", not wrong, str(wrong[:3]))

    cands = {}
    for key, cand in conn.execute("""
            SELECT r.match_key, c.candidate_entry_id
            FROM resolved_cross_references r
            JOIN resolved_cross_reference_candidates c
              ON c.entry_id = r.entry_id AND c.ordinal = r.ordinal
            WHERE r.status = 'ambiguous'"""):
        cands.setdefault(key, set()).add(cand)
    wrong = [t["key"] for t in terms if len(cands.get(t["key"], ())) != t["candidate_count"]]
    check("every term's candidate count matches the database", not wrong, str(wrong[:3]))
    check("every candidate node index is valid",
          all(c["node"] is None or 0 <= c["node"] < n for t in terms for c in t["candidates"]))
    check("every candidate has a headword",
          all(c["headword"].strip() for t in terms for c in t["candidates"]))

    conflicts = conn.execute("SELECT COUNT(*) FROM lemma_conflicts").fetchone()[0]
    check("homonym list matches lemma_conflicts", len(amb["homonyms"]) == conflicts)
    check("every homonym lists as many entries as it claims",
          all(len(h["entries"]) == h["count"] for h in amb["homonyms"]))


def _check_corpus(conn, graph, story):
    c = story["corpus"]
    check("corpus entry count matches the database",
          c["entries"] == conn.execute("SELECT COUNT(*) FROM entries").fetchone()[0])
    check("corpus reference count matches the database",
          c["references"] == conn.execute(
              "SELECT COUNT(*) FROM resolved_cross_references").fetchone()[0])
    check("corpus node and edge counts match graph.json",
          c["nodes"] == len(graph["ids"]) and
          c["directed_edges"] == len(graph["edges"]["source"]) and
          c["communities"] == len(graph["communities"]))


if __name__ == "__main__":
    sys.exit(main())
