"""Why is an entry headword not tagged? Census + failure-mode diagnosis.

ISSUES.md issue #8: a subset of entries never gets an
`<!-- entry:... -->` marker, so the article is silently absorbed into the
body of whichever entry precedes it. 161 capitalised names with >=10
cross-references have no entry of that name at all.

This script finds them and says WHY, without re-running extraction. The
expensive half of `extract_markdown.py` is pymupdf4llm's Markdown reflow;
the headword side is just `page.get_text("dict")` font spans, which is
cheap. And the reflowed text is already on disk: md-data/<volume>.md is
exactly what `inject_entry_markers()` was handed, page by page, with its
own markers inserted afterwards. So we can replay the match:

    candidates  <- find_entry_candidates(patched PDF page)   [cheap]
    page text   <- md-data/<volume>.md, markers stripped     [free]
    verdict     <- replay inject_entry_markers()'s regex

Verdicts, which is the point of the exercise -- "detected but
unanchorable" and "never detected" need completely different fixes:

  tagged        the marker is in the Markdown; working as intended
  no_match      the anchor was built, but its pattern matches nothing in
                the page text -- an anchor/text mismatch (see the
                `unsafe` column: get_text() hands back raw control bytes
                where pymupdf4llm's Markdown has U+FFFD, so any headword
                whose line contains an unmapped glyph -- every "X (griech.
                ...)" etymology -- cannot match literally)
  ambiguous     several matches, none uniquely at a paragraph start, so
                inject_entry_markers() deliberately skips it
  unexpected    replay found the unique match that the real run did not;
                means md-data is stale relative to the current code

Run via uv:
  uv run --with pymupdf4llm --with pikepdf python scripts/diagnose_tagging.py \
      [--only Bd05] [--pages 380-420] [--list-all]
"""
import argparse
import re
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
# anchors are full of raw control bytes and Greek; never let the
# console encoding turn a diagnosis into a traceback
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from extract_markdown import (  # noqa: E402
    HEADWORD_FONT,
    VOLUME_OVERRIDES,
    build_anchor_pattern,
    find_entry_candidates,
    find_running_heads,
    merge_split_lemmas,
    patch_pdf_fonts,
    sanitize_hint,
    cleanup_temp_pdfs,
)

ROOT = Path(__file__).resolve().parent.parent
PDF_DIR = ROOT / "pdf-data"
MD_DIR = ROOT / "md-data"

# The marker now also carries the printed page number, which
# extract_markdown.py promoted out of the body text (pipeline-strategy.md
# §5.4 step 1). Without the optional group this matched nothing and the
# census silently reported "0 headword candidates" for every volume.
PAGE_SPLIT_RE = re.compile(r"\n\n<!-- page:(\d+)(?: printed:\d+)? -->\n\n")
MARKER_RE = re.compile(r"<!-- entry:(.*?) -->\n\n", re.S)
UNSAFE_RE = re.compile(r"[\x00-\x1f\ufffd]")


def md_pages(md_path: Path) -> dict:
    """{pdf_page_number: (text_without_markers, [marker hints on the page])}"""
    text = md_path.read_text(encoding="utf-8")
    parts = PAGE_SPLIT_RE.split(text)
    out = {}
    for i in range(1, len(parts), 2):
        page_text = parts[i + 1]
        out[int(parts[i])] = (MARKER_RE.sub("", page_text),
                              MARKER_RE.findall(page_text))
    return out


def replay(page_text: str, hint: str) -> str:
    """inject_entry_markers()'s matching logic, verdict only.

    Imports the real pattern builder rather than restating it, so this
    doubles as the cheap validation harness for any change to it: edit
    build_anchor_pattern(), re-run this, read the verdict counts. No
    re-extraction needed -- the Markdown on disk is what the real run
    matched against."""
    if not hint.strip():
        return "empty_anchor"
    matches = list(re.finditer(build_anchor_pattern(hint), page_text))
    if not matches:
        return "no_match"
    para = [m for m in matches if page_text[:m.start()].endswith("\n\n")]
    if len(para) == 1 or len(matches) == 1:
        return "unexpected"
    return "ambiguous"


def diagnose(pdf_path: Path, page_range, list_all: bool) -> Counter:
    stem = pdf_path.stem
    md_path = MD_DIR / f"{stem}.md"
    if not md_path.exists():
        print(f"  no {md_path.name}; skipping")
        return Counter()

    overrides = VOLUME_OVERRIDES.get(stem, {})
    headword_font = overrides.get("headword_font", HEADWORD_FONT)
    body_start = overrides.get("body_start_page", 0)

    pages = md_pages(md_path)
    doc = patch_pdf_fonts(pdf_path)
    verdicts = Counter()
    failures = []

    for page_num in sorted(pages):
        if page_num < body_start:
            continue
        if page_range and not (page_range[0] <= page_num <= page_range[1]):
            continue
        page_text, hints = pages[page_num]
        # Mirror extract_one() exactly: a two-line headword is merged
        # into ONE candidate before matching. Without this the census
        # compares unmerged candidates against merged markers and
        # reports both halves of every merge as a failure.
        page_obj = doc[page_num - 1]
        cands = find_entry_candidates(page_obj, headword_font)
        cands = merge_split_lemmas(cands, find_running_heads(page_obj, headword_font))
        for cand in cands:
            # find_entry_candidates() now returns {"anchor", "lemma"}: the
            # anchor locates, the lemma names (ISSUES.md issue #11a). The
            # replay matches on the anchor; the marker written into
            # md-data carries the lemma, so both are checked here.
            hint, lemma = cand["anchor"], cand["lemma"]
            if (hint in hints or sanitize_hint(hint) in hints
                    or lemma in hints or sanitize_hint(lemma) in hints):
                verdicts["tagged"] += 1
                continue
            verdict = replay(page_text, hint)
            verdicts[verdict] += 1
            failures.append((page_num, verdict, hint))

    doc.close()
    cleanup_temp_pdfs()

    total = sum(verdicts.values())
    print(f"  {total} headword candidates on pages >= {body_start}: "
          + ", ".join(f"{v} {k}" for k, v in verdicts.most_common()))

    unsafe = sum(1 for _, v, h in failures if v == "no_match" and UNSAFE_RE.search(h))
    no_match = sum(1 for _, v, _ in failures if v == "no_match")
    if no_match:
        print(f"  of {no_match} no_match anchors, {unsafe} "
              f"({unsafe / no_match:.0%}) contain a control char or U+FFFD")
    shown = failures if list_all else failures[:25]
    for page_num, verdict, hint in shown:
        flag = "UNSAFE" if UNSAFE_RE.search(hint) else "      "
        print(f"    p{page_num:<5d} {verdict:<10s} {flag}  {hint[:70]!r}")
    if len(failures) > len(shown):
        print(f"    ... {len(failures) - len(shown)} more (use --list-all)")
    return verdicts


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", help="volume-name substring")
    ap.add_argument("--pages", help="PDF page range, e.g. 380-420")
    ap.add_argument("--list-all", action="store_true")
    args = ap.parse_args()

    page_range = None
    if args.pages:
        lo, _, hi = args.pages.partition("-")
        page_range = (int(lo), int(hi or lo))

    grand = Counter()
    for pdf_path in sorted(PDF_DIR.glob("Bd*.pdf")):
        if args.only and args.only not in pdf_path.name:
            continue
        print(f"[diagnose] {pdf_path.name}")
        grand += diagnose(pdf_path, page_range, args.list_all)

    if grand:
        total = sum(grand.values())
        print(f"\n[diagnose] all volumes: {total} candidates, "
              + ", ".join(f"{v} {k} ({v / total:.1%})" for k, v in grand.most_common()))


if __name__ == "__main__":
    main()
