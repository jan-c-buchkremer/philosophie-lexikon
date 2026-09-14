"""Repair the formula fonts' ToUnicode tables: they are TeX fonts.

WHY THIS EXISTS
---------------
After derive_symbol_cmaps.py, the mathematics in the corpus was still
~half wrong and all of it silent: `AdvP4C4E74`, `AdvP4C4E51` and
`AdvP4C4E59` carry ordinary Latin glyph names, so "p ! O" stood where
"p → O" was printed, "9x" for "∃x", "VðAÞ ¼" for "𝒱(A) =". ISSUES.md open
issue #1 left them alone because their `/C<n>` numbers run 0-31, outside
every code page tried, and nothing was known about what they index.

WHAT THEY ARE
-------------
Computer Modern. The typesetter (3B2) embedded Knuth's TeX fonts under
its own names and generated glyph names from StandardEncoding positions:

    AdvP4C4E74   cmsy    OMS "math symbols"   ∈ ∀ ∃ ¬ ∧ ∨ ⇒ ⊆ ⟨ ⟩ ...
    AdvP4C4E51   cmmi    OML "math italic"    α β γ ... , . / < >
    AdvP4C4E59   cmr     OT1 "text"           Γ Δ Σ ... ! & . : ; accents
    AdvP4C4E46   cmex    delimiter PIECES     (not repaired -- see below)
    AdvMH3       four big operators           ⋀ ⋁ ⩓ ⩔

So the byte at 0x21 is named /exclam and decoded "!", but the glyph at
OMS position 0x21 is →. The `/C<n>` names are the same story as the
Greek font: n is the position in the ORIGINAL font, and it is the glyphs
from the control range (0x00-0x1F, which PDF text cannot carry cleanly)
that were relocated to bytes 2-20 and named by where they came from. A
handful of glyphs from OTHER fonts were relocated into the 0x80-0xFF range
of `AdvP4C4E74` -- cmr's ( ) = [ ] + as ð Þ ¼ ½ Ð þ -- and those are
subset-specific, so they are listed per volume, verified by eye.

Every hypothesis here was checked against rendered glyphs before it was
written (Bd05, 55/55 for cmsy, 26/26 for cmmi, 18/18 for cmr), and the
contact sheets in export/glyphs/ show every mapped code beside the
character claimed for it, per volume, so the check can be repeated.

WHAT IT DOES NOT TOUCH
----------------------
`AdvP4C4E46` is cmex: the pieces of stretchy parentheses, radicals and
integral signs. They have no character meaning -- a formula's layout is
out of scope by construction (ISSUES.md #4) -- and mapping a rule
segment to anything would be a repair no better than the wrong letter.
Left alone.

Two TeX composites cannot be expressed in a ToUnicode table and are
finished by clean_text.py: ↦ is set as 0x37 (the short bar) + 0x21 (→),
and ⇋ as two harpoons (cmmi 0x28 over 0x2B). The bar and both harpoons
are mapped to the whole symbol here, and the doubled result is collapsed
there.

Run via uv (writes into the same font_cmaps.json extract_markdown.py
already consumes; overwrites only the fonts named above):
  uv run python scripts/derive_tex_cmaps.py [--only Bd02] [--dry-run] [--no-sheets]
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

from derive_symbol_cmaps import INK_SAMPLES, differences  # noqa: E402
from tex_encodings import TABLES  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
PDF_DIR = ROOT / "pdf-data"
CMAP_PATH = Path(__file__).resolve().parent / "font_cmaps.json"
SHEET_DIR = ROOT / "export" / "glyphs"

FONT_ENCODING = {
    "AdvP4C4E74": "OMS",
    "AdvP4C4E51": "OML",
    "AdvP4C4E59": "OT1",
}

# Glyphs that are not at a TeX position: relocated from another font, or
# named C<n> with n beyond the 128 the encoding has. Each entry was read
# off a rendered glyph in context. Keyed on the font's own glyph NAME, not
# the byte, because the name is what identifies the glyph across subsets;
# the byte it lands on differs per volume and is looked up at run time.
VERIFIED_BY_NAME = {
    "AdvP4C4E74": {
        "eth": "(", "Thorn": ")", "onequarter": "=", "onehalf": "[",
        "thorn": "+",
        "Eth": "\u21cb",         # ⇋  "[x] ⇋ [", definitional equivalence (Bd05 p.25)
        "quoteleft": "\u22a2",   # ⊢  "⊢⊢K"
        "C131": "\u22a8",        # ⊨  "M, t ⊨ Sφψ"
        "C138": "]",             # pairs with onehalf "[" -- 73/73 in Bd05, 26/26 in Bd03
    },
    "AdvP4C4E51": {
        "quoteright": "\u03c6",  # φ  varphi (OML 0x27) relocated; "Hüllenoperation φM"
    },
    "AdvP4C4E59": {
        "Euro": "\u00a8",        # ¨  diaeresis accent (OT1 0x7F) relocated; "ẍ"
    },
}

# The two halves of a composite; see the docstring.
COMPOSITE = {
    ("AdvP4C4E51", 0x28): "\u21cb",  # ↼ over
    ("AdvP4C4E51", 0x2B): "\u21cb",  # ⇁  = ⇋
}

# AdvMH3 is not a TeX font. Its glyphs, read off the page (Bd05 p.19 lists
# them as notation): the n-ary connectives. The C201 glyph -- a ≡ with a
# vertical stroke -- had been mapped to ⊃ by derive_symbol_cmaps.py's
# Adobe-Symbol assumption, which the rendering contradicts; it is now the
# only code of this font left as a gap.
ADVMH3_BY_NAME = {
    "asciitilde": "\u22c1",      # ⋁
    "quoteleft": "\u22c0",       # ⋀
    "grave": "\u2a53",           # ⩓
    "quotedblleft": "\u2a54",    # ⩔
    "bar": "\u22ab",             # ⊫  "⊫ ⊢K" (Bd01 p.23, Bd04 p.18)
    "L": "\u02c6",               # ˆ  a wide hat set over a whole word ("falsch", Bd01 p.459)
}

# derive_symbol_cmaps.py rejects a code that draws no ink, because a
# /Differences entry can name a code the text uses as a word space. Its
# threshold (0.05 of the box) was set for letters; the symbols here are
# thin -- an arrow darkens 0.047 of its box, a minus 0.027, a period
# 0.023 -- while a real space measures 0.000-0.005. Two glyphs, the
# negation slash and the ↦ bar, have ZERO advance width in TeX, so their
# boxes are empty and cannot be measured; a space always has an advance,
# so an unmeasurable code is kept.
MIN_INK = 0.012

C_NAME_RE = re.compile(r"C(\d+)$")
BFCHAR_RE = re.compile(r"<([0-9a-fA-F]{2})>\s*<([0-9a-fA-F]{4,8})>")
BFRANGE_RE = re.compile(r"<([0-9a-fA-F]{2})>\s*<([0-9a-fA-F]{2})>\s*<([0-9a-fA-F]{4,8})>")


def tex_char(font: str, code: int, name: "str | None") -> "str | None":
    """The character a byte of one of the TeX fonts stands for, or None."""
    if (font, code) in COMPOSITE:
        return COMPOSITE[(font, code)]
    table = TABLES[FONT_ENCODING[font]]
    m = C_NAME_RE.fullmatch(name or "")
    if m:
        n = int(m.group(1))
        if n < 128:
            return table[n]
    if name in VERIFIED_BY_NAME.get(font, {}):
        return VERIFIED_BY_NAME[font][name]
    if 0x21 <= code <= 0x7E and not m:
        return table[code]
    return None


def tounicode(doc, xref) -> dict[int, str]:
    """The font's own code -> character table, so a character seen in the
    extracted text can be traced back to the byte that produced it."""
    obj = doc.xref_object(xref).replace("\n", " ")
    m = re.search(r"/ToUnicode (\d+) 0 R", obj)
    if not m:
        return {}
    text = doc.xref_stream(int(m.group(1))).decode("latin1")
    table = {}
    # Sections are parsed separately: a bfrange line "<20> <21> <0020>"
    # also matches the bfchar pattern on its last two tokens.
    for section in re.findall(r"beginbfrange(.*?)endbfrange", text, re.S):
        for a, b, u in BFRANGE_RE.findall(section):
            for code in range(int(a, 16), int(b, 16) + 1):
                table[code] = chr(int(u, 16) + code - int(a, 16))
    for section in re.findall(r"beginbfchar(.*?)endbfchar", text, re.S):
        for a, u in BFCHAR_RE.findall(section):
            table[int(a, 16)] = chr(int(u, 16))
    return table


def scan_volume(path: Path):
    """Per font: {byte: char} proposed, occurrence counts, crop samples,
    and the codes that occur but could not be mapped."""
    doc = pymupdf.open(path)
    fonts = set(FONT_ENCODING) | {"AdvMH3"}
    names: dict[str, dict[int, str]] = {}
    seen_chars: dict[str, dict[int, str]] = {}
    seen_xrefs = set()
    for pno in range(len(doc)):
        for f in doc[pno].get_fonts(full=True):
            xref, short = f[0], f[3].split("+")[-1]
            if short in fonts and xref not in seen_xrefs:
                seen_xrefs.add(xref)
                names.setdefault(short, {}).update(differences(doc, xref))
                seen_chars.setdefault(short, {}).update(tounicode(doc, xref))

    # Extracted character -> byte. A code without a ToUnicode entry comes
    # through as its own code point.
    reverse: dict[str, dict[str, int]] = {}
    for font in names:
        rev = {}
        for code in names[font]:
            rev[seen_chars.get(font, {}).get(code, chr(code))] = code
        reverse[font] = rev

    occurrences: Counter = Counter()
    places: dict = defaultdict(list)
    unknown_chars: Counter = Counter()
    for pno in range(len(doc)):
        for blk in doc[pno].get_text("rawdict")["blocks"]:
            for line in blk.get("lines", []):
                for span in line["spans"]:
                    font = span["font"].split("+")[-1]
                    if font not in names:
                        continue
                    for ch in span["chars"]:
                        code = reverse[font].get(ch["c"])
                        if code is None:
                            unknown_chars[(font, ch["c"])] += 1
                            continue
                        occurrences[(font, code)] += 1
                        if len(places[(font, code)]) < INK_SAMPLES:
                            places[(font, code)].append((pno, ch["bbox"]))

    mapping: dict[str, dict[int, str]] = defaultdict(dict)
    unmapped: list = []
    for font, table in names.items():
        for code, name in table.items():
            if code == 0x20 or (font, code) not in occurrences:
                continue
            if font == "AdvMH3":
                char = ADVMH3_BY_NAME.get(name)
            else:
                char = tex_char(font, code, name)
            if char is None or char == " ":
                unmapped.append((font, code, name, occurrences[(font, code)]))
                continue
            mapping[font][code] = char

    blank = []
    for font, table in mapping.items():
        for code in list(table):
            share = _ink(doc, places.get((font, code), []))
            if share is not None and share < MIN_INK:
                blank.append((font, code, table.pop(code)))

    samples = {k: v[0] for k, v in places.items()}
    doc.close()
    return dict(mapping), occurrences, samples, unmapped, blank, unknown_chars, names


def _ink(doc, places) -> "float | None":
    """Median share of dark pixels across sampled occurrences of a code;
    None when the glyph has no measurable box (zero advance width)."""
    shares = []
    for pno, bbox in places:
        rect = pymupdf.Rect(bbox)
        if rect.is_empty or rect.width < 0.5 or rect.height < 0.5:
            continue
        pix = doc[pno].get_pixmap(clip=rect, dpi=200, colorspace=pymupdf.csGRAY)
        total = pix.width * pix.height
        if not total:
            continue
        dark = sum(1 for i in range(0, total * pix.n, pix.n) if pix.samples[i] < 128)
        shares.append(dark / total)
    if not shares:
        return None
    shares.sort()
    return shares[len(shares) // 2]


def write_sheet(path: Path, pdf: Path, font: str, mapping, occurrences, samples, names):
    """Every mapped glyph beside the character now claimed for it -- the
    check that established these tables, kept repeatable."""
    entries = sorted(mapping.items(), key=lambda kv: -occurrences.get((font, kv[0]), 0))
    if not entries:
        return
    doc = pymupdf.open(pdf)
    cols, cw, rh = 8, 92, 100
    out = pymupdf.open()
    sheet = out.new_page(width=cols * cw + 24, height=((len(entries) + cols - 1) // cols) * rh + 40)
    label_font = next((p for p in (r"C:\Windows\Fonts\cambria.ttc",
                                   r"C:\Windows\Fonts\seguisym.ttf",
                                   r"C:\Windows\Fonts\times.ttf") if Path(p).exists()), None)
    sheet.insert_text((12, 14), f"{pdf.stem}  {font}", fontsize=9)
    for i, (code, char) in enumerate(entries):
        x, y = 12 + (i % cols) * cw, 30 + (i // cols) * rh
        if (font, code) in samples:
            pno, bbox = samples[(font, code)]
            r = pymupdf.Rect(bbox)
            r = pymupdf.Rect(r.x0 - 1, r.y0 - 1, r.x1 + 1, r.y1 + 1)
            try:
                pix = doc[pno].get_pixmap(clip=r, dpi=400)
                sheet.insert_image(pymupdf.Rect(x + 22, y, x + cw - 22, y + 40),
                                   pixmap=pix, keep_proportion=True)
            except Exception:
                pass
        sheet.insert_text((x + 2, y + 54), f"{code:02X} {names[font].get(code, '')} x{occurrences.get((font, code), 0)}",
                          fontsize=6.5)
        try:
            sheet.insert_text((x + 2, y + 80), char, fontsize=17, fontfile=label_font, fontname="lbl")
        except Exception:
            sheet.insert_text((x + 2, y + 80), f"U+{ord(char):04X}", fontsize=8)
    path.parent.mkdir(parents=True, exist_ok=True)
    sheet.get_pixmap(dpi=130).save(path)
    doc.close()


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--only", help="volume substring filter")
    ap.add_argument("--dry-run", action="store_true", help="report, do not write font_cmaps.json")
    ap.add_argument("--no-sheets", action="store_true")
    args = ap.parse_args()

    cmaps = json.loads(CMAP_PATH.read_text(encoding="utf-8")) if CMAP_PATH.exists() else {}
    total_codes = total_chars = 0
    print(f"{'volume':<14}{'font':<12}{'codes':>6}{'chars':>8}  unmapped (code name ×n)")
    for pdf in sorted(PDF_DIR.glob("*.pdf")):
        vol = pdf.stem
        if args.only and args.only not in vol:
            continue
        mapping, occurrences, samples, unmapped, blank, unknown, names = scan_volume(pdf)
        for font in sorted(set(mapping) | {f for f, *_ in unmapped}):
            table = mapping.get(font, {})
            chars = sum(occurrences.get((font, c), 0) for c in table)
            total_codes += len(table)
            total_chars += chars
            miss = ", ".join(f"{c:02X} {n} ×{k}" for f, c, n, k in unmapped if f == font)
            print(f"{vol:<14}{font:<12}{len(table):>6}{chars:>8}  {miss}")
            if table:
                # These fonts had no table before (AdvMH3 had one wrong
                # entry), so the whole per-font table is replaced.
                cmaps.setdefault(vol, {})[font] = {f"0x{c:02x}": ord(ch) for c, ch in sorted(table.items())}
                if not args.no_sheets:
                    write_sheet(SHEET_DIR / f"{vol}_{font}.png", pdf, font, table, occurrences, samples, names)
        for font, code, char in blank:
            print(f"    {vol} {font} {code:02X} would be {char!r} but draws no ink -- skipped")
        for (font, ch), n in unknown.items():
            print(f"    {vol} {font}: extracted {ch!r} ×{n} has no byte in the font's tables")

    print(f"\n{total_codes} byte mappings across all volumes, covering {total_chars} characters")
    if args.dry_run:
        print("dry run - font_cmaps.json not written")
        return 0
    CMAP_PATH.write_text(json.dumps(cmaps, ensure_ascii=False, indent=1, sort_keys=True),
                         encoding="utf-8")
    print(f"wrote {CMAP_PATH}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
