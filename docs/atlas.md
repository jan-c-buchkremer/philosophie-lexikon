# The atlas — a 2D map of the corpus

Covers the stage that turns `structured-data/lexikon.db` into a navigable
map, and the artifacts it produces. Bump this doc whenever any of those
shapes change, the same rule `docs/schema.md` follows.

Every article in the encyclopedia is a point on one plane. Position comes
from the **citation graph alone** — two entries sit near each other because
the editors cross-referenced them, not because their prose is similar.
There are no text embeddings and no topic model in this stage; see
"Deferred" below.

## Running it

```
uv sync                                          # once
uv run python scripts/build_atlas.py             # -> export/viz/  (servable bundle)
uv run python scripts/build_atlas.py --dev       # -> viz/data/    (iterate on the frontend)
uv run python scripts/check_viz.py               # 45 checks on the data
uv run python -m http.server -d export/viz 8000
```

The frontend has its own smoke test, `viz/_smoke.html`, which drives the
real modules — search, canvas render, quadtree hit-testing, sidebar
linkify — and reports into `#out`. It needs the data served, so run it
against a served copy:

```
uv run python -m http.server -d viz 8731 &
chrome --headless=new --virtual-time-budget=45000 \
       --dump-dom http://localhost:8731/_smoke.html | grep -E 'FAIL|SMOKE'
```

It is not copied into `export/viz/` — `copy_frontend` ships only
`index.html`, `style.css` and `js/`.

Stages are `load -> communities -> layout -> metrics -> shard -> export`,
each cached under `.atlas-cache/`. `--start-from layout` re-runs the
geometry without re-reading the database or re-sharding 17 MB of text.
A full build is ~20 seconds.

Everything tunable lives in `pipeline/config.py` and is read from `.env`;
every value that affects geometry or clustering is written into the output
manifest, which is what makes a given map reproducible rather than merely
repeatable.

## What becomes a node, and what becomes an edge

| | Count | Rule |
|---|---|---|
| Nodes | 4,259 | Every entry except the 367 `redirect`s. |
| Edges | 54,692 directed | `resolved_cross_references` with a target and a status in `same_volume`, `cross_volume`, `deinflected`, `slash_half`. |

**Redirects are not nodes.** They carry no prose — a redirect's whole body
is "anima, ›Seele." — and `resolve_xrefs.py` already chases through them,
so almost nothing points at one. As nodes they would be 367 content-free
leaves. They stay in the database and stay findable: `build_lemma_index.py`
records each redirect's name against the article the chase ended on, and
those `redirect_alias` rows go into the search index. Typing `anima` finds
`Seele`.

**Ambiguous and unresolved references are not edges, but they are not
dropped either.** All 2,580 of them travel into the entry shards and are
shown in the reading pane, marked and inert. The resolver recorded
candidates and never guessed; an interface that silently omitted its
misses would claim a certainty the dataset does not have.

Self-loops (12) are dropped. Duplicate directed pairs collapse into a
`weight`: 53,255 of 55,117 pairs occur once, but a few are cited up to 8
times, and that repetition says something real about how tightly two
articles are bound.

## Communities

Leiden (`leidenalg`), on the undirected weighted projection. Leiden rather
than Louvain because Louvain can return internally disconnected
communities — on a map that is a "region" whose members have nothing
joining them, which is exactly the claim a spatial layout should not make
by accident.

Resolution is the one knob that decides how many regions the map has.
Measured on this corpus:

| resolution | communities ≥ 12 members | modularity |
|---|---|---|
| 0.55 | 4 | 0.451 |
| 1.0 | 8 | 0.451 |
| 1.5 | 13 | 0.432 |
| **2.0** | **20** | **0.395** |
| 3.0 | 39 | 0.351 |

2.0 is the default: ~20 is about the ceiling on how many hues stay tellable
apart, so past it the colour channel stops carrying information. Groups
below `MIN_COMMUNITY_SIZE` (12) are rounding artifacts rather than regions
and render neutral grey.

Community names are the **three most-cited headwords** in the community. No
LLM, no topic model: it says what a region's landmarks are instead of
inventing a theme for it, and for a cross-referenced encyclopedia the
most-cited member usually *is* the theme. The result is recognisable —
`Stoa · Ethik · normativ`, `Mengenlehre · Funktion · eindeutig`,
`Quantentheorie · Kausalität · Mechanik`, `Philosophie, indische ·
Philosophie, buddhistische · Logik, indische`.

## Layout

Fruchterman-Reingold on the giant component (4,208 of 4,259 nodes), seeded
through igraph's RNG. `ATLAS_LAYOUT` also accepts `drl`, `kk` and `umap`
(see `analysis.LAYOUTS`).

**The layout is community-aware, and it has to be.** The graph is dense —
50,001 edges over 4,259 nodes — so a plain force pass produces one hairball
with every community interleaved: pretty and unreadable. Edges whose ends
share a community are scaled by `LAYOUT_COMMUNITY_BOOST` (default 8) before
the simulation runs. This invents nothing: Leiden found those communities
in these same edges, so the boost only amplifies a division the graph
already contains. What changes is whether the eye can see it.

Measured as the ratio of mean intra-community to mean inter-community
distance (lower = more separated):

| | ratio | what it looks like |
|---|---|---|
| fr, boost 1 | 0.551 | one hairball, colours interleaved |
| **fr, boost 8** | **0.345** | readable regions, articles still distinct |
| drl, boost 1 | 0.343 | thin filaments around a large void |
| drl, boost 4 | 0.024 | each community collapses into a blob |

The best number is not the lowest one. Past roughly 0.3 the communities
contract into balls you cannot pick a single article out of, and the map
stops showing the corpus and starts showing only the partition.

The 51 nodes outside the giant component are placed **deliberately**, on a
ring outside the map. A force layout has no opinion about where a
disconnected node belongs, so left alone it flings them to arbitrary
distances, which reads as data. On a labelled ring, "nothing cites this and
it cites nothing" becomes a visible fact about the corpus.

Coordinates are normalised to ±1000 (the ring sits at ±1280) so the
frontend's opening zoom does not depend on what the force pass converged
to.

Node radius is `RADIUS_MIN + (RADIUS_MAX - RADIUS_MIN)·√(in_degree/max)`.
Square root, not linear: in-degree runs 0–269 with a median of 3, so a
linear scale collapses everything that is not a hub. `RADIUS_MIN` is a
floor rather than a zero — 1,381 entries are never cited, and they are
still articles.

## Artifacts (`export/viz/data/`, or `viz/data/` under `--dev`)

Data always sits at `<bundle>/data/`, so the frontend's fetch paths are
identical in both modes.

### `graph.json` (~1.0 MB)
Parallel arrays, not per-node objects — 4,259 objects would repeat every
key 4,259 times.

`ids`, `headwords`, `volumes`, `types`, `x`, `y`, `r`, `in_degree`,
`community` (all length 4,259, indexed by node number); `edges.source` /
`edges.target` (node indices) / `edges.weight`; and `communities`, one
record per region with `id`, `size`, `color`, `label`, `anchor` (the node
index of its most-cited member, used to place the region's name).

### `search-index.json` (~0.5 MB)
The `lemmas` table, filtered to entries that are on the map. Per row: `k`
(the already-folded `lemma_key`), `l` (display spelling), `n` (node index),
`v` (`primary` | `slash_half` | `comma_inverted` | `redirect_alias`), `t`
(the headword of the article you land on, so an alias hit can be shown as
`anima → Seele`).

Nothing is re-derived here — `build_lemma_index.py` already answered "find
the entry named X" across eight alphabetical volumes.

### `entries/<volume>.json` (8 shards, ~2.7–3.6 MB)
Per entry: `headword`, `volume`, `type`, `sigil`, `printed_page`, `body`,
`has_bib`, `refs`, `marks`.

Deliberately *not* here: the "cited by" list. The pane derives it from
graph.json's edge arrays, which hold the same information, so shipping it
again cost 0.32 MB a build for nothing.

`refs` is every outgoing reference *including* the failures: `o` (ordinal),
`raw`, `s` (status), `n` (target node index, or null), and `ctx` only when
the reference phrase says more than the arrow-marked word alone.

### `entries/<volume>.bib.json` (8 shards, ~1.5–2.0 MB)
`Werke:` and `Literatur:` per entry. Split out because the apparatus is
13.7 MB against the articles' 17.2 MB — carrying it inline would nearly
double every fetch to deliver something most readers never scroll to. It
is fetched only when its section is expanded.

### `MANIFEST.json`
Schema version, timestamp, every build parameter, counts, modularity, and
the inline-linkification coverage.

## Paragraph reflow — a display transform, not a dataset fix

`body_clean` still carries the printed edition's column and page breaks:
**6,214 of its 14,198 line breaks fall mid-sentence**, so an article reads
"…der Mensch verlangt nach einer" / blank line / "sinnvollen Welt". The
`Werke:`/`Literatur:` blocks are worse — 2,082 of 2,582 breaks land inside
a single citation.

`graph_data.reflow_for_display()` closes them for the reading pane. A break
survives only where the text before it ends a sentence *and* the text after
starts one; the bibliography (`keep_paragraphs=False`) closes every break,
since it is one run of semicolon-separated citations with no paragraphs in
it. A hyphen at the break is three different things, and the distinctions
are `parse_entries.py`'s, not new ones:

| | | |
|---|---|---|
| `unbezeich-` + `nete` | word broken by the typesetter | drop hyphen, join tight |
| `Ordinal-` + `und …` | suspended hyphen (the editors' own) | keep hyphen, add a space |
| `Leib-` + `Seele-…` | compound broken at its own hyphen | keep hyphen, join tight |

Two things this deliberately is not:

- **Not a dataset change.** The artifact is still in `body_clean` and in
  `export/entries.jsonl` for every other consumer. Fixing it upstream would
  mean re-running the whole chain and revising the golden suites; it is
  worth doing, but it is a dataset decision, not a rendering one.
- **Not in the link path.** References are detected in the *original* text
  and their spans mapped onto the reflowed string via
  `reflow_with_offsets()`. Detecting them after reflowing instead let
  formatting change the answer: joining two lines moves other text into
  `is_quotation()`'s 120-character window, which reclassified nine
  articles' references as quotations and cost them their links. Layout must
  never be able to decide what is a reference.

`check_viz.py` asserts no article breaks mid-sentence and no bibliography
contains a line break at all.

## Inline reference offsets, and why they are gated

`marks` makes `›Konfuzianismus` clickable in the reading pane: a list of
`[start, end, ref_index]` spans into `body`.

These **cannot** be found in the frontend. In Bd01–06 `›` is both the
cross-reference arrow *and* the ordinary German opening quotation mark;
keying on the glyph alone once turned 22,015 quotations into references,
6,148 of them false edges (`ISSUES.md` issue #12). Bd07/08 spell the arrow
`↑` instead. `scripts/parse_entries.py` already solved all of this, so the
build imports its matcher (`build_xref_re`, factored out for this purpose)
and its quotation discriminator (`is_quotation`) rather than restating
them — a second copy would drift silently.

They also cannot be taken straight from the parse: the parse ran on
`body_text`, and cleaning shifts every offset after the first change. So
the matcher is re-run against `body_clean` and the result is accepted only
when it agrees with what the parse stored — same count, same targets, same
order. **96.5% of entries pass** (4,057 of 4,204); the other 147 keep
`marks = null` and render as plain text. A paragraph without links beats a
link on the wrong word.

The gate has to mirror the parse step for step, including the hyphen
rejoining: where the typesetter broke `›Übersetzung` across a line, the
parse puts it back together, and a recovery pass that did not was rejected
on `Prädikator` — the single most-cited article in the corpus. That one
omission cost 1.6 points of coverage and 1,741 links.

`check_viz.py` re-verifies every emitted span independently: each must
start on its own volume's arrow glyph, name a real reference, and not
overlap its neighbour.

## Frontend (`viz/`)

Vanilla ES modules, no build step; d3 v7 from CDN for `d3-zoom`,
`d3-quadtree` and `d3-scale` only.

- `js/data.js` — graph up front, article text on demand, one fetch per shard
- `js/atlas.js` — canvas renderer, zoom/pan, hit-testing, edge display
- `js/search.js` — lemma search
- `js/filters.js` — the filter bar: fields on/off, citation filter
- `js/sidebar.js` — reading pane, inline links, reference navigation
- `js/main.js` — wiring

**Canvas, not SVG.** 4,259 nodes as DOM elements is 4,259 objects the
browser styles, hit-tests and repaints; on canvas they are one pass of
`arc()` calls, and a `d3-quadtree` gives hover hit-testing in O(log n) with
no per-node listeners.

**Edges are drawn on demand only.** All 50,001 at once are an even grey
wash that hides the structure the layout encodes, and they are the only
thing in the renderer that would cost real time per frame. On hover, the
node's links show faintly; on selection they split into two colours —
*what this cites* and *what cites it*, which is the question a reader of a
lexicon actually has.

Hub glow is a translucent disc, not `shadowBlur`: 449 nodes clear the glow
threshold and that many blurred fills per frame stutters a pan.

Selection has exactly one owner. Every path that changes it — a canvas
click, a reference link, a search hit, the close button — goes through
`atlas.select()`, and the pane reacts to that, so the two cannot disagree.

**Three ways to narrow the map, and how they compose.** The search box
dims everything that does not match while a query is typed; opening an
article clears it, because the article's own neighbourhood is what the
reader clicked for. The filter bar on the left (collapsible; it replaced
the legend) holds the other two: the fields, each with a checkbox, and a
citation filter — a list of articles, most-cited first and searchable, in
which ticking one or more narrows the map to the articles that refer to
them (*Verwiesen von*) and/or that they refer to (*Verweist auf*); several
ticked articles combine as a union. Fields and citation filter combine as
AND. With a filter active, an open article lights only the neighbours
inside the filter — the edges to the others are still drawn — unless
*Auswahl zeigt alle Nachbarn* is on. The bar's state lives in
`filters.js`; the map only ever receives the resulting node set.

## Deferred

Entry embeddings and LLM topic labels. When they arrive, they replace the
*input* to the layout stage, not the architecture: `analysis.compute_layout`
is the only function that decides where a node goes, and a second view mode
would be a second module beside `TopicLandscapeView`-style siblings. Also
out of scope for now: any metadata filtering, temporal statistics,
bibliography parsing, and author-sigil resolution (still open per
`docs/pipeline-strategy.md` §6.3).
