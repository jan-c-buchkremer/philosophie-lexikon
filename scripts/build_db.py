"""Load structured-data/*.jsonl (scripts/parse_entries.py's output) into a
SQLite database as a queryable cache.

Per docs/pipeline-strategy.md strategy #9: this database is a disposable,
rebuildable artifact -- never hand-edited, always regenerable from the
JSONL + this script. Every run drops and recreates all tables from
scratch, so there is no migration story to maintain.

Uses SQLite rather than DuckDB (the strategy doc's original suggestion):
zero extra dependency (stdlib `sqlite3`), and the corpus is small enough
(a few MB of JSONL, ~4,300 entries) that DuckDB's install cost buys
nothing here. Revisit if/when the corpus grows enough that DuckDB's
columnar/analytical strengths would actually matter.

Run via uv:
  uv run python scripts/build_db.py [--only volume-substring] [--db-path structured-data/lexikon.db]
"""
import argparse
import json
import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "structured-data"
DEFAULT_DB_PATH = DATA_DIR / "lexikon.db"

SCHEMA = """
CREATE TABLE entries (
    id                  TEXT PRIMARY KEY,
    volume              TEXT NOT NULL,
    ordinal             INTEGER NOT NULL,
    headword            TEXT NOT NULL,
    pdf_page_start      INTEGER,
    pdf_page_end        INTEGER,
    printed_page_start  INTEGER,
    entry_type          TEXT NOT NULL,
    body_text           TEXT NOT NULL,
    werke_raw           TEXT,
    literatur_raw       TEXT,
    author_sigil        TEXT,
    -- Added by scripts/clean_text.py, strictly beside the raw columns
    -- above, never replacing them: markup removed, transliteration
    -- diacritics composed, U+FFFD preserved verbatim and counted in
    -- `unreadable_chars`. See docs/schema.md.
    headword_clean      TEXT,
    body_clean          TEXT,
    werke_clean         TEXT,
    literatur_clean     TEXT,
    lemma_key           TEXT,
    unreadable_chars    INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX idx_entries_volume ON entries(volume);
CREATE INDEX idx_entries_entry_type ON entries(entry_type);
CREATE INDEX idx_entries_headword ON entries(headword);
CREATE INDEX idx_entries_lemma_key ON entries(lemma_key);

-- Denormalized: one row per raw cross-reference occurrence, order
-- preserved via "ordinal". Deliberately UNRESOLVED here -- resolution is
-- scripts/resolve_xrefs.py's job (redirect-chasing, de-inflection,
-- cross-volume linking), out of scope for this cache.
--   raw_target  = the single word the arrow marks (the editors mark only
--                 the first word of a multi-word lemma).
--   raw_context = that word plus the rest of the reference phrase as it
--                 appears in the sentence ("Philosophie, praktische"),
--                 which is what makes qualified references resolvable.
CREATE TABLE cross_references (
    entry_id    TEXT NOT NULL REFERENCES entries(id),
    ordinal     INTEGER NOT NULL,
    raw_target  TEXT NOT NULL,
    raw_context TEXT NOT NULL
);
CREATE INDEX idx_xref_entry_id ON cross_references(entry_id);
CREATE INDEX idx_xref_raw_target ON cross_references(raw_target);

-- One row per (entry, flag) -- small closed vocabulary, see
-- scripts/parse_entries.py's flags comments for what each one means.
CREATE TABLE entry_flags (
    entry_id  TEXT NOT NULL REFERENCES entries(id),
    flag      TEXT NOT NULL
);
CREATE INDEX idx_entry_flags_entry_id ON entry_flags(entry_id);
CREATE INDEX idx_entry_flags_flag ON entry_flags(flag);
"""


def load_volume_records(stem: str) -> list[dict]:
    """Prefer the cleaned JSONL, fall back to the raw one.

    scripts/clean_text.py is additive -- its output is the raw records plus
    the `*_clean` fields -- so falling back just means those columns are
    NULL, and the fallback keeps this script runnable on a tree where the
    clean stage has not been run yet.
    """
    clean_path = DATA_DIR / f"{stem}_entries_clean.jsonl"
    path = clean_path if clean_path.exists() else DATA_DIR / f"{stem}_entries.jsonl"
    return [json.loads(line) for line in path.open(encoding="utf-8")]


def build(db_path: Path, only: "str | None") -> None:
    if db_path.exists():
        db_path.unlink()

    conn = sqlite3.connect(str(db_path))
    conn.executescript(SCHEMA)

    jsonl_paths = sorted(DATA_DIR.glob("Bd*_entries.jsonl"))
    total_entries = 0
    total_xrefs = 0
    total_flags = 0

    for path in jsonl_paths:
        stem = path.stem.removesuffix("_entries")
        if only and only not in stem:
            continue

        records = load_volume_records(stem)
        for r in records:
            conn.execute(
                "INSERT INTO entries (id, volume, ordinal, headword, "
                "pdf_page_start, pdf_page_end, printed_page_start, "
                "entry_type, body_text, werke_raw, literatur_raw, author_sigil, "
                "headword_clean, body_clean, werke_clean, literatur_clean, "
                "lemma_key, unreadable_chars) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (r["id"], r["volume"], r["ordinal"], r["headword"],
                 r["pdf_page_start"], r["pdf_page_end"], r["printed_page_start"],
                 r["entry_type"], r["body_text"], r["werke_raw"],
                 r["literatur_raw"], r["author_sigil"],
                 r.get("headword_clean"), r.get("body_clean"),
                 r.get("werke_clean"), r.get("literatur_clean"),
                 r.get("lemma_key"), r.get("unreadable_chars", 0)),
            )
            contexts = r.get("cross_references_context") or r["cross_references_raw"]
            for i, target in enumerate(r["cross_references_raw"]):
                conn.execute(
                    "INSERT INTO cross_references (entry_id, ordinal, raw_target, raw_context) "
                    "VALUES (?, ?, ?, ?)",
                    (r["id"], i, target, contexts[i]),
                )
            for flag in r["flags"]:
                conn.execute(
                    "INSERT INTO entry_flags (entry_id, flag) VALUES (?, ?)",
                    (r["id"], flag),
                )
            total_entries += 1
            total_xrefs += len(r["cross_references_raw"])
            total_flags += len(r["flags"])

        print(f"[db] loaded {stem}: {len(records)} entries")

    conn.commit()
    conn.close()
    print(f"[db] done: {total_entries} entries, {total_xrefs} cross-references, "
          f"{total_flags} flags -> {db_path}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", help="only load volumes whose stem contains this substring")
    ap.add_argument("--db-path", default=str(DEFAULT_DB_PATH))
    args = ap.parse_args()
    build(Path(args.db_path), args.only)


if __name__ == "__main__":
    main()
