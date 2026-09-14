"""Resolve the raw cross-reference targets in structured-data/lexikon.db
into actual entry IDs, producing the interlinked citation graph that
docs/structure-notes.md §7 identifies as this project's primary target
artifact.

Input:  the `entries` and `cross_references` tables (built by
        scripts/build_db.py). `cross_references.raw_target` is a single
        word captured immediately after a cross-reference arrow (`›` in
        Bd01-06, `↑` in Bd07/08), deliberately unresolved.
Output: two new tables written back into the SAME database file,
        `resolved_cross_references` (one row per raw occurrence, always
        -- including the ones that don't resolve) and
        `resolved_cross_reference_candidates` (the tied candidate set,
        for the ambiguous ones only).

ORDERING HAZARD: scripts/build_db.py deletes and recreates the whole
database file on every run, which silently destroys this script's two
tables along with it. Always run this script AFTER build_db.py, and
re-run it after any build_db.py re-run.

Resolution follows the editors' own documented reference convention
(docs/ontology-notes.md §2 point 5, docs/structure-notes.md §7): an
arrow precedes only the FIRST word of a multi-word target headword, and
inflected forms are not distinguished in the reference itself. The
funnel below (same-volume -> cross-volume -> de-inflection ->
slash-compound halves -> redirect-chasing) was calibrated against the
full 83,695-row corpus before implementation; see the plan/ISSUES.md for
the measured yield of each stage.

Run via uv:
  uv run python scripts/resolve_xrefs.py [--only volume-substring]
      [--db-path structured-data/lexikon.db] [--max-chase-depth 3]
"""
import argparse
import re
import sqlite3
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "structured-data"
DEFAULT_DB_PATH = DATA_DIR / "lexikon.db"

SCHEMA = """
-- One row per raw cross-reference occurrence, 1:1 with cross_references
-- via (entry_id, ordinal) -- including unresolved ones, so "what
-- happened to xref #3 of entry X" is always a single lookup.
CREATE TABLE IF NOT EXISTS resolved_cross_references (
    entry_id            TEXT NOT NULL REFERENCES entries(id),
    ordinal             INTEGER NOT NULL,
    raw_target          TEXT NOT NULL,
    status              TEXT NOT NULL,
    resolved_entry_id   TEXT REFERENCES entries(id),
    match_key           TEXT NOT NULL,
    suffix_stripped     TEXT,
    redirect_hops       INTEGER NOT NULL DEFAULT 0,
    match_words         INTEGER NOT NULL DEFAULT 1,
    PRIMARY KEY (entry_id, ordinal)
);
CREATE INDEX IF NOT EXISTS idx_resolved_xref_entry_id ON resolved_cross_references(entry_id);
CREATE INDEX IF NOT EXISTS idx_resolved_xref_status ON resolved_cross_references(status);
CREATE INDEX IF NOT EXISTS idx_resolved_xref_target ON resolved_cross_references(resolved_entry_id);

-- Only populated for status='ambiguous': the full tied candidate set,
-- normalized out the same way cross_references/entry_flags are.
CREATE TABLE IF NOT EXISTS resolved_cross_reference_candidates (
    entry_id            TEXT NOT NULL,
    ordinal             INTEGER NOT NULL,
    candidate_entry_id  TEXT NOT NULL REFERENCES entries(id),
    FOREIGN KEY (entry_id, ordinal) REFERENCES resolved_cross_references(entry_id, ordinal)
);
CREATE INDEX IF NOT EXISTS idx_resolved_candidates_source
    ON resolved_cross_reference_candidates(entry_id, ordinal);
CREATE INDEX IF NOT EXISTS idx_resolved_candidates_target
    ON resolved_cross_reference_candidates(candidate_entry_id);
"""

# Folded on BOTH sides of every comparison. Beyond ordinary robustness,
# this is the deliberate mitigation for the open AdvGILLSBC headword-font
# diacritic bug (see ISSUES.md): some stored headwords have ä/ü (and
# ë/Ü, è/é) swapped by a font-CMap bug, while raw_target values -- which
# come from a different extraction path -- are encoded correctly, so an
# unfolded comparison silently misses otherwise-correct matches. Folding
# makes MATCHING robust to that; it does not fix the stored headword.
DIACRITIC_FOLD = str.maketrans({
    "ä": "a", "ö": "o", "ü": "u", "Ä": "A", "Ö": "O", "Ü": "U", "ß": "ss",
    "é": "e", "è": "e", "ê": "e", "ë": "e",
    "á": "a", "à": "a", "â": "a",
    "í": "i", "ì": "i", "î": "i", "ï": "i",
    "ó": "o", "ò": "o", "ô": "o",
    "ú": "u", "ù": "u", "û": "u",
    "ç": "c", "ñ": "n",
})

# Tried in this order; first one that yields candidates wins. Calibrated
# empirically (recovers ~6,500 otherwise-unmatched references); a full
# German morphological analyzer would add a few points more, with sharply
# diminishing returns.
SUFFIX_RULES = ["en", "er", "em", "es", "e", "n", "s"]
MIN_STEM_LEN = 3

# No redirect chain deeper than 2 hops exists in the corpus (measured);
# 3 is a safe ceiling that also guards against cycles in future data.
CHASE_MAX_DEPTH = 3

CUT_RE = re.compile(r"[,(]")

# Both per-volume spellings of the Verweispfeil (see ISSUES.md issue #5).
# A redirect entry's stored headword contains its whole one-line body --
# e.g. 'ens, ›Seiende,' or 'anima, ›Seele.' -- because the entry-tagger's
# anchor captured the full line. Everything from the arrow onward is the
# reference target, not part of the headword, so the tiebreak below has
# to cut there or no redirect could ever win it.
ARROW_RE = re.compile(r"[›↑]")

# A handful of headwords are article-initial in one half, e.g.
# 'absurd/das Absurde', 'wahr/das Wahre'. Indexing those under the bare
# article turns 'das' into a garbage attractor (measured: 42 spurious
# edges, all pointing at whichever article-headword happened to share the
# citing entry's volume). A bare article carries no referential
# information, so index the head noun instead and let a bare 'das' go
# unresolved -- for a citation graph a missing edge beats a wrong one.
GERMAN_ARTICLES = {"der", "die", "das", "den", "dem", "des"}

# Status precedence when more than one label could apply to a single
# resolution (documented in docs/schema.md).
STATUS_RESOLVED = ("same_volume", "cross_volume", "deinflected", "slash_half")


def fold_diacritics(text: str) -> str:
    return text.translate(DIACRITIC_FOLD)


def normalize_key(word: str) -> str:
    # Parentheses are dropped rather than kept: a disambiguating
    # parenthetical is now part of the stored lemma ('Summe (logisch)'),
    # but the sentence-side phrase arrives clipped by
    # prefixes_longest_first()'s rstrip -- 'Summe (logisch'. Removing the
    # brackets on both sides lets the two agree without either having to
    # guess where the qualifier ends.
    return " ".join(fold_diacritics(word).replace("(", " ")
                    .replace(")", " ").split()).casefold()


def cut_at_first_comma_or_paren(headword: str) -> str:
    """'Logik, algebraische (engl. ...' -> 'Logik, algebraische' is NOT
    what we want; we want everything before the first comma/paren, i.e.
    'Logik'. Used to derive the indexable core of a headword."""
    m = CUT_RE.search(headword)
    return (headword[: m.start()] if m else headword).strip()


def full_trim(headword: str) -> str:
    """The headword's lemma: what the printed book would list as the
    entry's name, with the extraction's trailing debris removed.

    Cuts at the arrow (a redirect's stored headword carries its whole
    body, see ARROW_RE), then strips trailing punctuation. It does NOT
    cut at the first comma -- there the comma introduces a genuine
    qualifier that IS part of the lemma ('Logik, algebraische' is its own
    headword, distinct from 'Logik').

    It no longer cuts at the opening paren either. That cut existed to
    drop an etymology ('Realität (engl. reality,'), but the headword is
    now the typesetter's own bold run, which never contains an etymology
    -- and DOES contain a disambiguating parenthetical, which is part of
    the lemma. Cutting there collapsed 'Summe (logisch)',
    '(mathematisch)' and '(mengentheoretisch)' into one indistinguishable
    lemma; 36 such collapses caused 48% of all ambiguity.

    'Logik'                                -> 'Logik'
    'Logik, algebraische'                  -> 'Logik, algebraische'
    'Summe (logisch)'                      -> 'Summe (logisch)'
    'ens, ›Seiende,'                       -> 'ens'
    'möglich/Möglichkeit'                  -> 'möglich/Möglichkeit'
    """
    m = ARROW_RE.search(headword)
    if m:
        headword = headword[: m.start()]
    return headword.strip().rstrip(",.;: ")


def prefixes_longest_first(context: str, max_words: int = 6) -> list:
    """Multi-word prefixes of a reference phrase, longest first.

    The editors mark only the first word of a multi-word lemma with an
    arrow, but the rest follows in the sentence -- '›Philosophie,
    praktische)' means the entry 'Philosophie, praktische'. We captured
    the phrase generously (see parse_entries.py), so it may overshoot
    into ordinary prose; trying longest-first and falling back is what
    makes over-capture harmless.

    Single-word prefixes are excluded: those are the bare-word case,
    which the first-word index handles with its own tiebreak rules.
    """
    tokens = context.split()[:max_words]
    out = []
    for n in range(len(tokens), 1, -1):
        candidate = " ".join(tokens[:n]).rstrip(",.;:) ")
        if candidate and " " in candidate:
            out.append(candidate)
    return out


@dataclass(frozen=True)
class Candidate:
    entry_id: str
    volume: str
    headword: str
    entry_type: str
    via_slash_half: bool


@dataclass
class ResolveResult:
    status: str
    resolved: "Candidate | None"
    candidates: list
    match_key: str
    suffix_stripped: "str | None"
    match_words: int = 1  # >1 == matched a multi-word lemma from context


def build_index(conn: sqlite3.Connection) -> "tuple[dict, dict]":
    """Build both target indexes, returning (first_word_index, lemma_index).

    ALWAYS built from every volume regardless of --only: a reference in
    one volume routinely targets a headword in another (measured: the
    single largest resolution gain of any stage), so the target index
    cannot be scoped down the way source rows can.

    The lemma index keys on the WHOLE headword lemma ('Philosophie,
    praktische'), which is what a captured reference phrase gets matched
    against before falling back to the first word alone.
    """
    index = defaultdict(list)
    lemma_index = defaultdict(list)
    for entry_id, volume, headword, entry_type in conn.execute(
        "SELECT id, volume, headword, entry_type FROM entries"
    ):
        # Index the lemma AND its comma-delimited prefixes. The entry
        # tagger's anchor cuts at the 2nd punctuation mark, so a stored
        # headword often carries the first words of the body along with
        # it ('a priori, fundamentaler Terminus' -- the lemma is really
        # just 'a priori'). Indexing only the whole string would make
        # such entries unreachable: 79 references to '›a priori' resolved
        # to nothing until prefixes were indexed too. Single-word
        # prefixes are skipped -- those belong to the first-word index,
        # which has its own base-entry tiebreak.
        lemma = full_trim(headword)
        chunks = [chunk.strip() for chunk in lemma.split(",")]
        seen_prefixes = set()
        for n in range(1, len(chunks) + 1):
            prefix = ", ".join(chunks[:n]).strip().rstrip(",.;: ")
            key = normalize_key(prefix)
            if " " in prefix and key not in seen_prefixes:
                seen_prefixes.add(key)
                lemma_index[key].append(
                    Candidate(entry_id, volume, headword, entry_type, False)
                )
        core = cut_at_first_comma_or_paren(headword)
        if "/" in core:
            # Slash-compound headwords ('abhängig/Abhängigkeit') are
            # referenceable from EITHER half within a sentence, per the
            # editors' own rule -- so index both halves separately. The
            # compound's own first "word" is the whole slash-joined
            # string, which no single-word raw_target would ever match.
            parts = [(p.strip(), True) for p in core.split("/") if p.strip()]
        else:
            parts = [(core, False)]
        for part, via_slash in parts:
            words = part.split()
            if words and words[0].casefold() in GERMAN_ARTICLES:
                words = words[1:]  # 'das Absurde' -> index under 'Absurde'
            if not words:
                continue
            if len(words[0]) <= 1:
                # Same attractor problem as the bare article: a
                # single-letter first word ('I Ching', 'a priori',
                # 'c-Funktion') magnetises every reference to that letter
                # as a logic symbol or numeral. Measured: 208 references
                # to a bare 'I'/'i' were landing on 'I Ching'. Such
                # headwords stay in the LEMMA index, so '›a priori' and
                # '›I Ching' still resolve via their full phrase; only a
                # bare single-letter reference goes unresolved, which is
                # correct -- those are the syllogistic judgment symbols,
                # which aren't tagged as entries at all (see ISSUES.md).
                continue
            index[normalize_key(words[0])].append(
                Candidate(entry_id, volume, headword, entry_type, via_slash)
            )
    return index, lemma_index


def exact_headword_matches(candidates: list, key: str) -> list:
    """Candidates whose headword proper IS the key -- i.e. the unqualified
    base entry ('Logik,') as opposed to its qualified siblings
    ('Logik, algebraische')."""
    return [c for c in candidates if normalize_key(full_trim(c.headword)) == key]


def pick(index: dict, key: str, volume: str) -> "tuple[Candidate | None, list]":
    """Choose a target for `key`, returning (winner_or_None, considered).

    Order matters and is deliberate:

    1. A GLOBAL exact-headword match wins outright, before any
       same-volume preference is applied. The editors' rule is that a
       reference to X resolves to the headword X (docs/ontology-notes.md
       §2 point 5) -- wherever that headword lives. Same-volume
       preference is only a disambiguator between otherwise-equal
       candidates; letting it run first actively HIDES the right answer.
       Measured: filtering to same-volume first made all 403 Bd05
       references to 'Logik' ambiguous, because Bd05 holds dozens of
       'Logik, X' qualified variants while the base entry 'Logik,' lives
       in Bd03. Every other volume resolved it correctly.
    2. Otherwise fall back to the same-volume subset (a real signal when
       two unrelated entries genuinely share a first word), and retry the
       exact-headword tiebreak within it.
    3. A single remaining candidate wins by default; anything else is
       ambiguous.
    """
    candidates = index.get(key, [])
    if not candidates:
        return None, []

    exact = exact_headword_matches(candidates, key)
    if len(exact) == 1:
        return exact[0], candidates

    same_volume = [c for c in candidates if c.volume == volume]
    scoped = same_volume if same_volume else candidates

    exact_scoped = exact_headword_matches(scoped, key)
    if len(exact_scoped) == 1:
        return exact_scoped[0], scoped
    if len(scoped) == 1:
        return scoped[0], scoped
    return None, scoped


def resolve_raw_target(
    raw_target: str,
    source_volume: str,
    index: dict,
    lemma_index: "dict | None" = None,
    context: "str | None" = None,
) -> ResolveResult:
    # Stage 0: the reference phrase as it appears in the sentence. A
    # qualified reference ('›Philosophie, praktische)') names its target
    # exactly, so an unambiguous full-lemma match beats anything the
    # first-word index could infer -- and rescues the references that
    # would otherwise be ambiguous purely because the bare first word is
    # shared by dozens of qualified siblings.
    if lemma_index and context:
        for phrase in prefixes_longest_first(context):
            phrase_key = normalize_key(phrase)
            winner, candidates = pick(lemma_index, phrase_key, source_volume)
            if winner is not None:
                status = ("same_volume" if winner.volume == source_volume
                          else "cross_volume")
                return ResolveResult(status, winner, candidates, phrase_key,
                                     None, len(phrase.split()))

    key = normalize_key(raw_target)
    winner, candidates = pick(index, key, source_volume)
    suffix_used = None

    if not candidates and "/" in raw_target:
        # A slash-compound headword ('objektiv/Objektivität') is indexed
        # under EACH half (build_index), because either half can be
        # referenced from a sentence. But the editors also write the
        # compound out in full after the arrow, and that whole string was
        # being looked up verbatim -- a key the index never holds. 2,969
        # references, 292 distinct targets, 98% of which have a half that
        # is an indexed headword. Try the halves, longest first, so
        # 'objektiv/Objektivität' prefers the noun it actually names.
        for half in sorted((h for h in raw_target.split("/") if h.strip()),
                           key=len, reverse=True):
            half_key = normalize_key(half)
            half_winner, half_candidates = pick(index, half_key, source_volume)
            if half_candidates:
                winner, candidates, key = half_winner, half_candidates, half_key
                break

    if not candidates:
        for suffix in SUFFIX_RULES:
            if raw_target.endswith(suffix) and len(raw_target) - len(suffix) >= MIN_STEM_LEN:
                stem_key = normalize_key(raw_target[: -len(suffix)])
                stem_winner, stem_candidates = pick(index, stem_key, source_volume)
                if stem_candidates:
                    winner, candidates = stem_winner, stem_candidates
                    key, suffix_used = stem_key, suffix
                    break

    if not candidates:
        return ResolveResult("unresolved", None, [], key, suffix_used)

    if winner is None:
        return ResolveResult("ambiguous", None, candidates, key, suffix_used)

    if suffix_used:
        status = "deinflected"
    elif winner.via_slash_half:
        status = "slash_half"
    elif winner.volume == source_volume:
        status = "same_volume"
    else:
        status = "cross_volume"

    return ResolveResult(status, winner, candidates, key, suffix_used)


def resolve_with_chase(
    raw_target: str,
    source_volume: str,
    index: dict,
    entry_type_by_id: dict,
    first_xref_by_id: dict,
    max_depth: int,
    lemma_index: "dict | None" = None,
    context: "str | None" = None,
) -> "tuple[ResolveResult, int]":
    """Resolve, then chase through redirect entries to the canonical
    article (the 'redirect chase', same idea as Wikipedia redirects).

    `status`/`match_key`/`suffix_stripped` describe how the ORIGINAL
    raw_target was matched; only `resolved` is advanced to the end of the
    chain. That keeps the status column meaningful (it characterises the
    reference string we actually had) while resolved_entry_id points at
    the article a reader would end up on.
    """
    result = resolve_raw_target(raw_target, source_volume, index,
                                lemma_index, context)
    if result.resolved is None:
        return result, 0

    final = result.resolved
    hops = 0
    visited = {final.entry_id}

    while (
        entry_type_by_id.get(final.entry_id) == "redirect"
        and hops < max_depth
    ):
        next_raw = first_xref_by_id.get(final.entry_id)
        if next_raw is None:
            break
        next_result = resolve_raw_target(next_raw, final.volume, index)
        if next_result.resolved is None or next_result.resolved.entry_id in visited:
            # Chase stalled (ambiguous/unresolved next hop) or would
            # cycle: keep the last successfully-resolved hop rather than
            # propagating the failure back onto the original edge.
            break
        final = next_result.resolved
        visited.add(final.entry_id)
        hops += 1

    return ResolveResult(result.status, final, result.candidates,
                         result.match_key, result.suffix_stripped,
                         result.match_words), hops


def resolve_all(db_path: Path, only: "str | None", max_depth: int) -> None:
    conn = sqlite3.connect(str(db_path))

    if only:
        # Incremental dev-iteration mode: keep other volumes' rows.
        conn.executescript(SCHEMA)
        conn.execute(
            "DELETE FROM resolved_cross_reference_candidates WHERE entry_id LIKE ?",
            (f"%{only}%",),
        )
        conn.execute(
            "DELETE FROM resolved_cross_references WHERE entry_id LIKE ?",
            (f"%{only}%",),
        )
    else:
        # Authoritative full run: rebuild these two tables from scratch.
        # NOTE: drops only OUR tables -- never the whole file, which
        # would take entries/cross_references with it.
        conn.executescript(
            "DROP TABLE IF EXISTS resolved_cross_reference_candidates;\n"
            "DROP TABLE IF EXISTS resolved_cross_references;\n" + SCHEMA
        )

    index, lemma_index = build_index(conn)
    entry_type_by_id = dict(conn.execute("SELECT id, entry_type FROM entries"))
    first_xref_by_id = dict(
        conn.execute(
            "SELECT entry_id, raw_target FROM cross_references WHERE ordinal = 0"
        )
    )

    if only:
        source_rows = conn.execute(
            "SELECT entry_id, ordinal, raw_target, raw_context FROM cross_references "
            "WHERE entry_id LIKE ? ORDER BY entry_id, ordinal",
            (f"%{only}%",),
        ).fetchall()
    else:
        source_rows = conn.execute(
            "SELECT entry_id, ordinal, raw_target, raw_context FROM cross_references "
            "ORDER BY entry_id, ordinal"
        ).fetchall()

    status_counts = Counter()
    edge_rows = []
    candidate_rows = []

    for entry_id, ordinal, raw_target, raw_context in source_rows:
        source_volume = entry_id.split(":")[0]
        result, hops = resolve_with_chase(
            raw_target, source_volume, index, entry_type_by_id,
            first_xref_by_id, max_depth, lemma_index, raw_context,
        )
        status_counts[result.status] += 1
        edge_rows.append((
            entry_id, ordinal, raw_target, result.status,
            result.resolved.entry_id if result.resolved else None,
            result.match_key, result.suffix_stripped, hops, result.match_words,
        ))
        if result.status == "ambiguous":
            for candidate in result.candidates:
                candidate_rows.append((entry_id, ordinal, candidate.entry_id))

    conn.executemany(
        "INSERT INTO resolved_cross_references (entry_id, ordinal, raw_target, "
        "status, resolved_entry_id, match_key, suffix_stripped, redirect_hops, "
        "match_words) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        edge_rows,
    )
    conn.executemany(
        "INSERT INTO resolved_cross_reference_candidates "
        "(entry_id, ordinal, candidate_entry_id) VALUES (?, ?, ?)",
        candidate_rows,
    )
    conn.commit()

    total = sum(status_counts.values())
    resolved = sum(status_counts[s] for s in STATUS_RESOLVED)
    matched = resolved + status_counts["ambiguous"]
    chased = sum(1 for row in edge_rows if row[7] > 0)
    via_lemma = sum(1 for row in edge_rows if row[8] > 1)
    conn.close()

    print(f"[resolve] {total} references processed")
    for status, count in sorted(status_counts.items(), key=lambda kv: -kv[1]):
        print(f"           {status:<14} {count:>6}  ({count / total:.1%})")
    print(f"           {'-' * 32}")
    print(f"           cleanly resolved {resolved:>6}  ({resolved / total:.1%})")
    print(f"           matched at all   {matched:>6}  ({matched / total:.1%})")
    print(f"           via full lemma   {via_lemma:>6}  (multi-word context match)")
    print(f"           redirect-chased  {chased:>6}")
    print(f"[resolve] done -> {db_path}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--only",
        help="only re-resolve references FROM source entries whose volume "
             "matches this substring (the target index is always global)",
    )
    ap.add_argument("--db-path", default=str(DEFAULT_DB_PATH))
    ap.add_argument("--max-chase-depth", type=int, default=CHASE_MAX_DEPTH)
    args = ap.parse_args()
    resolve_all(Path(args.db_path), args.only, args.max_chase_depth)


if __name__ == "__main__":
    main()
