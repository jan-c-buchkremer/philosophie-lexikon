"""Parse each volume's tagged Markdown (md-data/BdNN_*.md) into one
structured JSON record per dictionary entry, written to
structured-data/BdNN_entries.jsonl (one JSON object per line).

This is the "structured JSONL entries" stage in the pipeline described in
docs/pipeline-strategy.md: PDF -> tagged Markdown (scripts/extract_markdown.py)
-> structured JSONL entries (this script) -> [later, separate stages]
cleaned/normalized JSONL -> resolved cross-reference graph -> database.

Deliberately OUT OF SCOPE here (later stages' job): resolving
cross-reference target strings to actual headword IDs, redirect-chasing,
inflection handling, cross-volume linking, deep text cleaning/
normalization beyond what's needed for correct structural extraction.
This stage emits raw material only.

Run via uv:
  uv run python scripts/parse_entries.py [--only volume-substring] [--out-dir structured-data]
"""
import argparse
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MD_DIR = ROOT / "md-data"
DEFAULT_OUT_DIR = ROOT / "structured-data"

# --- per-volume Markdown-text-convention config ---------------------------
# NOTE: this is a separate table from extract_markdown.py's VOLUME_OVERRIDES
# on purpose -- that table holds PDF-font quirks (an extraction-stage
# concern), this one holds Markdown-text-convention quirks (a parsing-stage
# concern). Per docs/pipeline-strategy.md strategy #3 (per-volume config
# over hardcoded branches), applied once per stage rather than merged into
# one shared table across stages.
DEFAULT_LABEL_STYLE = "plain"   # Bd01-06: bare "Werke:"/"Literatur:"
# The Verweispfeil is "↑" in ALL EIGHT volumes. It used to be "›" in
# Bd01-06 -- but that was never the editors' convention, only a broken
# ToUnicode entry on AdvSY byte 0x89, now repaired in
# extract_markdown.py's MANUAL_VOLUME_FONT_FIXES. With the arrow spelled
# correctly it can no longer collide with "›…‹", the German quotation
# mark, which is why is_quotation() is gone.
DEFAULT_XREF_ARROW = "↑"

VOLUME_OVERRIDES = {
    # Bd07/08 use "_Werke:_"/"_Literatur:_" (italic-wrapped) instead of
    # plain text -- a different authoring convention, nothing to "fix".
    "Bd07_Re-Te": {"label_style": "italic"},
    "Bd08_Th-Z": {"label_style": "italic"},
}

LABEL_PATTERNS = {
    "plain": {
        "werke": re.compile(r"Werke:\s*"),
        "literatur": re.compile(r"Literatur:\s*"),
    },
    "italic": {
        "werke": re.compile(r"_Werke:_\s*"),
        "literatur": re.compile(r"_Literatur:_\s*"),
    },
}

# Secondary bibliography-section labels seen on a small number of entries
# whose Werke:/Literatur: apparatus is more elaborate than the standard
# two-block convention (see docs/ontology-notes.md). Not treated as a
# third label_style -- these entries' internal structure is bespoke
# per-entry, not a systematic per-volume convention -- just used as a
# signal to flag "has some bibliography, just not in the standard shape"
# rather than mis-lumping them with genuinely uncited short entries.
# Must appear either at a genuine paragraph start (like the real Werke:/
# Literatur: labels do) or after a "(<number> <letter>)" outline marker,
# e.g. "(2 a) Texte:", "(2 b) Darstellungen:" -- confirmed directly this
# is how "Philosophie, indische" structures its bibliography. A bare
# substring search is NOT safe: "Titel:" alone false-positives constantly
# on the ordinary German bibliographic phrase "unter dem Titel:"
# ("published under the title:"), which appears inside completely normal
# citations with no relation to a section label.
NONSTANDARD_BIBLIOGRAPHY_RE = re.compile(
    r"(?:\n\n|\(\d+\s*[a-z]?\)\s*)(?:Werkausgaben|Titel|Texte|Darstellungen):"
)

# --- structural regexes -----------------------------------------------------

# A page marker, optionally followed by the per-page running header (a
# short header-word line -- sometimes **bold** in Bd07/08 -- then a line
# that is purely the printed page number). Present on ~97-99% of pages
# (structure-notes.md), so the header/page-number group is optional: the
# bare page marker always matches, the header lines are consumed only when
# actually present.
# The running head and the printed page number used to be scraped back
# out of the body text here, with an optional "header word then bare
# integer" tail after the page marker. extract_markdown.py now removes
# both as the print-layout furniture they are and promotes the printed
# page number into the marker itself, so this only has to read metadata
# (docs/pipeline-strategy.md §5.4 step 1).
PAGE_BLOCK_RE = re.compile(
    r"<!-- page:(?P<pdf_page>\d+)(?: printed:(?P<printed_page>\d+))? -->"
)

# An entry marker, tolerating an orphaned Markdown heading token
# (e.g. "# <!-- entry:anima, ›Seele. -->") that pymupdf4llm's own
# heading-promotion sometimes splices in front of the injected comment.
# NOT anchored to line start: the split-headword-across-two-markers
# artifact (see SPLIT_HEADWORD merge logic below) places the second
# marker immediately after the first fragment's plain text on the SAME
# line, e.g. "Anarchismus, <!-- entry:erkenntnistheoretischer, -->" --
# anchoring to line start would make that marker invisible and leak its
# raw HTML comment into the preceding entry's body text (confirmed bug,
# fixed by removing the anchor). The "prefix" group only ever captures a
# "#" run directly adjacent to "<!--", which is specific enough that this
# isn't at risk of swallowing an unrelated stray "#" elsewhere.
MARKER_RE = re.compile(
    r"(?P<prefix>#{1,6}[ \t]*)?<!--\s*entry:(?P<hint>.*?)\s*-->",
)

LETTER_HEADING_RE = re.compile(r"^#{1,6} \*{0,2}[A-ZÄÖÜ]{1,3}\*{0,2}\s*$", re.M)

AUTHOR_SIGIL_RE = re.compile(
    r"[A-ZÄÖÜ]\.\s?[A-ZÄÖÜ]\.(\s?/\s?[A-ZÄÖÜ]\.\s?[A-ZÄÖÜ]\.)?\s*\Z"
)

EMPHASIS_RE = re.compile(r"[*_]")


def strip_emphasis(text: str) -> str:
    return EMPHASIS_RE.sub("", text)


def normalize_for_compare(text: str) -> str:
    return re.sub(r"\s+", " ", strip_emphasis(text)).strip().rstrip(",.")


def volume_config(stem: str) -> dict:
    cfg = {"label_style": DEFAULT_LABEL_STYLE, "xref_arrow": DEFAULT_XREF_ARROW}
    cfg.update(VOLUME_OVERRIDES.get(stem, {}))
    return cfg


def find_page_blocks(text: str) -> list[tuple[int, int, int, "int | None"]]:
    """Return (start, end, pdf_page, printed_page_or_None) for every page
    block in document order."""
    blocks = []
    for m in PAGE_BLOCK_RE.finditer(text):
        printed = m.group("printed_page")
        blocks.append((
            m.start(), m.end(),
            int(m.group("pdf_page")),
            int(printed) if printed is not None else None,
        ))
    return blocks


def page_block_at_or_before(blocks: list[tuple[int, int, int, "int | None"]], pos: int):
    """Last page block starting at or before pos, or None."""
    chosen = None
    for b in blocks:
        if b[0] <= pos:
            chosen = b
        else:
            break
    return chosen


def strip_noise(span_start: int, span_end: int, text: str,
                 page_blocks: list[tuple[int, int, int, "int | None"]]):
    """Remove page-block noise and letter-heading noise from
    text[span_start:span_end], rejoining page-break splits with a single
    space (sentences continue mid-word across page breaks) and deleting
    letter-heading matches outright (they sit at a paragraph boundary, not
    mid-sentence). Returns (cleaned_text, pdf_page_end, printed_page_end)."""
    pdf_page_end = None
    printed_page_end = None
    pieces = []
    cursor = span_start

    # collect (start, end, kind) events inside the span, in order
    events = []
    for (bstart, bend, pdf_page, printed_page) in page_blocks:
        if bstart >= span_start and bstart < span_end:
            events.append((bstart, bend, "page", pdf_page, printed_page))
    for m in LETTER_HEADING_RE.finditer(text, span_start, span_end):
        events.append((m.start(), m.end(), "heading", None, None))
    events.sort(key=lambda e: e[0])

    for (estart, eend, kind, pdf_page, printed_page) in events:
        piece = text[cursor:estart]
        if kind == "page":
            # The blank-line padding immediately before "<!-- page:N -->"
            # (e.g. "Steue-\n\n\n\n<!-- page:476 -->...rung...") is layout
            # boilerplate around the page transition, not real paragraph
            # structure -- confirmed directly: without stripping it, a
            # word hyphenated across the page break ("Steue-" / "rung" =
            # "Steuerung") got a spurious paragraph break inserted instead
            # of rejoining. Strip it so the single rejoining space below
            # is the only thing left between the two sides of the break.
            piece = piece.rstrip()
        if kind == "page":
            pdf_page_end = pdf_page
            if printed_page is not None:
                printed_page_end = printed_page
            # A word broken across the PAGE break is healed here, the way
            # extract_markdown.heal_hyphenation() heals one broken across
            # a line -- the two halves are simply glued, with no space and
            # no hyphen. Same suspended-hyphen rule: only a lowercase
            # continuation that is not a conjunction is a broken word.
            tail = piece.rstrip()
            after = text[eend:eend + 60]
            lead = len(after) - len(after.lstrip())
            first = re.match(r"[A-Za-zÄÖÜäöüß]+", after.lstrip())
            if (tail.endswith("-") and first
                    and first.group(0)[:1].islower()
                    and first.group(0).lower() not in SUSPENDED_HYPHEN_NEXT_WORDS):
                # Glue the halves with NOTHING between them -- the hyphen
                # goes, and so does the blank-line padding that follows
                # the marker, or the two halves stay separated by a
                # paragraph break and the word is never actually rejoined.
                pieces.append(tail[:-1])
                cursor = eend + lead
                continue
            pieces.append(piece)
            pieces.append(" ")  # rejoin across the excised page-break noise
        else:
            pieces.append(piece)
        cursor = eend

    pieces.append(text[cursor:span_end])
    cleaned = "".join(pieces)
    cleaned = re.sub(r"[ \t]+", " ", cleaned)
    cleaned = re.sub(r" ?\n ?", "\n", cleaned)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    return cleaned.strip(), pdf_page_end, printed_page_end


def segment_entries(text: str, stem: str) -> list[dict]:
    page_blocks = find_page_blocks(text)
    markers = list(MARKER_RE.finditer(text))
    if not markers:
        return []

    raw_spans = []  # dicts: hint, prefix, content_start, content_end (raw, pre-noise-strip)
    for i, m in enumerate(markers):
        content_start = m.end()
        content_end = markers[i + 1].start() if i + 1 < len(markers) else len(text)
        raw_spans.append({
            "hint": m.group("hint").strip(),
            "prefix": bool(m.group("prefix")),
            "marker_start": m.start(),
            "content_start": content_start,
            "content_end": content_end,
        })

    # --- artifact fixup: split-headword-across-two-markers merge ---
    # Signature (confirmed directly, e.g. Bd01 "Anarchismus,"/
    # "erkenntnistheoretischer," and "Biedermann,"/"Gustav,"): the text
    # between marker i and marker i+1 is NOT new content -- it's just
    # marker i's own headword echoed back as plain prose (pymupdf4llm
    # keeps the original text; the marker is an inserted comment, not a
    # replacement), AND marker i+1 is glued directly onto that echoed
    # text with NO paragraph break before it. Both conditions are
    # required: content-equals-hint alone is NOT enough to distinguish
    # this from a genuine short redirect (e.g. "anima, ›Seele.") whose
    # entire body also happens to equal its own hint text, but which IS
    # followed by a real paragraph break before the next (unrelated)
    # entry's marker.
    PARA_BREAK_BEFORE_NEXT_RE = re.compile(r"\n[ \t]*\n[ \t]*\Z")
    merged_spans = []
    i = 0
    while i < len(raw_spans):
        span = raw_spans[i]
        raw_content = text[span["content_start"]:span["content_end"]]
        if (i + 1 < len(raw_spans)
                and not PARA_BREAK_BEFORE_NEXT_RE.search(raw_content)
                and normalize_for_compare(raw_content) == normalize_for_compare(span["hint"])):
            nxt = raw_spans[i + 1]
            merged = dict(nxt)
            merged["hint"] = span["hint"].rstrip(",") + ", " + nxt["hint"].lstrip(", ")
            merged["prefix"] = span["prefix"] or nxt["prefix"]
            merged["marker_start"] = span["marker_start"]
            merged["flags"] = ["split_headword_merged"]
            merged_spans.append(merged)
            i += 2
            continue
        span = dict(span)
        span["flags"] = []
        merged_spans.append(span)
        i += 1

    entries = []
    for span in merged_spans:
        if span["prefix"]:
            span["flags"].append("heading_promoted")

        cleaned, pdf_page_end, printed_page_end = strip_noise(
            span["content_start"], span["content_end"], text, page_blocks
        )

        # duplicate-heading-line artifact: paragraph 1 == paragraph 2
        # (normalized) -> drop paragraph 1.
        paras = cleaned.split("\n\n", 2)
        if len(paras) >= 2 and strip_emphasis(paras[0]).strip() == strip_emphasis(paras[1]).strip():
            cleaned = "\n\n".join(paras[1:])
            span["flags"].append("duplicate_heading_line_removed")

        pb = page_block_at_or_before(page_blocks, span["marker_start"])
        pdf_page_start = pb[2] if pb else None
        printed_page_start = pb[3] if pb else None

        if pdf_page_end is None:
            pdf_page_end = pdf_page_start
        if printed_page_end is None:
            printed_page_end = printed_page_start

        headword = strip_emphasis(span["hint"]).strip()
        headword = re.sub(r"\s+", " ", headword)

        entries.append({
            "headword": headword,
            "pdf_page_start": pdf_page_start,
            "pdf_page_end": pdf_page_end,
            "printed_page_start": printed_page_start,
            "body": cleaned,
            "flags": span["flags"],
        })

    for e in entries:
        if e["pdf_page_start"] is None:
            e["flags"].append("short_span_uncertain")

    return entries


# --- hyphenated-target rejoining -------------------------------------------
# The arrow capture below stops at whitespace, so a reference target the
# typesetter broke across a line or a page break arrives as an
# unresolvable fragment: "›Identitätsphi-" + "losophie". Both halves are
# still in the entry text -- page-break halves rejoined by strip_noise()
# with a single space, an in-page break surviving as a newline -- so the
# word can simply be put back together. 263 references corpus-wide ended
# in a hyphen this way, every one of them unresolvable by any downstream
# matching heuristic.
#
# Only a LOWERCASE continuation is a broken word. German hyphenation
# always resumes lowercase, so a hyphen before an uppercase word is a
# genuine compound broken at its own hyphen ("Leib-" / "Seele-Problem"),
# and a hyphen before a conjunction is the German suspended hyphen
# ("›Ordinal- und ›Kardinalzahlen", "›Lehr- und Lernsituation",
# "›Unter-‹ bzw. ›Totenwelt‹"). In both of those the hyphen belongs to
# the source text and the target really is incomplete -- leaving them
# unresolved is correct, and joining them would fabricate words
# ("Ordinalund"). Same trade as the resolver's attractor fixes: for a
# citation graph a missing edge beats a wrong one.
TARGET_CHARS = r"[^\s.,;:()\[\]›‹↑»«\"]"
HYPHEN_CONTINUATION_RE = re.compile(
    r"\s+(?P<cont>" + TARGET_CHARS + r"+(?:[/,]" + TARGET_CHARS + r"+)?)"
)
# Conjunctions/adverbs that follow a suspended hyphen. Trailing "." is
# already outside the continuation's character class, so "bzw." arrives
# here as "bzw".
SUSPENDED_HYPHEN_NEXT_WORDS = {
    "und", "oder", "bzw", "beziehungsweise", "sowie", "wie", "od", "u",
    "resp", "respektive",
}


REST_AFTER_TARGET_RE = re.compile(r"[^)\];:.›‹↑»«\n]{0,60}")


def rejoin_hyphenated_target(text: str, word: str, word_end: int):
    """If `word` (ending in "-") is the first half of a word broken across
    a line/page break, return (rejoined_word, position_after_continuation);
    otherwise None."""
    m = HYPHEN_CONTINUATION_RE.match(text, word_end)
    if m is None:
        return None
    cont = m.group("cont")
    # str.islower() rather than a character range: the range spelling had
    # already silently dropped "ß" ("Au-" / "ßenwelt"), and it also
    # excludes digits and stray markup, which are never a continuation.
    if not cont[:1].islower():
        return None
    if cont.lower() in SUSPENDED_HYPHEN_NEXT_WORDS:
        return None
    return word[:-1] + cont, m.end()


def build_xref_re(cfg: dict) -> "re.Pattern":
    """The cross-reference matcher for a volume, given its arrow glyph.

    Two groups, ONE pass, so the two output lists stay index-aligned:
      "word" -- the single token after the arrow.
      "rest" -- the remainder of the reference phrase.
    The editors' convention marks only the FIRST word of a multi-word
    target with the arrow (docs/ontology-notes.md §2 point 5), but the
    rest of the lemma is still sitting in the sentence:
    "›Philosophie, praktische)" refers to the entry "Philosophie,
    praktische". Capturing only "Philosophie" made ~960 references to
    that word unresolvable-by-ambiguity even though the source is
    perfectly explicit. "rest" runs to the first hard boundary (closing
    bracket, sentence period, semicolon, quote, another arrow, newline)
    and deliberately KEEPS commas and slashes, which are part of
    qualified and double headwords respectively. Over-capture is
    harmless: the resolver longest-matches and falls back to the bare
    word.

    Factored out of extract_fields() so the atlas stage can locate the
    same references inside cleaned body text (pipeline/graph_data.py's
    inline-offset recovery) without restating the pattern -- a second
    copy would drift from this one silently.

    Both character classes come from the module constants TARGET_CHARS
    and REST_AFTER_TARGET_RE rather than being restated here, so the
    arrow glyph stays excluded in exactly one place.

    The arrow may be followed by an opening single guillemet: "↑›Ich‹",
    "↑›Rettung der Phänomene‹" is how the editors point at a term used
    as a term, or at a multi-word phrase they want delimited. TARGET_CHARS
    excludes "›" on purpose (it is also the quotation mark), so without
    the optional prefix the arrow found no target and the reference was
    silently dropped -- 1,100 of them across the eight volumes, ~2% of
    all edges, and the best-delimited ones in the corpus: "rest" already
    stops at "‹", so the whole quoted phrase reaches the resolver as
    context. The guillemet is consumed but NOT captured, so `word` still
    starts at the target's first character (which the reading pane's
    link spans rely on).
    """
    arrow = re.escape(cfg["xref_arrow"])
    return re.compile(
        arrow
        + r"›?"
        + r"(?P<word>" + TARGET_CHARS + r"+(?:[/,]" + TARGET_CHARS + r"+)?)"
        + r"(?P<rest>" + REST_AFTER_TARGET_RE.pattern + r")"
    )


def extract_fields(entry: dict, cfg: dict) -> dict:
    text = entry["body"]
    flags = list(entry["flags"])

    m = AUTHOR_SIGIL_RE.search(text)
    author_sigil = None
    if m:
        author_sigil = m.group(0).strip()
        text = text[: m.start()].rstrip()

    patterns = LABEL_PATTERNS[cfg["label_style"]]
    werke_m = patterns["werke"].search(text)
    lit_m = patterns["literatur"].search(text)

    werke_raw = None
    literatur_raw = None
    body_end = len(text)

    if werke_m and lit_m:
        if werke_m.start() < lit_m.start():
            werke_raw = text[werke_m.end():lit_m.start()].strip()
            literatur_raw = text[lit_m.end():].strip()
            body_end = werke_m.start()
        else:
            # A "werke" match starting at/after the "literatur" match is
            # not a real second block -- Werke: always precedes
            # Literatur: structurally (structure-notes.md), so this is
            # bibliography-text noise: a citation *title* that happens to
            # contain the literal substring "Werke:" (confirmed directly,
            # Bd04 "karma": a cited edition titled "K., Werke: Fragmente
            # ...", not a real Werke: section for this entry). Treat as
            # if only "literatur" had matched.
            literatur_raw = text[lit_m.end():].strip()
            body_end = lit_m.start()
    elif werke_m:
        werke_raw = text[werke_m.end():].strip()
        body_end = werke_m.start()
    elif lit_m:
        literatur_raw = text[lit_m.end():].strip()
        body_end = lit_m.start()

    body_text = text[:body_end].strip()

    xref_re = build_xref_re(cfg)
    cross_references_raw = []
    cross_references_context = []
    hyphen_rejoins = 0
    for m in xref_re.finditer(text):
        word, rest = m.group("word"), m.group("rest")
        if word.endswith("-"):
            # see rejoin_hyphenated_target(): put a word the typesetter
            # broke across a line/page break back together, and re-take
            # the trailing context from after the continuation.
            rejoined = rejoin_hyphenated_target(text, word, m.end("word"))
            if rejoined is not None:
                word, cont_end = rejoined
                rest = REST_AFTER_TARGET_RE.match(text, cont_end).group(0)
                hyphen_rejoins += 1
        cross_references_raw.append(word)
        cross_references_context.append((word + rest).strip())

    is_redirect = (
        len(body_text) < 60
        and cfg["xref_arrow"] in body_text
        and literatur_raw is None
        and werke_raw is None
        and body_text.rstrip().endswith(".")
    )
    if is_redirect:
        entry_type = "redirect"
    elif werke_raw is not None:
        entry_type = "biography"
    elif literatur_raw is not None:
        entry_type = "subject_article"
    else:
        entry_type = "unknown"
        # A small number of the encyclopedia's flagship entries (Kant's
        # biography, several major topical surveys) use an entirely
        # different, more elaborate bibliographic structure than the
        # documented Werke:/Literatur: convention (confirmed against the
        # front matter's own "II Ordnung" policy statement -- it does not
        # mention any alternate structure, so this is a genuine author-
        # level exception, not a second convention we're missing a regex
        # for; see docs/ontology-notes.md). Rare (~8/4307 entries
        # corpus-wide) -- flag rather than attempt to split fields, since
        # each one's internal structure is bespoke (Kant alone has
        # "Werkausgaben:" plus separate "Literatur I:"/"II:"/"III:" lists
        # per major division of his philosophy).
        if NONSTANDARD_BIBLIOGRAPHY_RE.search(text):
            flags.append("nonstandard_bibliography")

    return {
        "entry_type": entry_type,
        "body_text": body_text,
        "werke_raw": werke_raw,
        "literatur_raw": literatur_raw,
        "author_sigil": author_sigil,
        "cross_references_raw": cross_references_raw,
        "cross_references_context": cross_references_context,
        "hyphen_rejoins": hyphen_rejoins,
        "flags": flags,
    }


def parse_volume(md_path: Path, out_dir: Path) -> dict:
    stem = md_path.stem
    cfg = volume_config(stem)
    text = md_path.read_text(encoding="utf-8")

    entries = segment_entries(text, stem)

    out_path = out_dir / f"{stem}_entries.jsonl"
    type_counts: dict[str, int] = {}
    flag_counts: dict[str, int] = {}
    total_xrefs = 0
    total_hyphen_rejoins = 0

    with out_path.open("w", encoding="utf-8") as f:
        for ordinal, entry in enumerate(entries, start=1):
            fields = extract_fields(entry, cfg)
            page_start = entry["pdf_page_start"] or 0
            record = {
                "id": f"{stem}:{page_start:04d}:{ordinal:04d}",
                "volume": stem,
                "ordinal": ordinal,
                "headword": entry["headword"],
                "pdf_page_start": entry["pdf_page_start"],
                "pdf_page_end": entry["pdf_page_end"],
                "printed_page_start": entry["printed_page_start"],
                "entry_type": fields["entry_type"],
                "body_text": fields["body_text"],
                "werke_raw": fields["werke_raw"],
                "literatur_raw": fields["literatur_raw"],
                "author_sigil": fields["author_sigil"],
                "cross_references_raw": fields["cross_references_raw"],
                "cross_references_context": fields["cross_references_context"],
                "flags": fields["flags"],
            }
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
            type_counts[fields["entry_type"]] = type_counts.get(fields["entry_type"], 0) + 1
            for flag in fields["flags"]:
                flag_counts[flag] = flag_counts.get(flag, 0) + 1
            total_xrefs += len(fields["cross_references_raw"])
            total_hyphen_rejoins += fields["hyphen_rejoins"]

    print(f"[parse] {md_path.name} -> {out_path.name}: {len(entries)} entries, "
          f"types={type_counts}, flags={flag_counts}, cross_refs={total_xrefs} "
          f"(hyphen-rejoined: {total_hyphen_rejoins})")
    return {"entries": len(entries), "types": type_counts, "flags": flag_counts,
            "cross_refs": total_xrefs, "hyphen_rejoins": total_hyphen_rejoins}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", help="only process volumes whose filename contains this substring")
    ap.add_argument("--out-dir", default=str(DEFAULT_OUT_DIR))
    args = ap.parse_args()

    out_dir = Path(args.out_dir)
    out_dir.mkdir(exist_ok=True)

    md_paths = sorted(MD_DIR.glob("Bd*.md"))
    if not md_paths:
        print("No Markdown files found in", MD_DIR)
        return

    for md_path in md_paths:
        if args.only and args.only not in md_path.name:
            continue
        parse_volume(md_path, out_dir)


if __name__ == "__main__":
    main()
