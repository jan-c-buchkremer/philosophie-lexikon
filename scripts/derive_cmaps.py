"""Derive per-font-object ToUnicode repairs empirically, and cache them
in scripts/font_cmaps.json for scripts/extract_markdown.py to apply.

WHY THIS EXISTS
---------------
The volume PDFs (3B2/Arbortext) embed SUBSET fonts whose /ToUnicode CMaps
omit the accented characters: extraction yields a raw control byte where
"ä" should be. The original fix hardcoded one byte->character table and
applied it to every font whose name started with "Adv".

That is unsound, and produced three separate silent-corruption bugs (see
ISSUES.md). Subset fonts number their glyphs independently, per subset,
as the typesetter encounters them -- so the same byte means different
characters in different fonts, in different volumes, and even in
different subsets of the same font within one volume. Measured:

    byte 0x02  = "ü" in Bd01's AdvGILLSBC        (Abkürzungs-)
    byte 0x03  = "ä" in Bd01's AdvGILLSBC        (abhängig)
    byte 0x05  = "Ä" in Bd01's AdvGILLSBC        (Ähnlichkeit)
    byte 0x05  = "á" in Bd06's AdvGILLSBC        (Palágyi)      <-- differs
    byte 0x06  = "è" in Bd01's AdvGILLSBC        (Ampère)
    byte 0x06  = "ò" in one Bd06 subset          (Piccolòmini)  <-- differs

The fonts' own /Encoding /Differences arrays name these glyphs /C252,
/C143 and so on. Against LATIN-1 that scheme does not decode reliably
(C252/C228 happen to match ü/ä, but C143/C190 do not match ë/Ä), so it is
no help for the Latin text fonts this script repairs.

It is NOT useless in general, which took a while to see: the number is a
code point in *the font's own original encoding*, and Latin-1 is simply
the wrong one for these. It decodes exactly for the symbol fonts, given
the right code page per font -- ISO-8859-7 for the Greek AdvOLDGRI,
Adobe Symbol for AdvSY and its relatives. That is a different method for
a different family of fonts, and it lives in derive_symbol_cmaps.py;
see ISSUES.md settled lesson #2.

METHOD
------
The corpus is its own ground truth. A headword rendered "abh<0x03>ngig"
also occurs hundreds of times as ordinary prose "abhängig", set in the
roman body font whose mapping is known good. So: for each font object,
take the words containing exactly one untrusted position, look the same
word up in the reference corpus, and read off the character sitting
there. Votes are weighted by occurrence and must clear a confidence
floor AND beat the runner-up by a margin.

"Untrusted" covers two cases, not one: a byte with no ToUnicode entry
(surfaces as a control character), and a byte the font maps to something
positively WRONG (see SUSPECT_CHARS -- several fonts claim "ç" where the
glyph is "ö", which never looks unmapped and so hid for a long time).

The reference corpus must come from OUTSIDE the pipeline, or it confirms
its own mistakes. It is read unpatched from Bd07/Bd08, whose MinionPro
CMaps are correct and need no repair (see CLEAN_CORPUS_VOLUMES). Earlier
versions used patched Adv* text from all eight volumes; that is circular,
and it measurably went wrong -- "Lukôcs" outvoted "Lukács" 79 to 15,
because 79 of those were the corruption under test.

Anything that does not clear the floor is deliberately left OUT of the
table. extract_markdown.py then leaves that byte unmapped, so it surfaces
as a visible replacement character rather than as a plausible-looking
wrong letter. That is the property that actually kills this bug class: a
visible gap is honest and findable, silent corruption is neither.

Run via uv (slow on a cold cache -- it scans every PDF once to build the
reference corpus, then caches it; the output is committed as data):
  uv run --with pymupdf4llm --with pikepdf python scripts/derive_cmaps.py \
      [--only Bd01] [--page-step 3]
"""
import argparse
import json
import re
from collections import Counter, defaultdict
from pathlib import Path

import pymupdf

import sys
sys.path.insert(0, str(Path(__file__).resolve().parent))

ROOT = Path(__file__).resolve().parent.parent
PDF_DIR = ROOT / "pdf-data"
MD_DIR = ROOT / "md-data"
OUT_PATH = Path(__file__).resolve().parent / "font_cmaps.json"

# Acceptance floor. Votes are weighted by OCCURRENCE, not by distinct
# word: the same word usually appears once as a corrupted headword and
# many times as correct body prose, so per-word voting has each word
# voting for both readings and nothing ever clears 50%.
MIN_OCCURRENCES = 5      # winner must have at least this much evidence
MIN_CONFIDENCE = 0.55    # winner's share of all votes for that byte
MIN_MARGIN = 2.0         # winner must beat the runner-up by this factor

# We are repairing ACCENTED LATIN glyphs specifically. A vote for a plain
# ASCII letter is pattern-matching noise (the wildcard matched an
# unrelated word), and a vote for a Greek letter means we strayed into a
# symbol font, whose unmapped bytes are not diacritics at all and must be
# left alone -- the existing pipeline deliberately skips those.
ACCENTED_LATIN = set(
    "äöüÄÖÜß"
    "áàâãåéèêëíìîïóòôõúùûçñýÿ"
    "ÁÀÂÃÅÉÈÊËÍÌÎÏÓÒÔÕÚÙÛÇÑ"
    "½¼¾"
)

# A word, for evidence purposes. The separator class is spelled out
# instead of using "\s", and that is the whole point: Python's \s matches
# TAB (0x09), VT (0x0b), FF (0x0c) and CR (0x0d), and this typesetter
# hands out exactly those codes as ordinary glyph numbers. With "\s" here,
# any glyph unlucky enough to land on one was split off as though it were
# a space, so its word never had "exactly one unknown position" and the
# byte could never collect a single vote -- invisible to the derivation,
# permanently. Measured cost of that blind spot: Bd02/Bd03 0x0b = "Ä"
# ("Ästhetik", "Äquivalenz", "Ähnlichkeit"), 0x09 = "è" ("siècle"),
# Bd05 0x0b = "è" and 0x09 = "É" ("Études") -- around 2,100 characters
# corpus-wide, silently mis-mapped for as long as a table happened to
# cover them and silently blank afterwards.
#
# Real word breaks in this text are plain spaces; a control code inside a
# span is a glyph, not a break. If a genuine 0x0d line break does end up
# inside one, the two halves simply join into a token that matches nothing
# in the corpus and casts no vote -- the safe direction to be wrong in.
WORD_RE = re.compile(r"[^ \n,;:()\[\]/›‹↑»«\"]+")
UNMAPPED_MAX = 0x20  # pymupdf passes an unmapped byte through as a control char

# Deliberately EMPTY, and worth explaining.
#
# Not all breakage here is a missing entry: some fonts positively assert
# the WRONG character, so nothing looks unmapped (0xE7 claims "ç" where
# the glyph is "ö" -- "Schildkrçte", "çkonomische"). It is tempting to
# re-test such characters against the corpus like any unmapped byte, and
# that was tried. It is not safe, for a reason specific to this data:
# pymupdf reports a span's font WITHOUT its subset tag, so every subset
# of a family looks identical here, and a family cannot be judged as a
# unit. Bd07/08's MinionPro-Regular then gets its perfectly legitimate ç
# ("Leçons", "français", "sçavans") re-tested and "corrected" to "Å" on
# 44 unanimous votes -- confident, automatic, and wrong, which is exactly
# what this rewrite exists to prevent.
#
# So wrongly-mapped bytes are NOT auto-derived. They go in
# extract_markdown.py's MANUAL_VOLUME_FONT_FIXES, per (volume, font),
# after looking at the glyph or the surrounding words. Overriding what a
# font actively claims is a strong enough assertion to deserve a human.
SUSPECT_CHARS: set = set()

CMAP_BFCHAR_RE = re.compile(r"<([0-9A-Fa-f]{2})>\s*<([0-9A-Fa-f]{4,6})>")
CMAP_BFRANGE_RE = re.compile(
    r"<([0-9A-Fa-f]{2})>\s*<([0-9A-Fa-f]{2})>\s*<([0-9A-Fa-f]{4,6})>"
)


def font_char_to_byte(pdf_path: Path) -> dict:
    """{font_family: {character: byte}} from each font's own ToUnicode.

    Needed to act on SUSPECT_CHARS: the extractor hands us the (wrong)
    character the font claims, but a repair has to be expressed as a byte
    code, so we invert the font's own table to find which byte produced
    it.
    """
    import pikepdf

    out = defaultdict(dict)
    pdf = pikepdf.open(str(pdf_path))
    for obj in pdf.objects:
        try:
            if obj.get("/Type") != pikepdf.Name("/Font"):
                continue
            if "/ToUnicode" not in obj:
                continue
            family = str(obj.get("/BaseFont", "")).split("+")[-1]
            text = obj["/ToUnicode"].read_bytes().decode("latin1")
        except Exception:
            continue
        mapping = {}
        for lo, hi, start in CMAP_BFRANGE_RE.findall(text):
            base = int(start, 16)
            for offset in range(int(hi, 16) - int(lo, 16) + 1):
                mapping[int(lo, 16) + offset] = chr(base + offset)
        for code, target in CMAP_BFCHAR_RE.findall(text):
            mapping[int(code, 16)] = chr(int(target, 16))
        for byte, char in mapping.items():
            out[family].setdefault(char, byte)
    pdf.close()
    return out


CORPUS_WORD_RE = re.compile(r"[A-Za-zÄÖÜäöüß" + "".join(sorted(ACCENTED_LATIN)) + r"]{2,}")


# The ground-truth volumes. Bd07/Bd08 are set in MinionPro, whose
# ToUnicode CMaps are complete and correct: they need no repair at all
# (font_cmaps.json holds nothing for either), and that is exactly what
# qualifies them to judge the volumes that do. Roughly 1.0M words, 16k
# distinct accented forms -- enough German philosophical vocabulary, plus
# the French and Spanish of the bibliographies, to resolve most bytes.
#
# Any earlier corpus was downstream of the repair it was meant to verify:
# it was built from PATCHED documents, so wherever the table was wrong,
# the corpus contained the wrong spelling and voted for it. Measured on
# the output that shipped: "Lukôcs" occurs 79 times corpus-wide against
# 15 for the correct "Lukács", and Bd06's "razën" 4 against 2 for
# "razón". The derivation was confirming its own corruption, which is how
# Bd05's 0x13 came out as "ô" (it is "á") and Bd06's 0x11 as "ë" (it is
# "ó"). Ground truth has to come from outside the thing being tested.
CLEAN_CORPUS_VOLUMES = ("Bd07_Re-Te", "Bd08_Th-Z")
UNSAFE_WORD_RE = re.compile(r"[\x00-\x1f�]")
CORPUS_CACHE_PATH = Path(__file__).resolve().parent / ".reference_corpus.json"

_CORPUS_CACHE: "dict[str, int] | None" = None


def corpus_word_counts(page_step: int) -> "dict[str, int]":
    """Word frequencies from the CLEAN_CORPUS_VOLUMES, read unpatched.

    Unpatched on purpose: those volumes' body font needs no repair, and
    reading them raw guarantees nothing this pipeline produced can leak
    back in as evidence. Their own Adv* spans (Bd07/08 do still contain
    one) come through with control characters and are dropped by
    UNSAFE_WORD_RE, so what survives is text the PDF itself spells
    correctly.

    md-data is not usable here either, for the same reason at one remove:
    it is this pipeline's output.
    """
    global _CORPUS_CACHE
    if _CORPUS_CACHE is not None:
        return _CORPUS_CACHE
    if CORPUS_CACHE_PATH.exists():
        _CORPUS_CACHE = json.loads(CORPUS_CACHE_PATH.read_text(encoding="utf-8"))
        return _CORPUS_CACHE

    counts = defaultdict(int)
    for stem in CLEAN_CORPUS_VOLUMES:
        pdf_path = PDF_DIR / f"{stem}.pdf"
        print(f"  [corpus] scanning {stem} (unpatched, clean ground truth)")
        doc = pymupdf.open(str(pdf_path))
        for pno in range(0, doc.page_count, page_step):
            for block in doc[pno].get_text("dict")["blocks"]:
                if "lines" not in block:
                    continue
                for line in block["lines"]:
                    for span in line["spans"]:
                        text = span["text"]
                        if UNSAFE_WORD_RE.search(text):
                            continue
                        for word in CORPUS_WORD_RE.findall(text):
                            counts[word] += 1
        doc.close()
    print(f"  [corpus] {sum(counts.values()):,} words, {len(counts):,} distinct")
    CORPUS_CACHE_PATH.write_text(json.dumps(counts, ensure_ascii=False), encoding="utf-8")
    _CORPUS_CACHE = counts
    return _CORPUS_CACHE


def stitch_spans(spans: list) -> list:
    """Merge runs of consecutive spans that share a font into (font, text)."""
    out = []
    for span in spans:
        text = "".join(c["c"] for c in span["chars"])
        if out and out[-1][0] == span["font"]:
            out[-1] = (span["font"], out[-1][1] + text)
        else:
            out.append((span["font"], text))
    return out


def derive_for_volume(pdf_path: Path, page_step: int) -> dict:
    """Return {basefont_with_subset_tag: {byte: codepoint}}."""
    doc = pymupdf.open(str(pdf_path))

    char_to_byte = font_char_to_byte(pdf_path)

    def unknown_positions(word: str, font: str) -> list:
        """Positions we cannot trust: an unmapped byte, or a mapped byte
        whose claimed character is on the suspect list."""
        out = []
        for i, ch in enumerate(word):
            if ord(ch) < UNMAPPED_MAX:
                out.append((i, ord(ch)))
            elif ch in SUSPECT_CHARS and ch in char_to_byte.get(font, {}):
                out.append((i, char_to_byte[font][ch]))
        return out

    # Second-guessing a character the font positively ASSERTS is a much
    # stronger claim than filling a gap it left blank, so it is gated on
    # the font having demonstrated brokenness independently -- i.e. on it
    # having at least one genuinely unmapped byte somewhere. Without this
    # gate the ç test fires on Bd07/08's MinionPro-Regular, whose CMap is
    # complete and whose ç is entirely legitimate ("Leçons", "français",
    # "sçavans"), and "derives" a confident, unanimous, wrong answer --
    # exactly the kind of silent corruption this rewrite exists to stop.
    fonts_with_unmapped = set()
    needed_unmapped = defaultdict(set)
    needed_suspect = defaultdict(set)
    for pno in range(0, doc.page_count, page_step):
        for block in doc[pno].get_text("rawdict")["blocks"]:
            if "lines" not in block:
                continue
            for line in block["lines"]:
                # Stitch consecutive same-font spans before splitting into
                # words. A PDF routinely breaks a word into several spans
                # (often exactly AT the accented glyph), and the resulting
                # fragments -- "\x02cher" out of "Wörterbücher" -- match
                # nothing in the corpus, silently starving that byte of
                # evidence.
                for font, text in stitch_spans(line["spans"]):
                    if not any(ord(c) < UNMAPPED_MAX or c in SUSPECT_CHARS
                               for c in text):
                        continue
                    if any(ord(c) < UNMAPPED_MAX for c in text):
                        fonts_with_unmapped.add(font)
                    for m in WORD_RE.finditer(text):
                        word = m.group()
                        unknown = unknown_positions(word, font)
                        if len(unknown) != 1 or len(word) < 4:
                            continue
                        i, code = unknown[0]
                        bucket = (needed_unmapped if ord(word[i]) < UNMAPPED_MAX
                                  else needed_suspect)
                        bucket[(word[:i], word[i + 1:])].add((font, code))
    doc.close()

    needed = defaultdict(set, {k: set(v) for k, v in needed_unmapped.items()})
    for key, entries in needed_suspect.items():
        for font, code in entries:
            if font in fonts_with_unmapped:
                needed[key].add((font, code))

    # Resolve every needed slot in one pass over the corpus vocabulary,
    # rather than re-scanning the text per candidate word.
    per_key = defaultdict(Counter)
    for word, n in corpus_word_counts(page_step).items():
        for i, ch in enumerate(word):
            if ch not in ACCENTED_LATIN:
                continue
            key = (word[:i], word[i + 1:])
            if key in needed:
                per_key[key][ch] += n

    # Drop keys that cannot decide CASE, before they get a vote.
    #
    # German writes both "über" and "Über", so the key ("", "ber") offers
    # the corpus's own ü and Ü in whatever ratio those two words happen to
    # occur -- around 60/40, which is noise about frequency, not evidence
    # about a glyph. And "über" is common enough to outvote every
    # unambiguous word for the same byte put together: Bd05's 0x04 and
    # Bd06's 0x07 are plainly "Ü" ("Übersetzung", "Überlegungen",
    # "Übergang" -- no lower-case reading exists) yet both were rejected
    # at 61%/1.6x on the strength of it. Keys like ("", "bergang"), where
    # the corpus knows exactly one case, decide the same byte outright.
    #
    # So a key whose corpus candidates include both cases of one letter is
    # silent here rather than misleading. Nothing else changes: the floor,
    # confidence and margin still apply to what remains.
    evidence = defaultdict(lambda: defaultdict(lambda: defaultdict(int)))
    for key, candidates in per_key.items():
        if any(ch.swapcase() in candidates for ch in candidates):
            continue
        for font, code in needed[key]:
            for ch, n in candidates.items():
                evidence[font][code][ch] += n

    tables = {}
    for font, codes in sorted(evidence.items()):
        table = {}
        lines = []
        for code, candidates in sorted(codes.items()):
            ranked = sorted(candidates.items(), key=lambda kv: -kv[1])
            best, n_best = ranked[0]
            n_total = sum(n for _, n in ranked)
            runner_up = ranked[1][1] if len(ranked) > 1 else 0
            conf = n_best / n_total if n_total else 0
            margin = n_best / runner_up if runner_up else float("inf")
            ok = (n_best >= MIN_OCCURRENCES and conf >= MIN_CONFIDENCE
                  and margin >= MIN_MARGIN)
            lines.append(
                f"      0x{code:02x} -> {best!r} U+{ord(best):04X}  "
                f"{n_best}/{n_total} ({conf:.0%}, {margin:.1f}x)"
                f"{'' if ok else '   REJECTED -> left unmapped'}"
            )
            if ok:
                table[f"{code:#04x}"] = ord(best)
        if lines:
            print(f"    [{font}]")
            for line in lines:
                print(line)
        if table:
            tables[font] = table
    return tables


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", help="only this volume-name substring")
    ap.add_argument("--page-step", type=int, default=1,
                    help="sample every Nth page (1 = every page, most evidence)")
    args = ap.parse_args()

    existing = {}
    if OUT_PATH.exists():
        existing = json.loads(OUT_PATH.read_text(encoding="utf-8"))

    for pdf_path in sorted(PDF_DIR.glob("Bd*.pdf")):
        if args.only and args.only not in pdf_path.name:
            continue
        print(f"[derive] {pdf_path.name}")
        existing[pdf_path.stem] = derive_for_volume(pdf_path, args.page_step)

    OUT_PATH.write_text(
        json.dumps(existing, indent=2, ensure_ascii=False, sort_keys=True),
        encoding="utf-8",
    )
    total = sum(len(t) for v in existing.values() for t in v.values())
    print(f"[derive] wrote {total} byte mappings across "
          f"{sum(len(v) for v in existing.values())} font objects -> {OUT_PATH}")


if __name__ == "__main__":
    main()
