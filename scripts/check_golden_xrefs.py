"""Golden/regression check for scripts/resolve_xrefs.py output, per
docs/pipeline-strategy.md strategy #8.

Sibling of scripts/check_golden.py (which covers the entry parser). Kept
separate because the unit of assertion is different: a single
(entry_id, ordinal) row in resolved_cross_references, checked for
status/target/hop-count/candidate-set, rather than an entry record.

Reads tests/golden_xrefs.json and checks it against the CURRENT
structured-data/lexikon.db, so run scripts/resolve_xrefs.py first.

Run via uv:
  uv run python scripts/check_golden_xrefs.py [--db-path structured-data/lexikon.db]
"""
import argparse
import json
import sqlite3
import sys
from pathlib import Path

# Headwords and targets in this corpus contain U+FFFD and Greek, and a
# Windows console defaults to cp1252 -- printing a FAILURE used to raise
# UnicodeEncodeError and kill the run before the remaining checks, i.e.
# the suite broke exactly when it had something to report.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parent.parent
GOLDEN_PATH = ROOT / "tests" / "golden_xrefs.json"
DEFAULT_DB_PATH = ROOT / "structured-data" / "lexikon.db"


def resolve_entry_id(conn: sqlite3.Connection, case: dict) -> "str | None":
    """Cases identify their citing entry by HEADWORD, not by id.

    Entry ids embed an ordinal, so they shift whenever the number of
    entries changes -- which a re-extraction routinely does. Pinning ids
    made the whole suite fail on drift and said nothing about
    correctness. Headwords are stable."""
    if "entry_id" in case:
        return case["entry_id"]
    row = conn.execute(
        "SELECT id FROM entries WHERE volume = ? AND headword = ? LIMIT 1",
        (case["entry_volume"], case["entry_headword"]),
    ).fetchone()
    return row["id"] if row else None


def find_row(conn: sqlite3.Connection, case: dict) -> "sqlite3.Row | None":
    """Locate the row a case refers to. `raw_target` alone can occur many
    times within one entry, so a case may additionally pin `raw_context`
    to select the exact occurrence it means."""
    entry_id = resolve_entry_id(conn, case)
    if entry_id is None:
        return None
    sql = """SELECT r.*, x.raw_context, e.headword AS resolved_headword
             FROM resolved_cross_references r
             JOIN cross_references x
               ON x.entry_id = r.entry_id AND x.ordinal = r.ordinal
             LEFT JOIN entries e ON e.id = r.resolved_entry_id
             WHERE r.entry_id = ? AND r.raw_target = ?"""
    params = [entry_id, case["raw_target"]]
    if "raw_context" in case:
        sql += " AND x.raw_context = ?"
        params.append(case["raw_context"])
    return conn.execute(sql + " ORDER BY r.ordinal LIMIT 1", params).fetchone()


def candidates_for(conn: sqlite3.Connection, entry_id: str, ordinal: int) -> list:
    return [
        row["candidate_entry_id"]
        for row in conn.execute(
            "SELECT candidate_entry_id FROM resolved_cross_reference_candidates "
            "WHERE entry_id = ? AND ordinal = ?",
            (entry_id, ordinal),
        )
    ]


def check_row(conn: sqlite3.Connection, row: sqlite3.Row, checks: dict) -> list:
    failures = []
    for key, expected in checks.items():
        if key == "resolved_headword_startswith":
            actual = row["resolved_headword"]
            if not actual or not actual.startswith(expected):
                failures.append(f"resolved_headword does not start with {expected!r}: {actual!r}")
        elif key == "resolved_headword":
            if row["resolved_headword"] != expected:
                failures.append(f"resolved_headword: expected {expected!r}, got {row['resolved_headword']!r}")
        elif key == "candidates_include_headwords":
            ids = candidates_for(conn, row["entry_id"], row["ordinal"])
            actual = [
                conn.execute("SELECT headword FROM entries WHERE id = ?", (i,)).fetchone()["headword"]
                for i in ids
            ]
            missing = [h for h in expected
                       if not any(a.startswith(h) for a in actual)]
            if missing:
                failures.append(f"candidates missing {missing}: has {actual}")
        elif key == "candidate_count_min":
            actual = len(candidates_for(conn, row["entry_id"], row["ordinal"]))
            # Candidates are only stored for ambiguous rows; for a resolved
            # row this asserts against the tiebreak having had a real
            # contest, which we can only observe via the index -- so skip
            # rather than fail when the row resolved cleanly.
            if row["status"] == "ambiguous" and actual < expected:
                failures.append(f"candidate count {actual} < expected minimum {expected}")
        else:
            actual = row[key]
            if actual != expected:
                failures.append(f"{key}: expected {expected!r}, got {actual!r}")
    return failures


def check_aggregate(conn: sqlite3.Connection, agg: dict) -> list:
    corpus = agg.get("absent_reference_corpus")
    if corpus:
        # The same negative guard as absent_reference, but corpus-wide:
        # some texts must never be captured in ANY entry. Bare German
        # articles are the case -- they only ever entered the reference
        # list as quotations, so a single one anywhere means "›" is
        # being read as an arrow again somewhere.
        bad = []
        for target in corpus["raw_targets"]:
            n = conn.execute(
                "SELECT COUNT(*) FROM cross_references WHERE raw_target = ?",
                (target,),
            ).fetchone()[0]
            if n:
                bad.append(f"{target!r} captured {n}x")
        return [f"bare articles captured as references: {', '.join(bad)}"] if bad else []

    absent = agg.get("absent_reference")
    if absent:
        # A NEGATIVE guard: this text must NOT have been captured as a
        # cross-reference at all. Needed for ISSUES.md issue #12 -- "›...‹"
        # is the German quotation mark as well as the Verweispfeil in
        # Bd01-06, and every quoted word used to be recorded as a
        # reference (27% of all captures). A positive check cannot express
        # "and this one is not a reference".
        entry_id = resolve_entry_id(conn, absent)
        if entry_id is None:
            return [f"entry {absent.get('entry_headword')!r} not found"]
        n = conn.execute(
            "SELECT COUNT(*) FROM cross_references WHERE entry_id = ? AND raw_target = ?",
            (entry_id, absent["raw_target"]),
        ).fetchone()[0]
        if n:
            return [f"{absent['raw_target']!r} was captured {n}x in "
                    f"{absent['entry_headword']!r}, but it is a quotation, not a reference"]
        return []

    if agg.get("one_to_one_with_cross_references"):
        n_src = conn.execute("SELECT COUNT(*) FROM cross_references").fetchone()[0]
        n_res = conn.execute("SELECT COUNT(*) FROM resolved_cross_references").fetchone()[0]
        if n_src != n_res:
            return [f"{n_src} cross_references rows but {n_res} resolved rows"]
        return []

    total = conn.execute("SELECT COUNT(*) FROM resolved_cross_references").fetchone()[0]
    if not total:
        return ["no resolved_cross_references rows at all -- did resolve_xrefs.py run?"]
    placeholders = ",".join("?" * len(agg["statuses"]))
    matched = conn.execute(
        f"SELECT COUNT(*) FROM resolved_cross_references WHERE status IN ({placeholders})",
        agg["statuses"],
    ).fetchone()[0]
    rate = matched / total
    if not (agg["min_rate"] <= rate <= agg["max_rate"]):
        return [f"rate {rate:.1%} outside expected band "
                f"{agg['min_rate']:.0%}-{agg['max_rate']:.0%} ({matched}/{total})"]
    return []


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db-path", default=str(DEFAULT_DB_PATH))
    args = ap.parse_args()

    golden = json.loads(GOLDEN_PATH.read_text(encoding="utf-8"))
    conn = sqlite3.connect(str(args.db_path))
    conn.row_factory = sqlite3.Row

    total = 0
    passed = 0

    for case in golden["cases"]:
        total += 1
        row = find_row(conn, case)
        if row is None:
            # Not every case is keyed by entry_id (an aggregate-style case
            # may identify its row differently), so report whatever the
            # case actually carries instead of assuming both keys exist --
            # this line used to raise KeyError and abort the whole run
            # precisely when something had failed.
            ident = ", ".join(f"{k}={case[k]!r}" for k in
                              ("entry_id", "raw_target", "source_headword")
                              if k in case)
            print(f"FAIL  {case['name']}: no resolved row for {ident or case}")
            continue
        failures = check_row(conn, row, case["checks"])
        if failures:
            print(f"FAIL  {case['name']}:")
            for f in failures:
                print(f"        - {f}")
        else:
            passed += 1
            print(f"PASS  {case['name']}")

    for agg in golden.get("aggregate_checks", []):
        total += 1
        failures = check_aggregate(conn, agg)
        if failures:
            print(f"FAIL  {agg['name']}:")
            for f in failures:
                print(f"        - {f}")
        else:
            passed += 1
            print(f"PASS  {agg['name']}")

    conn.close()
    print(f"\n{passed}/{total} checks passed")
    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(main())
