# philosophie-lexikon

A structured dataset and 2D atlas of the *Enzyklopädie Philosophie und
Wissenschaftstheorie* (ed. Jürgen Mittelstraß, 2nd edition, 8 volumes,
Metzler/Springer).

The eight PDFs are turned into a citation graph — 4,627 entries linked by
59,942 editorial cross-references, 95.9 % of them cleanly resolved to a
target article — and that graph is laid out as a navigable map in which
every article is a point and articles sit close together because the
editors cross-referenced them, not because their prose is similar.

## What is (and is not) in this repository

The encyclopedia is in copyright. The source PDFs and every full-text
derivative of them stay local and are excluded by `.gitignore`:

| Excluded | What it is |
|---|---|
| `pdf-data/` | the eight volumes as downloaded from SpringerLink |
| `md-data/` | tagged Markdown extracted from the PDFs |
| `structured-data/` | per-volume entry JSONL, cleaned JSONL, and `lexikon.db` |
| `export/entries.jsonl`, `export/viz/`, `viz/data/` | dataset and atlas bundles that carry article text |
| `.atlas-cache/`, `.venv/` | regenerable caches |

What is published is the machinery and the graph:

| Included | What it is |
|---|---|
| `scripts/` | the extraction, parsing, cleaning, resolution, and export pipeline |
| `pipeline/` | the atlas stage (graph model, Leiden communities, force layout, sharding) |
| `viz/` | the atlas frontend (`index.html`, `style.css`, `js/`) |
| `export/edges.csv` | all 59,942 cross-references with their resolution status and target |
| `export/lemmas.csv`, `export/ambiguous.csv`, `export/MANIFEST.json` | lemma index, unresolved-ambiguity list, row counts |
| `export/atlas.html` | the atlas flattened into one self-contained page (article prose embedded, bibliographies left out) |
| `export/glyphs/` | glyph renderings used to repair the PDFs' broken symbol-font encodings |
| `docs/`, `ISSUES.md`, `tests/` | design notes, the issues ledger, golden regression fixtures |

`export/atlas.html` is the one artifact that contains article text; it
exists so the map can be opened from a single file without a server.

## Setup

Requires Python ≥ 3.11 and [uv](https://docs.astral.sh/uv/).

```
uv sync
```

To rebuild from source you need the eight volume PDFs in `pdf-data/`,
named `Bd01_A-B.pdf` … `Bd08_Th-Z.pdf`. `scripts/download-volumes.ps1`
documents how they were obtained through an institutional SpringerLink
login; in practice the volumes had to be downloaded by hand in a browser
because Springer's bot check blocks scripted access.

## The pipeline

Each stage reads the previous stage's output from disk and writes its
own, so any later stage can be rerun without paying the slow PDF stage
again. The per-volume stages (`extract_markdown.py` via a positional
argument, `parse_entries.py` through `resolve_xrefs.py` via `--only`)
accept a volume-name substring so one volume can be reprocessed alone.

```
scripts/extract_markdown.py   pdf-data/*.pdf          -> md-data/*.md                        (~6 min/volume)
scripts/parse_entries.py      md-data/*.md            -> structured-data/*_entries.jsonl
scripts/clean_text.py         *_entries.jsonl         -> structured-data/*_entries_clean.jsonl
scripts/build_db.py           *_entries_clean.jsonl   -> structured-data/lexikon.db
scripts/build_lemma_index.py  lexikon.db              -> lemmas table
scripts/resolve_xrefs.py      lexikon.db              -> resolved_* tables          (run last, see below)
scripts/extract_lifedates.py  lexikon.db              -> birth/death columns        (after build_db.py, before export)
scripts/export_dataset.py     lexikon.db              -> export/
scripts/build_atlas.py        lexikon.db              -> export/viz/                (or viz/data/ with --dev)
scripts/build_story.py        lexikon.db + graph.json -> export/viz/data/story.json (same --dev flag as build_atlas)
scripts/build_story_html.py   viz/geschichte.md       -> viz/geschichte.html         (the essay prose; no data needed)
scripts/build_artifact.py     viz/data/               -> export/atlas.html          (needs a --dev build first)
```

Run each with `uv run python scripts/<name>.py`.

**Ordering hazard:** `build_db.py` deletes and recreates the whole `.db`
file, taking the resolved cross-reference tables with it. Always run
`resolve_xrefs.py` after any `build_db.py` run.

`scripts/font_cmaps.json` is generated data that is committed on purpose:
per-volume, per-font byte-to-character tables that repair the PDFs'
broken ToUnicode CMaps. It only needs regenerating (`derive_cmaps.py`) if
new volumes are added.

### Checks

Four check suites pin down behaviour that has regressed at least once:

```
uv run python scripts/check_golden.py        # entry parser, against tests/golden_entries.json
uv run python scripts/check_golden_xrefs.py  # cross-reference resolver, against tests/golden_xrefs.json
uv run python scripts/check_dataset.py       # export/ invariants
uv run python scripts/check_viz.py           # atlas data invariants
uv run python scripts/check_golden_lifedates.py  # birth/death extraction, against tests/golden_lifedates.json
uv run python scripts/check_story.py         # story.json, every figure recomputed independently
```

## The essay

`viz/geschichte.html` ("Das unabsichtliche Selbstporträt") is a German
long-form piece built on the same graph, linked from the top of the atlas:
five chapters and a postscript, each around one chart -- the most-cited
entries (no person among them), the communities as a chord diagram and a
volume-by-community table, hubs against bridges, every dated life as a
stratigraphy of the communities, and the references the resolver refused
to decide. All figures in the text come from `story.json`
(`scripts/build_story.py`), never from the HTML; the community names are
the one hand-written input (`pipeline/community_labels.json`).

The prose is written in `viz/geschichte.md` and rendered to
`viz/geschichte.html` by `scripts/build_story_html.py`; edit the Markdown,
not the HTML. `{key}` in the Markdown marks a number or name filled in at
load time (the keys are defined in `viz/js/story-main.js`); the few other
conventions -- `## Kicker · Title` for chapters, `> ` for asides, `::: fig`
blocks for charts -- are documented at the top of the Markdown file.

## The atlas

```
uv run python scripts/build_atlas.py              # -> export/viz/
uv run python -m http.server -d export/viz 8000   # then open http://localhost:8000
```

Or open `export/atlas.html` directly in a browser.

Nodes are every non-redirect entry (4,259); edges are the resolved
cross-references (54,692 directed). Communities come from Leiden on the
weighted undirected projection, positions from a force-directed layout in
`igraph`. Everything tunable lives in `pipeline/config.py`, is read from
`.env`, and is written into the output manifest so a given map is
reproducible. See `docs/atlas.md` for the design and its trade-offs.

## Documentation

- `docs/pipeline-strategy.md` — the principles the project runs on and why
- `docs/schema.md` — the shape of every data artifact, and the rebuild order
- `docs/atlas.md` — the atlas stage: nodes, edges, communities, layout, frontend
- `docs/structure-notes.md` — how the printed encyclopedia is structured
- `docs/ontology-notes.md` — the editors' own stated conventions
- `ISSUES.md` — open issues, and the settled lessons behind the code's shape

## Data notes

- Entry ids are `{volume}:{pdf_page}:{ordinal}`, so every record points
  back to the exact PDF page it came from.
- Cross-references that could not be resolved unambiguously are kept and
  marked (`export/ambiguous.csv`, status column in `edges.csv`), never
  guessed.
- Symbol-font recovery is incomplete: the mathematical fonts are largely
  fixed, the Greek font is not. `ISSUES.md` issue #1 has the per-font
  census.
