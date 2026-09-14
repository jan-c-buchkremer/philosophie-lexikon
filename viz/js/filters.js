/**
 * The filter bar: which part of the corpus the map shows.
 *
 * Two filters, both expressed as "which nodes are lit": the fields (the
 * Leiden clusters the legend used to only name), and a citation filter --
 * everything that refers to, or is referred to by, a chosen set of
 * articles. They combine as AND; inside the citation filter, several
 * chosen articles combine as OR ("refers to Kant or to Hegel").
 *
 * The bar owns the state and the DOM; the map only ever receives the
 * resulting Set through onChange, so the two cannot disagree about what
 * is filtered.
 */
import { EDGE_COLORS } from './atlas.js';
import { escapeHtml } from './format.js';
import { foldQuery } from './search.js';

// The citation list is a menu, not an index: the most-cited entries are
// what a reader reaches for, and the search box gets to the rest.
const LIST_LIMIT = 60;
const STORAGE_KEY = 'atlas.filters.collapsed';

export class Filters {
  constructor(element, graph, { onChange, onFlyTo }) {
    this.el = element;
    this.graph = graph;
    this.onChange = onChange || (() => {});
    this.onFlyTo = onFlyTo || (() => {});

    // Communities switched OFF -- empty means everything shows, which is
    // the common case and the one that must cost nothing.
    this.hiddenClusters = new Set();
    this.articles = new Set();
    this.direction = { incoming: true, outgoing: true };
    this.overrideOnSelect = false;
    this.query = '';

    // Every node once, most-cited first, with its headword folded the
    // same way the search index folds keys so one query matches both.
    this.ranked = graph.ids
      .map((_, i) => i)
      .sort((a, b) => graph.in_degree[b] - graph.in_degree[a] || graph.headwords[a].localeCompare(graph.headwords[b]));
    this.folded = graph.headwords.map((h) => foldQuery(h));

    this.els = {
      tab: element.querySelector('.filters-tab'),
      clusters: element.querySelector('.cluster-list'),
      articleSearch: element.querySelector('.article-search'),
      articles: element.querySelector('.article-list'),
      status: element.querySelector('.filters-status'),
      override: element.querySelector('[data-override]'),
    };

    this._renderClusters();
    this._renderDirection();
    this._renderArticles();
    this._wire();
    this._restoreCollapsed();
  }

  /** Nodes that pass every active filter, or null when nothing is filtered. */
  visibleSet() {
    const { graph } = this;
    const byCluster = this.hiddenClusters.size > 0;
    const byArticle = this.articles.size > 0;
    if (!byCluster && !byArticle) return null;

    let set;
    if (byArticle) {
      set = new Set(this.articles);
      const { inc, out } = graph.adjacency;
      for (const a of this.articles) {
        // "Verwiesen von": nodes whose article points at a -- a's incoming.
        if (this.direction.incoming) for (const n of inc[a]) set.add(n);
        if (this.direction.outgoing) for (const n of out[a]) set.add(n);
      }
    } else {
      set = new Set(graph.ids.map((_, i) => i));
    }
    if (byCluster) {
      for (const i of set) {
        if (this.hiddenClusters.has(graph.community[i])) set.delete(i);
      }
    }
    return set;
  }

  reset() {
    this.hiddenClusters.clear();
    this.articles.clear();
    this.direction.incoming = this.direction.outgoing = true;
    this.query = '';
    this.els.articleSearch.value = '';
    this._renderClusters();
    this._renderDirection();
    this._renderArticles();
    this._changed();
  }

  get collapsed() {
    return document.body.classList.contains('filters-collapsed');
  }

  setCollapsed(collapsed) {
    document.body.classList.toggle('filters-collapsed', collapsed);
    this.els.tab.setAttribute('aria-expanded', String(!collapsed));
    try {
      localStorage.setItem(STORAGE_KEY, collapsed ? '1' : '0');
    } catch {
      // Storage can be unavailable (private mode, blocked site data);
      // the bar then simply opens fresh next time.
    }
  }

  // --- rendering -----------------------------------------------------------

  _renderClusters() {
    this.els.clusters.innerHTML = this.graph.communities
      .map((c) => {
        const on = !this.hiddenClusters.has(c.id);
        return `
          <li class="${on ? '' : 'is-off'}" data-cluster="${c.id}" title="${escapeHtml(c.label)}">
            <input type="checkbox" ${on ? 'checked' : ''} aria-label="Feld ein-/ausblenden">
            <i style="background:${c.color}"></i>
            <span data-fly="${c.anchor}">${escapeHtml(c.label.split(' · ')[0])}</span>
            <b>${c.size}</b>
          </li>`;
      })
      .join('');
  }

  _renderDirection() {
    for (const button of this.el.querySelectorAll('[data-direction]')) {
      const kind = button.dataset.direction;
      const on = this.direction[kind];
      button.classList.toggle('is-off', !on);
      button.setAttribute('aria-pressed', String(on));
      button.querySelector('i').style.background = EDGE_COLORS[kind === 'incoming' ? 'citedBy' : 'cites'];
    }
  }

  _renderArticles() {
    const { graph } = this;
    const q = this.query;
    // Chosen articles stay at the top whatever is typed, so they can be
    // unchosen without first finding them again.
    const chosen = [...this.articles].sort((a, b) => graph.in_degree[b] - graph.in_degree[a]);
    const rest = [];
    for (const i of this.ranked) {
      if (this.articles.has(i)) continue;
      if (q && !this.folded[i].includes(q)) continue;
      rest.push(i);
      if (rest.length >= LIST_LIMIT) break;
    }
    const row = (i) => `
      <li class="${this.articles.has(i) ? 'is-on' : ''}" data-article="${i}">
        <input type="checkbox" ${this.articles.has(i) ? 'checked' : ''} aria-label="Artikel als Filter">
        <span class="hit-lemma">${escapeHtml(graph.headwords[i])}</span>
        <b title="Verwiesen von">${graph.in_degree[i]}</b>
      </li>`;
    this.els.articles.innerHTML =
      chosen.map(row).join('') +
      rest.map(row).join('') +
      (chosen.length + rest.length === 0 ? '<li class="hit-empty">Kein Treffer.</li>' : '');
  }

  _renderStatus(visible) {
    const total = this.graph.ids.length;
    const n = visible === null ? total : visible.size;
    this.els.status.textContent =
      `${n.toLocaleString('de-DE')} von ${total.toLocaleString('de-DE')} Artikeln`;
  }

  // --- events --------------------------------------------------------------

  _wire() {
    this.els.tab.addEventListener('click', () => this.setCollapsed(!this.collapsed));

    this.el.addEventListener('click', (event) => {
      const all = event.target.closest('[data-clusters]');
      if (all) {
        if (all.dataset.clusters === 'all') this.hiddenClusters.clear();
        else this.graph.communities.forEach((c) => this.hiddenClusters.add(c.id));
        this._renderClusters();
        return this._changed();
      }

      const fly = event.target.closest('[data-fly]');
      if (fly) return this.onFlyTo(Number(fly.dataset.fly), 1.1);

      const direction = event.target.closest('[data-direction]');
      if (direction) {
        const kind = direction.dataset.direction;
        this.direction[kind] = !this.direction[kind];
        this._renderDirection();
        return this._changed();
      }

      if (event.target.closest('[data-reset]')) return this.reset();

      // The row is the control: a click anywhere on it that is not the
      // checkbox itself (which handles its own click) flips the checkbox
      // and lets the change handler below do the rest.
      const row = event.target.closest('[data-cluster], [data-article]');
      if (row && event.target.tagName !== 'INPUT') {
        const box = row.querySelector('input');
        box.checked = !box.checked;
        box.dispatchEvent(new Event('change', { bubbles: true }));
      }
    });

    // Checkboxes fire `change`, and a click on the row's remaining
    // surface should toggle them too: the row is the control.
    this.el.addEventListener('change', (event) => {
      const cluster = event.target.closest('[data-cluster]');
      if (cluster) {
        const id = Number(cluster.dataset.cluster);
        event.target.checked ? this.hiddenClusters.delete(id) : this.hiddenClusters.add(id);
        cluster.classList.toggle('is-off', !event.target.checked);
        return this._changed();
      }
      const article = event.target.closest('[data-article]');
      if (article) {
        const i = Number(article.dataset.article);
        event.target.checked ? this.articles.add(i) : this.articles.delete(i);
        this._renderArticles();
        return this._changed();
      }
      if (event.target === this.els.override) {
        this.overrideOnSelect = event.target.checked;
        return this._changed();
      }
    });

    let timer = null;
    this.els.articleSearch.addEventListener('input', () => {
      clearTimeout(timer);
      timer = setTimeout(() => {
        this.query = foldQuery(this.els.articleSearch.value);
        this._renderArticles();
      }, 90);
    });
  }

  _changed() {
    const visible = this.visibleSet();
    this._renderStatus(visible);
    this.onChange(visible, {
      override: this.overrideOnSelect,
      hiddenClusters: new Set(this.hiddenClusters),
    });
  }

  _restoreCollapsed() {
    let stored = null;
    try {
      stored = localStorage.getItem(STORAGE_KEY);
    } catch {
      stored = null;
    }
    // Small screens start closed: open, the bar covers the map. The
    // stylesheet decides what "small" means, via the tab's data attribute.
    const small = getComputedStyle(this.els.tab).getPropertyValue('--small').trim() === '1';
    this.setCollapsed(stored === null ? small : stored === '1');
    this._renderStatus(null);
  }
}
