# Pipeline strategy — the principles this project runs on

How the work is organised and why. For *what the data contains* see
`docs/schema.md` (shapes and rebuild order), `docs/atlas.md` (the map),
`docs/structure-notes.md` (document structure), `docs/ontology-notes.md`
(the editors' own stated intent — read that before designing further
extraction logic), and `ISSUES.md` (open issues and the bugs that produced
these rules).

## 1. The core tension

The goal is a structured, interlinked database built from all 8 volumes,
reached through a long sequence of structuring, cleaning, normalising and
graph-building steps. Two constraints shape how that work is organised:

- **Extraction is slow and RAM-constrained.** PDF parsing plus font
  patching over 600–900 pages takes ~6 minutes per volume, and the machine
  has ~5.8 GB with unpredictable headroom. Volumes must be processed one at
  a time, in separate processes. Check free memory *before* starting rather
  than after losing an hour — a full re-extraction has been OOM-killed
  three times with a browser open and run fine with it closed.
- **Most iteration is on *downstream* logic** — cleaning, normalisation,
  cross-reference resolution — not on extraction itself. Re-running full
  extraction to validate a one-line regex change in a later stage is
  wasteful.

Everything below optimises for cheap iteration on later stages without
re-paying extraction cost, while keeping every stage resumable per volume.

## 2. Working principles

1. **Staged pipeline with stable intermediate artifacts on disk.**
   PDF → tagged Markdown → structured JSONL → cleaned JSONL → resolved
   graph → database → dataset export → atlas. Each stage reads the
   previous stage's output from disk and writes its own. This is the
   highest-leverage decision in the project: it lets a later stage be rerun
   a hundred times while never touching the slow PDF stage again.

2. **Small-sample iteration, with one caveat.**
   Validate against curated page ranges before committing to a full run.
   **The caveat:** `pymupdf4llm.to_markdown()`'s heading *level* (`#` vs
   `##`) is not a per-page property — it depends on which other pages are
   in the same call. The same page yields `## A` in a 60-page call and
   `# A` in a 12-page slice. Anything sensitive to heading level must
   replicate the real `PAGE_BATCH` size and alignment. Logic keyed off raw
   PDF font spans (`page.get_text("dict")`) is unaffected and safe to
   sample at any size. See `ISSUES.md` settled lesson #5 for what happened
   when this was forgotten.

3. **Per-volume config tables, not hardcoded branches.**
   `VOLUME_OVERRIDES` holds headword font, body-start page and text
   conventions. `extract_markdown.py` and `parse_entries.py` keep
   *separate* tables on purpose: one holds PDF-font quirks (an extraction
   concern), the other Markdown-text conventions (a parsing concern).

4. **Provenance on every derived record**: volume + PDF page + printed
   page, carried through as `{volume}:{pdf_page}:{ordinal}`. Nearly free,
   and this corpus has enough extraction noise that jumping back to the
   exact source page is a recurring need.

5. **Keep the issues ledger honest.** Log deliberate gaps and their
   reasoning; don't silently resolve-and-forget. `ISSUES.md` is the memory
   that stops a fixed bug returning.

6. **"Volume" is the atomic unit through extraction and cleaning;
   cross-volume unification is one distinct, late stage.** Keeps every
   stage rerunnable one volume at a time, matching the RAM reality, and
   isolates cross-volume concerns (sigil collisions, edition differences,
   references crossing volumes) to a single place.

7. **CLI convention across scripts**: `--only <volume-substring>`,
   sample/dry-run modes. Cheap, and compounds — every script gets the
   "isolate and iterate fast" property by default.

8. **Golden/regression snapshots**, checked on every pipeline change:
   `check_golden.py`, `check_golden_xrefs.py`, `check_dataset.py`,
   `check_viz.py`. Each assertion corresponds to a real hazard this project
   has already been bitten by.

9. **The database is a disposable, rebuildable cache** — never hand-edited,
   always regenerable from JSONL plus pipeline code. `export/` is the
   artifact other tools consume.

10. **Schema docs per stage**, bumped when the shape changes, living next
    to the data they describe.

## 3. Two process lessons worth more than the fixes that produced them

**Remove a print artifact once, at extraction — don't tolerate it
repeatedly downstream.** Every early session was driven by a *symptom*: a
volume with zero markers, a wrong diacritic, a missing `Metaphysik`. A
symptom points at where it hurts, not where it originates, so each fix
landed downstream of the actual defect. Line-break hyphenation ended up
compensated for in three separate places — the anchor pattern dropping a
trailing hyphen, `strip_noise()` rejoining page-break splits, and
`rejoin_hyphenated_target()` rejoining them again — while thousands of
word-splitting hyphens survived into the stored text regardless.

**Check what your denominator is made of.** An early claim that "36%
unresolved is mostly irreducible" was wrong for a reason worth
remembering: it measured a denominator that was 27% quotation marks. The
residue after fixing that is genuinely irreducible — references to things
the encyclopedia does not lemmatise (proper names, foreign and
transliterated terms, formula fragments), plus Sanskrit transliterations
truncated at their combining diacritics.

## 4. Rebuild order and its one hazard

The full chain and its ordering hazard are documented in
`docs/schema.md`; the atlas stage on top of it in `docs/atlas.md`. The
hazard in one line: **`build_db.py` deletes and recreates the whole `.db`
file, taking both resolved tables with it — always run `resolve_xrefs.py`
last.**

## 5. What is next

The corpus is a clean citation graph and the atlas is built on it. The
open work is in `ISSUES.md`: the symbol-font corruption (open issue #1),
the cross-reference arrow (open issue #2), and the downstream items —
author-sigil resolution and bibliography parsing.
