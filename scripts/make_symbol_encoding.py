"""Extract the Adobe Symbol encoding table, once, as committed data.

The symbol fonts in these PDFs name their glyphs `/C<n>`, where n is a code
point in the font's ORIGINAL encoding -- Adobe Symbol for AdvSY and its
relatives (see ISSUES.md settled lesson #2). Decoding those names therefore
needs a Symbol code -> Unicode table, and Python has no such codec.

Transcribing 189 entries by hand is exactly the silent-corruption risk this
project keeps being bitten by, so the table is read from an authoritative
source instead: Adobe's own `Symbol.afm` metrics file, which pairs each
code with a glyph name, resolved to Unicode through the Adobe Glyph List.

matplotlib ships that AFM and is used only to locate it -- it is NOT a
project dependency. Run this once with a throwaway environment; the output
is committed like `font_cmaps.json` and reviewed as a diff:

    uv run --with matplotlib python scripts/make_symbol_encoding.py

Verified independently: seven codes read off rendered glyphs from the PDFs
(C204 subset, C209 nabla, C216 logicalnot, C217 logicaland, C218 logicalor,
C219 arrowdblboth, C222 arrowdblright) all match this table exactly.
"""
import json
import os
import re
import sys
from pathlib import Path

from fontTools.agl import toUnicode

OUT = Path(__file__).resolve().parent / "adobe_symbol_encoding.json"

# Codes whose Symbol glyph is a plain ASCII character are dropped: the
# fonts never need a repair entry for those, and keeping them would let a
# table meant for symbols quietly rewrite ordinary punctuation.
ASCII_PASSTHROUGH = set(range(0x20, 0x7F))


def main() -> int:
    try:
        import matplotlib
    except ImportError:
        print("run with:  uv run --with matplotlib python scripts/make_symbol_encoding.py")
        return 1

    afm = (Path(matplotlib.__file__).parent / "mpl-data" / "fonts"
           / "pdfcorefonts" / "Symbol.afm")
    if not afm.exists():
        print(f"Symbol.afm not found at {afm}")
        return 1

    table, skipped = {}, 0
    for line in afm.read_text(encoding="latin-1").splitlines():
        m = re.match(r"C (-?\d+) ; WX \d+ ; N (\S+)", line)
        if not m:
            continue
        code, name = int(m.group(1)), m.group(2)
        if code < 0:
            continue
        char = toUnicode(name)
        if not char:
            skipped += 1
            continue
        if code in ASCII_PASSTHROUGH and char == chr(code):
            continue
        table[code] = char

    OUT.write_text(
        json.dumps({str(k): v for k, v in sorted(table.items())},
                   ensure_ascii=False, indent=0),
        encoding="utf-8",
    )
    print(f"{len(table)} Symbol codes -> {OUT}  ({skipped} names had no Unicode)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
