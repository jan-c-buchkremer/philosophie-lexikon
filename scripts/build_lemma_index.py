"""Build the canonical cross-volume lemma index.

The work is eight ALPHABETICAL volumes, so a reference in Bd01 routinely
targets an entry in Bd05 and "find the entry named X" is a cross-volume
question every consumer of this dataset would otherwise have to solve for
itself. This writes that lookup once, as the `lemmas` table.

Entries are NOT merged. Where several entries share a lemma -- `Summe
(logisch)` / `(mathematisch)` / `(mengentheoretisch)` -- they are genuinely
distinct senses, and all of them are kept as separate rows. The
`lemma_conflicts` view lists such keys explicitly so the ambiguity is
visible rather than silently collapsed.

KEY DERIVATION IS IMPORTED, NOT REIMPLEMENTED. scripts/resolve_xrefs.py
already derives exactly these keys, and every rule in it encodes a bug
found the hard way (see ISSUES.md's resolver section): bare German
articles indexed under "das" produced 42 spurious edges; single-letter
first words magnetised 208 references onto "I Ching"; comma-delimited
prefixes were needed before "a priori" could resolve at all. A second,
independently written notion of "lemma" here would silently disagree with
the resolved edges this dataset ships alongside.

ORDERING: run after scripts/build_db.py, which recreates the whole file.
Safe to run before or after resolve_xrefs.py -- each only drops its own
tables.

Run via uv:
  uv run python scripts/build_lemma_index.py [--db-path structured-data/lexikon.db]
"""
import argparse
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from resolve_xrefs import (  # noqa: E402
    ARROW_RE,
    GERMAN_ARTICLES,
    build_index,
    cut_at_first_comma_or_paren,
    full_trim,
    normalize_key,
)

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DB_PATH = ROOT / "structured-data" / "lexikon.db"

SCHEMA = """
DROP VIEW IF EXISTS lemma_conflicts;
DROP TABLE IF EXISTS lemmas;

-- One row per (lemma spelling -> entry). A single entry contributes
-- several rows: its own lemma, each half of a slash compound, and the
-- natural-order form of an inverted headword.
CREATE TABLE lemmas (
    lemma_key    TEXT NOT NULL,   -- normalised: diacritic-folded, casefolded, parens dropped
    lemma        TEXT NOT NULL,   -- display form
    entry_id     TEXT NOT NULL REFERENCES entries(id),
    volume       TEXT NOT NULL,
    variant_type TEXT NOT NULL    -- primary | slash_half | comma_inverted | redirect_alias
);
CREATE INDEX idx_lemmas_key ON lemmas(lemma_key);
CREATE INDEX idx_lemmas_entry ON lemmas(entry_id);
CREATE INDEX idx_lemmas_variant ON lemmas(variant_type);

-- Lemma keys claimed by more than one entry as its PRIMARY name. These
-- are real distinct senses, not duplicates to be merged -- the view
-- exists so a consumer can see them rather than discover them.
CREATE VIEW lemma_conflicts AS
SELECT lemma_key, COUNT(*) AS n,
       GROUP_CONCAT(entry_id, ' | ') AS entry_ids
FROM lemmas WHERE variant_type = 'primary'
GROUP BY lemma_key HAVING COUNT(*) > 1;
"""


def comma_inverted(lemma: str) -> "str | None":
    """'Logik, algebraische' -> 'algebraische Logik'.

    Multi-word headwords are alphabetised with inverted word order per the
    front matter's own convention (structure-notes.md §4), so the natural
    reading order is a spelling a consumer will look for and the book never
    prints. Only applied to a two-part, comma-separated lemma whose second
    part is a single lowercase word -- i.e. an adjectival qualifier, not a
    biographical given name ('Biedermann, Gustav') or a longer phrase.
    """
    parts = [p.strip() for p in lemma.split(",")]
    if len(parts) != 2 or not parts[0] or not parts[1]:
        return None
    if " " in parts[1] or not parts[1][:1].islower():
        return None
    return f"{parts[1]} {parts[0]}"


def build(db_path: Path) -> None:
    conn = sqlite3.connect(str(db_path))
    conn.executescript(SCHEMA)

    # The resolver's own indexes, so the two agree by construction.
    first_word_index, lemma_index = build_index(conn)

    rows = []
    seen = set()

    def add(key, lemma, entry_id, volume, variant):
        if not key or not lemma:
            return
        if (key, entry_id, variant) in seen:
            return
        seen.add((key, entry_id, variant))
        rows.append((key, lemma, entry_id, volume, variant))

    entries = list(conn.execute(
        "SELECT id, volume, headword, COALESCE(headword_clean, headword), entry_type "
        "FROM entries"))

    for entry_id, volume, headword, headword_clean, entry_type in entries:
        lemma = full_trim(headword_clean)
        add(normalize_key(lemma), lemma, entry_id, volume, "primary")

        core = cut_at_first_comma_or_paren(headword_clean)
        if "/" in core:
            for half in (h.strip() for h in core.split("/")):
                words = half.split()
                if words and words[0].casefold() in GERMAN_ARTICLES:
                    half = " ".join(words[1:])
                if half:
                    add(normalize_key(half), half, entry_id, volume, "slash_half")

        inverted = comma_inverted(lemma)
        if inverted:
            add(normalize_key(inverted), inverted, entry_id, volume, "comma_inverted")

    # A redirect's lemma is also a usable name for the article it points at,
    # so record it against the FINAL target -- consumers can then look up
    # "anima" and land on "Seele" without re-implementing the redirect chase
    # that resolve_xrefs.py already performed.
    n_alias = 0
    for lemma, src_volume, target_id in conn.execute(
            "SELECT COALESCE(e.headword_clean, e.headword), e.volume, r.resolved_entry_id "
            "FROM entries e "
            "JOIN resolved_cross_references r ON r.entry_id = e.id AND r.ordinal = 0 "
            "WHERE e.entry_type = 'redirect' AND r.resolved_entry_id IS NOT NULL"):
        alias = full_trim(ARROW_RE.split(lemma)[0])
        if alias:
            add(normalize_key(alias), alias, target_id, src_volume, "redirect_alias")
            n_alias += 1

    conn.executemany(
        "INSERT INTO lemmas (lemma_key, lemma, entry_id, volume, variant_type) "
        "VALUES (?, ?, ?, ?, ?)", rows)
    conn.commit()

    counts = dict(conn.execute(
        "SELECT variant_type, COUNT(*) FROM lemmas GROUP BY variant_type"))
    conflicts = conn.execute("SELECT COUNT(*) FROM lemma_conflicts").fetchone()[0]
    distinct = conn.execute("SELECT COUNT(DISTINCT lemma_key) FROM lemmas").fetchone()[0]
    conn.close()

    print(f"[lemmas] {len(rows)} rows over {distinct} distinct keys")
    for k, v in sorted(counts.items()):
        print(f"           {k:16s} {v:6d}")
    print(f"[lemmas] {conflicts} keys claimed by >1 entry as primary "
          f"(distinct senses, kept separate) -> {db_path}")


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--db-path", default=str(DEFAULT_DB_PATH))
    args = ap.parse_args()
    build(Path(args.db_path))


if __name__ == "__main__":
    main()
