/**
 * Kapitel 3: how often an entry is cited against how often it lies on the
 * shortest path between two others.
 *
 * Both axes are square-root scales, the same encoding the atlas uses for
 * node radius: a third of all entries are never cited and most have
 * betweenness zero, which a log scale cannot show, while a linear scale
 * would pile everything into the corner. The named points are the two
 * kinds of exception -- bridges that are seldom cited, and the loudest
 * hubs.
 */
import { communityColor, communityLabel, entryUrl, fmt } from '../story-data.js';
import { ACCENT, ACCENT_COOL, NEUTRAL, TEXT_FAINT, TEXT_SOFT, escapeHtml, gridLines, mount, styleAxis, tip } from './chart-common.js';

export function renderHubBridgeScatter(container, graph, story) {
  const bt = story.hub_bridge_scatter.betweenness;
  const deg = graph.in_degree;
  const n = deg.length;
  const narrow = container.getBoundingClientRect().width < 640;
  const margin = { top: 16, right: 24, bottom: 46, left: 62 };
  const { g, inner } = mount(container, { height: narrow ? 380 : 480, margin });

  const x = d3.scaleSqrt().domain([0, d3.max(deg)]).range([0, inner.width]).nice();
  const y = d3.scaleSqrt().domain([0, d3.max(bt)]).range([inner.height, 0]).nice();

  const xTicks = [0, 5, 25, 50, 100, 150, 200, 250].filter((v) => v <= x.domain()[1]);
  const yTicks = [0, 5000, 25000, 50000, 100000, 200000, 300000].filter((v) => v <= y.domain()[1]);
  gridLines(g, x, 'x', inner.height, xTicks);
  gridLines(g, y, 'y', inner.width, yTicks);
  styleAxis(g.append('g').attr('transform', `translate(0,${inner.height})`)
    .call(d3.axisBottom(x).tickValues(xTicks).tickFormat(fmt.int)));
  styleAxis(g.append('g').call(d3.axisLeft(y).tickValues(yTicks).tickFormat((v) => (v >= 1000 ? `${v / 1000}k` : v))));

  g.append('text').attr('x', inner.width).attr('y', inner.height + 36).attr('text-anchor', 'end')
    .attr('fill', TEXT_FAINT).attr('font-family', 'var(--sans)').attr('font-size', 11)
    .text('eingehende Verweise (Zentralität als Prestige) →');
  g.append('text').attr('transform', 'rotate(-90)').attr('x', 0).attr('y', -46).attr('text-anchor', 'end')
    .attr('fill', TEXT_FAINT).attr('font-family', 'var(--sans)').attr('font-size', 11)
    .text('Betweenness (Zentralität als Vermittlung) →');

  // Bridges: high betweenness relative to their citations. The ratio
  // singles out entries that are on many paths without being a landmark.
  const byBt = d3.range(n).sort((a, b) => bt[b] - bt[a]);
  const byDeg = d3.range(n).sort((a, b) => deg[b] - deg[a]);
  const degRank = new Map(byDeg.map((i, r) => [i, r]));
  const bridges = byBt.slice(0, 40).filter((i) => degRank.get(i) >= 30).slice(0, 8);
  const hubs = byDeg.slice(0, 6);
  const named = new Set([...bridges, ...hubs]);

  const points = d3.range(n).filter((i) => deg[i] > 0 || bt[i] > 0);
  g.append('g').selectAll('circle').data(points.filter((i) => !named.has(i))).join('circle')
    .attr('cx', (i) => x(deg[i])).attr('cy', (i) => y(bt[i])).attr('r', 2.2)
    .attr('fill', NEUTRAL).attr('fill-opacity', 0.45);

  // Labels: bridges to the left of their point, hubs to the right, each
  // column spread apart so no two overlap, with a leader line back.
  const lineH = narrow ? 13 : 15;
  const place = (ids, side) => {
    const items = ids.map((i) => ({ i, px: x(deg[i]), py: y(bt[i]), ly: y(bt[i]), side }))
      .sort((a, b) => a.py - b.py);
    for (let k = 1; k < items.length; k++) {
      if (items[k].ly - items[k - 1].ly < lineH) items[k].ly = items[k - 1].ly + lineH;
    }
    // Push back up if the column ran off the bottom.
    const over = items.length ? items[items.length - 1].ly - (inner.height - 4) : 0;
    if (over > 0) for (const it of items) it.ly -= over;
    return items;
  };
  const labels = [...place(bridges, -1), ...place(hubs, 1)];
  const marks = g.append('g').selectAll('g').data(labels).join('g');
  marks.append('line')
    .attr('x1', (d) => d.px).attr('y1', (d) => d.py)
    .attr('x2', (d) => d.px + d.side * 9).attr('y2', (d) => d.ly)
    .attr('stroke', TEXT_FAINT).attr('stroke-width', 1).attr('stroke-opacity', 0.7);
  marks.append('circle').attr('cx', (d) => d.px).attr('cy', (d) => d.py).attr('r', 5)
    .attr('fill', (d) => (d.side < 0 ? ACCENT_COOL : ACCENT))
    .attr('stroke', '#0e0f13').attr('stroke-width', 1.5);
  marks.append('text')
    .attr('x', (d) => d.px + d.side * 12).attr('y', (d) => d.ly).attr('dy', '0.35em')
    .attr('text-anchor', (d) => (d.side < 0 ? 'end' : 'start'))
    .attr('fill', TEXT_SOFT).attr('font-family', 'var(--serif)').attr('font-size', narrow ? 11 : 12.5)
    .attr('paint-order', 'stroke').attr('stroke', '#16181f').attr('stroke-width', 3)
    .text((d) => graph.headwords[d.i]);
  marks.style('cursor', 'pointer').on('click', (event, d) => { window.location.href = entryUrl(graph, d.i); });

  // Hover anywhere: the nearest point, found through a Delaunay mesh.
  const delaunay = d3.Delaunay.from(points, (i) => x(deg[i]), (i) => y(bt[i]));
  const halo = g.append('circle').attr('r', 7).attr('fill', 'none').attr('stroke', ACCENT).attr('stroke-width', 1.5).style('display', 'none');
  g.append('rect').attr('width', inner.width).attr('height', inner.height).attr('fill', 'transparent')
    .style('cursor', 'crosshair')
    .on('mousemove', (event) => {
      const [mx, my] = d3.pointer(event);
      const i = points[delaunay.find(mx, my)];
      halo.style('display', null).attr('cx', x(deg[i])).attr('cy', y(bt[i]));
      tip.show(event, `<b>${escapeHtml(graph.headwords[i])}</b><br>` +
        `${fmt.int(deg[i])} eingehende Verweise · Betweenness ${fmt.int(bt[i])}<br>` +
        `<i style="background:${communityColor(graph, graph.community[i])}"></i>${escapeHtml(communityLabel(graph, graph.community[i]))}`);
    })
    .on('mouseleave', () => { halo.style('display', 'none'); tip.hide(); })
    .on('click', (event) => {
      const [mx, my] = d3.pointer(event);
      window.location.href = entryUrl(graph, points[delaunay.find(mx, my)]);
    });

  const legend = d3.select(container).append('p').attr('class', 'fig-legend');
  legend.html(`<span><i style="background:${ACCENT_COOL}"></i>leise Brücken: unter den 40 höchsten Betweenness-Werten, aber nicht unter den 30 meistzitierten</span>` +
    `<span><i style="background:${ACCENT}"></i>laute Zentren: die sechs meistzitierten Einträge</span>`);
  return { bridges, hubs };
}
