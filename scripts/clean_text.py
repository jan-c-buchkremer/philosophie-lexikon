"""Add a cleaned text layer to the structured entries.

The stage docs/pipeline-strategy.md §1 always named ("cleaned/normalized
JSONL") and never built. Reads structured-data/{volume}_entries.jsonl and
writes structured-data/{volume}_entries_clean.jsonl.

STRICTLY ADDITIVE: every field parse_entries.py produced is copied through
byte-identical, and new `*_clean` fields are added beside them. Nothing
downstream that reads `headword` or `body_text` can change behaviour, which
is what lets both golden suites keep meaning exactly what they meant before
this stage existed.

What "clean" means here, and what it deliberately does NOT mean:

  - Markdown emphasis and <sup> markup are removed or folded to plain text.
  - Transliteration diacritics that the typesetter set as superscripts are
    composed into real Unicode characters.
  - U+FFFD is LEFT EXACTLY AS IT IS, and merely counted. Every previous
    attempt in this project to guess at an unreadable glyph produced silent
    corruption (ISSUES.md issues #6, #7, #9); a visible gap beats a
    confident wrong letter, and a downstream consumer can see and count the
    gaps rather than trusting invented text.

Run via uv:
  uv run python scripts/clean_text.py [--only volume-substring]
"""
import argparse
import json
import re
import sys
import unicodedata
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from resolve_xrefs import normalize_key  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "structured-data"

REPLACEMENT = "�"

# --- 1. transliteration diacritics set as superscripts ---------------------
# The typesetter renders Indological transliteration by setting the
# combining mark as a superscript after the base letter, so "Āryadeva"
# arrives as "A<sup>¯</sup>ryadeva" and "Śri" as "S<sup>´</sup>ri". These
# are not exponents. Measured in body_text: 227 acute, 86 macron.
#
# Only composed when the preceding character is a LETTER -- anything else
# (a superscript mark after a digit, a bracket, a space) is left alone as a
# visible artifact rather than guessed at.
SUP_COMBINING = {
    "´": "́",  # acute      S´ -> Ś
    "¯": "̄",  # macron     A¯ -> Ā
    "˙": "̇",  # dot above
    "ˇ": "̌",  # caron
    "˜": "̃",  # tilde
}
SUP_DIACRITIC_RE = re.compile(
    r"(?P<base>[^\W\d_])<sup>(?P<mark>[" + "".join(SUP_COMBINING) + r"])</sup>"
)
# The same marks also arrive WITHOUT the <sup> wrapper. Headwords come from
# the PDF's own font spans while body text comes through pymupdf4llm's
# reflow, and only the reflow adds the markup -- so "Bhāvaviveka" is
# "Bha<sup>¯</sup>vaviveka" in a body but a bare "Bha¯vaviveka" in a
# headword.
#
# Measured before enabling this: in headwords these marks occur 102 times
# directly after a letter and ZERO times anywhere else, and the letter+mark
# pairs are exactly Indological/Slavic transliteration -- a¯ ī s´ ṅ ṁ ū ō č
# (also Bochen´ski -> Bocheński). Restricting to "directly after a letter"
# is what makes this safe; the 464 body-text marks that are NOT after a
# letter are left alone.
BARE_DIACRITIC_RE = re.compile(
    r"(?P<base>[^\W\d_])(?P<mark>[" + "".join(SUP_COMBINING) + r"])"
)
# "ı" + macron is "ī", but NFC only composes that from a DOTTED i, so the
# dotless form the typesetter used has to be restored first.
DOTLESS_I = {"ı": "i"}

# --- 2. remaining superscripts --------------------------------------------
# "<sup>2</sup>" -> "^2". The information is kept but the markup goes.
# NOTE it stays AMBIGUOUS on purpose: in a Literatur: citation "^2 1958"
# means the 2nd edition, in running prose "x^2" is an exponent, and the
# markup cannot tell them apart (structure-notes.md §4). Resolving that
# needs context, which is a later stage's problem, not this one's.
SUP_RE = re.compile(r"<sup>(.*?)</sup>", re.S)

# --- 3. emphasis -----------------------------------------------------------
# Paired matching, NOT blunt character deletion. parse_entries.py's
# strip_emphasis() deletes every "*" and "_", which is right for the
# headword comparisons it does but wrong here: underscores also occur
# inside formulas. Measured corpus-wide: 14,508 well-formed "_..._" pairs
# and only 151 stray underscores, which are left in place.
BOLD_RE = re.compile(r"\*\*(.+?)\*\*", re.S)
ITALIC_RE = re.compile(r"_([^_\n]{1,200})_")
STRAY_STARS_RE = re.compile(r"\*{1,2}")

# Underscore is not only an italic delimiter in this corpus -- it is also
# formula notation. Two distinct uses, both of which must survive:
#
#   "›__� P‹ (z.B. ›__ ist scheinend‹)"  a RUN of underscores is the
#                                        argument blank (Leerstelle) of an
#                                        Aussageform
#   "X^_ A"                              a modal operator
#
# A run of 2+ underscores is therefore atomic and is masked out before any
# pairing happens. Without that mask the italic regex pairs the INNER
# underscores of two separate blanks -- "__ ... __" -> "_ ... _" -- which
# both corrupts the notation and is not idempotent, since the surviving
# outer pair is then eaten by a second pass.
#
# After masking, italics are stripped only on lines with an EVEN number of
# remaining underscores, where every one can be accounted for as a
# delimiter. An odd count means the line still mixes emphasis with formula
# notation, and is left completely alone: visible markup beats a silently
# mangled formula, the same trade this project makes for U+FFFD.
UNDERSCORE_RUN_RE = re.compile(r"_{2,}")
RUN_SENTINEL = ""  # private-use area; cannot occur in the source text


def strip_italics(text: str) -> str:
    out = []
    for line in text.split("\n"):
        runs = []

        def stash(m):
            runs.append(m.group(0))
            return RUN_SENTINEL

        masked = UNDERSCORE_RUN_RE.sub(stash, line)
        if masked.count("_") and masked.count("_") % 2 == 0:
            masked = ITALIC_RE.sub(r"\1", masked)
        it = iter(runs)
        out.append(re.sub(RUN_SENTINEL, lambda _m: next(it), masked))
    return "\n".join(out)

WS_RE = re.compile(r"[ \t]+")


# TeX sets two of the symbols in the formula fonts as PAIRS of glyphs, and
# a ToUnicode table maps one glyph at a time (scripts/derive_tex_cmaps.py):
#   ↦  is the short bar 0x37 followed by the arrow 0x21; the bar is
#      mapped to ↦, so "↦→" is one symbol;
#   ⇋  is one harpoon set over another, so both arrive as ⇋.
# The negation slash (cmsy 0x36) is a combining character that TeX
# places BEFORE the symbol it strikes; Unicode wants it after.
TEX_PAIR_RE = re.compile(r"\u21a6\s*\u2192|\u21cb\s*\u21cb")
# Only a slash with nothing attached in front of it is moved: once it
# follows its symbol it is preceded by a non-space, and a second pass
# must leave it there (check_dataset.py: cleaning is idempotent).
NEG_SLASH_RE = re.compile(r"(?<!\S)\u0338\s*(\S)")


def join_tex_composites(text: str) -> str:
    out = TEX_PAIR_RE.sub(lambda m: m.group(0)[0], text)
    return NEG_SLASH_RE.sub(lambda m: m.group(1) + "\u0338", out)


NL_RE = re.compile(r"\n{3,}")


def compose_diacritics(text: str) -> str:
    def repl(m):
        base = DOTLESS_I.get(m.group("base"), m.group("base"))
        # NFC turns "A" + combining macron into the single character "Ā";
        # if no precomposed form exists the combining sequence survives,
        # which is still correct Unicode.
        return unicodedata.normalize("NFC", base + SUP_COMBINING[m.group("mark")])
    return BARE_DIACRITIC_RE.sub(repl, SUP_DIACRITIC_RE.sub(repl, text))


def clean(text: "str | None") -> "str | None":
    """Markup-free form of `text`. U+FFFD survives untouched."""
    if text is None:
        return None
    out = compose_diacritics(text)
    out = join_tex_composites(out)
    out = SUP_RE.sub(lambda m: "^" + m.group(1), out)
    out = BOLD_RE.sub(r"\1", out)
    out = strip_italics(out)
    out = STRAY_STARS_RE.sub("", out)
    out = WS_RE.sub(" ", out)
    out = NL_RE.sub("\n\n", out)
    return "\n".join(line.strip() for line in out.split("\n")).strip()


def clean_record(r: dict) -> dict:
    out = dict(r)  # every original field copied through unchanged
    out["headword_clean"] = clean(r["headword"])
    out["body_clean"] = clean(r["body_text"])
    out["werke_clean"] = clean(r["werke_raw"])
    out["literatur_clean"] = clean(r["literatur_raw"])
    out["lemma_key"] = normalize_key(out["headword_clean"])
    out["unreadable_chars"] = sum(
        (t or "").count(REPLACEMENT)
        for t in (r["body_text"], r["werke_raw"], r["literatur_raw"])
    )
    return out


def process(only: "str | None") -> None:
    paths = sorted(DATA_DIR.glob("Bd*_entries.jsonl"))
    if not paths:
        print("No *_entries.jsonl found in", DATA_DIR)
        sys.exit(1)

    grand = grand_unreadable = 0
    for path in paths:
        stem = path.stem.removesuffix("_entries")
        if only and only not in stem:
            continue
        out_path = DATA_DIR / f"{stem}_entries_clean.jsonl"
        n = unreadable = 0
        with out_path.open("w", encoding="utf-8") as f:
            for line in path.open(encoding="utf-8"):
                rec = clean_record(json.loads(line))
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
                n += 1
                unreadable += rec["unreadable_chars"]
        grand += n
        grand_unreadable += unreadable
        print(f"[clean] {path.name} -> {out_path.name}: {n} entries, "
              f"{unreadable} unreadable chars preserved")
    print(f"[clean] done: {grand} entries, {grand_unreadable} unreadable chars "
          f"(left as-is, never guessed)")


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--only", help="volume-name substring")
    args = ap.parse_args()
    process(args.only)


if __name__ == "__main__":
    main()
