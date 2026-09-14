"""Regression checks for the clean/lemma/export stages.

Same discipline as scripts/check_golden.py and check_golden_xrefs.py: assert
the properties that, if they ever silently stopped holding, would put wrong
data in front of a consumer. Every check here corresponds to a real hazard
this project has already been bitten by at least once.

Run via uv:
  uv run python scripts/check_dataset.py [--db-path ...] [--export export]
"""
import argparse
import csv
import json
import re
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from clean_text import clean, REPLACEMENT, UNDERSCORE_RUN_RE  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DB_PATH = ROOT / "structured-data" / "lexikon.db"
DEFAULT_EXPORT = ROOT / "export"

ITALIC_RE = re.compile(r"_[^_\n]{1,200}_")
SUP_RE = re.compile(r"<sup>")
BOLD_RE = re.compile(r"\*\*")
# A transliteration diacritic, which the clean stage composes into real
# Unicode. Both spellings must be gone after a letter: the <sup>-wrapped
# form that pymupdf4llm's reflow produces in body text, AND the bare
# character that the PDF font spans hand back in headwords.
SUP_DIACRITIC_RE = re.compile(r"[^\W\d_](<sup>)?[´¯˙ˇ˜](</sup>)?")

results = []


def check(name, ok, detail=""):
    results.append((name, ok, detail))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--db-path", default=str(DEFAULT_DB_PATH))
    ap.add_argument("--export", default=str(DEFAULT_EXPORT))
    args = ap.parse_args()

    conn = sqlite3.connect(args.db_path)
    conn.row_factory = sqlite3.Row
    export_dir = Path(args.export)

    rows = list(conn.execute(
        "SELECT id, headword, headword_clean, body_text, body_clean, "
        "werke_raw, werke_clean, literatur_raw, literatur_clean, "
        "unreadable_chars FROM entries"))

    # 1. every entry actually got a clean layer
    missing = [r["id"] for r in rows if not (r["body_clean"] or "").strip()]
    check("every entry has non-empty body_clean", not missing,
          f"{len(missing)} empty, e.g. {missing[:3]}")

    # 2. no markup survives. Italics are only asserted gone where
    #    clean_text.strip_italics would actually have acted: runs of 2+
    #    underscores are the argument-blank notation and are masked out
    #    first, then a line is only processed if its REMAINING underscores
    #    pair up. Restating those rules here instead of reusing them is how
    #    a checker ends up demanding the very corruption the cleaner exists
    #    to avoid -- so the mask comes from clean_text itself.
    def has_stray_italics(text):
        for line in (text or "").split("\n"):
            masked = UNDERSCORE_RUN_RE.sub("", line)
            if masked.count("_") % 2 == 0 and ITALIC_RE.search(masked):
                return True
        return False

    dirty = [r["id"] for r in rows
             if BOLD_RE.search(r["body_clean"] or "")
             or SUP_RE.search(r["body_clean"] or "")
             or has_stray_italics(r["body_clean"])]
    check("no **, <sup> or resolvable _.._ survives in body_clean", not dirty,
          f"{len(dirty)} entries still marked up, e.g. {dirty[:3]}")

    # 3. THE important one. Cleaning must never remove or invent an
    #    unreadable glyph -- every previous attempt to "improve" one of
    #    these produced silent corruption (ISSUES.md #6/#7/#9).
    bad = []
    for r in rows:
        for raw_col, clean_col in (("body_text", "body_clean"),
                                   ("werke_raw", "werke_clean"),
                                   ("literatur_raw", "literatur_clean")):
            a = (r[raw_col] or "").count(REPLACEMENT)
            b = (r[clean_col] or "").count(REPLACEMENT)
            if a != b:
                bad.append(f"{r['id']}/{raw_col}: {a} -> {b}")
    check("U+FFFD count identical before and after cleaning", not bad,
          f"{len(bad)} mismatches, e.g. {bad[:3]}")

    # 4. unreadable_chars actually equals what is in the text
    wrong = [r["id"] for r in rows
             if r["unreadable_chars"] != sum(
                 (r[c] or "").count(REPLACEMENT)
                 for c in ("body_text", "werke_raw", "literatur_raw"))]
    check("unreadable_chars matches the text", not wrong,
          f"{len(wrong)} wrong, e.g. {wrong[:3]}")

    # 5. cleaning is idempotent -- re-running it on its own output is a
    #    no-op, so the stage can never be applied twice by accident
    nonidem = [r["id"] for r in rows[:1500]
               if clean(r["body_clean"]) != r["body_clean"]]
    check("cleaning is idempotent (1500-entry sample)", not nonidem,
          f"{len(nonidem)} changed on re-clean, e.g. {nonidem[:3]}")

    # 6. transliteration diacritics were composed, none left dangling
    left = [r["id"] for r in rows if SUP_DIACRITIC_RE.search(r["body_clean"] or "")
            or SUP_DIACRITIC_RE.search(r["headword_clean"] or "")]
    check("no superscript diacritic survives after a letter", not left,
          f"{len(left)} left, e.g. {left[:3]}")

    # 7. the clean stage was ADDITIVE: raw columns untouched. Compared
    #    against the JSONL parse_entries.py wrote, which is upstream of
    #    clean_text.py entirely.
    drift = []
    for path in sorted((ROOT / "structured-data").glob("Bd*_entries.jsonl")):
        for line in path.open(encoding="utf-8"):
            rec = json.loads(line)
            row = conn.execute(
                "SELECT headword, body_text FROM entries WHERE id = ?",
                (rec["id"],)).fetchone()
            if row is None:
                drift.append(f"{rec['id']} missing from db")
            elif row["headword"] != rec["headword"] or row["body_text"] != rec["body_text"]:
                drift.append(f"{rec['id']} raw text differs")
    check("raw headword/body_text unchanged by the clean stage", not drift,
          f"{len(drift)} drifted, e.g. {drift[:3]}")

    # 8. lemma index covers every entry
    uncovered = conn.execute(
        "SELECT COUNT(*) FROM entries e WHERE NOT EXISTS ("
        "  SELECT 1 FROM lemmas l WHERE l.entry_id = e.id AND l.variant_type='primary')"
    ).fetchone()[0]
    check("every entry has a primary lemma row", uncovered == 0,
          f"{uncovered} entries missing from the lemma index")

    # 9. referential integrity of the graph
    orphan = conn.execute(
        "SELECT COUNT(*) FROM resolved_cross_references r "
        "WHERE r.resolved_entry_id IS NOT NULL AND NOT EXISTS ("
        "  SELECT 1 FROM entries e WHERE e.id = r.resolved_entry_id)").fetchone()[0]
    check("every resolved edge points at a real entry", orphan == 0,
          f"{orphan} dangling targets")

    # 10. export matches the database
    manifest = json.loads((export_dir / "MANIFEST.json").read_text(encoding="utf-8"))
    file_rows = {}
    with (export_dir / "entries.jsonl").open(encoding="utf-8") as f:
        file_rows["entries.jsonl"] = sum(1 for _ in f)
    for name in ("edges.csv", "lemmas.csv", "ambiguous.csv"):
        with (export_dir / name).open(encoding="utf-8", newline="") as f:
            file_rows[name] = sum(1 for _ in csv.reader(f)) - 1  # minus header
    mismatch = [f"{k}: manifest {v} vs file {file_rows.get(k)}"
                for k, v in manifest["row_counts"].items() if file_rows.get(k) != v]
    check("MANIFEST row counts match the exported files", not mismatch, str(mismatch))

    db_entries = conn.execute("SELECT COUNT(*) FROM entries").fetchone()[0]
    db_edges = conn.execute("SELECT COUNT(*) FROM resolved_cross_references").fetchone()[0]
    check("export row counts match the database",
          file_rows["entries.jsonl"] == db_entries and file_rows["edges.csv"] == db_edges,
          f"entries {file_rows['entries.jsonl']}/{db_entries}, "
          f"edges {file_rows['edges.csv']}/{db_edges}")

    # 11. edges.csv is a COMPLETE account, unresolved rows included
    with (export_dir / "edges.csv").open(encoding="utf-8", newline="") as f:
        n_empty = sum(1 for r in csv.DictReader(f) if not r["target_entry_id"])
    db_unmatched = conn.execute(
        "SELECT COUNT(*) FROM resolved_cross_references "
        "WHERE resolved_entry_id IS NULL").fetchone()[0]
    check("edges.csv keeps unresolved references", n_empty == db_unmatched,
          f"{n_empty} empty targets vs {db_unmatched} unresolved in db")

    conn.close()

    passed = sum(1 for _, ok, _ in results if ok)
    for name, ok, detail in results:
        print(("PASS  " if ok else "FAIL  ") + name + ("" if ok else f":\n        - {detail}"))
    print(f"\n{passed}/{len(results)} checks passed")
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
