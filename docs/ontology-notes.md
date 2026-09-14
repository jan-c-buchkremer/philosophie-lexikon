# Ontology & logic notes — deciphering the editors' own structure

**Purpose of this document, and why it's separate from the others.**
`structure-notes.md` documents the Markdown/extraction-level structure
(what pymupdf4llm produces, what regex catches what). `ISSUES.md` tracks
extraction bugs. This document is different: it's about understanding
**the editors' own conceptual and structural intent** — how they think
the encyclopedia is organized, what categories of knowledge they believe
they're representing, and what formal apparatus (logic/math notation)
the work equips itself with — sourced from the front matter's own prose,
not reverse-engineered from data patterns. The working principle (stated
directly by the user): understand the author's intended structure before
building our own logic on top of it.

**This is a living document.** Update it whenever we read more of the
front matter, discover another editorial rule, or find another entry
that deviates from documented policy. Treat gaps here as open questions,
not a finished account.

## 1. What kind of work this claims to be (Vorwort, "I Konzeption")

Source: `md-data/Bd01_A-B.md` lines 85–144 — **only printed in Bd01**;
later volumes carry just a short "Vorwort zur 2. Auflage" and do not
repeat this. Bd01 is the sole authoritative source for the whole
8-volume series' stated editorial policy.

The editors are explicit about a self-aware tension: scholarly
encyclopedias tend to ossify into monuments of "what is already known,"
substituting for the working scholarship they should serve. They
position this work against that tendency — "ein Instrument
wissenschaftlicher Arbeit, nicht... ein Monument des wissenschaftlich
schon Geleisteten" (an instrument of scholarly work, not a monument to
work already done) — and structurally as **closer to a dictionary than a
treatise**: alphabetical, high headword count, predominantly short
entries, rather than a small number of long systematic essays.

Key stated commitments:
- **Scope**: Philosophy *and* Wissenschaftstheorie (philosophy of
  science) as one continuous field, not two departments — reflecting the
  editors' view that philosophy and the sciences share a common root in
  "rational orientation grounded in conceptual work," historically
  fractured since the 18th century's disciplinary specialization, and
  that Wissenschaftstheorie is the modern attempt to reunite them. This
  explains why the encyclopedia's title yokes the two, and why (per our
  own DB query) "Logik," "Philosophie," and "Wissenschaftstheorie" are
  literally the three most cross-referenced terms in the corpus (1514,
  962, 371 raw mentions) — that's not noise, it's the book's own stated
  center of gravity.
- **Named emphasis areas** (§I.2): (formale) Logik, Theorie der
  Wissenschaftssprache, allgemeine und spezielle Wissenschaftstheorie —
  explicitly the *modern* successor topics to what used to be called
  Erkenntnistheorie (epistemology). Practical philosophy (ethics, social
  theory) is explicitly included too (§I.3), against a possible
  impression that the work is only about "nature and mathematical mind."
- **Historical and systematic treatment are deliberately balanced**, not
  because history is padding, but on principle (§I.4): the editors argue
  thought that tries to stand entirely outside historical development is
  as naive as thought that finds truth only in development — reasoned
  judgment needs to know its own history, but historically reflectively,
  not as mere lineage-collecting.
- **Two article types as a deliberate structural choice, not an
  afterthought** (§I.4, last paragraph): **Sachartikel** (topic/concept
  articles) and **Personenartikel** (biographical articles) coexist
  specifically so that historical material can live in biographies,
  keeping systematic articles from being bloated with historical detail
  — "historische Teile in systematischen Artikeln kurz zu halten." This
  is the editors' own justification for the two-article-type ontology
  `structure-notes.md` and `parse_entries.py`'s `entry_type` already
  operationalize as `biography` / `subject_article`.
- **Editorial voice**: most contributors share a broadly constructivist
  orientation (§I.6) toward "begründete Sprach- und
  Wissenschaftskonstruktionen" (grounded language/science construction)
  — worth knowing as a soft interpretive bias when reading systematic
  articles, though the editors explicitly hope it doesn't read as
  dogmatism.

## 2. The editors' own stated structural rules ("II Ordnung")

Source: `md-data/Bd01_A-B.md` lines 145–169, §II.1–8 — again, Bd01-only.
This is the **primary source** for every mechanical convention
`structure-notes.md` had inferred from data; where they agree, treat
`structure-notes.md` as confirmed; where new detail appears below, prefer
this document (it's what the editors say they intended, not just what we
observed).

1. **No sections/departments** — one flat alphabetical order for
   everything (Sachartikel and Personenartikel interleaved). Umlauts
   alphabetize as their base letter (ä→a, ö→o, ü→u). Multi-word headwords
   alphabetize as one word, **except** noun+postposed-adjective compounds
   (`Algebra, polyadische`), which alphabetize under the noun.
2. **Bibliography convention** (the one this session's investigation was
   about): *"Die Sachartikel weisen in der Regel Literaturverzeichnisse
   auf, die Personenartikel Werk- und Literaturverzeichnisse."* — Sachartikel
   *generally* (not always) get a Literatur: list; Personenartikel get
   both Werke: and Literatur:. Neither claims bibliographic completeness.
   Werkverzeichnisse are chronological, Literaturverzeichnisse
   alphabetical; Werkverzeichnisse grow *more* detailed the *less*
   accessible an author's work is, and shrink to nothing when a reliable
   collected edition exists. **No exception is documented here for major
   figures** — confirming that Kant's and the major surveys' bespoke
   multi-part bibliography structure (§4 below) is a real, undocumented
   authorial deviation, not a second convention we're missing.
3. **No footnotes** — anything footnote-worthy is worked into the body
   text directly.
4. **Foreign-language equivalents** are given parenthetically only where
   genuinely terminological (not just translation trivia), with English
   equivalents dominant for Wissenschaftstheorie headwords specifically
   ("der modernen Forschungslage entsprechend" — reflecting where the
   live research literature actually is).
5. **The `›` cross-reference arrow, in full**: precedes the *first word*
   of a multi-word target. If that exact multi-word compound isn't its
   own headword, the reference silently resolves to the headword formed
   by the first word alone, with the compound concept then expected to
   be *discussed as a subsection of that broader entry* — i.e., a
   missing-compound-headword reference isn't a dead link by editorial
   design, it's a pointer into a specific subsection of a broader entry.
   Plural/inflected forms are never distinguished in the arrow itself.
   Adjective+noun double-headwords (`transitiv/Transitivität`) can be
   referenced from *either* half **within the same sentence** — i.e. this
   is a stylistic license for sentence flow, not two independent
   headwords needing separate resolution.
6. **Sigil abbreviation convention**: the entry's own headword, when
   referred to again within its own body text, is abbreviated to its
   first letter + period (`K.` inside the Kant entry, `B.` inside the
   Bewußtsein entry — already visible throughout the sampled text).
   Inflected forms of this self-abbreviation are also marked, though the
   exact marking convention isn't spelled out further here.
7. **Quotation marks are semantically distinct, not just typographic
   choice**: double guillemets `»…«` (rendered as `»…«` in the Markdown,
   confirmed) mark *quotations, work titles, and institution names*;
   single guillemets `›…‹` mark *emphasis, fragmentary quotation, and
   metalinguistic use* — the **same glyph** (`›`) used for the
   cross-reference arrow. This is the confirmed source of the ambiguity
   `structure-notes.md` §7 already flagged operationally (arrow vs.
   scare-quote use of `›`) — now with the editors' own stated rationale
   for why it's the same character doing two jobs.
8. **Author sigils**: 2–6 character codes resolved against the front
   matter's own "1. Autoren" table (name + affiliation, **re-stated per
   volume** — the same sigil can denote different people in different
   volumes, so any cross-volume author-identity resolution needs the
   per-volume table, never a merged one). Unsigned articles are
   editorial (Redaktionsartikel) by explicit policy, not an extraction
   gap.

## 3. Entry ontology — editors' categories vs. our operational model

| Editors' category (their words) | Our `entry_type` | Notes |
|---|---|---|
| Personenartikel | `biography` | Operationally: has a `Werke:` block. Matches editors' rule almost exactly (§II.2). |
| Sachartikel | `subject_article` | Operationally: has `Literatur:` but no `Werke:`. Matches editors' rule for the *majority* case — but see §4, several Sachartikel legitimately have neither block (short technical terms) and a handful have a bibliography apparatus the rule doesn't anticipate. |
| (redirect-only entries — not named as a formal category in the front matter text read so far; may be addressed elsewhere in the "Abkürzungs- und Symbolverzeichnisse" front matter we haven't fully read) | `redirect` | Operationally defined (short, single arrow, ends in period, no bibliography). Worth checking whether the front matter names this category explicitly somewhere we haven't read yet. |
| (no category — genuinely no citation) | `unknown` | The conservative fallback. §4 below has the real breakdown of what's actually in this bucket. |

**Open question, not yet resolved**: is there a documented editorial name
for redirect entries, and are single-letter symbol entries (e.g. "a", the
traditional-syllogistic universally-affirmative judgment symbol) treated
by the editors as a distinct category too? We haven't found this in the
front matter text read so far (only I Konzeption / II Ordnung / III
Dank) — worth checking the rest of the front matter (the numbered
abbreviation/symbol front-matter sections themselves may have their own
explanatory prose we haven't read as prose, only as data tables).

## 4. Known deviations from documented policy — the flagship entries

Confirmed this session, precisely, against real bytes (not inferred):

- **Kant, Immanuel** (`Bd04_Ins-Loc:0165:0111`, ~100K chars, PDF pages
  165–182): internally divided into major philosophical divisions
  (`I (Theoretische Philosophie):`, presumably continuing II/III for
  Praktische Philosophie and Ästhetik/Teleologie — not yet confirmed how
  far the numbering goes), each with its own prose sub-periods
  (`Vorkritische Periode:`, `Kritische Periode:` — inline run-in
  subheadings, not Markdown headers) and, remarkably, its **own separate
  bibliography per division**: a single `Werkausgaben:` list up front,
  then `Literatur I:`, `Literatur II:`, `Literatur III:` as separate
  lists (only `Literatur III:` directly confirmed so far — worth
  locating I and II precisely if this entry needs full structured
  extraction later). This is the encyclopedia's single most elaborate
  entry, unsurprisingly, and its structure is bespoke to Kant alone.
- **Philosophie, indische** (`Bd06_O-Ra:0252:0190`, ~117K chars) and
  **Philosophie, buddhistische** (`Bd06_O-Ra:0229:0181`, ~82K chars):
  major topical surveys, both using a **numbered outline bibliography**
  distinct from Kant's scheme: `(1) ...`, `(2 a) Texte:` (primary
  sources), `(2 b) Darstellungen:` (secondary/interpretive literature) —
  confirmed directly in the indische-Philosophie entry. This looks like
  a *reusable* convention for "broad survey needing texts-vs-commentary
  separation," distinct from Kant's "per-division Werke+Literatur" shape,
  but so far only confirmed on these two entries — **not yet checked
  whether other major surveys** (Philosophie, christliche /
  theoretische; Logik, indische — also long, also `unknown`, see below)
  use the same `(N a)/(N b)` scheme or something else again.
- **Handled in `scripts/parse_entries.py`**: these entries are flagged
  `nonstandard_bibliography` (a signal, not a parse) rather than forced
  into `werke_raw`/`literatur_raw` — deliberately, since each scheme is
  different enough that a generic splitter would either mis-split or
  require near-per-entry special-casing. Detection requires the label to
  appear at a genuine paragraph start or after a `(N)`/`(N a)` outline
  marker — a bare substring check was tried first and produced false
  positives on the ordinary German phrase "unter dem Titel:" ("published
  under the title:"), which appears constantly in normal citations.
- **Explicitly NOT yet resolved**: `Logik, indische` (`Bd05_Log-N:0057:0026`,
  36K chars) is also `unknown` and also a major survey, but shows no
  `Werkausgaben:`/`(N a)`-style marker at all in a first pass — either it
  uses a third scheme, or it genuinely has no separately-labeled
  bibliography. Worth checking before assuming the `(N a)/(N b)` pattern
  generalizes to "all major surveys."

## 5. The logic/math symbol system ("7. Logische und mathematische Symbole")

This is the encyclopedia's own formal notation glossary — literally "the
logics used in the lexicon." It exists in the Markdown in **two forms**:
an earlier badly-interleaved prose rendering (the "known extraction
artifact" `structure-notes.md` §4b already flagged, caused by
pymupdf4llm linearizing a two-column PDF layout without recognizing it
as a table), and — found this session — a **second, later occurrence
that pymupdf4llm *does* render as a clean pipe table**
(`md-data/Bd01_A-B.md` lines 730+, a 6-column table = two logical
3-column [Zeichen|Name|in Worten] blocks side by side, matching the
original two-PDF-column layout exactly). **This second form is directly
parseable right now** — `structure-notes.md`'s "needs column-aware
re-extraction, may not be worth it" assessment was too pessimistic; a
plain Markdown-table parse of this occurrence recovers the full glossary
structure today, no PDF-level work needed.

**Glyph column is still unreliable** (symbol fonts like `AdvSY` are
deliberately left unpatched by `patch_pdf_fonts()` — see `ISSUES.md`),
so glyphs below are the *raw garbled* characters, not real symbols; the
**names and meanings are fully legible German prose** and are reliable.
Resolving the glyphs is a well-scoped future task *because the source
self-describes every glyph's intended meaning* — the same
render-and-cross-reference method used for the `Adv*` diacritic table
applies directly, just keyed to this glossary's own name/meaning column
instead of external knowledge.

What the apparatus actually covers (German name → our English gloss):

- **Propositional connectives**: Negator (¬, "nicht"), Konjunktor (∧,
  "und"), Adjunktor (∨ inclusive, "oder (nicht ausschließend)"),
  Disjunktor (⊕ exclusive, "entweder…oder…"), Subjunktor (→,
  "wenn…dann…"), Bisubjunktor (↔, "genau dann wenn"), strikter
  Implikator (strict/modal implication, "es ist notwendig: wenn…dann…").
  A separate, older-style pair — [logisches] Implikationszeichen /
  Äquivalenzzeichen — is glossed identically to Subjunktor/Bisubjunktor,
  suggesting two notational conventions (a modern one and an older
  textbook-style one) are both documented for cross-referencing older
  vs. newer sourced articles.
- **Operator precedence, stated explicitly** (prose right after the
  table): negation binds tightest, then conjunction/adjunction, then
  the conditional/biconditional bind loosest — standard textbook
  convention, explicitly chosen to minimize bracketing in formulas.
- **Semantic vs. syntactic consequence, kept distinct**: a
  "semantisches Folgerungszeichen" (⊨, "aus … folgt …") is a separate
  glyph from an "Ableitbarkeitszeichen" indexed to a specific calculus
  K (⊢_K, "ist ableitbar in Kalkül K") — the encyclopedia's articles
  are expected to distinguish model-theoretic entailment from
  proof-theoretic derivability notationally, not just in prose.
- **Inference-rule arrows**: a single "Regelpfeil" ("man darf übergehen
  zu…") and a "doppelter Regelpfeil" (bidirectional) for rule-based
  derivation steps, separate from the entailment/derivability signs above.
- **Quantification, unusually rich**: not just ∀/∃ but a *third*,
  cardinality-marked existential ("kennzeichnender
  Eins-/Manch-/Existenzquantor" = "für genau ein x" = ∃!), **plus a
  separate indefinite-quantifier pair** ("indefiniter Allquantor" /
  "indefiniter Eins-/Manch-/Existenzquantor") glossed as ranging over an
  *indefinite* variability-domain — i.e. the encyclopedia distinguishes
  quantification over a fixed domain from quantification left
  domain-open, as two structurally different notational devices, not
  just a reading nuance.
- **Definite description**: a dedicated Kennzeichnungsoperator (ι, "the
  x such that"), distinct from the quantifiers.
- **Modal logic (alethic), four-way**: Notwendigkeits- (□),
  Möglichkeits- (◇), Wirklichkeits- (actuality — a third alethic
  modality beyond the standard box/diamond pair, notable), and
  Kontingenzoperator (contingency) — this is a richer alethic system
  than the textbook-standard necessity/possibility duo.
- **Deontic logic, structurally parallel to the modal system**:
  Gebots- (obligatory), Verbots- (forbidden), Erlaubnis- (permitted),
  Indifferenzoperator (optional/indifferent) — a four-way system
  mirroring the four-way alethic one above, suggesting the encyclopedia
  treats deontic logic as alethic logic's structural sibling, not an
  afterthought bolted onto it.
- **Identity and order**: Identitäts-/Nicht-Identitätszeichen (=, ≠,
  distinct from the *set*-theoretic membership signs below), plus
  ordinary order relations (<, ≤, >, ≥).
- **Naive/axiomatic set theory**: membership and non-membership (∈, ∉),
  set-builder braces and abstraction ("die Menge derjenigen x, für die
  … gilt"), subset and *proper* subset (kept as two distinct signs),
  the empty set, union (both a pairwise sign and a separate "for
  arbitrarily many sets" sign — again, two notations for what's
  conflated as one operator in many textbooks), intersection (same
  pairwise-vs-arbitrary-family split), complement (parametrized "in M"),
  power set.
- **Functions, notated set-theoretically**: a function-application sign
  and a separate function-*abstraction* sign (λx-style, "die Funktion
  von x, abstrahiert aus…"), a mapping/assignment sign (f: A→B style),
  and an element-assignment sign (x ↦ f(x)) — i.e. functions are treated
  via their set-theoretic graph/mapping apparatus, not as a primitive.

**Why this matters for our own logic**: this is direct, source-grounded
evidence of the conceptual vocabulary the encyclopedia's *own* authors
use to talk about logic articles — useful context before we design any
automated interpretation of formula-bearing entries (structure-notes.md
§3's "false-positive formula headings," §6 item 6's "embedded formulas"),
and a concrete, low-risk next extraction task (parse the clean table,
defer only the glyph-to-Unicode mapping).

## 5b. What resolving the cross-reference graph revealed about the editors' rule

Building `scripts/resolve_xrefs.py` against the editors' stated rule
(§2 point 5) tested that rule empirically for the first time. Results
worth recording as ontology, not just engineering:

- **The rule's fallback presupposes a base entry that often isn't
  there — but the text supplies the qualifier anyway.** §II.5 says a
  reference to a compound that isn't its own headword resolves to "the
  headword denoted by the first word." That works directly for `Logik`:
  there *is* a base entry `Logik,` alongside its 60+ `Logik, X`
  siblings. But the corpus's most-referenced terms have **no unqualified
  base entry at all**: `Philosophie` (962 references),
  `Wissenschaftstheorie` (371), `Sprache` (355), `System`, `Empirismus`,
  `Idealismus` exist only as families of qualified variants.
  **This does not make the references undeterminable** — the running
  text carries the qualifier immediately after the arrow:
  `›Philosophie, praktische)`, `›Philosophie, buddhistische)`,
  `›Philosophie, analytische)`. The arrow marks only the *first* word of
  the target (§2 point 5), but the rest of the lemma is right there in
  the sentence, and `Philosophie, praktische` is a real entry. A reader
  has no trouble; the editors' system is coherent.
  **The ambiguity was ours, not theirs** — and is now largely fixed.
  `parse_entries.py` originally captured only the single word following
  the arrow, discarding the qualifier at extraction time, so the resolver
  never saw it. It now stores the whole reference phrase and the resolver
  longest-matches it against a headword-lemma index: clean resolution
  went from 45.0% to 56.7% and ambiguity from 18.9% to 6.5%. The 962
  `›Philosophie` references now land on `Philosophie, analytische`,
  `, indische`, `, praktische` and so on, as the editors intended.
  **The lesson generalises**: this reference system is only "ambiguous"
  when read one word at a time. The editors designed it to be read in
  sentences, and any future component that consumes references (a search
  UI, a graph explorer, a citation resolver) should keep that in mind —
  the arrow is a pointer *into* running prose, not a self-contained link.
- **The `›`-as-scare-quote overloading (§2 point 7) has a measurable
  cost.** Roughly a third of unresolvable references are bare lowercase
  adjectives/adverbs — almost certainly the emphasis/metalinguistic use
  of `›`, not references at all. The editors' decision to use one glyph
  for both jobs is the single largest source of irreducible noise in the
  graph.
- **A redirect's headword ends at its arrow.** The stored headword for a
  redirect entry (`ens, ›Seiende,`) contains its whole body, because the
  arrow is what separates lemma from target. This turned out to be
  load-bearing for resolution and is now encoded in the resolver.

### Diacritic folding: originally a mitigation, now just robustness

The resolver folds diacritics (ä→a, ü→u, ß→ss, …) on both sides of every
comparison. This was introduced to paper over `ISSUES.md` issue #6 — the
headword font's diacritics were corrupted by a shared CMap table, so a
stored headword read `abhüngig` where the source says `abhängig`, while
cross-reference targets (extracted via a different path) were encoded
correctly and could never match.

That underlying corruption is now **fixed at the source** (`ISSUES.md`
issue #7: per-volume, per-exact-font tables derived from the corpus).
The folding stays, because it still earns its place against ordinary
noise — the deliberately-unpatched `0x0D`-as-"à" gap, and any byte whose
evidence fell below the derivation's floor and is therefore left as a
visible replacement character rather than guessed at.

**Worth knowing for anything user-facing**: where the derivation had no
confident answer, the stored text now contains a visible replacement
character instead of a wrong letter. That is deliberate — a findable gap
beats silent corruption — but a display layer should expect it, and each
one can be retired by rendering the glyph and adding it to
`MANUAL_VOLUME_FONT_FIXES`.

## 6. Open questions (living list — add to this, don't just resolve and delete)

- Does the rest of the front matter (beyond I/II/III, i.e. the
  abbreviation/symbol front-matter sections themselves) contain
  explanatory prose we haven't read as prose yet — in particular,
  anything naming redirect entries or single-letter symbol entries as
  formal categories?
- How far does Kant's `I/II/III` division numbering go, and what are
  `Literatur I:`/`Literatur II:`'s exact contents/positions?
- Does the `(N a)/(N b)` Texte/Darstellungen convention generalize to
  other long surveys (`Philosophie, christliche`, `Philosophie,
  theoretische`, `Logik, indische`), or is each of those a fourth
  distinct scheme?
- Later volumes' "Vorwort zur 2. Auflage" — what changed between the 1st
  and 2nd edition? Not yet read closely; may itself explain some
  cross-volume inconsistencies (e.g. the Bd07/08 font-family/label-style
  differences already found — were they a 2nd-edition production change?).
- The full "1. Autoren," "2. Nachschlagewerke," "3. Zeitschriften," "4.
  Werkausgaben," "5. Einzelwerke," "6. Sonstige Abkürzungen" front-matter
  sections exist per-volume but haven't been read as structured/ontology
  content yet, only referenced as "front matter tables" mechanically.
