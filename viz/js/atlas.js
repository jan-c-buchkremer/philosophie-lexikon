/**
 * The map itself: canvas rendering, zoom/pan, hit-testing, edge display.
 *
 * Canvas rather than SVG. 4,259 nodes as DOM elements means 4,259 layout
 * objects the browser must style, hit-test and repaint; on canvas they are
 * one pass of arc() calls with no DOM at all, and a d3-quadtree gives
 * hover hit-testing in O(log n) without any per-node listeners.
 */

const TAU = Math.PI * 2;

// Community labels are noise on the full map and orientation once you are
// inside a region, so they appear only past this zoom.
const LABEL_ZOOM = 0.55;
// Below this, individual nodes are sub-pixel anyway and drawing the small
// ones just greys the field; only the hubs are kept.
const DETAIL_ZOOM = 0.35;
// Roughly the top 450 most-cited entries; below it a halo is invisible
// anyway and only costs a fill.
const GLOW_MIN_RADIUS = 5;

// Direction is carried by hue, and the two hues are pushed well apart --
// warm amber outward, cold green-cyan inward -- because on a hub the two
// bundles are drawn over each other: Prädikator has 269 incoming against
// 75 outgoing, and a merely adjacent pair of blues loses the smaller
// bundle entirely. Outgoing also draws last and slightly heavier, so the
// minority direction stays findable. The toggles are the real fix; this
// is what makes the combined view legible at all.
export const EDGE_COLORS = {
  cites: '#ffa23d',    // what the selected entry points to
  citedBy: '#4fd6c4',  // what points at it
};

const COLORS = {
  base: '#0e0f13',
  neutral: '#5b6472',
  dimmed: 'rgba(120, 130, 145, 0.22)',
  selection: '#ffb86b',
  cites: 'rgba(255, 162, 61, 0.55)',
  citedBy: 'rgba(79, 214, 196, 0.34)',
  hoverEdge: 'rgba(150, 165, 185, 0.20)',
};

export class Atlas {
  constructor(canvas, graph, { onSelect, onHover, edgeView }) {
    this.canvas = canvas;
    this.ctx = canvas.getContext('2d');
    this.graph = graph;
    this.onSelect = onSelect;
    this.onHover = onHover;
    // Shared with the pane's direction toggles; mutated there, read here
    // on every draw so the two can never fall out of step.
    this.edgeView = edgeView || { incoming: true, outgoing: true };

    this.transform = d3.zoomIdentity;
    this.hover = null;
    this.selected = null;
    // null = no query. A Set of node indices = only these are lit.
    this.matches = null;
    // The filter bar's answer, same shape. `filterOverride` lets an open
    // article light its whole neighbourhood even outside the filter.
    this.filter = null;
    this.filterOverride = false;
    this.hiddenClusters = new Set();

    this.quadtree = d3
      .quadtree()
      .x((i) => graph.x[i])
      .y((i) => graph.y[i])
      .addAll(d3.range(graph.ids.length));

    this._initZoom();
    this._initPointer();
    this.resize();
    this.resetView();
  }

  // --- viewport ------------------------------------------------------------

  _initZoom() {
    this.zoom = d3
      .zoom()
      .scaleExtent([0.08, 14])
      .on('zoom', (event) => {
        this.transform = event.transform;
        this.draw();
      });
    d3.select(this.canvas).call(this.zoom).on('dblclick.zoom', null);
  }

  resize() {
    // Back the canvas at device resolution; at 1x the nodes are small
    // enough that the antialiasing does visible damage.
    const dpr = window.devicePixelRatio || 1;
    const rect = this.canvas.getBoundingClientRect();
    this.width = rect.width;
    this.height = rect.height;
    this.canvas.width = Math.round(rect.width * dpr);
    this.canvas.height = Math.round(rect.height * dpr);
    this.ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    this.draw();
  }

  resetView() {
    // The layout is normalised to +/-1000 with the disconnected ring just
    // outside it, so fitting ~1150 puts the whole corpus on screen with a
    // margin regardless of what the force pass converged to.
    const extent = 1150;
    const k = Math.min(this.width, this.height) / (extent * 2);
    this._applyTransform(d3.zoomIdentity.translate(this.width / 2, this.height / 2).scale(k), 0);
  }

  /** Centre one node without changing zoom, for a search hit. */
  flyTo(node, scale = 1.9) {
    const t = d3.zoomIdentity
      .translate(this.width / 2, this.height / 2)
      .scale(scale)
      .translate(-this.graph.x[node], -this.graph.y[node]);
    this._applyTransform(t, 650);
  }

  /** Bring a node back on screen at the current zoom if it has left it.
   *
   *  On small screens the canvas shrinks to make room for the pane, so
   *  the node that was just tapped can end up in the part of the map that
   *  is no longer drawn. Nothing happens while it is still in view: a
   *  desktop click must not move the map under the cursor.
   */
  ensureVisible(node) {
    const [x, y] = this.transform.apply([this.graph.x[node], this.graph.y[node]]);
    const margin = 24;
    const inView =
      x > margin && x < this.width - margin && y > margin && y < this.height - margin;
    if (!inView) this.flyTo(node, this.transform.k);
  }

  _applyTransform(transform, duration) {
    const sel = d3.select(this.canvas);
    (duration ? sel.transition().duration(duration) : sel).call(this.zoom.transform, transform);
  }

  // --- interaction ---------------------------------------------------------

  _initPointer() {
    const canvas = this.canvas;

    canvas.addEventListener('mousemove', (event) => {
      const node = this._nodeAt(event);
      if (node !== this.hover) {
        this.hover = node;
        canvas.style.cursor = node === null ? 'default' : 'pointer';
        this.onHover(node, event.clientX, event.clientY);
        this.draw();
      } else if (node !== null) {
        this.onHover(node, event.clientX, event.clientY);
      }
    });

    canvas.addEventListener('mouseleave', () => {
      this.hover = null;
      this.onHover(null);
      this.draw();
    });

    // A drag ends with a click event too, so distinguish the two by how
    // far the pointer travelled; otherwise panning the map opens whatever
    // node happened to be under the cursor when the drag stopped.
    let down = null;
    canvas.addEventListener('mousedown', (e) => { down = [e.clientX, e.clientY]; });
    canvas.addEventListener('click', (event) => {
      if (down && Math.hypot(event.clientX - down[0], event.clientY - down[1]) > 4) return;
      this.select(this._nodeAt(event));
    });
  }

  _nodeAt(event) {
    const rect = this.canvas.getBoundingClientRect();
    const [x, y] = this.transform.invert([event.clientX - rect.left, event.clientY - rect.top]);
    // Search radius in data units: a constant screen-space tolerance, so
    // small nodes stay clickable when zoomed out.
    const found = this.quadtree.find(x, y, 14 / this.transform.k);
    return found === undefined ? null : found;
  }

  select(node) {
    this.selected = node;
    this.onSelect(node);
    this.draw();
  }

  setMatches(matches) {
    this.matches = matches;
    this.draw();
  }

  setFilter(filter, { override = false, hiddenClusters = new Set() } = {}) {
    this.filter = filter;
    this.filterOverride = Boolean(override);
    this.hiddenClusters = hiddenClusters;
    this.draw();
  }

  _passesFilter(i) {
    return this.filter === null || this.filter.has(i);
  }

  // --- rendering -----------------------------------------------------------

  draw() {
    const { ctx, transform: t } = this;
    ctx.save();
    ctx.fillStyle = COLORS.base;
    ctx.fillRect(0, 0, this.width, this.height);
    ctx.translate(t.x, t.y);
    ctx.scale(t.k, t.k);

    this._drawEdges();
    this._drawNodes();
    ctx.restore();

    if (t.k >= LABEL_ZOOM) this._drawCommunityLabels();
    if (this.selected !== null) this._drawSelectedLabel();
  }

  /** Edges are drawn on demand only.
   *
   *  There are 50,001 of them. Drawn together they are an even grey wash
   *  that hides the very structure the layout encodes, and they would be
   *  the only thing in this renderer that costs real time per frame. Shown
   *  one neighbourhood at a time they answer the question a reader of a
   *  lexicon actually has: what does this article send me to, and what
   *  sent me here.
   */
  _drawEdges() {
    const focus = this.selected !== null ? this.selected : this.hover;
    if (focus === null) return;

    const { ctx, graph } = this;
    const { out, inc } = graph.adjacency;
    const isSelection = this.selected !== null;

    const stroke = (neighbours, color, width) => {
      ctx.strokeStyle = color;
      ctx.lineWidth = width / this.transform.k;
      ctx.beginPath();
      for (const n of neighbours) {
        ctx.moveTo(graph.x[focus], graph.y[focus]);
        ctx.lineTo(graph.x[n], graph.y[n]);
      }
      ctx.stroke();
    };

    if (isSelection) {
      // Incoming first so outgoing lands on top of it: outgoing is
      // usually the smaller bundle and would otherwise be buried.
      if (this.edgeView.incoming) stroke(inc[focus], COLORS.citedBy, 1);
      if (this.edgeView.outgoing) stroke(out[focus], COLORS.cites, 1.35);
    } else {
      stroke(out[focus].concat(inc[focus]), COLORS.hoverEdge, 1);
    }
  }

  _drawNodes() {
    const { ctx, graph, transform: t } = this;
    const detail = t.k >= DETAIL_ZOOM;
    const neighbours = this._focusNeighbourhood();
    const n = graph.ids.length;

    // Pass 1: haloes for the hubs. At this density size alone stops
    // reading once several large nodes sit near each other, so the
    // most-cited entries are also the brightest.
    //
    // Drawn as a plain translucent disc rather than canvas shadowBlur:
    // 449 nodes clear the glow threshold, and shadowBlur is expensive
    // enough that redrawing that many of them per frame visibly stutters
    // a pan. A second arc costs effectively nothing.
    ctx.globalAlpha = 0.13;
    for (let i = 0; i < n; i++) {
      const r = graph.r[i];
      if (r <= GLOW_MIN_RADIUS || !this._isLit(i, neighbours)) continue;
      ctx.beginPath();
      ctx.arc(graph.x[i], graph.y[i], r * 2.4, 0, TAU);
      ctx.fillStyle = this._colorOf(i);
      ctx.fill();
    }
    ctx.globalAlpha = 1;

    // Pass 2: the nodes themselves.
    for (let i = 0; i < n; i++) {
      const r = graph.r[i];
      // Below this zoom the small nodes are sub-pixel and only grey the
      // field; the hubs still carry the shape of the map.
      if (!detail && r < 3) continue;
      ctx.beginPath();
      ctx.arc(graph.x[i], graph.y[i], r, 0, TAU);
      ctx.fillStyle = this._isLit(i, neighbours) ? this._colorOf(i) : COLORS.dimmed;
      ctx.fill();
    }

    if (this.selected !== null) this._ring(this.selected, COLORS.selection, 3);
    if (this.hover !== null && this.hover !== this.selected) {
      this._ring(this.hover, 'rgba(255,255,255,0.75)', 2);
    }
  }

  /** Which nodes render at full strength.
   *
   *  A search query, the filter bar and an open article all narrow
   *  attention. A query wins outright while it is typed (selecting a hit
   *  clears it). Otherwise the filter applies, and an open article lights
   *  its neighbourhood WITHIN the filter -- the edges are still drawn to
   *  the neighbours outside it, so the reader sees that they exist -- or,
   *  with the bar's override on, the whole neighbourhood.
   */
  _isLit(i, neighbours) {
    if (this.matches) return this.matches.has(i);
    if (neighbours) return neighbours.has(i) && (this.filterOverride || this._passesFilter(i));
    return this._passesFilter(i);
  }

  _focusNeighbourhood() {
    if (this.selected === null) return null;
    const { out, inc } = this.graph.adjacency;
    return new Set([this.selected, ...out[this.selected], ...inc[this.selected]]);
  }

  _colorOf(i) {
    const community = this.graph.communityById.get(this.graph.community[i]);
    return community ? community.color : COLORS.neutral;
  }

  /** Called from inside draw()'s already-transformed context, so it must
   *  NOT re-apply the zoom transform -- only convert its screen-space
   *  offsets and stroke width into data units. */
  _ring(node, color, width) {
    const { ctx, graph, transform: t } = this;
    ctx.beginPath();
    ctx.arc(graph.x[node], graph.y[node], graph.r[node] + 5 / t.k, 0, TAU);
    ctx.strokeStyle = color;
    ctx.lineWidth = width / t.k;
    ctx.stroke();
  }

  /** Rectangles the labels must not be drawn under.
   *
   *  The header, legend and reading pane float over the canvas, so a
   *  label landing behind one of them renders as text tangled with the
   *  interface. The panels report their own boxes rather than the map
   *  guessing at their sizes.
   */
  setObstacles(rects) {
    this.obstacles = rects;
    this.draw();
  }

  _blocked(x, y) {
    return (this.obstacles || []).some(
      (r) => x > r.left - 60 && x < r.right + 60 && y > r.top - 14 && y < r.bottom + 14,
    );
  }

  /** Region names, anchored on each community's most-cited member. */
  _drawCommunityLabels() {
    const { ctx, graph, transform: t } = this;
    ctx.save();
    ctx.textAlign = 'center';
    ctx.font = '500 15px Iowan Old Style, Palatino Linotype, Georgia, serif';
    const fade = Math.min(1, (t.k - LABEL_ZOOM) * 2.2);

    for (const community of graph.communities) {
      const anchor = community.anchor;
      // The selected node draws its own, brighter label; drawing this one
      // too would print the same word twice in two colours.
      if (anchor === this.selected) continue;
      // A field switched off in the filter bar keeps no name either: the
      // label would float over a patch of dimmed nodes. (Other filters
      // leave the names: they are the reader's orientation.)
      if (this.hiddenClusters.has(community.id)) continue;

      const [x, y] = t.apply([graph.x[anchor], graph.y[anchor]]);
      if (y < 0 || y > this.height + 40) continue;
      if (this._blocked(x, y - 22)) continue;

      const name = graph.headwords[anchor];
      // Cull on the drawn width, not the anchor point: a centred label
      // whose anchor is just inside the viewport still runs off the edge,
      // and a half-word reads as a rendering fault.
      const half = ctx.measureText(name).width / 2;
      if (x - half < 8 || x + half > this.width - 8) continue;
      ctx.globalAlpha = fade * 0.5;
      ctx.fillStyle = '#05060a';
      ctx.fillText(name, x + 1, y - 21);
      ctx.globalAlpha = fade * 0.82;
      ctx.fillStyle = community.color;
      ctx.fillText(name, x, y - 22);
    }
    ctx.restore();
  }

  _drawSelectedLabel() {
    const { ctx, graph, transform: t } = this;
    const [x, y] = t.apply([graph.x[this.selected], graph.y[this.selected]]);
    ctx.save();
    ctx.font = '600 17px Iowan Old Style, Palatino Linotype, Georgia, serif';
    ctx.textAlign = 'center';
    const text = graph.headwords[this.selected];
    const offset = graph.r[this.selected] * t.k + 16;
    ctx.fillStyle = '#05060a';
    ctx.fillText(text, x + 1, y - offset + 1);
    ctx.fillStyle = COLORS.selection;
    ctx.fillText(text, x, y - offset);
    ctx.restore();
  }
}
