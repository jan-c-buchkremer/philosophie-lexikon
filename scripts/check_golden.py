"""Golden/regression check for scripts/parse_entries.py output, per
docs/pipeline-strategy.md strategy #8.

Reads tests/golden_entries.json (a small, hand-verified set of known
entries and their expected field values -- see that file's cases for
what specific bug/behavior each one guards) and checks the current
structured-data/*.jsonl against it. Run this after any change to
parse_entries.py, before trusting a full 8-volume re-run.

Run via uv:
  uv run python scripts/check_golden.py
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
GOLDEN_PATH = ROOT / "tests" / "golden_entries.json"
DATA_DIR = ROOT / "structured-data"


def load_volume(volume: str) -> list[dict]:
    path = DATA_DIR / f"{volume}_entries.jsonl"
    return [json.loads(line) for line in path.open(encoding="utf-8")]


def find_record(case: dict, cache: dict) -> "dict | None":
    if "id" in case:
        volume = case["id"].split(":")[0]
        records = cache.setdefault(volume, load_volume(volume))
        return next((r for r in records if r["id"] == case["id"]), None)

    volume = case["volume"]
    records = cache.setdefault(volume, load_volume(volume))
    if "headword" in case:
        return next((r for r in records if r["headword"] == case["headword"]), None)
    if "headword_startswith" in case:
        return next((r for r in records if r["headword"].startswith(case["headword_startswith"])), None)
    return None


def check_record(record: dict, checks: dict) -> list[str]:
    failures = []
    for key, expected in checks.items():
        if key == "body_text_startswith":
            if not record["body_text"].startswith(expected):
                failures.append(f"body_text does not start with {expected!r}: {record['body_text'][:60]!r}...")
        elif key == "body_text_endswith":
            if not record["body_text"].endswith(expected):
                failures.append(f"body_text does not end with {expected!r}: ...{record['body_text'][-60:]!r}")
        elif key == "body_text_not_contains":
            for bad in expected:
                if bad in record["body_text"]:
                    failures.append(f"body_text unexpectedly contains {bad!r}")
        elif key == "headword_startswith":
            if not record["headword"].startswith(expected):
                failures.append(f"headword does not start with {expected!r}: {record['headword']!r}")
        elif key.endswith("_not_null"):
            field = key[: -len("_not_null")]
            if record.get(field) is None:
                failures.append(f"{field} is null, expected non-null")
        elif key.endswith("_includes"):
            field = key[: -len("_includes")]
            actual = record.get(field) or []
            missing = [v for v in expected if v not in actual]
            if missing:
                failures.append(f"{field} missing expected values {missing}: has {actual}")
        elif key == "flags":
            actual = record.get("flags") or []
            missing = [v for v in expected if v not in actual]
            if missing:
                failures.append(f"flags missing {missing}: has {actual}")
        else:
            actual = record.get(key)
            if actual != expected:
                failures.append(f"{key}: expected {expected!r}, got {actual!r}")
    return failures


def check_aggregate(agg: dict, cache: dict) -> list[str]:
    volume = agg["volume"]
    records = cache.setdefault(volume, load_volume(volume))
    if "entry_type" in agg:
        actual = sum(1 for r in records if r["entry_type"] == agg["entry_type"])
    elif "flag" in agg:
        actual = sum(1 for r in records if agg["flag"] in (r.get("flags") or []))
    else:
        return [f"malformed aggregate check: {agg}"]
    if actual != agg["expect_count"]:
        return [f"expected count {agg['expect_count']}, got {actual}"]
    return []


def main() -> int:
    golden = json.loads(GOLDEN_PATH.read_text(encoding="utf-8"))
    cache: dict[str, list[dict]] = {}
    total = 0
    passed = 0

    for case in golden["cases"]:
        total += 1
        record = find_record(case, cache)
        if record is None:
            print(f"FAIL  {case['name']}: no matching record found")
            continue
        failures = check_record(record, case["checks"])
        if failures:
            print(f"FAIL  {case['name']} ({record['id']}):")
            for f in failures:
                print(f"        - {f}")
        else:
            passed += 1
            print(f"PASS  {case['name']}")

    for agg in golden.get("aggregate_checks", []):
        total += 1
        failures = check_aggregate(agg, cache)
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
