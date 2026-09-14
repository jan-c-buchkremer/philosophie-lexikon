# Structure Notes — Enzyklopädie Philosophie und Wissenschaftstheorie

Working notes on the PDF→Markdown conversion and the document structure of the
encyclopedia, for use when designing the next processing step (entry
extraction / parsing). Written against `Bd01_A-B.md`, `Bd02_C-F.md`,
`Bd03_G-Inn.md` (3 of 8 volumes converted so far; extraction is ongoing via
`scripts/extract_markdown.py`).

## 1. Source & pipeline

- 8 volume PDFs in `pdf-data/`, produced via 3B2/Arbortext.
- `scripts/extract_markdown.py` patches a font-encoding bug in-memory (via
  `pikepdf`) before running `pymupdf4llm.to_markdown(..., page_chunks=True)`:
  German/French diacritics in the Latin-text font family (`AdvMIN`,
  `AdvMINB`, `AdvMINI`, `AdvGILLSBC`, `MinionPro-Regular`, ...) are mapped to
  wrong or missing Unicode codepoints in the embedded `/ToUnicode` CMaps.
  See `CMAP_OVERRIDES` in the script for the fix table.
- **Known residual gap:** a handful of instances (mostly "à" in French/
  Italian bibliography citations) use raw byte `0x0D` (carriage return) as
  glyph code, deliberately left unpatched (0x0D is also a genuine line
  break in the source, so patching it would break paragraph structure more
  than it fixes). These surface as literal `U+FFFD` in the output.
  Residual counts: Bd01 ≈ 2975, Bd02 ≈ 2556, Bd03 ≈ 3221 occurrences.
  A future targeted pass could disambiguate by position (mid-word vs. real
  line break).
- No images are extracted — figure captions (e.g. "Römische Rechentafel,
  aus: K. Menninger, ...") survive as plain text, but the image itself does
  not end up in the Markdown (`![...]` count = 0 across all volumes).

## 2. Markdown conventions already in place

- `<!-- page:N -->` marks every PDF page (1-indexed), 100% coverage. This is
  the only fully reliable position anchor currently in the file.
- Document-level headings (real Markdown headings, produced by
  pymupdf4llm's bold/font-size heuristic):
  - `# TITLE` — title page only.
  - `### Vorwort ...`, `#### ...`, `##### ...` — preface and abbreviation
    front matter (author sigils table, reference-work abbreviations,
    journal/serial abbreviations, single-work abbreviations for e.g.
    Goethe, Kant, Leibniz, Marx/Engels, Nietzsche, Schelling, Aristoteles).
  - `## <Letter>` — exactly one per alphabetic section, reliably detected
    (e.g. Bd01: `## A` @ PDF p.25, `## B` @ p.360; Bd02: `## C` @ p.19,
    `## D` @ p.122, `## E` @ p.290, `## F` @ p.485; Bd03: `## G` @ p.19,
    `## H` @ p.267, `## I` @ p.513).
  - Front-matter tables (author sigils, reference works) are emitted as
    proper Markdown pipe tables.
- **Per-page running header noise:** on ~97–99% of body pages, the line(s)
  immediately following the `<!-- page:N -->` marker are the page's running
  header — a short "current headword" line, followed by a line that is
  purely the *printed* page number of the book (this numbering restarts at
  the start of the dictionary body and is distinct from the PDF page
  number). Detected pattern: short line (≤4 words, no terminal
  punctuation) + a line matching `^\d{1,4}$`. Present on 577/584 pages
  (Bd01), 603/618 (Bd02), 634/638 (Bd03) — the misses are mostly front
  matter / section-opening pages without a running header. Should be
  stripped (or captured separately as the citable page number) before any
  downstream text analysis.

## 3. THE key open problem: entry (article) boundaries are not reliably marked

- pymupdf4llm's bold-detection heuristic only promotes a paragraph to a
  heading (`#####`) when the *entire* paragraph block is bold in the
  source. This happens to catch short **cross-reference-only entries**
  (e.g. `Cauchy-Folge, ›Folge (mathematisch).`) — 65–90 such headings per
  volume, of which roughly 55–65% are clearly redirect-style (contain
  `›` or a comma-separated redirect gloss).
- It does **not** catch full articles, because there only the headword
  (first word or two) is bold/differently-fonted — the rest of the long
  paragraph is regular body text, so pymupdf4llm keeps the whole block as
  plain paragraph text. Full articles are therefore **invisible as
  structure** in the current Markdown; they start mid-paragraph,
  indistinguishable from continuing prose without further processing.
- A small number of `#####` headings (6–13 per volume) are **false
  positives**: bold-set mathematical formulas that happen to fill an
  entire paragraph block. Detectable heuristically by very low
  letter-to-total-character ratio.
- Rough lower-bound proxy for article count per volume, via counting
  `Literatur:` / `Werke:` occurrences (most full articles — but not all
  short/cross-reference entries — carry one or both):
  - Bd01 (A–B): `Literatur:` ×538, `Werke:` ×214
  - Bd02 (C–F): `Literatur:` ×566, `Werke:` ×181
  - Bd03 (G–Inn): `Literatur:` ×424, `Werke:` ×146
  Real entry count (including redirects) is higher.

### Confirmed fix available if/when needed

Verified directly against the PDF via `page.get_text("dict")`: headwords are
set in a **dedicated font, `AdvGILLSBC`** (a sans/grotesque face), clearly
distinct from the body serif font `AdvMIN` (and from `AdvMINI` = italic,
`AdvMINB` = bold serif used e.g. for the punctuation right after a
headword). This is a 100%-reliable, position-independent signal for entry
start, unlike anything derivable from the current Markdown text alone.

- The *same* font/size also appears in the per-page running header (at a
  distinct, near-top y-position on the page) — so a naive "font ==
  AdvGILLSBC" filter without a position/first-in-block check will produce
  duplicates (one hit for the header word, one for the real headword).
- To use this: extend `extract_markdown.py` to do a parallel
  `get_text("dict")` pass per page, identify `AdvGILLSBC` runs that start a
  paragraph/body block (excluding the near-top-of-page running header
  region), and inject an explicit marker before them in the emitted
  Markdown, e.g. `<!-- entry:Abaelard, Peter -->`, mirroring the existing
  `<!-- page:N -->` convention. This was scoped but **not implemented**
  (user chose "analysis only" for now) — worth doing before converting the
  remaining 5 volumes, since redoing already-finished volumes later is more
  expensive than building it in now.
- Cheaper fallback without touching the PDF again: regex heuristics on the
  existing Markdown (capitalized word(s) at paragraph start, followed by
  `(lat./griech./engl. ...)` etymology or a `*<place> <date>, †<place>
  <date>` biography pattern, previous paragraph ending in an author sigil
  or `Literatur:` citation list). Considered but rejected as first choice
  — will have both false positives (proper names mid-sentence) and false
  negatives (entries with no such intro pattern).

## 4. Other structural signals worth keeping for downstream parsing

- **Author sigils**: most articles end with a 2–6 character initial code
  (e.g. `P. S.`, `C. T.`, `O. S.`, multi-author as `C. T./K. L.`), resolved
  via the "1. Autoren" table in the front matter (name + affiliation per
  volume — note the same sigil can map to different people across volumes,
  the table must be re-read per volume). Unsigned paragraphs are editorial
  ("Redaktionsartikel") per the front matter's own explanation (§ II.8).
  This is a second, independent signal for "where does an article end".
- **Cross-reference arrows** `›` (U+203A) mark every internal link to
  another headword — very dense (~10,000 occurrences per volume). Useful
  for building a citation/reference graph between entries later.
- **Redirect phrasing** besides the bare-arrow form also includes explicit
  `..., synonym zu ›X.` (5 occurrences in Bd01) — a distinct sub-type of
  cross-reference entry worth handling separately from plain redirects.
- **Bibliographic abbreviations** used throughout `Literatur:`/`Werke:`
  blocks resolve against front-matter abbreviation tables: reference works
  (`FM`, `LMA`, `REP`, `DSB`, `TRE`, `Enc. Ph.`, `Hist. Wb. Ph.`, etc.),
  single works (Goethe/Kant/Leibniz/Marx-Engels/Nietzsche/Schelling/
  Aristoteles editions), and journals — each volume repeats its own copy of
  these tables in the front matter, so any citation-resolution step needs
  per-volume lookup tables, not a single global one.
- **Superscript markup** (`<sup>...</sup>`, 773 occurrences in Bd01) is used
  both for edition numbers in citations (e.g. "Göttingen`<sup>2</sup>`
  1958" = 2nd edition) and for mathematical/logical exponents — these two
  uses are not distinguishable by markup alone and need contextual
  disambiguation if superscripts are semantically parsed later.
- Multi-word headwords are alphabetized with **inverted word order** for
  noun+adjective compounds per the front matter's own stated convention
  (e.g. `Algebra, polyadische` sorts under "Algebra"), which any
  alphabetical-order-dependent logic must account for.

## 4b. Front matter also includes a logic/math symbol glossary

Beyond the abbreviation tables listed in §4, the front matter has a
"6. Abkürzungen" (general abbreviations) and "7. Logische und mathematische
Symbole" section — a glossary mapping every logic/math glyph used in the
body text (quantifiers, modal operators, connectives, etc.) to its spoken
name (e.g. "affirmative Kopula 'ist'", "Allquantor 'für alle x gilt'").
This is the key to interpreting the glyph-encoded formulas scattered through
articles (see §3's "false positive formula headings").

**Known extraction artifact:** this section (and the general-abbreviations
section next to it) was originally laid out as two side-by-side columns in
the PDF. pymupdf4llm's linear reading order interleaves the two columns'
lines, so the extracted text is a jumbled run of abbreviation-entry and
symbol-entry fragments rather than two clean lists. Needs either a
column-aware re-extraction or manual/regex reconstruction if this glossary
is needed as structured data later.

## 6. Content-level entry taxonomy

What kinds of entries and information actually appear inside the
dictionary body (as opposed to the front matter apparatus described
above). Observed by sampling across Bd01–03; all counts/examples are from
those three volumes.

1. **Biographical entries (Personenartikel)** — headword is
   `Surname, Firstname`, immediately followed by
   `*<place> <date>, †<place> <date>, <nationality> + <profession/role>`,
   then a prose biography, closed with **`Werke:`** (chronological,
   primary works — original + later editions, edition numbers as
   `<sup>2</sup>` etc.) and **`Literatur:`** (alphabetical secondary
   literature). Examples: Abaelard, Abano, Abbagnano — this pattern holds
   across every letter sampled.
2. **Subject/concept entries (Sachartikel)** — no biographical dates.
   Typically opens with etymology in parentheses (`griech.`, `lat.`,
   often plus an `engl.` gloss), then historical + systematic discussion,
   closes with `Literatur:` only (no `Werke:` — nothing personal to list).
   Can run very long, spanning many printed pages and repeated running
   headers (e.g. "Dialektik", "Bewußtsein"). Notably: **no internal
   enumeration** (no `1./2.` or `I./II.` substructure the way the preface
   itself uses) — long articles are continuous prose, not sectioned.
3. **Redirect / cross-reference-only entries** — short headword-only
   entries pointing to the canonical article: `X, ›Y.` (65–90 per volume;
   the only entries pymupdf4llm's own heading heuristic reliably catches,
   see §3). A distinct explicit sub-form exists: `X, synonym zu ›Y.`
   (rare — 5× in Bd01).
4. **Compound/qualified sub-lemmas** — multi-word headwords with
   **inverted word order** for alphabetization (e.g. `Algebra,
   polyadische`, `Alembertsches Prinzip`) — usually a specialized variant
   of a broader concept, often itself resolving as a redirect to the main
   article.
5. **Symbol/notation entries** — a small distinct category: entries about
   individual letters/symbols of the logical notation itself, not about a
   concept named by a word — e.g. the entry "a" (the traditional-syllogistic
   universally-affirmative judgment type, `PaQ`).
6. **Embedded formulas** — logical/mathematical notation inline within
   articles (quantifiers, connectives, modal operators), rendered via
   dedicated symbol fonts (`AdvSY`, `AdvP4C4E*`, `AdvOLDGR*`). Resolvable
   via the front matter's "7. Logische und mathematische Symbole" glossary
   (see §4b), but prone to `U+FFFD` encoding noise and occasional
   false-positive heading promotion (see §3).
7. **Foreign-language equivalents** — per the front matter's own stated
   editorial policy (§ II.4 of the preface), English/French equivalents
   are given parenthetically where terminologically relevant, especially
   for philosophy-of-science headwords, e.g. `(engl. picture)`,
   `(engl. derivation)`.
8. **Figures/illustrations** — occasional referenced images (e.g. an
   abacus woodcut illustration for "Abacus"); the caption text survives,
   the image itself is currently lost in extraction (see §1).
9. **Author attribution** — every article ends either with an
   **author sigil** (2–6 characters, e.g. `P. S.`; co-authored as
   `C. T./K. L.`), resolved against the front matter's "1. Autoren" table
   (name + affiliation — note the table is per-volume, the same sigil can
   denote different people in different volumes), or is unsigned, which
   per the preface (§ II.8) explicitly means **Redaktionsartikel**
   (editorial, unattributed). This is a second, text-independent signal
   for locating article ends.
10. **Bibliographic apparatus** — `Werke:`/`Literatur:` blocks cite
    consistently via the controlled abbreviations described in §4
    (reference works, journals, standard author editions), which must be
    resolved per-volume.

## 7. ★ Citation / cross-reference graph — primary target for downstream use

This is the most promising structured artifact hiding in the text, and the
main reason entry-boundary detection (§3) matters: **every internal link
between headwords is already marked** in the source, via the
Verweispfeil `›` (U+203A), at very high density — **~10,000 occurrences per
volume**. Roughly:

- `grep -o '›' Bd01_A-B.md | wc -l` → 10,036
- (Bd02/Bd03 counts not yet taken, expect similar order of magnitude)

**Bd07/Bd08 use a different glyph for the same feature**: `↑` (U+2191,
upward arrow), not `›` — their own house convention, confirmed via direct
font inspection (was briefly mis-decoded as `≠` due to a font CMap bug,
now fixed; see `ISSUES.md`). Any cross-reference extraction must check
the volume's arrow character (`scripts/parse_entries.py`'s
`VOLUME_OVERRIDES["xref_arrow"]`), not assume `›` universally.

What a `›`-arrow means, structurally (per preface § II.5):

- The arrow precedes the *first word* of the target headword. If the
  target is a multi-word headword, only the first word is arrow-marked —
  the rest of the compound term follows as plain text (e.g. `›Algebra der
  Logik` links to the full lemma "Algebra der Logik", not just "Algebra").
- If that compound doesn't exist as its own headword, the reference
  resolves to the headword formed by the first word alone, with the
  compound concept handled as a subsection of that broader entry (e.g.
  `›causa sui` → entry "causa" [or wherever "causa sui" is actually
  discussed under]).
- Inflected forms are not distinguished in the reference itself (e.g.
  `›Kalküle`, `›Kalkülen` both mean "look up Kalkül") — so resolving a
  `›`-target to an actual headword will sometimes require de-inflecting
  the word that follows the arrow, not just string-matching it.
- Compound double-headwords made of adjective+noun (e.g.
  `transitiv/Transitivität`) can be referenced from *either* half within a
  sentence.

**To build the graph you need, in order:**

1. Reliable entry/headword boundaries (§3 — the `AdvGILLSBC`-font
   detection is the robust path; still not implemented).
2. For every `›` occurrence: capture the word(s) immediately following it
   up to the next word boundary/punctuation as the raw reference target
   string.
3. A **normalization/resolution step** mapping raw reference strings to
   actual headword IDs — handling: first-word-only compound references,
   inflected forms, the noun/adjective either-half rule above, and
   redirect entries (a `›`-target may itself be a pure-redirect headword,
   in which case you likely want to resolve through it to the canonical
   article — a "redirect chase", same idea as Wikipedia redirects).
4. Cross-volume resolution: since the work is split A–B / C–F / G–Inn /
   ..., a `›`-reference in Bd01 can point to a headword that only exists
   in Bd02 or later — the graph is inherently cross-volume and can only be
   fully resolved once *all 8* volumes are converted and indexed.

Net effect: once entries are tagged, this is a directed graph with edges
close to the ~10,000/volume raw-arrow count (many will collapse together
once redirects and inflections are resolved) — likely on the order of tens
of thousands of edges across the full 8-volume work. Worth treating as a
first-class deliverable of the parsing step, not a byproduct.

## 8. Suggested next steps

1. ~~Implement `AdvGILLSBC`-based entry-tagging~~ — **done**, see
   `find_entry_candidates`/`inject_entry_markers` in `extract_markdown.py`.
   Works well on Bd01/02/03/06 (91–74% of raw font-detected candidates
   successfully tagged, near-zero false positives). **Currently broken on
   Bd04/05/07/08 — see `ISSUES.md` for the full diagnosis** (Bd04/05: a
   flawed front-matter/body gate never activates tagging even though the
   font detection itself works fine; Bd07/08: genuinely different font
   family, `GillSansMTPro-BoldConden` instead of `AdvGILLSBC`, not yet
   supported at all). Fixing this is the immediate next step before §7 can
   be attempted on the full 8-volume set.
2. Once entry boundaries are reliable, build a per-volume index
   (headword → page, PDF page, printed page number, article vs. redirect,
   author sigil(s)) as a machine-readable sidecar (e.g. JSON/CSV) alongside
   each `.md` file.
3. Extract the `›`-reference graph per §7 as its own sidecar (e.g. edge
   list: source headword → raw target string → resolved target headword
   ID, with a flag for unresolved/cross-volume-pending references).
4. Strip or relocate the running-header noise once entries are tagged
   (it becomes redundant with the entry markers, except for the printed
   page number, which is worth keeping for citation purposes).
