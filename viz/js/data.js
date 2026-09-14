/**
 * Data access: the graph up front, article text on demand.
 *
 * graph.json is ~1 MB and must be there before anything can be drawn.
 * Article text is 25 MB across eight volume shards and bibliography is a
 * further 14 MB, so both are fetched only when a reader actually opens
 * something, and each shard is fetched at most once.
 */

const DATA = 'data/';

/** A standalone bundle carries its data inside the page.
 *
 *  scripts/build_artifact.py inlines everything into one HTML file for
 *  hosts that cannot serve sibling files -- a published Artifact blocks
 *  fetch() outright. When that bundle is present the loaders read from it
 *  and every other module runs unchanged; otherwise they fetch as usual.
 */
const EMBEDDED = typeof window === 'undefined' ? null : window.__ATLAS_DATA || null;

function loadJSON(name) {
  return EMBEDDED ? EMBEDDED[name]() : fetch(DATA + name).then((r) => r.json());
}

/** Adjacency, built once from the flat edge arrays.
 *
 * graph.json ships edges as three parallel arrays because that is the
 * compact form to send. Every interaction, though, asks the neighbour
 * question -- "what does this node touch" -- so the arrays are indexed
 * once at load into per-node lists rather than scanned per hover.
 */
function buildAdjacency(graph) {
  const n = graph.ids.length;
  const out = Array.from({ length: n }, () => []);
  const inc = Array.from({ length: n }, () => []);
  const { source, target } = graph.edges;
  for (let i = 0; i < source.length; i++) {
    out[source[i]].push(target[i]);
    inc[target[i]].push(source[i]);
  }
  return { out, inc };
}

export async function loadGraph() {
  const [graph, search] = await Promise.all([
    loadJSON('graph.json'),
    loadJSON('search-index.json'),
  ]);

  graph.adjacency = buildAdjacency(graph);
  graph.index = new Map(graph.ids.map((id, i) => [id, i]));
  graph.communityById = new Map(graph.communities.map((c) => [c.id, c]));
  return { graph, search: search.rows };
}

const shardCache = new Map();

function loadShard(name) {
  if (!shardCache.has(name)) {
    // A bundle holds every article in one blob, so there is nothing to
    // shard; it carries no bibliography at all (see build_artifact.py).
    const load = EMBEDDED
      ? (name.endsWith('.bib') ? Promise.resolve({}) : EMBEDDED.entries())
      : fetch(`${DATA}entries/${name}.json`)
          .then((r) => (r.ok ? r.json() : {}))
          .catch(() => ({}));
    shardCache.set(name, load);
  }
  return shardCache.get(name);
}

/** The article behind a node. Volume is the shard key and is already the
 *  first segment of every entry id, so no lookup table is needed. */
export async function loadEntry(graph, node) {
  const id = graph.ids[node];
  const shard = await loadShard(id.split(':')[0]);
  return shard[id] || null;
}

/** Werke:/Literatur: for one entry, from the separate bibliography shard. */
export async function loadBibliography(graph, node) {
  const id = graph.ids[node];
  const shard = await loadShard(`${id.split(':')[0]}.bib`);
  return shard[id] || null;
}
