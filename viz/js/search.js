/**
 * Search over the lemma index -- the map's only filter.
 *
 * The index is the `lemmas` table as built by scripts/build_lemma_index.py,
 * which already answers "find the entry named X" across eight alphabetical
 * volumes. Nothing is re-derived here: the keys arrive diacritic-folded and
 * casefolded, so matching is a plain comparison against an equally folded
 * query.
 */

const VARIANT_NOTE = {
  primary: '',
  slash_half: 'Teil eines Doppellemmas',
  comma_inverted: 'umgestellte Form',
  redirect_alias: 'Verweis',
};

const MAX_RESULTS = 40;

/** Fold a query the way normalize_key() folded the stored keys. */
export function foldQuery(text) {
  return text
    .normalize('NFD')
    // Combining marks, written as escapes rather than literal characters
    // so the class survives any re-encoding of this file.
    .replace(/[\u0300-\u036f]/g, '')
    .replace(/[()]/g, '')
    .toLowerCase()
    .trim();
}

export class Search {
  constructor(rows, graph) {
    this.rows = rows;
    this.graph = graph;
  }

  /** Ranked hits: whole-word, then prefix, then anywhere.
   *
   *  A reader typing "Logik" wants the article Logik before the fourteen
   *  compounds containing it, so the match position is the ranking signal.
   */
  query(text) {
    const q = foldQuery(text);
    if (q.length < 2) return [];

    const hits = [];
    for (const row of this.rows) {
      const at = row.k.indexOf(q);
      if (at === -1) continue;
      const rank = row.k === q ? 0 : at === 0 ? 1 : 2;
      hits.push({ row, rank, length: row.k.length });
    }

    hits.sort((a, b) => a.rank - b.rank || a.length - b.length || a.row.l.localeCompare(b.row.l));
    return hits.slice(0, MAX_RESULTS).map(({ row }) => ({
      node: row.n,
      lemma: row.l,
      // For a redirect or an inverted spelling, the article you land on is
      // not the string you typed -- so say which it is.
      target: row.t,
      note: VARIANT_NOTE[row.v] || '',
      isAlias: row.v !== 'primary' && row.t !== row.l,
    }));
  }

  /** Every node matching the query, for dimming the rest of the map.
   *
   *  Deliberately not capped at MAX_RESULTS: the result list is a menu,
   *  but the map should show the query's full footprint across the corpus.
   */
  matchingNodes(text) {
    const q = foldQuery(text);
    if (q.length < 2) return null;
    const nodes = new Set();
    for (const row of this.rows) {
      if (row.k.includes(q)) nodes.add(row.n);
    }
    return nodes;
  }
}
