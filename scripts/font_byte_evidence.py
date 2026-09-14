"""Show, for every (volume, font, unmapped byte), the words it occurs in.

The companion to derive_cmaps.py, and the check on it. derive_cmaps
decides by weighted vote against a reference corpus and stays silent when
the evidence is thin; this prints the raw evidence instead and lets a
reader decide. "Luk[?]cs, Kar[?]di, Su[?]rez" is not ambiguous to anyone
who reads Latin script, no matter what the vote says.

Use it for three things:

  * confirming what derive_cmaps derived (the CURRENT column is what the
    pipeline would write today -- legacy table, derived table and manual
    fixes already merged, exactly as cmap_for_font() resolves them);
  * filling bytes it left unmapped, by adding a MANUAL_VOLUME_FONT_FIXES
    entry in extract_markdown.py citing the example word, which is the
    method the existing entries there were produced by;
  * catching a byte where the derivation is confidently WRONG -- which
    has happened, and is invisible to any check that only looks at
    whether a byte is mapped (Bd05's 0x13 was derived as "ô" from
    contaminated evidence; these contexts say "á" and are unanswerable).

Reads the PDFs UNPATCHED, so the bytes shown are the ones the document
actually contains.

Run via uv:
  uv run --with pymupdf4llm --with pikepdf python scripts/font_byte_evidence.py \
      [--only Bd05] [--font AdvMIN] [--page-step 4]
"""
import argparse
import sys
from collections import Counter, defaultdict
from pathlib import Path

import pymupdf

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from derive_cmaps import WORD_RE, UNMAPPED_MAX, stitch_spans  # noqa: E402
from extract_markdown import cmap_for_font, load_font_cmaps  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
PDF_DIR = ROOT / "pdf-data"


def evidence_for(pdf_path: Path, page_step: int, font_filter: str) -> dict:
    """{font: {byte: Counter of masked words}} from the raw document."""
    doc = pymupdf.open(str(pdf_path))
    out = defaultdict(lambda: defaultdict(Counter))
    for pno in range(0, doc.page_count, page_step):
        for block in doc[pno].get_text("rawdict")["blocks"]:
            if "lines" not in block:
                continue
            for line in block["lines"]:
                # same stitching as derive_cmaps: a PDF routinely breaks a
                # word into spans exactly AT the accented glyph
                for font, text in stitch_spans(line["spans"]):
                    if font_filter and font_filter not in font:
                        continue
                    for m in WORD_RE.finditer(text):
                        word = m.group()
                        positions = [i for i, c in enumerate(word)
                                     if ord(c) < UNMAPPED_MAX]
                        if len(positions) != 1 or len(word) < 4:
                            continue
                        i = positions[0]
                        masked = word[:i] + "[?]" + word[i + 1:]
                        out[font][ord(word[i])][masked] += 1
    doc.close()
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", help="volume-name substring")
    ap.add_argument("--font", default="", help="font-name substring")
    ap.add_argument("--page-step", type=int, default=4)
    ap.add_argument("--examples", type=int, default=4)
    args = ap.parse_args()

    derived_all = load_font_cmaps()

    for pdf_path in sorted(PDF_DIR.glob("Bd*.pdf")):
        if args.only and args.only not in pdf_path.name:
            continue
        stem = pdf_path.stem
        print(f"\n=== {stem} (every {args.page_step}th page, raw bytes)")
        evidence = evidence_for(pdf_path, args.page_step, args.font)
        for font in sorted(evidence):
            table = cmap_for_font(font, derived_all.get(stem, {}), stem) or {}
            print(f"  [{font}]")
            for code in sorted(evidence[font]):
                words = evidence[font][code]
                current = table.get(code)
                shown = ", ".join(w for w, _ in words.most_common(args.examples))
                mapped = f"'{chr(current)}'" if current else "GAP"
                print(f"    0x{code:02x} -> {mapped:5s} ({sum(words.values()):5d}x)  {shown[:88]}")


if __name__ == "__main__":
    main()
