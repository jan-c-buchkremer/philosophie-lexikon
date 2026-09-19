"""Render the essay from Markdown: viz/geschichte.md -> viz/geschichte.html.

The prose is written in Markdown so it can be reworked without touching
markup. Everything the page needs beyond CommonMark is a handful of
conventions, documented at the top of geschichte.md:

  {key}                  a number or name filled in at load time from
                         story.json (story-main.js `derive()`); becomes
                         <span data-fill="key">…</span> wherever it stands
  ## Kicker · Title      starts a chapter section; the kicker (left of
                         the middle dot) also gives the section its id
  > paragraph            an aside (p.aside), not a quotation
  ::: hero … :::         kicker line, # title, lede, stat list
  ::: fig <id> [wide] [specimen] … :::
                         a figure: an optional ![alt](src) image, then
                         the caption. <id> is the chart's mount point
                         (fig-hubs, fig-chord, …), omitted for images
  ::: foot Title … :::   the closing footer

Raw HTML passes through, so anything the conventions do not cover can be
written inline. The HTML file is generated and committed; the export step
copies it beside the data.

  uv run python scripts/build_story_html.py [--src viz/geschichte.md] [--out viz/geschichte.html]
"""
import argparse
import re
import sys
from pathlib import Path

from markdown_it import MarkdownIt

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_SRC = ROOT / "viz" / "geschichte.md"
DEFAULT_OUT = ROOT / "viz" / "geschichte.html"

md = MarkdownIt("commonmark", {"html": True})

FILL_RE = re.compile(r"\{(\w+)\}")

TEMPLATE = """<!doctype html>
<!-- GENERATED from viz/geschichte.md by scripts/build_story_html.py. Edit the Markdown. -->
<html lang="de" class="story" style="overflow: auto; height: auto;">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{title}</title>
  <meta name="description" content="{description}">
  <link rel="stylesheet" href="style.css?v=2">
</head>
<!-- The map's stylesheet fixes html and body at 100% with overflow hidden.
     Inline here as well as in style.css, so a cached stylesheet cannot
     leave the essay unscrollable. -->
<body class="story" style="overflow: auto; height: auto;">
  <div class="story-progress" hidden><i></i></div>

  <header class="story-top">
    <a class="story-back" href="index.html">← Zurück zum Atlas</a>
    <p class="story-top-title">Enzyklopädie Philosophie und Wissenschaftstheorie</p>
  </header>

  <div id="loading" class="loading">
    <p>Lade Daten …</p>
  </div>

  <main class="story-main">

{main}
  </main>

  <script src="https://cdnjs.cloudflare.com/ajax/libs/d3/7.9.0/d3.min.js"></script>
  <script type="module" src="js/story-main.js"></script>
</body>
</html>
"""


def inline(text: str) -> str:
    return md.renderInline(text.strip())


def fill(html: str) -> str:
    return FILL_RE.sub(r'<span data-fill="\1">…</span>', html)


def slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


def split_front_matter(source: str) -> tuple[dict, str]:
    meta = {}
    if source.startswith("---\n"):
        head, _, source = source[4:].partition("\n---\n")
        for line in head.splitlines():
            key, _, value = line.partition(":")
            meta[key.strip()] = value.strip()
    return meta, source


def parse_blocks(source: str) -> list[tuple[str, list[str], list[str]]]:
    """Top-level structure as (kind, args, body): a `:::` container, an `h2`, or plain `md`."""
    blocks, prose = [], []
    lines = iter(source.splitlines())

    def flush():
        if any(l.strip() for l in prose):
            blocks.append(("md", [], prose[:]))
        prose.clear()

    for line in lines:
        if line.startswith(":::"):
            flush()
            kind, *args = line[3:].split()
            body = []
            for inner in lines:
                if inner.strip() == ":::":
                    break
                body.append(inner)
            blocks.append((kind, args, body))
        elif line.startswith("## "):
            flush()
            blocks.append(("h2", [line[3:].strip()], []))
        else:
            prose.append(line)
    flush()
    return blocks


def render_hero(body: list[str]) -> str:
    lines = [l for l in body if l.strip()]
    kicker, title, lede = lines[0], lines[1].removeprefix("# "), lines[2]
    stats = [f'        <div class="stat"><b>{key}</b><span>{inline(label)}</span></div>'
             for key, label in (item.removeprefix("- ").split(" ", 1) for item in lines[3:])]
    return "\n".join([
        '    <section class="hero">',
        f'      <p class="kicker">{inline(kicker)}</p>',
        f"      <h1>{inline(title)}</h1>",
        f'      <p class="lede">{inline(lede)}</p>',
        '      <div class="stats">',
        *stats,
        "      </div>",
        "    </section>",
    ])


def render_fig(args: list[str], body: list[str]) -> str:
    ids = [a for a in args if a.startswith("fig-")]
    classes = ["fig"] + [f"fig-{a}" if a == "wide" else a for a in args if a not in ids]
    lines = [l for l in body if l.strip()]
    img = re.match(r"!\[(.*)\]\((.*)\)", lines[0])
    if img:
        alt, src = img.groups()
        mount = ('        <div class="specimen-sheet">\n'
                 f'          <img src="{src}" alt="{alt}" loading="lazy">\n'
                 "        </div>")
        lines = lines[1:]
    else:
        mount = f'        <div id="{ids[0]}" class="fig-body"></div>'
    caption = inline(" ".join(lines))
    return "\n".join([
        f'      <figure class="{" ".join(classes)}">',
        mount,
        f"        <figcaption>{caption}</figcaption>",
        "      </figure>",
    ])


def render_prose(lines: list[str]) -> str:
    html = md.render("\n".join(lines)).strip()
    html = re.sub(r"<blockquote>\s*<p>(.*?)</p>\s*</blockquote>", r'<p class="aside">\1</p>', html, flags=re.S)
    return "\n".join("      " + l for l in html.splitlines())


def render_foot(args: list[str], body: list[str]) -> str:
    return "\n".join([
        '    <footer class="story-foot">',
        f"      <h3>{' '.join(args)}</h3>",
        render_prose(body),
        "    </footer>",
    ])


def render_main(blocks: list[tuple[str, list[str], list[str]]]) -> str:
    out, in_section = [], False
    for kind, args, body in blocks:
        if kind in ("h2", "foot") and in_section:
            out.append("    </section>")
            in_section = False
        if kind == "hero":
            out.append(render_hero(body))
        elif kind == "foot":
            out.append(render_foot(args, body))
        elif kind == "h2":
            kicker, _, title = args[0].partition(" · ")
            out.append("    <!-- ============================================================ -->")
            out.append("\n".join([
                f'    <section class="chapter" id="{slug(kicker)}">',
                f'      <p class="kicker">{inline(kicker)}</p>',
                f"      <h2>{inline(title)}</h2>",
            ]))
            in_section = True
        else:
            if not in_section:  # content before the first heading: the prologue
                out.append('    <section class="chapter prologue">')
                in_section = True
            out.append(render_fig(args, body) if kind == "fig" else render_prose(body))
    if in_section:
        out.append("    </section>")
    return "\n\n".join(out)


def build(source: str) -> str:
    source = re.sub(r"<!--.*?-->", "", source, flags=re.S)  # author's notes stay in the source
    meta, body = split_front_matter(source)
    main = fill(render_main(parse_blocks(body)))
    return TEMPLATE.format(title=meta["title"], description=meta["description"], main=main)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--src", type=Path, default=DEFAULT_SRC)
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = ap.parse_args()

    html = build(args.src.read_text(encoding="utf-8"))
    args.out.write_text(html, encoding="utf-8", newline="\n")
    print(f"wrote {args.out} ({len(html):,} bytes)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
