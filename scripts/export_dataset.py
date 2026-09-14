"""Export the finished corpus as a documented, tool-agnostic dataset.

The database is a rebuildable cache (docs/pipeline-strategy.md strategy
#9); THIS is the artifact other tools are meant to consume. Everything
written here is derived -- delete export/ and re-run at any time.

Formats are deliberately JSONL and CSV only. Parquet would mean adding
pyarrow, and this project has held a zero-dependency line throughout
(stdlib sqlite3 over DuckDB, for the same reason); the corpus is a few MB,
and CSV loads directly into pandas, networkx and Gephi.

  entries.jsonl   one record per entry, raw AND cleaned text side by side
  edges.csv       the citation graph, one row per reference INCLUDING the
                  ones that did not resolve (empty target) -- so the file
                  is a complete account of the source's cross-references,
                  not a filtered success list
  lemmas.csv      the canonical cross-volume lemma index
  ambiguous.csv   every ambiguous reference with its full candidate set,
                  because the resolver records candidates and never guesses
  MANIFEST.json   schema version, counts, and the resolution breakdown

Run via uv:
  uv run python scripts/export_dataset.py [--out export] [--db-path ...]
"""
import argparse
import csv
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DB_PATH = ROOT / "structured-data" / "lexikon.db"
DEFAULT_OUT = ROOT / "export"

SCHEMA_VERSION = "1.0"


def write_csv(path: Path, header: list, rows) -> int:
    n = 0
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(header)
        for row in rows:
            w.writerow(["" if v is None else v for v in row])
            n += 1
    return n


def export(db_path: Path, out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    counts = {}

    # --- entries.jsonl ----------------------------------------------------
    flags = {}
    for eid, flag in conn.execute("SELECT entry_id, flag FROM entry_flags"):
        flags.setdefault(eid, []).append(flag)

    path = out_dir / "entries.jsonl"
    n = 0
    with path.open("w", encoding="utf-8") as f:
        for r in conn.execute("SELECT * FROM entries ORDER BY volume, ordinal"):
            rec = dict(r)
            rec["flags"] = flags.get(r["id"], [])
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
            n += 1
    counts["entries.jsonl"] = n

    # --- edges.csv --------------------------------------------------------
    counts["edges.csv"] = write_csv(
        out_dir / "edges.csv",
        ["source_entry_id", "source_headword", "source_volume", "ordinal",
         "raw_target", "raw_context", "status", "target_entry_id",
         "target_headword", "target_volume", "match_words", "redirect_hops",
         "suffix_stripped"],
        conn.execute("""
            SELECT r.entry_id,
                   COALESCE(s.headword_clean, s.headword), s.volume,
                   r.ordinal, r.raw_target, x.raw_context, r.status,
                   r.resolved_entry_id,
                   COALESCE(t.headword_clean, t.headword), t.volume,
                   r.match_words, r.redirect_hops, r.suffix_stripped
            FROM resolved_cross_references r
            JOIN entries s ON s.id = r.entry_id
            JOIN cross_references x
              ON x.entry_id = r.entry_id AND x.ordinal = r.ordinal
            LEFT JOIN entries t ON t.id = r.resolved_entry_id
            ORDER BY r.entry_id, r.ordinal"""))

    # --- lemmas.csv -------------------------------------------------------
    counts["lemmas.csv"] = write_csv(
        out_dir / "lemmas.csv",
        ["lemma_key", "lemma", "entry_id", "volume", "variant_type"],
        conn.execute("SELECT lemma_key, lemma, entry_id, volume, variant_type "
                     "FROM lemmas ORDER BY lemma_key, variant_type, entry_id"))

    # --- ambiguous.csv ----------------------------------------------------
    counts["ambiguous.csv"] = write_csv(
        out_dir / "ambiguous.csv",
        ["source_entry_id", "ordinal", "raw_target", "raw_context",
         "candidate_entry_id", "candidate_headword", "candidate_volume"],
        conn.execute("""
            SELECT c.entry_id, c.ordinal, r.raw_target, x.raw_context,
                   c.candidate_entry_id,
                   COALESCE(e.headword_clean, e.headword), e.volume
            FROM resolved_cross_reference_candidates c
            JOIN resolved_cross_references r
              ON r.entry_id = c.entry_id AND r.ordinal = c.ordinal
            JOIN cross_references x
              ON x.entry_id = c.entry_id AND x.ordinal = c.ordinal
            JOIN entries e ON e.id = c.candidate_entry_id
            ORDER BY c.entry_id, c.ordinal, c.candidate_entry_id"""))

    # --- MANIFEST.json ----------------------------------------------------
    status = dict(conn.execute(
        "SELECT status, COUNT(*) FROM resolved_cross_references GROUP BY status"))
    total_refs = sum(status.values())
    resolved = sum(v for k, v in status.items()
                   if k in ("same_volume", "cross_volume", "deinflected", "slash_half"))
    manifest = {
        "schema_version": SCHEMA_VERSION,
        "generated_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "source": "Enzyklopädie Philosophie und Wissenschaftstheorie, 8 volumes",
        "row_counts": counts,
        "entries_by_type": dict(conn.execute(
            "SELECT entry_type, COUNT(*) FROM entries GROUP BY entry_type")),
        "entries_by_volume": dict(conn.execute(
            "SELECT volume, COUNT(*) FROM entries GROUP BY volume")),
        "cross_references": {
            "total": total_refs,
            "by_status": status,
            "cleanly_resolved": resolved,
            "cleanly_resolved_share": round(resolved / total_refs, 4) if total_refs else 0,
        },
        "unreadable_chars_total": conn.execute(
            "SELECT SUM(unreadable_chars) FROM entries").fetchone()[0] or 0,
        "notes": [
            "Text fields come in pairs: *_raw / body_text is verbatim from "
            "extraction, *_clean has markup removed. U+FFFD marks a glyph the "
            "source PDF's font tables could not decode; it is preserved, never "
            "guessed at, and counted in unreadable_chars.",
            "In cleaned text '^x' was a superscript. It is AMBIGUOUS by nature: "
            "in a citation it is an edition number, in prose a mathematical "
            "exponent, and the source markup does not distinguish them.",
            "edges.csv includes unresolved references (empty target_entry_id) so "
            "the file is a complete account of the source's cross-references.",
            "Entries are never merged across volumes. Where several entries "
            "share a lemma they are distinct senses; see lemmas.csv and the "
            "lemma_conflicts view.",
        ],
    }
    (out_dir / "MANIFEST.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    conn.close()

    for name, n in counts.items():
        print(f"[export] {name:18s} {n:7,} rows")
    print(f"[export] MANIFEST.json      schema {SCHEMA_VERSION} -> {out_dir}")


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--db-path", default=str(DEFAULT_DB_PATH))
    ap.add_argument("--out", default=str(DEFAULT_OUT))
    args = ap.parse_args()
    export(Path(args.db_path), Path(args.out))


if __name__ == "__main__":
    main()
