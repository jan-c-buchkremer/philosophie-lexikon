# Schema — structured entry data

Covers the two artifacts `scripts/parse_entries.py` and
`scripts/build_db.py` produce. Bump this doc whenever either shape
changes. See `docs/pipeline-strategy.md` strategy #10.

## `structured-data/{volume}_entries.jsonl`

One JSON object per line, one line per dictionary entry.

| Field | Type | Nullable | Notes |
|---|---|---|---|
| `id` | string | no | `f"{volume}:{pdf_page_start:04d}:{ordinal:04d}"`. Stable per-record provenance key. |
| `volume` | string | no | PDF stem, e.g. `"Bd07_Re-Te"`. |
| `ordinal` | int | no | 1-indexed position within the volume, after split-headword-marker merging (contiguous, no gaps). |
| `headword` | string | no | Raw marker hint text (merge/emphasis-strip/whitespace-normalize only) — may look truncated, e.g. `"Realisierbarkeit, multiple (engl."`. Real cleanup is a later stage's job. |
| `pdf_page_start` / `pdf_page_end` | int | no | 1-indexed PDF page range the entry's text spans. |
| `printed_page_start` | int | yes | The book's own printed page number from the running header at `pdf_page_start`; null if unparseable/absent (~1-3% of pages per `structure-notes.md` §2). |
| `entry_type` | enum | no | `"biography"` \| `"subject_article"` \| `"redirect"` \| `"unknown"`. `"unknown"` is a deliberate conservative fallback, not a parse failure — see `ISSUES.md`'s "Structured entry parser" section for its known false-negative cases (flagship entries with a non-standard bibliography structure). |
| `body_text` | string | no | Prose only — `Werke:`/`Literatur:`/author-sigil content excluded, multi-page noise (running headers, letter-heading dividers) stripped. Markdown emphasis (`**`, `_..._`, `<sup>`) is left in as-is (raw). |
| `werke_raw` | string | yes | Raw text of the `Werke:` block, if present. |
| `literatur_raw` | string | yes | Raw text of the `Literatur:` block, if present. |
| `author_sigil` | string | yes | e.g. `"J. M."` or `"C. T./K. L."`; null = unsigned/editorial (`Redaktionsartikel` per `structure-notes.md` §4). |
| `cross_references_raw` | list[string] | no (may be empty) | The single word immediately following each cross-reference arrow — an opening `›` between arrow and word (`↑›Ich‹`) is skipped, not captured (body + werke + literatur combined), order-preserved, **not** deduplicated. **Unresolved** — resolution is `scripts/resolve_xrefs.py`'s job. |
| `cross_references_context` | list[string] | no (may be empty) | Index-aligned with the above: that word plus the rest of the reference phrase as it appears in the sentence (`"Philosophie, praktische"`). The editors mark only the *first* word of a multi-word lemma with an arrow, so this is what makes qualified references resolvable. |
| `flags` | list[enum] | no (may be empty) | Closed vocabulary: `split_headword_merged`, `heading_promoted`, `duplicate_heading_line_removed`, `short_span_uncertain`, `nonstandard_bibliography` (entry_type is `"unknown"` but a `Werkausgaben:`/`Titel:`/`Texte:`/`Darstellungen:` label was found — a flagship entry with a bespoke bibliography structure, see `docs/ontology-notes.md` §4, not a genuinely uncited entry). See `scripts/parse_entries.py` comments for what triggers each. |

## `structured-data/{volume}_entries_clean.jsonl`

Produced by `scripts/clean_text.py` from the JSONL above. **Strictly
additive**: every field of the raw record is copied through byte-identical
and the following are added beside them. That is what lets both golden
suites keep asserting exactly what they asserted before this stage existed
— if a raw field ever moves, `scripts/check_dataset.py` fails.

| Field | Type | Nullable | Notes |
|---|---|---|---|
| `headword_clean` | string | no | Markup removed, transliteration diacritics composed. |
| `body_clean` | string | no | Cleaned `body_text`. |
| `werke_clean` / `literatur_clean` | string | yes | Cleaned `werke_raw` / `literatur_raw`; null exactly when the raw field is. |
| `lemma_key` | string | no | Normalised key (`resolve_xrefs.normalize_key`): diacritic-folded, casefolded, parentheses dropped. Joins to `lemmas.lemma_key`. |
| `unreadable_chars` | int | no | Count of U+FFFD across the entry's three text fields. |

### What cleaning does, and what it deliberately does not

1. **Transliteration diacritics are composed.** The typesetter sets the
   combining mark after its base letter, and the two extraction paths spell
   it differently: `Bha<sup>¯</sup>vaviveka` in body text (via
   pymupdf4llm's reflow) but a bare `Bha¯vaviveka` in a headword (via the
   PDF font spans). Both become `Bhāvaviveka`. Also `Hı¯naya¯na` →
   `Hīnayāna` (the dotless `ı` is restored to `i` first, or NFC will not
   compose `ī`), `s´` → `ś`, `n˙` → `ṅ`, `Bochen´ski` → `Bocheński`.
   Applied **only directly after a letter**: measured across headwords,
   these marks occur 102 times after a letter and zero times anywhere else,
   which is what makes the rule safe. Marks not following a letter (464 in
   body text) are left alone.
2. **Superscripts become `^x`.** `Göttingen<sup>2</sup> 1958` →
   `Göttingen^2 1958`. **This stays ambiguous on purpose**: in a
   `Literatur:` citation `^2` is an edition number, in prose `x^2` is a
   mathematical exponent, and the source markup does not distinguish them
   (`structure-notes.md` §4). Resolving it needs context and belongs to a
   later stage.
3. **Emphasis is removed by PAIR matching, not character deletion.**
   `parse_entries.strip_emphasis()` deletes every `*` and `_`; that is
   correct for the headword comparisons it does and wrong here, because
   underscore is also notation in this corpus — a run of 2+ underscores is
   the argument blank of an Aussageform (`›__� P‹`), and `X^_ A` is a modal
   operator. Runs of 2+ underscores are therefore masked as atomic, and
   italics are stripped only on lines whose *remaining* underscores pair
   up. A line that still has an odd count is left completely alone.
4. **U+FFFD is never touched.** It marks a glyph the source PDF's font
   tables could not decode. It is preserved verbatim and counted; the check
   suite asserts the count is identical before and after cleaning. Every
   past attempt in this project to improve on an unreadable glyph produced
   silent corruption (`ISSUES.md` issues #6, #7, #9) — a visible gap beats
   a confident wrong letter.

## `structured-data/lexikon.db` (SQLite)

Rebuildable cache built from the JSONL by `scripts/build_db.py` — never
hand-edited; always regenerate via `uv run python scripts/build_db.py`
rather than migrating it.

### `entries`
One row per JSONL record, loaded from `*_entries_clean.jsonl` when it
exists and `*_entries.jsonl` otherwise (in which case the `*_clean`
columns are NULL). Carries every field of both sections above — the raw
ones and the cleaned ones side by side — minus `cross_references_raw` and
`flags`, which are normalized into their own tables below. `id` is the
primary key; `lemma_key` is indexed and joins to `lemmas`.

### `cross_references`
One row per raw cross-reference occurrence (denormalized from
`cross_references_raw`).

| Column | Type | Notes |
|---|---|---|
| `entry_id` | text | FK to `entries.id`. |
| `ordinal` | int | Position within the entry's own list (order-preserving). |
| `raw_target` | text | The single word the arrow marks. Unresolved. |
| `raw_context` | text | That word plus the rest of the reference phrase as it appears in the sentence (`"Philosophie, praktische"`). The editors mark only the *first* word of a multi-word lemma with an arrow, so this is what makes qualified references resolvable — matching on `raw_target` alone left ~9,500 references ambiguous that the source states explicitly. Equals `raw_target` when nothing followed. |

### `entry_flags`
One row per `(entry, flag)` pair (normalized from `flags`).

| Column | Type | Notes |
|---|---|---|
| `entry_id` | text | FK to `entries.id`. |
| `flag` | text | One of the closed-vocabulary values above. |

### `resolved_cross_references`
Written by `scripts/resolve_xrefs.py` (**not** `build_db.py` — see the
ordering hazard below). Exactly one row per `cross_references` row,
sharing its `(entry_id, ordinal)` key, **including references that did
not resolve** — so "what happened to reference #3 of entry X" is always a
single lookup rather than an existence check across two tables.

| Column | Type | Notes |
|---|---|---|
| `entry_id` | text | FK to `entries.id` — the *citing* entry. |
| `ordinal` | int | Together with `entry_id`, the primary key; matches `cross_references.ordinal`. |
| `raw_target` | text | Denormalized copy of the raw string, so common queries need no join. |
| `status` | text | See vocabulary below. |
| `resolved_entry_id` | text, nullable | The *cited* entry. NULL iff status is `ambiguous` or `unresolved`. For a redirect chase, this is the **final** article, not the redirect. |
| `match_key` | text | The normalized key that actually matched (post diacritic-fold, casefold, and any suffix-strip). |
| `suffix_stripped` | text, nullable | The de-inflection suffix removed (`en`/`n`/`s`/…), or NULL if none was needed. |
| `redirect_hops` | int | How many redirect hops were followed (0 = the first match was already a real article). |
| `match_words` | int | How many words of the reference phrase matched. `1` = matched on the bare arrow-marked word via the first-word index. `>1` = matched a full headword lemma from `raw_context` (`"Logik, algebraische"`), which is both more specific and more trustworthy. |

`status` vocabulary:

| status | meaning |
|---|---|
| `same_volume` | matched directly, target in the citing entry's own volume |
| `cross_volume` | matched directly, target in a different volume |
| `deinflected` | required suffix-stripping to find any candidate |
| `slash_half` | matched via one half of a slash-compound headword (`möglich/Möglichkeit`) |
| `ambiguous` | 2+ candidates survived the tiebreak; nothing guessed, all candidates recorded in the side table |
| `unresolved` | no candidate found at any stage |

Resolution is attempted in this order: full-lemma match from
`raw_context` (longest phrase first) → bare first word → de-inflected
first word. `status` records the *scope/method* of whichever stage
succeeded; `match_words` tells you whether it was the lemma stage.

When more than one label could apply, precedence is
`slash_half` > `deinflected` > `cross_volume` > `same_volume`. Note that
`status` describes **how the reference string was matched**, while
`resolved_entry_id` points at the **end of any redirect chain** — so a
`same_volume` row can legitimately have a target in another volume if the
chase crossed one. Check `redirect_hops > 0` to spot those.

### `resolved_cross_reference_candidates`
Only populated for `status = 'ambiguous'` — the full tied candidate set,
normalized out the same way `cross_references`/`entry_flags` are.

| Column | Type | Notes |
|---|---|---|
| `entry_id` | text | With `ordinal`, FK to the `resolved_cross_references` row. |
| `ordinal` | int | |
| `candidate_entry_id` | text | FK to `entries.id`. One row per candidate. |

### `lemmas`
Written by `scripts/build_lemma_index.py` (after `build_db.py`). The
canonical cross-volume index: the work is eight *alphabetical* volumes, so
"find the entry named X" is inherently a cross-volume question, and this
answers it once instead of in every consumer.

| Column | Type | Notes |
|---|---|---|
| `lemma_key` | text | Normalised form; the join key. |
| `lemma` | text | Display spelling. |
| `entry_id` | text | FK to `entries.id`. |
| `volume` | text | Volume the spelling came from. |
| `variant_type` | text | `primary` \| `slash_half` \| `comma_inverted` \| `redirect_alias` |

One entry contributes several rows:

- `primary` — its own lemma. Exactly one per entry (asserted).
- `slash_half` — each half of `möglich/Möglichkeit`, which the editors
  allow to be referenced from either side.
- `comma_inverted` — the natural-order form of an inverted headword
  (`Logik, algebraische` → `algebraische Logik`). The book alphabetises by
  inversion (`structure-notes.md` §4) and never prints this spelling, but
  it is the one a reader looks for.
- `redirect_alias` — a redirect's own name, recorded against the article it
  finally points at, so `anima` finds `Seele` without re-running the chase.

Key derivation is **imported from `scripts/resolve_xrefs.py`**, not
restated: each of its rules (bare-article exclusion, single-letter
exclusion, comma-prefix indexing) encodes a bug found the hard way, and a
second implementation would silently disagree with the edges shipped
alongside it.

Entries are **never merged**. 61 keys are claimed as `primary` by more than
one entry — `Summe (logisch)` / `(mathematisch)` / `(mengentheoretisch)` —
and those are genuine distinct senses. The `lemma_conflicts` view lists
them so the ambiguity is visible rather than discovered.

## `export/` — the dataset artifact

Produced by `scripts/export_dataset.py`. The database is a rebuildable
cache; **this** is what other tools are meant to consume. JSONL and CSV
only — Parquet would mean adding `pyarrow`, and this project has held a
zero-dependency line throughout.

| File | Contents |
|---|---|
| `entries.jsonl` | One record per entry: provenance, type, flags, raw **and** cleaned text. |
| `edges.csv` | The citation graph, one row per reference **including unresolved ones** (empty `target_entry_id`), so the file is a complete account of the source's cross-references rather than a filtered success list. Headwords are denormalised in, so the file stands alone. |
| `lemmas.csv` | The canonical lemma index. |
| `ambiguous.csv` | Every ambiguous reference with its full candidate set — the resolver records candidates and never guesses. |
| `MANIFEST.json` | Schema version, generation timestamp, per-file row counts, entry/status breakdowns, and the caveats above. |

`scripts/check_dataset.py` verifies all of it: markup gone, U+FFFD counts
preserved, cleaning idempotent, raw fields unmoved, lemma coverage
complete, graph referential integrity, and export counts matching the
database.

### Rebuild order

```
scripts/derive_cmaps.py     -> scripts/font_cmaps.json      (rarely; see below)
scripts/extract_markdown.py -> md-data/*.md                 (slow: ~6 min/volume)
scripts/parse_entries.py    -> structured-data/*_entries.jsonl
scripts/clean_text.py       -> structured-data/*_entries_clean.jsonl
scripts/build_db.py         -> structured-data/lexikon.db
scripts/resolve_xrefs.py    -> resolved_* tables in that same .db
scripts/build_lemma_index.py-> lemmas table + lemma_conflicts view
scripts/export_dataset.py   -> export/
```

Then the three check suites: `check_golden.py`, `check_golden_xrefs.py`,
`check_dataset.py`.

**Ordering hazard**: `build_db.py` deletes and recreates the whole `.db`
file on every run, which silently takes both resolved tables with it.
**Always run `resolve_xrefs.py` last**, and re-run it after any
`build_db.py` re-run. `resolve_xrefs.py` itself only ever drops its own
two tables, never the file.

`scripts/font_cmaps.json` is **generated data, committed to the repo**:
per-volume, per-exact-font byte→character tables that repair the PDFs'
broken ToUnicode CMaps, derived empirically from the corpus (see
`ISSUES.md` issue #7 for why anything keyed more coarsely than
(volume, exact font name) is unsound). It only needs regenerating if the
reference font's mapping changes or new volumes are added — it is not
part of a normal rebuild. Review it as a diff; a surprising change there
means the derivation's evidence shifted.

### Example queries

```sql
-- entries per volume/type
SELECT volume, entry_type, COUNT(*) FROM entries GROUP BY volume, entry_type;

-- most-referenced raw cross-reference targets
SELECT raw_target, COUNT(*) c FROM cross_references GROUP BY raw_target ORDER BY c DESC LIMIT 20;

-- headword lookup
SELECT id, headword, entry_type FROM entries WHERE headword LIKE 'Kant,%';

-- resolution outcome breakdown
SELECT status, COUNT(*) FROM resolved_cross_references GROUP BY status ORDER BY 2 DESC;

-- most-cited entries (the actual citation graph's hubs)
SELECT e.headword, COUNT(*) c
FROM resolved_cross_references r JOIN entries e ON e.id = r.resolved_entry_id
GROUP BY r.resolved_entry_id ORDER BY c DESC LIMIT 20;

-- what does entry X cite, and did it resolve?
SELECT r.raw_target, r.status, e.headword
FROM resolved_cross_references r LEFT JOIN entries e ON e.id = r.resolved_entry_id
WHERE r.entry_id = 'Bd04_Ins-Loc:0165:0111' ORDER BY r.ordinal;

-- the ambiguous cases most worth disambiguating by hand
SELECT raw_target, COUNT(*) c FROM resolved_cross_references
WHERE status = 'ambiguous' GROUP BY raw_target ORDER BY c DESC LIMIT 20;
```
