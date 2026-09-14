/**
 * Boot and wiring. Everything stateful lives in Atlas, Search, Filters or
 * Sidebar; this file only connects them.
 */
import { Atlas } from './atlas.js';
import { loadGraph } from './data.js';
import { Filters } from './filters.js';
import { escapeHtml } from './format.js';
import { Search } from './search.js';
import { Sidebar } from './sidebar.js';

const els = {
  canvas: document.getElementById('map'),
  tooltip: document.getElementById('tooltip'),
  sidebar: document.getElementById('pane'),
  search: document.getElementById('search'),
  results: document.getElementById('results'),
  filters: document.getElementById('filters'),
  status: document.getElementById('status'),
  reset: document.getElementById('reset'),
  loading: document.getElementById('loading'),
};

async function boot() {
  const { graph, search: rows } = await loadGraph();
  const search = new Search(rows, graph);

  // Selection has exactly one owner: the map. Every path that changes it
  // -- a click on the canvas, a reference link, a search hit, the close
  // button -- calls atlas.select(), and the pane reacts to that. Nothing
  // opens the pane directly, so the two can never disagree.
  // One object, read by the renderer and written by the pane's toggles.
  const edgeView = { incoming: true, outgoing: true };

  const sidebar = new Sidebar(els.sidebar, graph, {
    onNavigate: (node) => {
      atlas.select(node);
      if (node !== null) atlas.flyTo(node);
    },
    edgeView,
    onEdgeToggle: () => atlas.draw(),
  });

  const atlas = new Atlas(els.canvas, graph, {
    edgeView,
    onSelect: (node) => {
      node === null ? sidebar.close() : sidebar.show(node);
      // Opening an article ends the search: its point is the article's
      // own neighbourhood, which the query's dimming would hide.
      if (node !== null) clearSearch(atlas);
      // The pane covers part of the map and part of the header, so both
      // the header's usable width and the label safe area change with it.
      document.body.classList.toggle('pane-open', node !== null);
      // On small screens the stylesheet shrinks the canvas instead of
      // covering it, so it has to be re-measured; elsewhere this is a
      // no-op redraw. The tapped node may now sit off the smaller canvas.
      atlas.resize();
      if (node !== null) atlas.ensureVisible(node);
      updateObstacles(atlas);
    },
    onHover: (node, x, y) => showTooltip(graph, node, x, y),
  });
  const filters = new Filters(els.filters, graph, {
    onChange: (visible, options) => {
      atlas.setFilter(visible, options);
      updateObstacles(atlas);
    },
    onFlyTo: (node, scale) => atlas.flyTo(node, scale),
  });
  // The map needs to know where the bar is from the start, and it may
  // have opened or closed itself from the stored preference.
  els.filters.querySelector('.filters-tab').addEventListener('click', () => updateObstacles(atlas));
  updateObstacles(atlas);

  wireSearch(atlas, search);

  els.reset.addEventListener('click', () => {
    atlas.select(null);
    clearSearch(atlas);
    filters.reset();
    atlas.resetView();
  });

  window.addEventListener('resize', () => {
    atlas.resize();
    updateObstacles(atlas);
  });
  window.addEventListener('keydown', (event) => {
    if (event.key === 'Escape') {
      if (els.search.value) clearSearch(atlas);
      else atlas.select(null);
      els.search.blur();
    }
    // "/" is the conventional jump-to-search key and costs nothing.
    if (event.key === '/' && document.activeElement !== els.search) {
      event.preventDefault();
      els.search.focus();
    }
  });

  // Debugging handle. The map is a canvas, so there is nothing in the
  // DOM to inspect when something renders wrong; this is how you ask it
  // what it thinks it is drawing. Also what viz/_smoke.html drives.
  window.__atlas = atlas;

  els.status.textContent =
    `${graph.ids.length.toLocaleString('de-DE')} Artikel · ` +
    `${graph.edges.source.length.toLocaleString('de-DE')} Verweise · ` +
    `${graph.communities.length} Felder`;
  els.loading.hidden = true;
}

/** Tell the map which parts of the canvas the interface is covering.
 *
 *  Visibility is decided from the measured rectangle, not `offsetParent`:
 *  all three panels are `position: fixed`, and a fixed element's
 *  offsetParent is always null, so testing it hid every obstacle and the
 *  labels drew straight through the legend.
 */
function updateObstacles(atlas) {
  // The filter bar slides out of view rather than hiding, so its box is
  // the part of it that is actually on screen: the whole bar, or its tab.
  const bar = document.body.classList.contains('filters-collapsed')
    ? els.filters.querySelector('.filters-tab')
    : els.filters;
  const boxes = [els.sidebar, bar, document.querySelector('.top')]
    .filter((el) => el && !el.hidden)
    .map((el) => el.getBoundingClientRect())
    .filter((rect) => rect.width > 0 && rect.height > 0);
  atlas.setObstacles(boxes);
}

function showTooltip(graph, node, x, y) {
  if (node === null) {
    els.tooltip.hidden = true;
    return;
  }
  els.tooltip.hidden = false;
  els.tooltip.textContent = graph.headwords[node];
  // Flip before the tooltip would run off the right edge.
  const flip = x + 260 > window.innerWidth;
  els.tooltip.style.left = `${flip ? x - 14 : x + 14}px`;
  els.tooltip.style.top = `${y + 16}px`;
  els.tooltip.style.transform = flip ? 'translateX(-100%)' : 'none';
}

function wireSearch(atlas, search) {
  let timer = null;

  els.search.addEventListener('input', () => {
    clearTimeout(timer);
    // Scanning 5,313 lemmas is fast, but not on every keystroke of a fast
    // typist while the canvas is also redrawing.
    timer = setTimeout(() => runSearch(atlas, search), 90);
  });

  els.results.addEventListener('click', (event) => {
    const item = event.target.closest('[data-node]');
    if (!item) return;
    const node = Number(item.dataset.node);
    // Selecting clears the search (see onSelect), list included.
    atlas.select(node);
    atlas.flyTo(node);
  });

  document.addEventListener('pointerdown', (event) => {
    if (!event.target.closest('.find')) els.results.hidden = true;
  });
  els.search.addEventListener('focus', () => {
    if (els.results.children.length) els.results.hidden = false;
  });
}

function runSearch(atlas, search) {
  const text = els.search.value;
  if (text.trim().length < 2) {
    resetSearchResults(atlas);
    return;
  }

  const hits = search.query(text);
  atlas.setMatches(search.matchingNodes(text));

  els.results.hidden = false;
  els.results.innerHTML = hits.length
    ? hits
        .map((hit) => `
          <li data-node="${hit.node}">
            <span class="hit-lemma">${escapeHtml(hit.lemma)}</span>
            ${hit.isAlias ? `<span class="hit-target">→ ${escapeHtml(hit.target)}</span>` : ''}
            ${hit.note ? `<span class="hit-note">${hit.note}</span>` : ''}
          </li>`)
        .join('')
    : '<li class="hit-empty">Kein Treffer.</li>';
}

/** Drop the results and the map filter, but LEAVE WHAT THE USER TYPED.
 *
 *  These were one function once, and runSearch() called it for any query
 *  under two characters -- so typing a single letter erased itself 90 ms
 *  later, and only typing fast enough to beat the debounce worked. The
 *  query belongs to the user; only Escape, the reset button and opening
 *  an article clear it.
 */
function resetSearchResults(atlas) {
  els.results.hidden = true;
  els.results.innerHTML = '';
  atlas.setMatches(null);
}

function clearSearch(atlas) {
  els.search.value = '';
  resetSearchResults(atlas);
}

boot().catch((error) => {
  console.error(error);
  els.loading.innerHTML =
    '<p>Daten konnten nicht geladen werden.</p>' +
    '<p class="hint">Zuerst <code>uv run python scripts/build_atlas.py --dev</code> ausführen.</p>';
});
