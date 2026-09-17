"""Numbers for the essay page (viz/geschichte.html).

Everything here is derived from two inputs: the built atlas (graph.json,
which already fixes node order, community membership and colours) and
lexikon.db. Nothing is recomputed that the atlas already decided -- the
essay must never disagree with the map about which entry belongs where.

Each function returns plain JSON-serialisable data. scripts/build_story.py
assembles them into story.json; scripts/check_story.py recomputes the
invariants independently.
"""
import json
import logging
import sqlite3
import statistics
from collections import Counter, defaultdict
from pathlib import Path

import igraph as ig
import numpy as np

logger = logging.getLogger(__name__)

# The clock the essay draws on. Signed years: -428 is 428 v. Chr.
ERA_BOUNDS = [
    ("antike", None, 500),
    ("mittelalter", 500, 1450),
    ("fruehe_neuzeit", 1450, 1800),
    ("neunzehntes", 1800, 1900),
    ("zwanzigstes", 1900, None),
]


# --- inputs ------------------------------------------------------------------

def load_graph(data_dir: Path) -> dict:
    path = data_dir / "graph.json"
    if not path.exists():
        raise SystemExit(
            f"{path} not found. Build the atlas first:\n"
            f"  uv run python scripts/build_atlas.py [--dev]")
    return json.loads(path.read_text(encoding="utf-8"))


def load_labels(path: Path, graph: dict) -> list[dict]:
    """The hand-written community names, checked against the atlas.

    Community ids are ranks by size, so a rebuilt atlas can renumber them.
    Each label therefore records the anchor headword it was written for;
    a mismatch is reported rather than shipped under the wrong colour.
    """
    raw = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    headwords = graph["headwords"]
    out = []
    for c in graph["communities"]:
        anchor = headwords[c["anchor"]]
        entry = raw.get(str(c["id"]))
        if entry is None:
            logger.warning("community %d (%s) has no label in %s; using the atlas label",
                           c["id"], anchor, path.name)
            out.append({"id": c["id"], "short_label": c["label"], "anchor": anchor,
                        "label_status": "missing"})
            continue
        status = "ok"
        if entry.get("anchor") != anchor:
            logger.warning("community %d is now anchored on %r but its label was written for %r",
                           c["id"], anchor, entry.get("anchor"))
            status = "stale"
        out.append({"id": c["id"], "short_label": entry["label"], "anchor": anchor,
                    "label_status": status})
    return out


PERSON_SQL = """
    SELECT id FROM entries
    WHERE lifedates_extracted = 1
       OR (entry_type = 'biography' AND instr(substr(COALESCE(body_clean, body_text), 1, 500), '†') > 0)
"""


def person_flags(conn: sqlite3.Connection, graph: dict) -> list[int]:
    """1 for every node that is a person.

    entry_type is read off the bibliography apparatus -- "biography" means
    Werke: and Literatur: both present -- so it both undercounts (Sokrates
    has no Werke: and is a subject_article; Kant's bespoke bibliography
    makes him unknown) and overcounts (Pythagoreer, Patristik, Bourbaki,
    and the operator Demonstrator all carry both blocks). The death sign
    in the head of the entry is the signal that actually means a person:
    a dated life, or a biography whose head has the sign even where the
    years could not be read (see scripts/extract_lifedates.py).
    """
    persons = {r[0] for r in conn.execute(PERSON_SQL)}
    return [1 if i in persons else 0 for i in graph["ids"]]


# --- chapter data ------------------------------------------------------------

def corpus_counts(conn: sqlite3.Connection, graph: dict) -> dict:
    total = conn.execute("SELECT COUNT(*) FROM entries").fetchone()[0]
    by_type = dict(conn.execute("SELECT entry_type, COUNT(*) FROM entries GROUP BY entry_type"))
    refs = conn.execute("SELECT COUNT(*) FROM resolved_cross_references").fetchone()[0]
    by_status = dict(conn.execute(
        "SELECT status, COUNT(*) FROM resolved_cross_references GROUP BY status"))
    resolved = sum(v for k, v in by_status.items() if k not in ("ambiguous", "unresolved"))
    return {
        "entries": total,
        "entries_by_type": by_type,
        "references": refs,
        "references_by_status": by_status,
        "resolved_share": resolved / refs if refs else 0.0,
        "nodes": len(graph["ids"]),
        "directed_edges": len(graph["edges"]["source"]),
        "communities": len(graph["communities"]),
        "volumes": sorted(set(graph["volumes"])),
    }


def hub_ranking(graph: dict, person: list[int], top_n: int) -> dict:
    deg = graph["in_degree"]
    order = sorted(range(len(deg)), key=lambda i: (-deg[i], graph["ids"][i]))
    persons = [i for i in order if person[i]]
    return {
        "n": top_n,
        "nodes": order[:top_n],
        "persons_in_top": sum(person[i] for i in order[:top_n]),
        "top_persons": persons[:12],
        "median_in_degree": statistics.median(deg),
        "uncited": sum(1 for d in deg if d == 0),
        "uncited_persons": sum(1 for i, d in enumerate(deg) if d == 0 and person[i]),
    }


def community_matrix(graph: dict) -> dict:
    """matrix[i][j]: weighted count of references from community i to j."""
    k = len(graph["communities"])
    comm = graph["community"]
    matrix = [[0] * k for _ in range(k)]
    unassigned = {"in": 0, "out": 0, "internal": 0}
    e = graph["edges"]
    for s, t, w in zip(e["source"], e["target"], e["weight"]):
        cs, ct = comm[s], comm[t]
        if cs < 0 and ct < 0:
            unassigned["internal"] += w
        elif cs < 0:
            unassigned["out"] += w      # from the unassigned bucket into a community
        elif ct < 0:
            unassigned["in"] += w       # from a community into the bucket
        else:
            matrix[cs][ct] += w
    return {"matrix": matrix, "unassigned": unassigned}


def volume_community_heatmap(graph: dict) -> dict:
    volumes = sorted(set(graph["volumes"]))
    k = len(graph["communities"])
    vindex = {v: i for i, v in enumerate(volumes)}
    counts = [[0] * k for _ in volumes]
    unassigned = [0] * len(volumes)
    for v, c in zip(graph["volumes"], graph["community"]):
        if c < 0:
            unassigned[vindex[v]] += 1
        else:
            counts[vindex[v]][c] += 1
    chi2, dof, v = cramers_v(counts)
    return {
        "volumes": volumes,
        "community_ids": list(range(k)),
        "counts": counts,
        "unassigned_by_volume": unassigned,
        "n": int(sum(map(sum, counts))),
        "chi2": chi2,
        "dof": dof,
        "cramers_v": v,
    }


def cramers_v(table: list[list[int]]) -> tuple[float, int, float]:
    """Chi-square and Cramér's V of a contingency table, with numpy only."""
    t = np.asarray(table, dtype=float)
    n = t.sum()
    expected = np.outer(t.sum(axis=1), t.sum(axis=0)) / n
    mask = expected > 0
    chi2 = float(((t[mask] - expected[mask]) ** 2 / expected[mask]).sum())
    dof = (t.shape[0] - 1) * (t.shape[1] - 1)
    v = float(np.sqrt(chi2 / (n * (min(t.shape) - 1))))
    return chi2, dof, v


def betweenness(graph: dict) -> list[float]:
    """Directed, unweighted betweenness on exactly the atlas's edge list."""
    n = len(graph["ids"])
    e = graph["edges"]
    g = ig.Graph(n=n, edges=list(zip(e["source"], e["target"])), directed=True)
    return [round(b, 3) for b in g.betweenness(directed=True)]


def lifedates(conn: sqlite3.Connection, graph: dict) -> dict:
    index = {i: n for n, i in enumerate(graph["ids"])}
    entries = []
    for r in conn.execute(
            "SELECT id, birth_year, birth_bc, death_year, death_bc FROM entries "
            "WHERE lifedates_extracted = 1"):
        node = index.get(r[0])
        if node is None:
            continue
        birth = -r[1] if r[2] else r[1]
        death = -r[3] if r[4] else r[3]
        entries.append({"node": node, "birth": birth, "death": death})
    entries.sort(key=lambda d: (d["birth"], d["node"]))

    biographies = conn.execute(
        "SELECT COUNT(*), SUM(lifedates_extracted) FROM entries WHERE entry_type = 'biography'"
    ).fetchone()
    eras = Counter(era_of(d["birth"]) for d in entries)
    return {
        "entries": entries,
        "coverage": {
            "total_biographies": biographies[0],
            "dated_biographies": biographies[1],
            "dated_total": len(entries),
        },
        "eras": [{"key": key, "from": lo, "to": hi, "count": eras.get(key, 0)}
                 for key, lo, hi in ERA_BOUNDS],
    }


def era_of(year: int) -> str:
    for key, lo, hi in ERA_BOUNDS:
        if (lo is None or year >= lo) and (hi is None or year < hi):
            return key
    raise ValueError(year)


def ambiguity(conn: sqlite3.Connection, graph: dict, top_n: int) -> dict:
    """The references the resolver refused to decide, and the names several
    people share."""
    index = {i: n for n, i in enumerate(graph["ids"])}
    headword = dict(conn.execute(
        "SELECT id, COALESCE(headword_clean, headword) FROM entries"))
    volume = dict(conn.execute("SELECT id, volume FROM entries"))

    # One row per ambiguous reference, grouped by its normalised key so
    # that "Implikation" and "Implikationen" count as one contested term.
    groups: dict[str, dict] = {}
    for key, raw in conn.execute(
            "SELECT match_key, raw_target FROM resolved_cross_references "
            "WHERE status = 'ambiguous'"):
        g = groups.setdefault(key, {"count": 0, "forms": Counter(), "candidates": set()})
        g["count"] += 1
        g["forms"][raw] += 1
    for key, cand in conn.execute("""
            SELECT r.match_key, c.candidate_entry_id
            FROM resolved_cross_references r
            JOIN resolved_cross_reference_candidates c
              ON c.entry_id = r.entry_id AND c.ordinal = r.ordinal
            WHERE r.status = 'ambiguous'"""):
        groups[key]["candidates"].add(cand)

    ranked = sorted(groups.items(), key=lambda kv: (-kv[1]["count"], kv[0]))
    terms = []
    for key, g in ranked[:top_n]:
        cands = sorted(g["candidates"], key=lambda i: (headword[i], i))
        terms.append({
            "key": key,
            "display": g["forms"].most_common(1)[0][0],
            "forms": [f for f, _ in g["forms"].most_common()],
            "citation_count": g["count"],
            "candidate_count": len(cands),
            "candidates": [{"node": index.get(i), "headword": headword[i],
                            "volume": volume[i]} for i in cands],
        })

    body = dict(conn.execute("SELECT id, substr(COALESCE(body_clean, body_text), 1, 200) FROM entries"))
    homonyms = []
    for key, n, ids in conn.execute(
            "SELECT lemma_key, n, entry_ids FROM lemma_conflicts ORDER BY n DESC, lemma_key"):
        members = [i.strip() for i in ids.split("|")]
        homonyms.append({
            "key": key,
            "count": n,
            "entries": [{"node": index.get(i), "headword": headword[i], "volume": volume[i],
                         "display": _display_name(headword[i], body[i])}
                        for i in members],
        })

    total_ambiguous = conn.execute(
        "SELECT COUNT(*) FROM resolved_cross_references WHERE status = 'ambiguous'").fetchone()[0]
    return {
        "n": top_n,
        "total_ambiguous": total_ambiguous,
        "distinct_terms": len(groups),
        "terms": terms,
        "homonyms": homonyms,
    }


def _display_name(headword: str, body: str) -> str:
    """'Ariston' + 'Ariston von Chios, ...' -> 'Ariston von Chios';
    'Bernoulli' + 'Bernoulli, Daniel, Groningen ...' -> 'Bernoulli, Daniel'.

    Homonymous lemmas are bare surnames; the head of the entry carries
    what tells them apart.
    """
    if not body.startswith(headword):
        return headword
    rest = body[len(headword):]
    inverted = rest.startswith(",")
    rest = rest.lstrip(", ")
    for stop in (",", "†", "(", ";", "."):
        cut = rest.find(stop)
        if cut >= 0:
            rest = rest[:cut]
    gloss = rest.strip()
    if not gloss or len(gloss) > 40:
        return headword
    return f"{headword}, {gloss}" if inverted else f"{headword} {gloss}"


def redirect_aliases(conn: sqlite3.Connection, graph: dict, top_n: int) -> list[dict]:
    """Articles reachable under the most alternative names."""
    index = {i: n for n, i in enumerate(graph["ids"])}
    aliases: dict[str, list[str]] = defaultdict(list)
    for lemma, entry_id in conn.execute(
            "SELECT lemma, entry_id FROM lemmas WHERE variant_type = 'redirect_alias'"):
        aliases[entry_id].append(lemma)
    ranked = sorted(aliases.items(), key=lambda kv: (-len(kv[1]), kv[0]))
    return [{"node": index[i], "aliases": sorted(names)}
            for i, names in ranked[:top_n] if i in index]
