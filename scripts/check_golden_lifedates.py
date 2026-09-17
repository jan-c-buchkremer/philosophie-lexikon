"""Golden/regression check for scripts/extract_lifedates.py, per
docs/pipeline-strategy.md strategy #8.

Reads tests/golden_lifedates.json (hand-verified entries and the dates the
pass must -- or must not -- read off them) and checks the live
structured-data/lexikon.db against it. Run after any change to
extract_lifedates.py.

Run via uv:
  uv run python scripts/check_golden_lifedates.py [--db-path ...]
"""
import argparse
import json
import sqlite3
import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parent.parent
GOLDEN_PATH = ROOT / "tests" / "golden_lifedates.json"
DEFAULT_DB_PATH = ROOT / "structured-data" / "lexikon.db"

FIELDS = ("birth_year", "birth_bc", "death_year", "death_bc")


def find_record(conn, case):
    rows = conn.execute(
        "SELECT id, lifedates_extracted, birth_year, birth_bc, death_year, death_bc, "
        "COALESCE(body_clean, body_text) AS body FROM entries "
        "WHERE volume = ? AND COALESCE(headword_clean, headword) = ?",
        (case["volume"], case["headword"])).fetchall()
    prefix = case.get("headword_startswith_body")
    if prefix:
        rows = [r for r in rows if r["body"].startswith(prefix)]
    if len(rows) != 1:
        return None, f"{len(rows)} matching entries"
    return rows[0], ""


def check_case(record, expect) -> list[str]:
    if expect is None:
        if record["lifedates_extracted"]:
            return [f"expected no dates, got {tuple(record[f] for f in FIELDS)}"]
        return []
    if not record["lifedates_extracted"]:
        return ["expected dates, entry is undated"]
    return [f"{f}: expected {expect[f]!r}, got {record[f]!r}"
            for f in FIELDS if record[f] != expect[f]]


def check_aggregate(conn, agg) -> list[str]:
    if "entry_type" in agg:
        total, dated = conn.execute(
            "SELECT COUNT(*), SUM(lifedates_extracted) FROM entries WHERE entry_type = ?",
            (agg["entry_type"],)).fetchone()
        share = dated / total
        if not agg["min_share"] <= share <= agg["max_share"]:
            return [f"share {share:.3f} outside [{agg['min_share']}, {agg['max_share']}]"]
        return []
    if agg.get("invariant") == "plausible_lifespans":
        bad = conn.execute("""
            SELECT id FROM entries WHERE lifedates_extracted = 1 AND NOT (
                (CASE WHEN death_bc THEN -death_year ELSE death_year END)
              - (CASE WHEN birth_bc THEN -birth_year ELSE birth_year END) BETWEEN 1 AND 120)
        """).fetchall()
        return [f"{len(bad)} entries, e.g. {[r[0] for r in bad[:3]]}"] if bad else []
    return [f"malformed aggregate check: {agg}"]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--db-path", default=str(DEFAULT_DB_PATH))
    args = ap.parse_args()

    conn = sqlite3.connect(args.db_path)
    conn.row_factory = sqlite3.Row
    present = {r[1] for r in conn.execute("PRAGMA table_info(entries)")}
    if "lifedates_extracted" not in present:
        print("entries has no lifedates columns. Run: uv run python scripts/extract_lifedates.py")
        return 1

    golden = json.loads(GOLDEN_PATH.read_text(encoding="utf-8"))
    total = passed = 0

    for case in golden["cases"]:
        total += 1
        record, problem = find_record(conn, case)
        if record is None:
            print(f"FAIL  {case['name']}: {problem}")
            continue
        failures = check_case(record, case["expect"])
        if failures:
            print(f"FAIL  {case['name']} ({record['id']}):")
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

    print(f"\n{passed}/{total} checks passed")
    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(main())
