"""
Extract each encyclopedia volume PDF into a per-volume Markdown file, one
page-marker per page, so downstream parsing can trace any entry back to a
physical page.

The PDFs (produced via 3B2/Arbortext) have a font-encoding bug: German and
French diacritics are assigned to byte codes with either no ToUnicode entry
at all (so extraction passes the raw byte through as a C0 control char) or
an explicitly wrong one (ö mapped to ç).

Repairing that requires knowing what each byte means -- and that is a
property of the individual embedded font, NOT of a font family or a
naming convention. These are subset fonts: each embeds only the glyphs its
own text needs, numbered independently, so byte 0x02 is "ä" in AdvMIN,
"ü" in AdvMINI and AdvGILLSBC, and byte 0x05 is "Ä" in Bd01's AdvGILLSBC
but "á" in Bd06's.

An earlier version applied one hand-built table to every font whose name
began with "Adv". That assumption caused four separate silent-corruption
bugs (see ISSUES.md). Tables are now looked up per volume and per EXACT
font name, from scripts/font_cmaps.json (produced by
scripts/derive_cmaps.py, which derives them empirically from the corpus).
A font with no verified table is left completely alone, so its unmapped
bytes show up as visible replacement characters rather than as confident
wrong letters -- a gap you can find beats corruption you cannot.

We patch each affected font's /ToUnicode CMap stream in-memory (via pikepdf)
before handing the document to pymupdf4llm, so every extraction path in
pymupdf4llm (running text AND its table-cell detection) sees corrected text
-- a post-hoc string replace on the output is NOT sufficient because
pymupdf4llm's table-cell code path sanitizes undefined control chars to the
U+FFFD replacement character before we ever see it.

Run via uv:
  uv run --with pymupdf4llm --with pikepdf python scripts/extract_markdown.py [volume-substring]
"""
import argparse
import gc
import json
import tempfile
import re
import sys
from pathlib import Path

import pikepdf
import pymupdf4llm
import pymupdf

# Process this many pages per to_markdown() call, to bound peak memory.
# Lowered 60 -> 20 after the OOM killer repeatedly took out the larger
# volumes (Bd05 onward) on this ~5.8GB machine -- see ISSUES.md's
# environment note.
#
# Smaller batches cost a little speed -- and, until this was found, one
# silent catastrophe. Heading-level ranking is per to_markdown() CALL
# (docs/pipeline-strategy.md strategy #2), so changing this value changes
# the Markdown for pages that are otherwise untouched: lowering it 60 -> 20
# turned "## A" into "# A" and, through LETTER_HEADING_RE, cost Bd01 every
# one of its 674 entry markers on the next re-extraction. Nothing depends
# on heading level any more (VOLUME_OVERRIDES gives every volume an
# explicit body_start_page), but treat this constant as affecting OUTPUT,
# not just memory: re-extract and diff before and after changing it.
PAGE_BATCH = 20

ROOT = Path(__file__).resolve().parent.parent
PDF_DIR = ROOT / "pdf-data"
MD_DIR = ROOT / "md-data"
MD_DIR.mkdir(exist_ok=True)

# code -> correct Unicode codepoint, established by cross-referencing font
# name + surrounding word context, and for ambiguous cases (0x11, 0x1e,
# 0x16) by visually rendering the glyph from the page (see conversation).
CMAP_OVERRIDES = {
    0x01: 0x0020,  # (rare; behaves as a plain space in context)
    0x02: 0x00E4,  # ä
    0x03: 0x00FC,  # ü
    0x04: 0x00DC,  # Ü
    0x05: 0x00C4,  # Ä
    0x06: 0x00E9,  # é
    0x07: 0x00E2,  # â
    0x0B: 0x00F3,  # ó
    0x0C: 0x00F4,  # ô
    0x10: 0x00D6,  # Ö
    0x11: 0x00EB,  # ë  (visually confirmed: "Averroës", not "Averroès")
    0x12: 0x00BD,  # ½
    0x16: 0x00C1,  # Á
    0x1C: 0x00E0,  # à
    0x1E: 0x00C7,  # Ç  (visually confirmed: "Çankara", not "Śankara")
    0x95: 0x00DF,  # ß  (alternate code some subsets use besides native 0xDF)
    0xBC: 0x00E3,  # ã  ("São Paulo"; rare enough that colliding with a
                   #     genuine "¼" fraction elsewhere is unlikely
    0xE7: 0x00F6,  # ö (font's own CMap wrongly says ç, U+00E7)
}
# KNOWN RESIDUAL GAP: a handful of instances (mostly "à" in French/Italian
# bibliography citations) use raw byte 0x0D (carriage return) as their glyph
# code. Left unpatched deliberately -- 0x0D is also genuinely used for line
# breaks throughout the document, so overriding it would risk far more
# damage (destroying paragraph structure) than the rare citations it would
# fix. Shows up as literal U+FFFD in the output; a future targeted pass
# could disambiguate by position (mid-word vs. real line break) if needed.

# (A is_symbol_font_cmap() heuristic used to live here, to stop the shared
# table being forced onto Greek/math fonts. It is gone: nothing is forced
# onto anything any more. A font is patched only if it has its own
# verified table, so symbol fonts are excluded by simply not having one --
# no guessing, and no heuristic that can itself be wrong. That guard was
# in fact wrong: it whitelisted the MT-Symbol font precisely because its
# buggy entry landed in the Mathematical-Operators block it checked for.)


def build_override_block(overrides: dict[int, int]) -> str:
    lines = [f"{len(overrides)} beginbfchar"]
    for code, target in overrides.items():
        lines.append(f"<{code:02x}> <{target:04x}>")
    lines.append("endbfchar")
    return "\n".join(lines)


CODESPACE_RE = re.compile(
    r"\d+\s+begincodespacerange.*?endcodespacerange", re.S
)
FULL_CODESPACE = "1 begincodespacerange\n<00> <ff>\nendcodespacerange"

# Bd07/08 use "↑" (U+2191), not "›", as their own house convention for the
# Verweispfeil (cross-reference marker) -- see ISSUES.md. Both volumes
# embed a tiny purpose-built 2-glyph subset font literally named
# "MT-Symbol" (BaseFont, subset tag stripped) whose only two glyphs are
# byte 0x02 (the arrow icon) and byte 0x20 (space) -- but its own
# ToUnicode CMap wrongly maps 0x02 to U+2260 (≠) instead of U+2191 (↑),
# visually confirmed by rendering the glyph. It lives here rather than in
# font_cmaps.json because derive_cmaps.py can only identify accented
# LATIN letters -- an arrow is invisible to it. The font has exactly two
# glyphs, so this cannot affect anything else.
MANUAL_FONT_FIXES = {
    "MT-Symbol": {0x02: 0x2191},

    # 0xE7 is not missing in these two fonts -- it is present and WRONG:
    # the font asserts "ç" where the glyph is "ö". Nothing looks unmapped,
    # which is why it hid. Not auto-derived (see SUSPECT_CHARS in
    # derive_cmaps.py for why overriding a font's own claim can't be done
    # safely by vote); checked by hand instead, in every volume where
    # these fonts appear, and unambiguous in all of them:
    #   AdvGILLSBC: çkonomische, Lçwenheimscher, Mçgliche-Welten-Semantik
    #   AdvMINI:    Gçttliche, ermçglichen, religiçse, Nationalçkonomie
    # Note this is emphatically NOT true of every font with a ç: Bd07/08's
    # MinionPro-Regular uses it correctly ("Leçons", "français"), and the
    # Greek face AdvOLDGRI has ç inside Greek strings. Both are excluded
    # by having no table of their own.
    "AdvGILLSBC": {0xE7: 0x00F6},
    "AdvMINI": {0xE7: 0x00F6},
}

# Per-(volume, font) entries confirmed by rendering the glyph and reading
# it, for bytes too rare for derive_cmaps.py to clear its evidence floor.
# Same method that produced the "visually confirmed" entries in
# CMAP_OVERRIDES. Add to this freely -- each entry turns one visible gap
# in the output back into the right character, and unlike a derived
# guess, a rendered glyph is not ambiguous.
# Each entry cites the word it was read off. Those marked (rendered) were
# confirmed by rasterising the glyph from the page and looking at it,
# which is what scripts/font_byte_evidence.py exists to set up; the rest
# are unambiguous in ordinary orthography ("virtù", "Komenský", "Pólya",
# "compréhension" admit no second reading).
#
# THE "à" NOTE. One character defeats the derivation in six volumes out of
# six, and always the same way. The à byte (0x0d in Bd01/Bd06, 0x0c in
# Bd02/Bd03/Bd05, 0x0b in Bd04 -- per-volume numbering, as ever) is
# derived as "é" or "á" at 57-79%, never enough to be right and sometimes
# enough to pass. Its words are Italian and French proper nouns:
# "Università", "società", "Pluralità", "voilà". The clean corpus
# (Bd07/Bd08) is a German philosophy encyclopedia, so it holds very few
# of them, while the accented vowels it holds in abundance are é and á.
# Thin real evidence plus a large confusable neighbour is exactly the
# shape a vote gets wrong, and no threshold fixes it -- raising the floor
# only turns a wrong answer into no answer. Rendering the glyph settles it
# in one look, which is why all six are stated here.
#
# This also retires the "known, deliberately-unfixed" 0x0D-as-à gap that
# ISSUES.md carried for several sessions: the byte is a glyph code inside
# a text string, and the ToUnicode entry that decodes it has nothing to do
# with the line breaks pymupdf derives from text POSITIONING. Verified on
# a page sample, paragraph structure unchanged.
#
# The 0xE7 entries are a different animal from the rest, and the reason
# they appear per volume: that byte is not unmapped, it is mapped WRONG,
# and the wrongness is invisible in the tables. Bd01-06's AdvMIN CMap
# claims U+00E6 for it, pymupdf reports "ç", and the glyph is "ö" --
# "Kçln", "Gçttingen", "kçnnen", "mçglich", 600-750 sampled words in
# EVERY one of the six volumes. It used to be repaired as a side effect
# of the legacy table being applied to AdvMIN everywhere; scoping that
# table to Bd01 (rightly) took the repair with it, and a page sample put
# "Kçln" straight back into the output. So it is stated explicitly, once
# per volume where the glyph was checked. Bd07/08's AdvMIN is deliberately
# NOT included: its 0xE7 is a legitimate "ç" and it has no ö-words at all.
MANUAL_VOLUME_FONT_FIXES = {
    # --- the Verweispfeil in Bd01-06 -------------------------------------
    # AdvSY byte 0x89 is an UP ARROW. Every one of the six volumes' own
    # ToUnicode sends it to U+203A instead -- five by bfchar, Bd02 by the
    # bfrange <88> <89> <2039>. Confirmed by rendering the glyph in all six:
    # it is the same arrow Bd07/08 spell correctly as U+2191.
    #
    # This is not cosmetic. U+203A is also the German opening quotation
    # mark, which the body font emits for real quotations, so the two
    # collided in the extracted text and cost 22,015 false captures and
    # 6,148 false edges (ISSUES.md settled lesson #7). The fonts always
    # distinguished them -- measured over 124 pages of Bd02, AdvSY emits
    # "arrow" 1,350 times with no closing partner while AdvMIN emits
    # 821/822 balanced quotation marks. Mapping the byte correctly makes
    # all eight volumes agree and removes the ambiguity at its source.
    **{(vol, "AdvSY"): {0x89: 0x2191}
       for vol in ("Bd01_A-B", "Bd02_C-F", "Bd03_G-Inn",
                   "Bd04_Ins-Loc", "Bd05_Log-N", "Bd06_O-Ra")},

    ("Bd01_A-B", "AdvGILLSBC"): {
        0x05: 0x00C4,  # Ä -- "Ähnlichkeit"
        0x06: 0x00E8,  # è -- "Ampère"
        0x07: 0x00E9,  # é -- "Bouillé" (rendered)
    },
    ("Bd01_A-B", "AdvMIN"): {
        0x0D: 0x00E0,  # à -- "Università" (rendered). Overrides a derived
                       # "é" (71%): see the à note below.
        0xE7: 0x00F6,  # ö -- "Köln"; also in CMAP_OVERRIDES, stated here so
                       # the repair does not depend on that table's scope
    },
    ("Bd01_A-B", "AdvMINI"): {
        0x04: 0x00C4,  # Ä -- "Äquiva-", "Ä.s-Form"
        0x07: 0x00E9,  # é -- "encyclopédi-"
    },
    ("Bd02_C-F", "AdvMIN"): {
        0x07: 0x00C9,  # É -- "Études" (rendered). Overrides a DERIVED "é":
                       # the vote had 7 occurrences and the tokens carrying
                       # this byte ("d’Étaples", "l’École") exist in both
                       # cases in French titles, which is precisely what
                       # derive_cmaps' case guard cannot see once the
                       # apostrophe is part of the token. This font already
                       # has é at 0x05 on 518 votes.
        0x0C: 0x00E0,  # à -- "voilà" (rendered)
        0x0D: 0x00F4,  # ô -- "hôpitaux" (rendered); derived 3/3 but under
                       # the evidence floor
        0x15: 0x00FD,  # ý -- "Komenský" (rendered)
        0x11: 0x00C5,  # Å -- "Å." (rendered); derived 1/1, under the floor
        0xE7: 0x00F6,  # ö -- "Köln", "Göttingen"
    },
    ("Bd03_G-Inn", "AdvMIN"): {
        0x07: 0x00C9,  # É -- "Élie", "École", "Étude" (rendered)
        0x0C: 0x00E0,  # à -- "Università" (rendered). Overrides a derived
                       # "é" (79%): see the à note below.
        0x0D: 0x00EB,  # ë -- "Averroës", "Joël" (rendered)
        0x10: 0x00F9,  # ù -- "Maierù"
        0x11: 0x00FD,  # ý -- "Tichý"
        0x17: 0x00F4,  # ô -- "rôle"
        0x18: 0x00C5,  # Å -- "Åqvist"
        0xE7: 0x00F6,  # ö -- "Göttingen", "Körper"
    },
    ("Bd04_Ins-Loc", "AdvGILLSBC"): {
        0x05: 0x00E1,  # á -- "Tomás"
        0x08: 0x00E9,  # é -- "Lévi-Strauss"
    },
    ("Bd04_Ins-Loc", "AdvMIN"): {
        0x0B: 0x00E0,  # à -- "società" (rendered). Overrides a derived
        0x0D: 0x00F4,  # ô -- "l’hôpital", "contrôle", "rôle"
                       # "á" (67%): see the à note below.
        0x10: 0x00C5,  # Å -- "Åqvist" (rendered)
        0x11: 0x00EB,  # ë -- "Joël", "Studiën"
        0x16: 0x00F9,  # ù -- "Maierù"
        0xE7: 0x00F6,  # ö -- "Köln", "können"
    },
    ("Bd04_Ins-Loc", "AdvMINI"): {
        0x04: 0x00E9,  # é -- "compréhension", "étendue", "continuité"
    },
    ("Bd05_Log-N", "AdvGILLSBC"): {
        0x05: 0x00E9,  # é -- "Maréchal-Schule"
    },
    ("Bd05_Log-N", "AdvMIN"): {
        0x09: 0x00C9,  # É -- "Élements" (rendered). The vote split 58/42
                       # between É and é and was rejected: French titles
                       # genuinely use both "Études" and "études", so the
                       # corpus cannot decide this one -- the glyph can.
        0x0C: 0x00E0,  # à -- "Università" (rendered). Overrides a derived
                       # "é" (67%): see the à note below.
        0x11: 0x00C5,  # Å -- "Åqvist"
        0x12: 0x00F9,  # ù -- "virtù"
        0x14: 0x00F2,  # ò -- "filosò-", "Nicolò" (rendered)
        0x16: 0x00F4,  # ô -- "rôle", "pôles", "Diplôme"
        0x17: 0x00C7,  # Ç -- "Çankara". Same word and same series as the
        0x1C: 0x00FD,  # ý -- "českých", "Višňovský" (rendered)
                       # visually confirmed 0x1E in CMAP_OVERRIDES, but a
                       # different byte in a different volume: read from
                       # context, not rendered.
        0xE7: 0x00F6,  # ö -- "Göttingen", "möglich"
    },
    ("Bd06_O-Ra", "AdvGILLSBC"): {
        0x05: 0x00E1,  # á -- "Palágyi"
        0x06: 0x00F2,  # ò -- "Piccolòmini"
        0x08: 0x00F3,  # ó -- "Pólya"
    },
    ("Bd06_O-Ra", "AdvMIN"): {
        0x0D: 0x00E0,  # à -- "Pluralità" (rendered). Overrides a derived
        0x09: 0x00C9,  # É -- "Étude", "École" (rendered)
        0x1E: 0x00F2,  # ò -- "Niccolò"
                       # "é" (60%): see the à note below.
        0x12: 0x00F9,  # ù -- "Maierù"
        0x14: 0x00F4,  # ô -- "apôtres"
        0xE7: 0x00F6,  # ö -- "können", "Möglichkeit"
    },
}

# The hand-derived table above (CMAP_OVERRIDES) belongs to the ROMAN BODY
# FACE and nothing else. Its contents were never the problem; applying it
# to every font whose name merely starts with "Adv" was. Subset fonts
# number their glyphs independently, so the same byte means different
# characters in different fonts and different volumes -- byte 0x02 is "ä"
# in AdvMIN but "ü" in AdvMINI and AdvGILLSBC, and byte 0x05 is "Ä" in
# Bd01's AdvGILLSBC but "á" in Bd06's. Prefix matching silently corrupted
# all of them (see ISSUES.md; it caused four separate bugs).
#
# So: this table is now scoped to the one font it describes, every other
# font gets its own empirically derived table from font_cmaps.json, and a
# font with no table is left ALONE rather than guessed at.
#
# ...and scoped to the one VOLUME it describes, which is the same lesson
# arriving a second time. Keying this on the font name alone still spread
# Bd01's byte numbering across all eight volumes, because AdvMIN is
# subset-numbered per volume just like every other font here. Measured
# directly from the raw bytes:
#
#   byte   Bd01 AdvMIN      Bd05 AdvMIN        Bd06 AdvMIN
#   0x04   Ü (Übersetzung)  Ü (Überlegungen)   é (pensée, théologie)
#   0x06   é (pensée)       -- unused --       -- unused --
#   0x07   â (moyen-âge)    é (théorie)        Ü (Übergang)
#
# So this table stamped "â" onto Bd05's é ("mâtaphysique", 38 times) and
# onto Bd06's Ü ("âbersetzung", 87 times, plus 200 more "âber ") -- in
# plain roman body text, in every entry of those volumes. Its bytes are
# right for Bd01 and for nothing else.
REFERENCE_FONT_CMAP = {("Bd01_A-B", "AdvMIN"): CMAP_OVERRIDES}

FONT_CMAPS_PATH = Path(__file__).resolve().parent / "font_cmaps.json"


def load_font_cmaps() -> dict:
    """{volume_stem: {exact_font_name: {byte: codepoint}}} from
    scripts/font_cmaps.json, produced by scripts/derive_cmaps.py."""
    if not FONT_CMAPS_PATH.exists():
        return {}
    raw = json.loads(FONT_CMAPS_PATH.read_text(encoding="utf-8"))
    return {
        volume: {
            font: {int(code, 16): cp for code, cp in table.items()}
            for font, table in fonts.items()
        }
        for volume, fonts in raw.items()
    }


def cmap_for_font(family: str, derived: dict, volume: str) -> "dict | None":
    """The byte->codepoint table for one exact font, or None to leave the
    font untouched.

    Precedence, lowest to highest:
      1. REFERENCE_FONT_CMAP -- the legacy hand-built table, scoped to the
         one (volume, font) it was read off. It is no longer a fallback
         for other volumes: a byte it does not cover there is a gap, and a
         gap is the correct answer when the evidence is absent.
      2. the derived per-volume table -- volume-specific evidence beats a
         table generalised from one volume.
      3. MANUAL_FONT_FIXES / MANUAL_VOLUME_FONT_FIXES -- visually
         confirmed by rendering the glyph; not derivable (the
         arrow glyph is not an accented Latin letter, so the derivation
         cannot see it).
    """
    table = dict(REFERENCE_FONT_CMAP.get((volume, family), {}))
    table.update(derived.get(family, {}))
    table.update(MANUAL_FONT_FIXES.get(family, {}))
    table.update(MANUAL_VOLUME_FONT_FIXES.get((volume, family), {}))
    return table or None


def _splice_override(tu_stream, override_block: str) -> None:
    text = tu_stream.read_bytes().decode("latin1")
    text = CODESPACE_RE.sub(FULL_CODESPACE, text, count=1)
    if "endcmap" in text:
        text = text.replace("endcmap", override_block + "\nendcmap", 1)
    else:
        text = text + "\n" + override_block + "\n"
    tu_stream.write(text.encode("latin1"))


def patch_pdf_fonts(pdf_path: Path) -> pymupdf.Document:
    """Return a pymupdf.Document with repaired ToUnicode CMaps, built
    in-memory (the file on disk is never modified).

    Tables are looked up per volume and per EXACT font name -- see
    cmap_for_font and scripts/derive_cmaps.py for why anything coarser is
    unsound."""
    pdf = pikepdf.open(str(pdf_path))
    derived = load_font_cmaps().get(pdf_path.stem, {})

    seen = set()
    patched = 0
    skipped_no_table = 0
    for obj in pdf.objects:
        try:
            if not (isinstance(obj, pikepdf.Dictionary) or hasattr(obj, "get")):
                continue
            if obj.get("/Type") != pikepdf.Name("/Font"):
                continue
            if "/ToUnicode" not in obj:
                continue
        except Exception:
            continue

        key = obj.objgen  # stable (obj_id, gen) pair; id() is unreliable
        if key in seen:
            continue
        seen.add(key)

        # EXACT font match only -- never a name prefix. A font we have no
        # table for is left completely alone: its unmapped bytes then
        # surface as visible replacement characters instead of confident
        # wrong letters. That is the property that makes this bug class
        # impossible rather than merely fixed.
        base_font = str(obj.get("/BaseFont", ""))
        family = base_font.split("+")[-1]

        table = cmap_for_font(family, derived, pdf_path.stem)
        if table is None:
            skipped_no_table += 1
            continue

        try:
            _splice_override(obj["/ToUnicode"], build_override_block(table))
            patched += 1
        except Exception:
            skipped_no_table += 1

    print(f"  fonts patched: {patched}, "
          f"fonts left alone (no verified table): {skipped_no_table}")

    # Round-trip through a temp FILE rather than a BytesIO. The in-memory
    # version held three copies of the document at once -- pikepdf's
    # parsed object graph, the serialized bytes, and pymupdf's document
    # over those bytes -- which is what kept getting the larger volumes
    # OOM-killed on this ~5.8GB machine (ISSUES.md's environment note).
    # Via a file, pikepdf is closed and freed before pymupdf opens it,
    # and pymupdf can memory-map instead of holding the bytes.
    tmp = tempfile.NamedTemporaryFile(suffix=".pdf", delete=False)
    tmp.close()
    tmp_path = Path(tmp.name)
    try:
        pdf.save(str(tmp_path))
    finally:
        pdf.close()
    doc = pymupdf.open(str(tmp_path))
    # Safe to unlink now on POSIX; on Windows the handle keeps it alive,
    # so record it for cleanup after the document is closed.
    _TEMP_PDFS.append(tmp_path)
    return doc


_TEMP_PDFS: list = []


def cleanup_temp_pdfs() -> None:
    while _TEMP_PDFS:
        path = _TEMP_PDFS.pop()
        try:
            path.unlink()
        except OSError:
            pass  # still held open, or already gone; not worth failing over



# Headwords are set in a dedicated font ("AdvGILLSBC", a grotesque/sans face)
# distinct from the body serif font ("AdvMIN" and friends), confirmed by
# inspecting span-level font names via page.get_text("dict"). The SAME font
# also appears in the per-page running header (word + printed page number,
# repeated at the top of every page) -- distinguished from real headwords by
# the fact that the header's containing text block spans (almost) the full
# page width across both columns, while real content is confined to one
# column.
HEADWORD_FONT = "GILLSBC"
FULL_WIDTH_RATIO = 0.6  # block wider than this fraction of the page = header/footer band

# Per-volume overrides for quirks that don't hold across the whole series.
# Keyed by PDF stem (e.g. "Bd04_Ins-Loc"). See docs/pipeline-strategy.md
# strategy #3 (per-volume config over hardcoded/per-volume branches) and
# ISSUES.md issues #2/#3/#4 for how each entry here was derived.
#   body_start_page: bypasses the "## <Letter>" heading-based in_body gate
#     with a plain PDF-page-number threshold, for volumes where
#     pymupdf4llm never promotes that heading (Bd04/05 -- see issue #2).
#   headword_font: substring to match against span["font"] instead of the
#     Bd01-06 default "GILLSBC", for volumes using a different headword
#     typeface (Bd07/08 use "GillSansMTPro-BoldConden", not "AdvGILLSBC"
#     -- see issue #3).
#
# EVERY volume now carries a body_start_page, and that is deliberate. The
# four that previously relied on the "## <Letter>" heading gate broke the
# first time the corpus was re-extracted after PAGE_BATCH was lowered
# 60 -> 20: pymupdf4llm ranks heading levels per to_markdown() CALL, so
# the same page that yielded "## A" in a 60-page batch yields "# A" in a
# 20-page one, LETTER_HEADING_RE (anchored on exactly "##") stopped
# matching, in_body never opened, and Bd01 re-extracted to 584 pages with
# ZERO entry markers. The comment on PAGE_BATCH asserting that "nothing
# downstream depends on heading LEVEL any more" was true only for the
# volumes that already had an override here.
#
# The values below reproduce the gate's own historical behaviour exactly:
# each is the page on which the letter heading appeared, which is also the
# page carrying that volume's first entry marker, read off the last
# known-good extraction. A page number cannot be re-ranked by a batching
# change; a heading level can.
VOLUME_OVERRIDES = {
    "Bd01_A-B": {"body_start_page": 25},
    "Bd02_C-F": {"body_start_page": 19},
    "Bd03_G-Inn": {"body_start_page": 19},
    "Bd04_Ins-Loc": {"body_start_page": 20},
    "Bd05_Log-N": {"body_start_page": 20},
    "Bd06_O-Ra": {"body_start_page": 20},
    "Bd07_Re-Te": {
        "headword_font": "GillSansMTPro-BoldConden",
        "body_start_page": 20,
    },
    "Bd08_Th-Z": {
        "headword_font": "GillSansMTPro-BoldConden",
        "body_start_page": 21,
    },
}


def find_running_heads(
    page: "pymupdf.Page", headword_font: str = HEADWORD_FONT
) -> list[str]:
    """The running-head band's text: the complete printed lemma of the
    entry that owns this page.

    find_entry_candidates() deliberately skips this band -- a running head
    is not an entry occurrence -- but the string itself is the single
    highest-quality lemma in the document. It is set on ONE line, so it is
    never hyphenated, and it carries the full qualifier that a body
    headword may have split across two lines:

        Bd03 p335  'Hegelsche Logik'
        Bd07 p566  'Strukturalismus (philosophisch, wissenschaftstheoretisch)'

    Used for two things: merging a two-line headword back together
    (merge_split_lemmas), and removing the band from the body text
    (strip_page_furniture) so it can no longer collide with the real
    headword during anchor matching -- ISSUES.md issue #11b.
    """
    d = page.get_text("dict")
    page_width = page.rect.width
    heads = []
    for block in d["blocks"]:
        if "lines" not in block:
            continue
        bx0, _, bx1, _ = block["bbox"]
        if (bx1 - bx0) <= FULL_WIDTH_RATIO * page_width:
            continue  # a body column, not the header/footer band
        for line in block["lines"]:
            spans = line["spans"]
            if not spans or headword_font not in spans[0]["font"]:
                continue
            raw = "".join(span["text"] for span in spans).strip()
            if len(raw) > 1:
                heads.append(raw)
    return heads


def find_entry_candidates(
    page: "pymupdf.Page", headword_font: str = HEADWORD_FONT
) -> list[dict]:
    """Return one dict per probable entry headword on this page, in
    reading order, with two DIFFERENT strings for two different jobs
    (ISSUES.md issue #11a -- conflating them is why 83% of stored
    headwords were not lemmas):

      "anchor"  -- for LOCATING the headword in the reflowed Markdown.
                   The run of leading headword_font spans plus a few more
                   words from the same line regardless of font, cut at the
                   2nd punctuation mark, so it is long enough to be
                   unique. Not a name: "Abacus (lat.,".
      "lemma"   -- for NAMING the entry. The leading run of headword_font
                   spans ONLY, which is exactly what the typesetter set as
                   the headword: "Abacus".

    The lemma also settles the etymology-vs-disambiguator question for
    free. An etymology is not set in the headword font ("Abacus" + roman
    "(lat., von griech. ...)"), while a disambiguating qualifier is
    ("Strukturalismus (philosophisch, wissenschaftstheoretisch)" is bold
    throughout) -- so keeping the bold run keeps the disambiguator and
    drops the etymology, with no word-list heuristic.
    """
    d = page.get_text("dict")
    page_width = page.rect.width
    candidates = []

    for block in d["blocks"]:
        if "lines" not in block:
            continue
        bx0, _, bx1, _ = block["bbox"]
        if (bx1 - bx0) > FULL_WIDTH_RATIO * page_width:
            continue  # running header/footer band spanning both columns

        for line in block["lines"]:
            spans = line["spans"]
            if not spans or headword_font not in spans[0]["font"]:
                continue

            # Concatenate spans verbatim (not word-split-then-rejoined) so
            # inter-span spacing exactly matches the rendered text -- e.g.
            # the comma right after a headword ("Abaelard" + "," as two
            # separate spans) must stay glued with no space, or the anchor
            # won't be found in the reflowed Markdown later.
            raw = "".join(span["text"] for span in spans).strip()
            if not raw:
                continue
            # a bare single letter is the "## <Letter>" section divider, not
            # a real entry -- skip it
            if len(raw) <= 1:
                continue

            # cut the anchor at the 2nd punctuation boundary (comma/period/
            # closing-paren) for a reasonably unique but still robust-to-
            # reflow anchor string; fall back to first 4 words if no such
            # boundary appears early in the line
            cut = None
            hits = 0
            for i, ch in enumerate(raw):
                if ch in ",.)" and i > 0:
                    hits += 1
                    if hits == 2:
                        cut = i + 1
                        break
            anchor = raw[:cut] if cut else " ".join(raw.split()[:4])

            # the lemma: leading headword-font spans only, stopping at the
            # first span in any other font (the etymology / body text)
            lemma_parts = []
            for span in spans:
                if headword_font not in span["font"]:
                    break
                lemma_parts.append(span["text"])
            lemma = " ".join("".join(lemma_parts).split()).strip(" ,.;:")

            candidates.append({"anchor": anchor, "lemma": lemma or anchor})

    return candidates


def _norm_lemma(text: str) -> str:
    """Comparison form for matching a merged lemma against a running head:
    whitespace collapsed, Markdown emphasis dropped, case folded."""
    return " ".join(re.sub(r"[*_]", "", text).split()).casefold()


def merge_split_lemmas(candidates: list[dict], running_heads: list[str]) -> list[dict]:
    """Rejoin a printed headword the typesetter set across two lines.

    An anchor is one PDF LINE, so a two-line headword yields two
    candidates and the entry ends up named after whichever line happened
    to tag -- its own continuation fragment. Measured: Bd03's "Hegelsche
    Logik" was stored as `Logik,` (where it then impersonated the base
    Logik entry corpus-wide) and Bd07's Strukturalismus as `retisch),`.

    A merge is only accepted when the RUNNING HEAD confirms it, because
    the joined form is otherwise a guess: joining "Differential-" to a
    following "und Integralrechnung" on the hyphen would fabricate
    "Differentialund", while joining it with a space is correct. Both
    join forms are tried and the running head decides; with no running
    head on the page, nothing is merged.
    """
    if not running_heads or len(candidates) < 2:
        return candidates
    heads = {_norm_lemma(h) for h in running_heads}
    merged = []
    i = 0
    while i < len(candidates):
        cur = candidates[i]
        if i + 1 < len(candidates):
            nxt = candidates[i + 1]
            joins = []
            if cur["lemma"].endswith("-"):
                joins.append(("hyphen", cur["lemma"][:-1] + nxt["lemma"]))
            joins.append(("space", cur["lemma"] + " " + nxt["lemma"]))
            hit = next((j for j in joins if _norm_lemma(j[1]) in heads), None)
            if hit is not None:
                how, lemma = hit
                # The ANCHOR has to be joined the same way, not just
                # inherited from the first line. A first line can be a
                # single common word ("Hegelsche"), which occurs all over
                # the page as a prefix of other words and is skipped as
                # non-unique; joined, "Hegelsche Logik," is unique. The
                # text has already been hyphen-healed, so the joined form
                # is what is actually there to match.
                # ...but only for a SPACE join. A hyphen-split headword
                # needs a line long enough to have been broken, so its
                # first anchor is already unique; and the Markdown may
                # keep emphasis markers across the break
                # ("...theo-**\n\n**retisch)"), which no joined anchor can
                # match -- build_anchor_pattern drops the trailing hyphen
                # and matches the first line alone instead.
                anchor = (cur["anchor"] if how == "hyphen"
                          else cur["anchor"] + " " + nxt["anchor"])
                merged.append({"anchor": anchor, "lemma": lemma.strip(" ,.;:")})
                i += 2
                continue
        merged.append(cur)
        i += 1
    return merged


ENTRY_MARKER_TMPL = "<!-- entry:{} -->\n\n"

# An anchor is built from page.get_text("dict"), then matched against
# pymupdf4llm's REFLOWED Markdown for the same page. Those two views of
# one line disagree in three measured ways, and each one silently cost us
# the entry (ISSUES.md issue #8 -- 402 of 4,783 headword candidates
# corpus-wide, "Metaphysik", "Mechanik", "Seele", "Rhetorik" among them,
# each absorbed into the preceding entry's body instead):
#
#   1. an unmapped glyph is a raw control byte here and U+FFFD there,
#      one for one -- so every "X (griech. ...)" etymology, i.e. exactly
#      the most classical headwords in the encyclopedia, failed;
#   2. the Markdown interleaves emphasis markers the PDF text has no
#      trace of, and not only around whole tokens: Bd07's Rhetorik reads
#      "**Rhetorik** (von griech. _..._ )" -- an underscore and a space
#      inserted before the closing paren;
#   3. an anchor is one PDF LINE, so it can end mid-word on a hyphen
#      ("... Bezeich-") that the reflow has already healed
#      ("Bezeichnung").
#
# So match character by character, letting Markdown's own noise
# (whitespace, "*", "_") fall between any two characters, treating an
# unsafe character as "either spelling", and dropping a trailing hyphen.
# The anchor's own whitespace is dropped for the same reason: the gap
# pattern between every pair already covers it.
UNSAFE_ANCHOR_CLASS = "[\\x00-\\x1f\\ufffd]"
ANCHOR_GAP = "[\\s*_]*"
UNSAFE_CHAR_RE = re.compile("[\\x00-\\x1f]")


def build_anchor_pattern(hint: str) -> str:
    """Regex matching `hint` as the reflowed Markdown may have rewritten it."""
    pieces = []
    for ch in hint.strip().rstrip("-"):
        # unsafe BEFORE whitespace: a glyph code of 0x09 or 0x0d is both,
        # and it is a character in the Markdown (U+FFFD), not a gap. Half
        # the Greek etymologies still failed while this was the other way
        # round.
        if ord(ch) < 0x20 or ch == "�":
            pieces.append(UNSAFE_ANCHOR_CLASS)
        elif ch.isspace():
            continue
        else:
            pieces.append(re.escape(ch))
    # leading emphasis belongs to the match, so the marker lands BEFORE it
    # rather than splitting "**Rhetorik**" down the middle
    return "[*_]{0,2}" + ANCHOR_GAP.join(pieces)


def sanitize_hint(hint: str) -> str:
    """Marker text for `hint`: unmapped bytes written as U+FFFD, the way
    the same characters appear in the Markdown body, so no downstream
    stage ever sees a raw control byte inside a headword."""
    return UNSAFE_CHAR_RE.sub("�", " ".join(hint.split()))


def inject_entry_markers(page_text: str, candidates: list[dict]) -> str:
    """Insert an `<!-- entry:LEMMA -->` marker immediately before each
    candidate anchor's occurrence in page_text, preferring a match right
    after a paragraph break. Ambiguous (non-unique, no paragraph-start
    match) candidates are skipped rather than guessed at.

    The marker carries the candidate's LEMMA while the search uses its
    ANCHOR -- see find_entry_candidates() for why those are two different
    strings. Note that the running head must already have been removed
    from page_text (strip_page_furniture): while it was still there, a
    headword's anchor matched both it and the real headword, and the
    entry was skipped as ambiguous."""
    insertions = []  # (position, hint)
    for cand in candidates:
        anchor, hint = cand["anchor"], cand["lemma"]
        if not anchor.strip() or not hint.strip():
            continue
        pattern = build_anchor_pattern(anchor)
        matches = list(re.finditer(pattern, page_text))
        if not matches:
            continue
        para_start_matches = [
            m for m in matches if page_text[:m.start()].endswith("\n\n")
        ]
        if len(para_start_matches) == 1:
            chosen = para_start_matches[0]
        elif len(matches) == 1:
            chosen = matches[0]
        else:
            continue  # ambiguous on this page -- skip rather than guess
        insertions.append((chosen.start(), sanitize_hint(hint)))

    # apply back-to-front so earlier offsets stay valid
    for pos, hint in sorted(insertions, key=lambda t: t[0], reverse=True):
        page_text = page_text[:pos] + ENTRY_MARKER_TMPL.format(hint) + page_text[pos:]
    return page_text


BARE_PAGE_NUMBER_RE = re.compile(r"^\s*\**\s*(\d{1,4})\s*\**\s*$")
FURNITURE_WINDOW = 6  # non-empty lines at each end of a page to inspect


def strip_page_furniture(text: str, running_heads: list[str]):
    """Remove the running head and the bare printed page number from a
    page's Markdown, returning (cleaned_text, printed_page_or_None).

    These are artifacts of the printed page, not content: the running head
    repeats the owning entry's headword across the top of every page, and
    the page number is a bare integer on its own line. Both were being
    carried into the Markdown and then into entries' body_text -- 5,019
    page-number lines and 1,386 running heads corpus-wide. The page number
    is not discarded, it is promoted to the page marker, so provenance
    survives as METADATA rather than as text indistinguishable from
    content (docs/pipeline-strategy.md strategy #4, §5.4 step 1).

    Only the first/last FURNITURE_WINDOW non-empty lines are inspected, so
    a bare integer inside a formula or a numbered list mid-page is safe.
    """
    heads = {_norm_lemma(h) for h in running_heads}
    lines = text.split("\n")
    idx = [i for i, ln in enumerate(lines) if ln.strip()]
    edge = set(idx[:FURNITURE_WINDOW]) | set(idx[-FURNITURE_WINDOW:])
    printed_page = None
    drop = set()
    for i in edge:
        stripped = lines[i].lstrip("#").strip()
        m = BARE_PAGE_NUMBER_RE.match(stripped)
        if m is not None:
            if printed_page is None:
                printed_page = int(m.group(1))
            drop.add(i)
            continue
        if heads and _norm_lemma(stripped) in heads:
            drop.add(i)
    kept = [ln for i, ln in enumerate(lines) if i not in drop]
    return "\n".join(kept), printed_page


# A word the typesetter broke across a line arrives as "wissenschaftstheo-
# retisch" -- reflowed to "...theo- retisch" or "...theo-\nretisch". This
# is print layout, not text, and healing it HERE means no later stage has
# to compensate (three separate places used to; see
# docs/pipeline-strategy.md §5.0).
#
# German SUSPENDED hyphens are real text and must survive: "Ordinal- und
# Kardinalzahlen", "Lehr- und Lernsituation" (itself a headword). They are
# identified by the conjunction that follows. An uppercase continuation is
# a genuine compound ("Leib-" / "Seele-Problem") and is excluded by the
# pattern requiring a lowercase continuation.
SUSPENDED_HYPHEN_NEXT_WORDS = {
    "und", "oder", "bzw", "beziehungsweise", "sowie", "wie", "od", "u",
    "resp", "respektive",
}
# The whitespace between the hyphen and the continuation is REQUIRED, not
# optional. Allowing it to match empty was a silent-corruption bug of the
# exact kind ISSUES.md issues #6/#7/#9 keep recording: it ate the hyphen
# out of every ordinary compound too, turning "ad-hoc" into "adhoc" (31x),
# "nicht-euklidisch" into "nichteuklidisch" (110x) and
# "theologisch-philosophisch" into one word. A line break always leaves
# behind at least the space pymupdf4llm reflows it to, so requiring one
# costs nothing and confines the rule to actual line breaks.
HYPHEN_SPLIT_RE = re.compile(
    r"(?P<head>[A-Za-zÄÖÜäöüß])-(?:[ \t]*\n[ \t]*|[ \t]+)(?P<cont>[a-zäöüßſ]+)"
)


def heal_hyphenation(text: str) -> str:
    """Rejoin words broken across a line, keeping suspended hyphens."""
    def repl(m):
        if m.group("cont").lower() in SUSPENDED_HYPHEN_NEXT_WORDS:
            return m.group(0)
        return m.group("head") + m.group("cont")
    return HYPHEN_SPLIT_RE.sub(repl, text)


# Fallback gate for a volume with no body_start_page (there are none right
# now -- see VOLUME_OVERRIDES). Accepts any heading LEVEL: which level
# pymupdf4llm assigns depends on the other pages in the same
# to_markdown() call, so pinning "##" is a silent time bomb, and was one.
LETTER_HEADING_RE = re.compile(r"^#{1,3} [A-ZÄÖÜ]{1,3}\s*$", re.M)


def extract_one(pdf_path: Path, first_page: int = 1,
                last_page: "int | None" = None,
                out_path: "Path | None" = None) -> None:
    """Extract a volume, or (for `--pages`) a slice of one.

    A slice goes to its own file and never touches md-data, which makes it
    the cheap validation loop docs/pipeline-strategy.md strategy #2 asks
    for: extraction over 600-900 pages takes minutes, over 20 pages it
    takes seconds, and most changes here are answered by a handful of
    known pages (a Greek-etymology headword, a page with French
    bibliography, the front-matter boundary).

    Batches stay aligned to absolute PAGE_BATCH boundaries even for a
    slice. pymupdf4llm's heading LEVEL depends on which pages share a
    to_markdown() call (see pipeline-strategy.md strategy #2's caveat), so
    a misaligned slice can produce different Markdown than the real run
    does for the very same page.
    """
    out_path = out_path or MD_DIR / (pdf_path.stem + ".md")
    print(f"[extract] {pdf_path.name} -> {out_path.name}")

    overrides = VOLUME_OVERRIDES.get(pdf_path.stem, {})
    doc = patch_pdf_fonts(pdf_path)
    n = doc.page_count
    body_start_page = overrides.get("body_start_page")
    headword_font = overrides.get("headword_font", HEADWORD_FONT)

    lo = max(0, first_page - 1)
    hi = min(n, last_page if last_page is not None else n)
    # A slice that starts mid-volume has already missed the "## <Letter>"
    # heading that opens the body, so tag from the first sampled page --
    # the real run would have been in the body here long ago.
    in_body = lo > 0 and body_start_page is None
    tagged_pages = 0
    total_pages = 0
    with out_path.open("w", encoding="utf-8") as f:
        for start in range(lo - (lo % PAGE_BATCH), hi, PAGE_BATCH):
            batch = list(range(start, min(start + PAGE_BATCH, n)))
            page_chunks = pymupdf4llm.to_markdown(
                doc, pages=batch, page_chunks=True
            )
            for chunk in page_chunks:
                page_num = chunk["metadata"]["page_number"]  # 1-indexed
                text = chunk["text"]
                # outside the requested slice: present in the call so the
                # reflow matches the real run, but not written out
                if not (lo < page_num <= hi):
                    continue

                if not in_body:
                    if body_start_page is not None:
                        in_body = page_num >= body_start_page
                    elif LETTER_HEADING_RE.search(text):
                        in_body = True  # first "## <Letter>" -> lexicon body starts

                # Print-layout furniture comes off every page, body or
                # front matter, BEFORE anything is matched against the
                # text: while the running head was still present, a
                # headword's own anchor matched it as well as the real
                # headword and the entry was skipped as ambiguous.
                page_obj = doc[page_num - 1]
                running_heads = find_running_heads(page_obj, headword_font)
                text, printed_page = strip_page_furniture(text, running_heads)
                text = heal_hyphenation(text)

                if in_body:
                    candidates = find_entry_candidates(page_obj, headword_font)
                    candidates = merge_split_lemmas(candidates, running_heads)
                    if candidates:
                        text = inject_entry_markers(text, candidates)
                        tagged_pages += 1

                printed = "" if printed_page is None else f" printed:{printed_page}"
                f.write(f"\n\n<!-- page:{page_num}{printed} -->\n\n")
                f.write(text)
                total_pages += 1
            del page_chunks
            gc.collect()

    print(f"  done: {total_pages} pages, {tagged_pages} tagged, "
          f"{out_path.stat().st_size / 1024:.0f} KB")
    doc.close()
    cleanup_temp_pdfs()  # only removable once pymupdf has released the file


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("only", nargs="?", help="volume-name substring")
    ap.add_argument("--pages", help="PDF page range to sample, e.g. 380-400. "
                                    "Requires --out; md-data is never touched.")
    ap.add_argument("--out", help="output file for a --pages sample")
    args = ap.parse_args()

    if bool(args.pages) != bool(args.out):
        ap.error("--pages and --out go together (a sample must not overwrite md-data)")

    first, last = 1, None
    if args.pages:
        lo, _, hi = args.pages.partition("-")
        first, last = int(lo), int(hi or lo)

    pdfs = sorted(PDF_DIR.glob("Bd*.pdf"))
    if not pdfs:
        print("No PDFs found in", PDF_DIR)
        sys.exit(1)

    for pdf_path in pdfs:
        if args.only and args.only not in pdf_path.name:
            continue
        extract_one(pdf_path, first, last,
                    Path(args.out) if args.out else None)


if __name__ == "__main__":
    main()
