# Known issues and settled lessons

Two sections. **Open issues** is what still needs doing. **Settled
lessons** is why the code looks the way it does — kept because every one
of them is a bug this project shipped at least once, and the reasoning is
what stops it coming back. Session-by-session status has been removed;
what survives is cause and evidence.

Current state: all 8 volumes extract and tag correctly. 4,627 entries,
59,942 cross-references, 95.9% cleanly resolved. See `docs/schema.md` for
the data shapes and `docs/atlas.md` for the map built on them.

The reference count fell from 59,740 while the resolved share rose,
because issue #2 below is now fixed: German quotations set in `AdvMIN`
were being captured as references and are not any more. Bd01 lost 152
such captures, 146 of which appear in the text as balanced `›…‹` pairs,
and gained 15 genuine references that the old `is_quotation()` heuristic
had suppressed.

---

## Open issues

### 1. The symbol fonts were 21% wrong, all of it silent; the mathematics is now fixed, the Greek is not

Measured by a full census of all eight PDFs, counting the characters
emitted by the seven symbol fonts. The "after" column reads the PDFs
through `patch_pdf_fonts()`, so it is what actually reaches `md-data`:

| font | chars | before | after | silent | gaps |
|---|---|---|---|---|---|
| `AdvSY` | 64,132 | 66.4% | **1.7%** | 1,060 | 16 |
| `AdvOLDGRI` (Greek) | 21,706 | 85.8% | **40.7%** | 8,839 | **0** |
| `AdvMH3` | 1,323 | 38.3% | 37.9% | 502 | 0 |
| `AdvP4C4E74` (formulas) | 23,855 | 51.1% | 51.2% | 10,115 | 2,090 |
| `AdvP4C4E51` | 7,833 | 22.7% | 22.7% | 172 | 1,610 |
| `AdvP4C4E59` | 6,686 | 17.2% | 17.2% | 564 | 589 |
| `AdvP4C4E46` | 1,090 | 88.8% | 88.8% | 867 | 101 |
| **total** | **126,671** | **61.4%** | **20.9%** | 22,119 | 4,406 |

51,289 characters repaired. Two distinct fixes account for all of it:
issue #2's arrow (40,987 of the silent errors, all in `AdvSY`) and the
`/C<n>` derivation below (10,302 gaps closed, and every Greek gap with
it). Greek in the corpus went from **71 characters to 9,927**.

What remains is the half that was never tractable: 22,119 silently wrong
characters on Latin-named codes, whose names carry no information because
they are the corrupted `/ToUnicode` restated. `Æ` where α belongs is valid
text that nothing flags — exactly the class settled lesson #2 exists to
prevent, which is why it is left visible here rather than guessed at.
Glyph-shape matching was built and measured against codes whose answer is
already known from `/C<n>`: **20.3% accurate**, far below anything
shippable, so it was rejected rather than tuned.

**Why the fixed half was fixable.** The fonts partly describe themselves:
their `/Encoding /Differences` arrays name glyphs `/C<n>`, and `n` is the
code point in **that font's own original encoding** — ISO-8859-7 for
`AdvOLDGRI`, Adobe Symbol for the rest; see the correction under settled
lesson #2. Those C-named codes were precisely the ones producing `U+FFFD`,
which is why the gaps went to zero in the fonts that carry them and the
silent errors did not move. `scripts/derive_symbol_cmaps.py` does this.

**The next avenue, if it is ever worth it.** The residual errors are a
consistent per-`(volume, font)` substitution — `å`=χ, `æ`=ρ, `Æ`=α,
`Ø`=ι, `ç`=φ, `Œ`=κ, `ı`=θ, `º`=λ. Now that the `/C<n>` fix supplies
partial plaintext (`åøæØσμός` for χωρισμός), solving the rest as a
substitution cipher against a Greek lexicon is a far better-posed problem
than the shape matching that failed. Untried.

**FIXED for the formula fonts (2026-09-12): they are TeX.** The scheme
nobody had established for `AdvP4C4E74/51/59` is Knuth's. The typesetter
embedded Computer Modern under its own names and named the glyphs from
StandardEncoding positions, so `/exclam` at 0x21 decodes "!" where the
glyph is →, `/two` is ∈, `/nine` is ∃, `/asciicircum` is ∧; and the
`/C<n>` numbers are, as with the Greek font, positions in the original
font — cmsy's control range (−, ·, ×, ≤, ≥, ⊂, ⊃, ≡, ∼, ≺ …), relocated
to bytes 2–20. Glyphs from *other* fonts were parked in the 0x80–0xFF
range of `AdvP4C4E74` — cmr's ( ) = [ + as ð Þ ¼ ½ þ — which is where
"VðAÞ ¼" came from.

| font | is | verified against rendered glyphs |
|---|---|---|
| `AdvP4C4E74` | `cmsy` (OMS) | Bd01 47/47, Bd02 45/45, Bd03 49/49, Bd04 52/52, Bd05 60/60, Bd06 40/40 |
| `AdvP4C4E51` | `cmmi` (OML) | Bd01 22/22, Bd02 26/26, Bd03 28/28, Bd05 30/30 |
| `AdvP4C4E59` | `cmr` (OT1) | Bd01 44/44, Bd02 39/39, Bd05 17/17 |
| `AdvMH3` | ⋀ ⋁ ⩓ ⩔ ⊫ and a wide hat | all volumes; its `C201` (a ≡ struck vertically, the sign for »entweder–oder«) has no Unicode and stays a gap |
| `AdvP4C4E46` | `cmex` | **not repaired**: pieces of stretchy delimiters, radicals and integral signs — layout fragments, out of scope like the rest of formula structure |

`scripts/tex_encodings.py` holds the three tables; `scripts/derive_tex_cmaps.py`
applies them and writes the contact sheets (`export/glyphs/`). 613 byte
mappings across Bd01–06, covering 26,535 characters — about 60% of the
symbol-font total the census above counted as silently wrong. Two things
the tables cannot express are finished in `clean_text.py`: TeX sets ↦ as a
bar glyph followed by → and ⇋ as two stacked harpoons, so the pairs are
collapsed there, and the negation slash (a combining character TeX places
*before* its symbol) is moved after it.

Three lessons from the verification, all of the "confident wrong letter"
kind this ledger exists for: `C138` looked like ⇋ on a cramped crop and
is `]` (it pairs with `½`=`[`, 73/73 in Bd05); `AdvMH3`'s `C201` had been
mapped to ⊃ by the Adobe-Symbol assumption and the glyph is nothing of
the sort; and the ink test that guards against mapping a space had to be
recalibrated for symbols — an arrow darkens 4.7% of its box, a period
2.3%, both under the 5% letter threshold, while the two zero-advance
glyphs (the negation slash, the ↦ bar) cannot be measured at all.

**Still open: the Greek text font.** `AdvOLDGRI`'s residual 8,839 silent
errors are the substitution cipher described above; untouched.

### 2. FIXED: the cross-reference arrow was a font bug, not a house convention

`AdvSY`'s arrow glyph is a real `↑`; its `/ToUnicode` calls it `›`, which
is also the German opening quotation mark. Settled lesson #7 treats the
resulting collision as an editorial fact of Bd01–06. It is not — the fonts
separate the two cleanly. Measured over 124 pages of Bd02:

| font | char | count | what it is |
|---|---|---|---|
| `AdvSY` | `›` | 1,350 | arrows — no `‹` partner |
| `AdvMIN` | `›` / `‹` | 821 / 822 | quotations — balanced pairs |

So the ambiguity `is_quotation()` existed to survive was manufactured by
discarding font identity during extraction. Mapping `AdvSY` byte `0x89` to
`↑` in Bd01–06 made the arrow unambiguous in all eight volumes, as it
already was in Bd07/08 — the same shape of fix as settled lesson #1.
`is_quotation()`, `QUOTATION_WINDOW` and the per-volume `xref_arrow`
override are gone; `DEFAULT_XREF_ARROW` is `↑` for every volume.

Kept as a heading rather than moved to settled lessons because the
evidence above is the whole argument for the change, and the guard that
now protects it (`absent_reference_corpus` in `tests/golden_xrefs.json`)
only makes sense read against it.

### 3. Deliberately unfixed: byte `0x0D` reused as a glyph code for "à"

In a handful of French/Italian bibliography citations ("à l'époque").
Surfaces as `U+FFFD`. `0x0D` is also a genuine carriage return throughout
the document, so a blanket fix risks destroying paragraph structure
everywhere to correct a few accents. A context-sensitive pass (mid-word vs.
real line break) could disambiguate if it ever matters.

### 4. Still open downstream

- **~8,800 silently-wrong Greek characters** in `AdvOLDGRI` — see issue
  #1; the substitution-cipher route is the untried avenue. The formula
  fonts are fixed.
- **Formula structure** — superscripts, fractions and matrices are
  two-dimensional layout. A byte→character table recovers the characters
  in reading order, never the arrangement. Out of scope by construction.
- **Author-sigil resolution** — the front-matter "1. Autoren" tables flatten
  their two columns in the reflow, so a splitter keyed on the sigil pattern
  is needed.
- **Bibliography parsing** — 3,535 `Literatur:` and 1,135 `Werke:` blocks
  are still single strings. Its own project; the `^2` edition/exponent
  ambiguity (`docs/schema.md`) is one of its problems.
- **`heal_hyphenation()` has no regression test.**
- **`entry_type` = `"unknown"`** for ~10–20% of entries per volume. Mostly
  correct (short entries genuinely citing no bibliography), but it also
  catches flagship articles using a bespoke bibliography structure — Kant
  (`Bd04_Ins-Loc:0165:0111`, ~100K chars) is divided by philosophical
  division instead. Flagged as `nonstandard_bibliography`, not a parse
  failure.
- **De-inflection is a 7-suffix heuristic**, not German morphology. A real
  lemmatizer would add a few points with sharply diminishing returns.

### 5. Environment constraint

~5.8 GB total RAM, fluctuating with other apps — sometimes under 1 GB free.
Extraction of a 600–900 page volume can be OOM-killed. Process **one volume
at a time**, never all eight in one process.

---

## Settled lessons

### 1. A 2-glyph symbol font can lie, and the heuristic whitelisted it

Bd07/08 use `↑` for the Verweispfeil, not `›`. Both embed a purpose-built
2-glyph font named `MT-Symbol` whose only glyphs are the arrow (`0x02`) and
space — and whose own `/ToUnicode` mapped `0x02` to `U+2260` (≠) instead of
`U+2191`. It was skipped by `patch_pdf_fonts()` (not an `Adv*` font), and
even if reached, `is_symbol_font_cmap()` would have whitelisted it as
"already a symbol font" *precisely because* its wrong target lands in the
Mathematical Operators block that heuristic tested for.

Fixed via `EXACT_FONT_CMAP_FIXES`: exact `/BaseFont` match, a private
1-entry table, bypassing the heuristic. The font structurally cannot
represent anything else (2 glyphs), so the fix was risk-free. Post-fix `↑`
counts (9,329 / 10,111) exactly matched the pre-fix `≠` counts.

**Downstream:** `›` (Bd01–06) and `↑` (Bd07–08) are two spellings of one
structural feature — but see open issue #2, which argues the split is
itself an artifact.

### 2. Font tables must be keyed on (volume, exact font), never a prefix

This is the central lesson. Three earlier bugs -- the MinionPro
non-breaking space, the MT-Symbol arrow, and the corrupted headword
diacritics -- were the same mistake in different clothes, and each
individual fix only patched one symptom.

**Why no table keyed on a font name can be right.** These are *subset*
fonts: each embeds only the glyphs its own text needs, numbered
independently in the order the typesetter met them. Nothing makes two
subsets agree. Measured by rendering the glyphs and reading them:

| byte | Bd01 `AdvGILLSBC` | Bd06 `AdvGILLSBC` | `AdvMIN` | `AdvMINI` |
|---|---|---|---|---|
| `0x02` | ü | ü | **ä** | ü |
| `0x03` | ä | ä | **ü** | ä |
| `0x05` | **Ä** | **á** | Ä | Ü |
| `0x06` | **è** | **ò** | é | – |

Two consequences the old design could not survive: the *italic* body font
`AdvMINI` has ä/ü swapped relative to the roman `AdvMIN`, so all italic
text was corrupted too — a fourth instance nobody had noticed; and the same
byte differs *between volumes* of the same font, so even a per-font-name
table would be wrong.

**The design that replaced it** (`extract_markdown.py` +
`derive_cmaps.py` → `font_cmaps.json`):

- Tables keyed on **(volume, exact font name)**. No prefix matching.
- Tables **derived empirically**. The corpus is its own ground truth: a
  headword rendered `abh<0x03>ngig` also occurs hundreds of times as prose
  `abhängig`. Votes are occurrence-weighted, filtered to accented-Latin
  candidates, and must clear a confidence floor *and* beat the runner-up by
  a margin.
- The reference corpus is read **unpatched from Bd07/08**, whose MinionPro
  CMaps are correct. Using `md-data` instead — the obvious shortcut — is
  circular: it contains the corruption under test and votes for it.
- **A font with no verified table is left completely alone**, so its bytes
  surface as visible replacement characters instead of confident wrong
  letters. This is the part that kills the bug class.
- Rare bytes below the floor can be promoted by rendering the glyph and
  reading it — `MANUAL_VOLUME_FONT_FIXES`.
- `is_symbol_font_cmap()` was deleted. Nothing is forced onto anything now,
  so symbol fonts are excluded by simply not having a table.

**Correction to this lesson (2026-09-09).** It concluded that the fonts'
`/C<n>` glyph names "do not decode reliably", on the evidence that
`C252`/`C228` match Latin-1 for ü/ä but `C143`/`C190` do not match ë/Ä.
That test used **Latin-1**. The rule is that `n` is a code point in *the
font's own original encoding*, which differs per font:

| font | code page | verified |
|---|---|---|
| `AdvOLDGRI` (Greek) | ISO-8859-7 | 15/15 against rendered glyphs; reconstructs `διχοτομία` 6/6 |
| `AdvSY` (symbols) | Adobe Symbol | 7/7 — C216→¬, C217→∧, C218→∨, C209→∇, C222→⇒, C219→⇔, C204→⊂ |

So the names are usable *given the right code page*, which is why open
issue #1 is tractable. The original caution stands for any font whose code
page has not been established.

### 3. The same scoping lesson, arriving a second time

`REFERENCE_FONT_CMAP = {"AdvMIN": CMAP_OVERRIDES}` was scoped to the exact
font name as intended — but not to the volume it was read off. Bd01's byte
`0x07` ("â", from "moyen-âge") was stamped onto Bd05's (really "é") and
Bd06's (really "Ü"), producing `âbersetzung` 87×, `âber ` 200×, with no
correct spelling anywhere. Confident wrong letters, in the very redesign
meant to guarantee visible gaps.

**A second, independent bug compounded it.** `derive_cmaps.py`'s reference
corpus was built from `md-data` — this pipeline's own *patched* output.
Wherever a table was wrong, the corpus contained the wrong spelling and
voted for it, confirming its own corruption. Measured: `Lukôcs` outvoted
the correct `Lukács` 79 to 15.

**Fixes:** key on `(volume, font)`; rebuild the corpus from Bd07/08 read
unpatched (~530k words, genuinely outside the system under test); reject
evidence keys that cannot decide case (`über`/`Über` dragged correct
mappings under the floor — `...bergang` decides it, `...ber` cannot).

Re-derivation changed 23 byte mappings, added 11, and correctly reverted 62
legacy fills to gaps. Every changed or doubtful entry was confirmed by
rendering the glyph — all confirmed the vote except Bd02 `AdvMIN` `0x07`,
which the vote had at 78% as "é" but the glyph reads "É"; corrected in
`MANUAL_VOLUME_FONT_FIXES`.

A third bug surfaced from the same scoping: `CMAP_OVERRIDES`'s `0xE7`→ö fix
had been riding on the over-broad table. Scoping correctly took it with it,
and `Kçln` reappeared. The fonts genuinely *assert* `0xE7`→æ in their own
ToUnicode, so this was never derivable — overriding what a font actively
claims needs a human, and it is now restated per volume.

### 4. Anchor matching must tolerate the reflow's noise

402 of 4,783 headword candidates (8.4%) failed to tag, silently absorbing
their text into the preceding entry — including `Metaphysik` (176 inbound
references), `Mechanik`, `Seele`, `Skeptizismus`, `Hermeneutik`, `Semiotik`.

Not a font-detection failure: `find_entry_candidates()` saw every one. The
anchor and the reflowed Markdown are two renderings of the same PDF line
and disagree three ways:

1. an unmapped glyph is a raw control byte in the anchor but `U+FFFD` in
   the Markdown — so every `"X (griech. …)"` etymology, i.e. the most
   classical headwords, failed;
2. the reflow interleaves emphasis the PDF has no trace of, not only around
   whole tokens (`**Rhetorik** (von griech. _…_ )`);
3. an anchor is one PDF *line*, so it can end mid-word on a hyphen the
   reflow has already healed.

`build_anchor_pattern()` matches character by character, lets Markdown noise
fall between any two characters, treats an unsafe byte as matching either
spelling, and drops a trailing hyphen. 402 → 19 no-match candidates; the
residue is real ambiguity the code declines to guess at.
`scripts/diagnose_tagging.py` is the census tool (replays the matching
logic against `md-data`, so it costs a text pass, not a re-extraction).

### 5. A resource knob that silently changed the output

`PAGE_BATCH` was lowered 60 → 20 to stop the OOM killer, with a comment
asserting nothing downstream depended on heading *level* any more. That was
true only for the four volumes that had a `body_start_page` override.
`pymupdf4llm` ranks heading levels per `to_markdown()` call, so under
20-page batches the same page yields `# A` instead of `## A`, the
`LETTER_HEADING_RE` gate never opens, and every entry in Bd01/02/03/06 goes
untagged. It stayed invisible because those volumes' `md-data` predated the
change — the constant and the artifacts it invalidated were changed in
different sessions.

**Fix:** every volume has an explicit `body_start_page`. A page number
survives a batching change; a heading level does not.

**The general lesson is worth more than the fix.** A constant tuned for
resources changed the text, and the belief that it hadn't was written down
as a comment and then trusted. Anything that changes how pages are grouped,
batched or sliced should be treated as changing the output until a
re-extraction and diff says otherwise.

### 6. The stored headword was a locator, not a lemma

`find_entry_candidates()` checks that a line's first span is in the
headword font, then concatenates **every span on the line** and cuts at the
2nd punctuation mark — deliberately, because the anchor must be unique when
matched against reflowed Markdown. The defect was storing that locator as
the name: `Abacus (lat.,`, `Scholastik, Sammelbezeichnung für die`. 54.1%
of headwords ended in a comma, 30.3% carried an etymology parenthetical,
and only 17% passed a lenient "is this a lemma" test.

Worse, the running head collided with the real headword: excluded from
candidate *generation* but not from *matching*, so a two-line headword
tagged on its second line and stored under a fragment — Bd03's **Hegelsche
Logik** became `Logik,`, which then impersonated the base `Logik` entry and
won the tiebreak for every bare `›Logik` reference in the corpus.

**The running head is the fix, not just the cause**: read off the PDF it
carries the complete, un-hyphenated lemma. `find_entry_candidates()` now
returns `{"anchor", "lemma"}`, `find_running_heads()` reads the band, and
`merge_split_lemmas()` rejoins a two-line headword. Entry count 4,246 →
4,626.

### 7. `›` does double duty in Bd01–06

`›…‹` is the ordinary German single-guillemet quotation mark. Bd01–06 also
extract the Verweispfeil as `›`, so keying on the glyph alone captured
every quoted word as a cross-reference: **22,015 of 83,694 captures (27%)
were quotations**, 15,867 landing in "unresolved" and 6,148 becoming
**false edges** in the citation graph.

Bd07/08 are the control that proved it: they spell the arrow `↑` and keep
`›…‹` for quotation, and their unresolved share was 8–9% against Bd01–06's
30–34%.

The discriminator is the closing mark: a quotation closes with `‹` before
the next `›` opens. Two cases must **not** be treated as quotations —
Bd07/08, where the arrow is unambiguous; and a doubled `››X‹`, which is
arrow + quoted term and so a genuine reference (859 corpus-wide).

Result — the per-volume gap that diagnosed the bug closed, which is the
check that matters:

| volumes | arrow | unresolved before | after |
|---|---|---|---|
| Bd01–06 | `›` | 30.1% – 34.3% | 2.5% – 4.0% |
| Bd07–08 | `↑` | 7.9% – 9.0% | 2.8% – 3.0% |

**Superseded — kept for the diagnosis, not the remedy.** Open issue #2
resolved the premise: Bd01–06 never used `›` as the arrow, the extraction
did, because the `AdvSY` arrow glyph's `/ToUnicode` says `›`. The
heuristic was correct given the input it received; the input was wrong.
Byte `0x89` now maps to `↑` and the closing-mark discriminator, the
doubled-`››X‹` special case and `is_quotation()` are all deleted — the
glyph itself is the discriminator.

What the numbers above understated: the heuristic still let ~900
quotations through corpus-wide. Removing it dropped captures from 59,740
to 58,839 while the cleanly-resolved share *rose* to 95.9%, which is the
signature of removing false positives rather than real edges.

**Coda: the arrow and the quotation mark also occur together.** Excluding
`›` from the target's character class had a side effect nobody measured:
`↑›Ich‹`, `↑›Konsequens‹`, `↑›Rettung der Phänomene‹` — the editors'
form for a term used as a term, or a phrase they want delimited — matched
nothing, because the arrow was followed by a character the target may not
start with. Those references were never captured, so they were missing
from `cross_references`, from the graph and from the reading pane alike,
and no downstream check could notice an absence. 1,100 of them corpus-wide
(Bd01 123 … Bd04 193), 742 distinct targets.

The fix is an optional `›` after the arrow in `build_xref_re()`; nothing
else changes, because `REST_AFTER_TARGET_RE` already stops at `‹`, so the
quoted phrase reaches the resolver as multi-word context. That makes these
the *best*-delimited references in the corpus: 1,103 more captures (58,839
→ 59,942), 1,056 of them cleanly resolved (95.7%, in line with the corpus
rate), 38 unresolved (no entry: `élan vital`, `Weber-F`, mangled Sanskrit
diacritics), 9 ambiguous. Undirected edges 50,001 → 50,240. Guarded by two
golden cases (`Autonomie → Ich`, `Astronomie → Rettung der Phänomene`).

### 8. Per-volume config beats hardcoded branches

`VOLUME_OVERRIDES` (keyed by PDF stem) holds `body_start_page`,
`headword_font`, and the Markdown-convention quirks. Bd07/08 use
`GillSansMTPro-BoldConden` for headwords rather than `AdvGILLSBC`, and
`_Werke:_`/`_Literatur:_` italic labels rather than plain. `parse_entries.py`
keeps its own separate table from `extract_markdown.py`'s on purpose: one
holds PDF-font quirks (an extraction concern), the other Markdown-text
conventions (a parsing concern).

One consequence worth remembering: `patch_pdf_fonts()` must touch only
`Adv*` fonts. Applying the `Adv` table to `MinionPro-*` turned a legitimate
non-breaking space into `ä` — `"(= Ges. Werke II)"` became
`"(=äGes. Werke II)"` — corrupting text that needed no fix at all.
