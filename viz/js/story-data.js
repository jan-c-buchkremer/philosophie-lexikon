/**
 * Data access for the essay page.
 *
 * graph.json is the atlas's own file -- node order, communities, colours --
 * and story.json (scripts/build_story.py) holds the numbers derived from
 * it. Reading both means the essay can never disagree with the map about
 * which entry belongs where.
 */

const DATA = 'data/';

function loadJSON(name) {
  return fetch(DATA + name).then((r) => {
    if (!r.ok) throw new Error(`${name}: ${r.status}`);
    return r.json();
  });
}

export async function loadStory() {
  const [graph, story] = await Promise.all([loadJSON('graph.json'), loadJSON('story.json')]);
  graph.index = new Map(graph.ids.map((id, i) => [id, i]));
  graph.communityById = new Map(graph.communities.map((c) => [c.id, c]));
  for (const c of story.community_graph.communities) {
    graph.communityById.get(c.id).shortLabel = c.short_label;
  }
  return { graph, story };
}

/** The atlas, opened on one entry (main.js reads ?entry=). */
export function entryUrl(graph, node) {
  return `index.html?entry=${encodeURIComponent(graph.ids[node])}`;
}

export function communityLabel(graph, c) {
  const meta = graph.communityById.get(c);
  return meta ? meta.shortLabel || meta.label : 'ohne Region';
}

export function communityColor(graph, c) {
  const meta = graph.communityById.get(c);
  return meta ? meta.color : '#6b7280';
}

/** The node for a headword; where several entries share one, the most cited. */
export function findByHeadword(graph, headword) {
  let best = -1;
  graph.headwords.forEach((h, i) => {
    if (h === headword && (best < 0 || graph.in_degree[i] > graph.in_degree[best])) best = i;
  });
  return best < 0 ? null : best;
}

const intFormat = new Intl.NumberFormat('de-DE');
const fixed = (digits) =>
  new Intl.NumberFormat('de-DE', { minimumFractionDigits: digits, maximumFractionDigits: digits });
const oneDecimal = fixed(1);
const twoDecimals = fixed(2);

export const fmt = {
  int: (v) => intFormat.format(Math.round(v)),
  pct: (v, digits = 1) => `${fixed(digits).format(v * 100)} %`,
  decimal: (v) => oneDecimal.format(v),
  two: (v) => twoDecimals.format(v),
  ratio: (v) => `${oneDecimal.format(v)}:1`,
  /** -428 -> "428 v. Chr.", 1724 -> "1724". */
  year: (y) => (y < 0 ? `${-y} v. Chr.` : String(y)),
  /** A life: "428–348 v. Chr.", "4 v. Chr.–65", "1724–1804". */
  life: (b, d) => {
    if (b < 0 && d < 0) return `${-b}–${-d} v. Chr.`;
    if (b < 0) return `${-b} v. Chr.–${d}`;
    return `${b}–${d}`;
  },
};
