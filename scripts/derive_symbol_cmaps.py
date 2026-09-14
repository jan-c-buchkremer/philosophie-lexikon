"""Repair the symbol fonts' ToUnicode tables from the fonts' own encodings.

WHY THIS EXISTS
---------------
Greek and mathematics are largely destroyed in the extracted text. Measured
across all eight PDFs, 42.9% of the characters set in the seven symbol
fonts are wrong -- 22,115 silently wrong (a Latin letter standing in for a
symbol) and 14,708 visible gaps. Only 71 Greek characters survive in the
whole corpus.

WHY IT IS A SEPARATE SCRIPT FROM derive_cmaps.py
------------------------------------------------
That one repairs the Latin TEXT fonts, and its method is a corpus word-vote
-- a headword rendered "abh<0x03>ngig" is read off the prose "abhängig"
elsewhere. That method has no traction here: a lone alpha in a formula has
no German word to vote on.

This script uses a different, deterministic source. The fonts name their
own glyphs in /Encoding /Differences, and where that name is "/C<n>", n is
a code point in THE FONT'S OWN ORIGINAL ENCODING:

    AdvOLDGRI   ISO-8859-7 (Greek)
    everything else   Adobe Symbol

derive_cmaps.py's docstring says this scheme "does not decode reliably",
having tested it against LATIN-1 for the Latin text fonts. That conclusion
is right for those fonts and wrong as a generalisation; the code page just
has to match the font. See ISSUES.md settled lesson #2.

Two structural facts make this safe and cheap:

  * The C-number is VOLUME-INDEPENDENT. It names a position in the original
    font, not in the subset, so one verified answer serves all six volumes
    even though each subset numbers its glyphs differently. There are only
    113 distinct (font, C-name) pairs in the entire corpus.
  * C-named codes are exactly the ones with no /ToUnicode entry, i.e. the
    ones now surfacing as U+FFFD. Verified corpus-wide: no C-named code
    decodes to a plausible character in any volume. So this script only
    ever fills gaps -- it never overwrites a mapping the font asserts,
    which is the case ISSUES.md says needs a human.

WHAT IT DOES NOT TOUCH
----------------------
The silently-wrong codes. Those carry ordinary Latin glyph names (/AE,
/Oslash) restating the corrupted ToUnicode, so they carry no information
and are left alone -- a visible gap beats a confident wrong letter, and
they are already wrong rather than absent.

Run via uv (writes into the same font_cmaps.json extract_markdown.py
already consumes, so nothing downstream changes):
  uv run python scripts/derive_symbol_cmaps.py [--only Bd02] [--dry-run]
"""
import argparse
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

import pymupdf

sys.path.insert(0, str(Path(__file__).resolve().parent))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parent.parent
PDF_DIR = ROOT / "pdf-data"
CMAP_PATH = Path(__file__).resolve().parent / "font_cmaps.json"
SYMBOL_PATH = Path(__file__).resolve().parent / "adobe_symbol_encoding.json"
SHEET_DIR = ROOT / "export" / "glyphs"

# Which code page each font's /C<n> numbers refer to. A font absent from
# here is not touched at all: guessing a code page is exactly the kind of
# plausible-looking assumption that produced this project's worst bugs.
#
# DELIBERATELY EXCLUDED -- AdvP4C4E46/51/59/74. They carry C-names too, but
# their numbers run 0-31 (plus a stray 131/138), which is outside Adobe
# Symbol's range entirely: Symbol starts at 32. Whatever those numbers
# index, it is not a code page established here, and the fonts hold ~4,400
# of the corpus's visible gaps -- too many to fill on a guess. They stay
# gaps until someone establishes their scheme.
CODE_PAGE = {
    "AdvOLDGRI": "iso-8859-7",   # 15/15 confirmed against rendered glyphs
    "AdvSY": "symbol",           # 7/7 confirmed against rendered glyphs
    # AdvMH3 is NOT here any more: its single C-name, C201, decoded to ⊃
    # under Adobe Symbol, and the rendered glyph (a ≡ with a vertical
    # stroke) says otherwise. derive_tex_cmaps.py owns that font now.
}

# Symbol reserves the Private Use Area for the pieces of stretchy brackets
# and integral signs -- glyph fragments with no character meaning. AGL maps
# them to U+F8xx, which would be a repair no better than the gap.
PRIVATE_USE = range(0xE000, 0xF900)

# A /Differences array can name a code that the text then uses for SPACING.
# Bd05's AdvOLDGRI names code 32 "/C215" -- chi -- and the page uses code 32
# as an ordinary word space, 363 times a volume. Mapping it would have put a
# chi in place of every one of those spaces.
#
# So a code is only mapped if it actually puts ink on the page. Measured by
# rendering: a real letter darkens 0.15-0.40 of its box, a space 0.01. The
# median across occurrences is used rather than the mean because a tight
# crop sometimes catches the edge of a neighbouring glyph.
MIN_INK = 0.05
INK_SAMPLES = 12

C_NAME_RE = re.compile(r"C(\d+)$")


def load_symbol_table() -> dict[int, str]:
    if not SYMBOL_PATH.exists():
        raise SystemExit(
            f"{SYMBOL_PATH.name} missing. Generate it once:\n"
            f"  uv run --with matplotlib python scripts/make_symbol_encoding.py"
        )
    return {int(k): v for k, v in json.loads(SYMBOL_PATH.read_text(encoding="utf-8")).items()}


def decode_c_name(name: str, code_page: str, symbol: dict[int, str]) -> "str | None":
    """The character a /C<n> glyph name stands for, or None."""
    m = C_NAME_RE.fullmatch(name)
    if not m:
        return None
    n = int(m.group(1))
    if not 0 <= n <= 255:
        return None
    if code_page == "symbol":
        char = symbol.get(n)
    else:
        try:
            char = bytes([n]).decode(code_page)
        except (UnicodeDecodeError, ValueError):
            return None
    if char is None:
        return None
    # A slot landing on ASCII, a control character or the Private Use Area
    # is not a symbol repair; leave those as gaps.
    return char if 0xA0 < ord(char) and ord(char) not in PRIVATE_USE else None


def differences(doc, xref) -> dict[int, str]:
    """The font's own code -> glyph-name table."""
    obj = doc.xref_object(xref).replace("\n", " ")
    m = re.search(r"/Encoding (\d+) 0 R", obj)
    if not m:
        return {}
    enc = doc.xref_object(int(m.group(1))).replace("\n", " ")
    d = re.search(r"/Differences \[(.*?)\]", enc, re.S)
    if not d:
        return {}
    table, code = {}, None
    for tok in d.group(1).split():
        if tok.isdigit():
            code = int(tok)
        elif tok.startswith("/") and code is not None:
            table[code] = tok[1:]
            code += 1
    return table


def scan_volume(path: Path, symbol: dict[int, str]):
    """Returns (mapping, occurrences, samples) for one volume.

    `mapping`  font -> {byte: character}
    `samples`  (font, byte) -> (page, bbox) for the contact sheet
    """
    doc = pymupdf.open(path)
    encodings: dict[str, dict[int, str]] = {}
    seen_xrefs = set()

    for pno in range(len(doc)):
        for f in doc[pno].get_fonts(full=True):
            xref, short = f[0], f[3].split("+")[-1]
            if short in CODE_PAGE and xref not in seen_xrefs:
                seen_xrefs.add(xref)
                encodings.setdefault(short, {}).update(differences(doc, xref))

    mapping: dict[str, dict[int, str]] = defaultdict(dict)
    for font, table in encodings.items():
        for code, name in table.items():
            char = decode_c_name(name, CODE_PAGE[font], symbol)
            if char is not None:
                mapping[font][code] = char

    # Count how often each candidate byte occurs, and collect places to
    # crop it from -- for the ink test and for the contact sheet.
    occurrences: Counter = Counter()
    places: dict = defaultdict(list)
    for pno in range(len(doc)):
        for blk in doc[pno].get_text("rawdict")["blocks"]:
            for line in blk.get("lines", []):
                for span in line["spans"]:
                    font = span["font"].split("+")[-1]
                    if font not in mapping:
                        continue
                    for ch in span["chars"]:
                        code = ord(ch["c"])
                        if code in mapping[font]:
                            occurrences[(font, code)] += 1
                            if len(places[(font, code)]) < INK_SAMPLES:
                                places[(font, code)].append((pno, ch["bbox"]))

    # Drop anything the page does not actually draw.
    blank = []
    for font, table in mapping.items():
        for code in list(table):
            if _ink(doc, places.get((font, code), [])) < MIN_INK:
                blank.append((font, code, table.pop(code)))

    samples = {k: v[0] for k, v in places.items()}
    doc.close()
    return dict(mapping), occurrences, samples, blank


def _ink(doc, places) -> float:
    """Median share of dark pixels across sampled occurrences of a code."""
    if not places:
        return 0.0
    shares = []
    for pno, bbox in places:
        rect = pymupdf.Rect(bbox)
        if rect.is_empty or rect.width < 0.5 or rect.height < 0.5:
            shares.append(0.0)
            continue
        pix = doc[pno].get_pixmap(clip=rect, dpi=200, colorspace=pymupdf.csGRAY)
        total = pix.width * pix.height
        if not total:
            shares.append(0.0)
            continue
        dark = sum(1 for i in range(0, total * pix.n, pix.n) if pix.samples[i] < 128)
        shares.append(dark / total)
    shares.sort()
    return shares[len(shares) // 2]


def write_sheet(path: Path, pdf: Path, font: str, mapping, occurrences, samples):
    """Every repaired glyph beside the character now claimed for it.

    Reviewing this is optional -- the mapping is deterministic -- but it is
    the only thing that would catch a wrong code page, and it is the
    arbiter this project already uses for font questions.
    """
    entries = sorted(mapping.items(), key=lambda kv: -occurrences.get((font, kv[0]), 0))
    if not entries:
        return
    doc = pymupdf.open(pdf)
    cols, cw, rh = 8, 84, 96
    out = pymupdf.open()
    sheet = out.new_page(width=cols * cw + 24, height=((len(entries) + cols - 1) // cols) * rh + 32)
    label_font = next((p for p in (r"C:\Windows\Fonts\seguisym.ttf",
                                   r"C:\Windows\Fonts\cambria.ttc",
                                   r"C:\Windows\Fonts\times.ttf") if Path(p).exists()), None)

    for i, (code, char) in enumerate(entries):
        x, y = 12 + (i % cols) * cw, 16 + (i // cols) * rh
        if (font, code) in samples:
            pno, bbox = samples[(font, code)]
            pix = doc[pno].get_pixmap(clip=pymupdf.Rect(bbox), dpi=400)
            sheet.insert_image(pymupdf.Rect(x + 18, y, x + cw - 18, y + 40),
                               pixmap=pix, keep_proportion=True)
        sheet.insert_text((x + 2, y + 58), f"{code}  ×{occurrences.get((font, code), 0)}", fontsize=7)
        try:
            sheet.insert_text((x + 2, y + 78), char, fontsize=17,
                              fontfile=label_font, fontname="lbl")
        except Exception:
            sheet.insert_text((x + 2, y + 78), f"U+{ord(char):04X}", fontsize=8)
    path.parent.mkdir(parents=True, exist_ok=True)
    sheet.get_pixmap(dpi=150).save(path)
    doc.close()


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--only", help="volume substring filter")
    ap.add_argument("--dry-run", action="store_true", help="report, do not write font_cmaps.json")
    ap.add_argument("--no-sheets", action="store_true")
    args = ap.parse_args()

    symbol = load_symbol_table()
    cmaps = json.loads(CMAP_PATH.read_text(encoding="utf-8")) if CMAP_PATH.exists() else {}

    total_new = total_chars = 0
    dropped: list = []
    print(f"{'volume':<14}{'font':<12}{'repaired':>9}{'chars':>9}  code page")
    for pdf in sorted(PDF_DIR.glob("*.pdf")):
        vol = pdf.stem
        if args.only and args.only not in vol:
            continue
        mapping, occurrences, samples, blank = scan_volume(pdf, symbol)
        dropped += [(vol, f, c, ch, occurrences.get((f, c), 0)) for f, c, ch in blank]
        for font, table in sorted(mapping.items()):
            chars = sum(occurrences.get((font, c), 0) for c in table)
            total_new += len(table)
            total_chars += chars
            print(f"{vol:<14}{font:<12}{len(table):>9}{chars:>9}  {CODE_PAGE[font]}")

            existing = cmaps.setdefault(vol, {}).setdefault(font, {})
            # Same shape derive_cmaps.py writes and extract_markdown.py's
            # load_font_cmaps() reads: hex-string byte -> integer code
            # point. Never overwrite an entry another stage established.
            for code, char in table.items():
                existing.setdefault(f"0x{code:02x}", ord(char))

            if not args.no_sheets:
                write_sheet(SHEET_DIR / f"{vol}_{font}.png", pdf, font,
                            table, occurrences, samples)

    if dropped:
        print(f"\nrejected as blank (the code is used for spacing, not a glyph):")
        for vol, font, code, char, n in sorted(dropped, key=lambda d: -d[4]):
            print(f"  {vol:<14}{font:<12}code {code:>3} would have become {char!r} in {n} places")

    print(f"\n{total_new} byte mappings across all volumes, "
          f"covering {total_chars} characters in the corpus")
    if args.dry_run:
        print("dry run - font_cmaps.json not written")
        return 0
    CMAP_PATH.write_text(json.dumps(cmaps, ensure_ascii=False, indent=1, sort_keys=True),
                         encoding="utf-8")
    print(f"wrote {CMAP_PATH}")
    if not args.no_sheets:
        print(f"contact sheets in {SHEET_DIR}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
