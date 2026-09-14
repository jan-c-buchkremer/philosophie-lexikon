/**
 * The reading pane: one article, its apparatus, and its references.
 */
import { EDGE_COLORS } from './atlas.js';
import { escapeHtml } from './format.js';
import { loadBibliography, loadEntry } from './data.js';

const TYPE_LABEL = {
  subject_article: 'Sachartikel',
  biography: 'Biographie',
  unknown: 'Artikel',
  redirect: 'Verweis',
};

// Statuses the resolver reports when a reference actually landed.
const RESOLVED = new Set(['same_volume', 'cross_volume', 'deinflected', 'slash_half']);

export class Sidebar {
  constructor(element, graph, { onNavigate, edgeView, onEdgeToggle }) {
    this.el = element;
    this.graph = graph;
    this.onNavigate = onNavigate;
    // The same object the map reads when it draws, so the buttons cannot
    // show one state while the canvas draws another. Defaulted so the
    // pane still renders if it is constructed on its own.
    this.edgeView = edgeView || { incoming: true, outgoing: true };
    this.onEdgeToggle = onEdgeToggle || (() => {});
    this.node = null;

    this.el.addEventListener('click', (event) => {
      // Closing is a selection change, not just a panel action: the map
      // has to drop its highlight too. So it routes through the same
      // navigation callback, which calls back into close().
      if (event.target.closest('[data-close]')) return this.onNavigate(null);

      const toggle = event.target.closest('[data-edge]');
      if (toggle) {
        const kind = toggle.dataset.edge;
        this.edgeView[kind] = !this.edgeView[kind];
        toggle.classList.toggle('is-off', !this.edgeView[kind]);
        toggle.setAttribute('aria-pressed', String(this.edgeView[kind]));
        this.onEdgeToggle();
        return;
      }

      const link = event.target.closest('[data-node]');
      if (link) {
        event.preventDefault();
        this.onNavigate(Number(link.dataset.node));
        return;
      }
      const bib = event.target.closest('[data-load-bib]');
      if (bib) this._revealBibliography(bib);
    });
  }

  close() {
    this.node = null;
    this.el.hidden = true;
  }

  async show(node) {
    this.node = node;
    this.el.hidden = false;
    this.el.scrollTop = 0;
    this.el.innerHTML = `<div class="pane-loading">…</div>`;

    const entry = await loadEntry(this.graph, node);
    // A second click while this one was in flight; that render wins.
    if (this.node !== node) return;
    if (!entry) {
      this.el.innerHTML = `<div class="pane-loading">Eintrag nicht gefunden.</div>`;
      return;
    }
    this.el.innerHTML = this._render(node, entry);
  }

  _render(node, entry) {
    const community = this.graph.communityById.get(this.graph.community[node]);
    const cited = this.graph.in_degree[node];
    const sources = this.graph.adjacency.inc[node].length;
    const targets = this.graph.adjacency.out[node].length;

    return `
      <button class="pane-close" data-close aria-label="Schließen">×</button>
      <header class="pane-head">
        <p class="pane-kicker">${TYPE_LABEL[entry.type] || 'Artikel'}</p>
        <h2>${escapeHtml(entry.headword)}</h2>
        <p class="pane-meta">
          ${entry.volume.replace('_', ' ')}${entry.printed_page ? `, S.&nbsp;${entry.printed_page}` : ''}
          ${entry.sigil ? ` · ${escapeHtml(entry.sigil)}` : ''}
        </p>
        <p class="pane-stats">
          ${this._edgeToggle('incoming', 'Verwiesen von', sources, EDGE_COLORS.citedBy,
            `${cited} ${cited === 1 ? 'Verweis' : 'Verweise'} aus ${sources} Artikeln`)}
          ${this._edgeToggle('outgoing', 'Verweist auf', targets, EDGE_COLORS.cites,
            `${targets} aufgelöste Verweise auf der Karte`)}
          ${community ? `<span class="pane-region"><i style="background:${community.color}"></i>${escapeHtml(community.label.split(' · ')[0])}</span>` : ''}
        </p>
      </header>
      ${this._body(entry)}
      ${this._bibliography(entry)}
      ${this._references(entry)}
      ${this._citedBy(node)}
    `;
  }

  /** One direction of the citation graph: a count, a colour key, a switch.
   *
   *  The swatch is the map's own line colour for that direction, so the
   *  pane doubles as the legend for what is drawn behind it -- and the
   *  same control turns it off, which is the only reliable way to read a
   *  hub where 269 incoming lines cover 75 outgoing ones.
   */
  _edgeToggle(kind, label, count, color, title) {
    const on = this.edgeView[kind] !== false;
    return `
      <button class="edge-toggle${on ? '' : ' is-off'}" data-edge="${kind}"
              aria-pressed="${on}" title="${escapeHtml(title)} — ein-/ausblenden">
        <i style="background:${color}"></i>${label} <b>${count}</b>
      </button>`;
  }

  /** Article text, with its cross-references made navigable.
   *
   *  `marks` comes from the build stage, which re-ran the parser's own
   *  matcher over this exact string; it is null when that did not
   *  reproduce the stored reference list, and then the text renders plain
   *  rather than with links guessed in the browser. The arrow glyph is
   *  ambiguous in six of the eight volumes -- it is also the German
   *  opening quotation mark -- so guessing here would put links on quoted
   *  words.
   */
  _body(entry) {
    if (!entry.body) return '';
    const html = entry.marks ? this._linkify(entry) : escapeHtml(entry.body);
    return `<div class="pane-body">${html}</div>`;
  }

  _linkify(entry) {
    const { body, marks, refs } = entry;
    let html = '';
    let at = 0;

    for (const [start, end, refIndex] of marks) {
      html += escapeHtml(body.slice(at, start));
      const ref = refs[refIndex];
      // The span covers the arrow and the marked word; the arrow stays
      // visible but is not part of the clickable text. An opening
      // guillemet after the arrow ("↑›Ich‹") is punctuation the editors
      // wrote, not part of the target, so it stays with the arrow.
      const lead = body[start + 1] === '›' ? 2 : 1;
      const arrow = escapeHtml(body.slice(start, start + lead));
      const word = escapeHtml(body.slice(start + lead, end));

      if (ref && ref.n !== null && ref.n !== undefined) {
        const title = this.graph.headwords[ref.n];
        html += `<span class="xref-arrow">${arrow}</span><a class="xref" data-node="${ref.n}" title="${escapeHtml(title)}">${word}</a>`;
      } else {
        // Ambiguous and unresolved references are shown, marked, and
        // inert. The resolver never guessed which entry was meant; the
        // reading pane should not appear to know either.
        const why = ref && ref.s === 'ambiguous' ? 'mehrdeutig' : 'nicht aufgelöst';
        html += `<span class="xref-arrow">${arrow}</span><span class="xref xref-dead" title="Verweis ${why}">${word}</span>`;
      }
      at = end;
    }
    return html + escapeHtml(body.slice(at));
  }

  _bibliography(entry) {
    if (!entry.has_bib) return '';
    // Fetched only on expand: the bibliography shards are 14 MB in total
    // and most readers never open them.
    return `
      <details class="pane-section" data-load-bib>
        <summary>Werke &amp; Literatur</summary>
        <div class="bib-slot"><span class="pane-loading">…</span></div>
      </details>`;
  }

  async _revealBibliography(details) {
    if (details.dataset.loaded) return;
    details.dataset.loaded = '1';
    const slot = details.querySelector('.bib-slot');
    const bib = await loadBibliography(this.graph, this.node);
    slot.innerHTML = !bib
      ? '<p class="pane-empty">Keine Angaben.</p>'
      : ['werke', 'literatur']
          .filter((k) => bib[k])
          .map((k) => `<h4>${k === 'werke' ? 'Werke' : 'Literatur'}</h4><p class="bib-text">${escapeHtml(bib[k])}</p>`)
          .join('');
  }

  _references(entry) {
    if (!entry.refs.length) return '';
    const items = entry.refs.map((ref) => {
      if (ref.n !== null && ref.n !== undefined) {
        return `<li><a data-node="${ref.n}">${escapeHtml(this.graph.headwords[ref.n])}</a></li>`;
      }
      const why = ref.s === 'ambiguous' ? 'mehrdeutig' : 'nicht aufgelöst';
      return `<li class="ref-dead">${escapeHtml(ref.ctx || ref.raw)} <em>${why}</em></li>`;
    });
    const dead = entry.refs.filter((r) => !RESOLVED.has(r.s)).length;
    return `
      <details class="pane-section" open>
        <summary>Verweist auf <span class="count">${entry.refs.length}</span></summary>
        <ul class="ref-list">${items.join('')}</ul>
        ${dead ? `<p class="pane-note">${dead} davon konnten nicht eindeutig aufgelöst werden und bleiben unverlinkt.</p>` : ''}
      </details>`;
  }

  _citedBy(node) {
    const sources = this.graph.adjacency.inc[node];
    if (!sources.length) return '';
    const items = [...new Set(sources)]
      .sort((a, b) => this.graph.in_degree[b] - this.graph.in_degree[a])
      .map((n) => `<li><a data-node="${n}">${escapeHtml(this.graph.headwords[n])}</a></li>`);
    return `
      <details class="pane-section">
        <summary>Verwiesen von <span class="count">${items.length}</span></summary>
        <ul class="ref-list">${items.join('')}</ul>
      </details>`;
  }
}

