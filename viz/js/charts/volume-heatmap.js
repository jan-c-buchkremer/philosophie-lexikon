/**
 * Kapitel 2: volume (alphabet) against region (citation structure).
 *
 * Each cell is the share of a volume's entries that fall into a region --
 * shares rather than counts, because the volumes differ in size and the
 * question is whether the rows look alike. They do: no column belongs to
 * a volume, which is what Cramér's V near zero says in one number.
 */
import { communityColor, communityLabel, fmt } from '../story-data.js';
import { ACCENT_COOL, INK_EDGE, TEXT_FAINT, TEXT_SOFT, escapeHtml, labelLines, mount, stackLines, textWidth, tip } from './chart-common.js';

export function renderVolumeHeatmap(container, graph, story) {
  const h = story.volume_community_heatmap;
  const volumes = h.volumes;
  const ids = h.community_ids;
  const rowTotals = h.counts.map((row) => d3.sum(row) + 0);
  const shares = h.counts.map((row, i) => row.map((v) => v / rowTotals[i]));

  const narrow = container.getBoundingClientRect().width < 640;
  const cell = narrow ? 16 : 24;
  const fontSize = narrow ? 9 : 10;

  // The column labels lean at 55 degrees from their dot; the header and
  // the right margin must hold the longest one, so it is measured.
  const lean = (55 * Math.PI) / 180;
  const lines = ids.map((id) => labelLines(communityLabel(graph, id)));
  const reach = textWidth(container, lines.flat(), fontSize) + 11;
  const margin = { top: Math.ceil(reach * Math.sin(lean)) + 14, right: Math.ceil(reach * Math.cos(lean)) - 8, bottom: 8, left: 74 };
  const { g, inner } = mount(container, { height: volumes.length * cell + margin.top + margin.bottom, margin });

  const x = d3.scaleBand().domain(ids).range([0, inner.width]).paddingInner(0.12);
  const y = d3.scaleBand().domain(volumes).range([0, volumes.length * cell]).paddingInner(0.12);
  const maxShare = d3.max(shares.flat());
  const color = d3.scaleSequential([0, maxShare], d3.interpolateRgb('#16181f', ACCENT_COOL));

  const cells = g.selectAll('rect').data(shares.flatMap((row, i) => row.map((v, j) => ({ i, j, v, n: h.counts[i][j] })))).join('rect')
    .attr('x', (d) => x(ids[d.j])).attr('y', (d) => y(volumes[d.i]))
    .attr('width', x.bandwidth()).attr('height', y.bandwidth()).attr('rx', 2)
    .attr('fill', (d) => color(d.v));

  cells.on('mouseenter', (event, d) => {
    tip.show(event, `<b>${escapeHtml(volumeName(volumes[d.i]))}</b> · ` +
      `<i style="background:${communityColor(graph, ids[d.j])}"></i>${escapeHtml(communityLabel(graph, ids[d.j]))}<br>` +
      `${fmt.int(d.n)} Einträge = ${fmt.pct(d.v)} des Bandes`);
  }).on('mousemove', (event) => tip.move(event)).on('mouseleave', () => tip.hide());

  g.selectAll('text.row').data(volumes).join('text').attr('class', 'row')
    .attr('x', -8).attr('y', (d) => y(d) + y.bandwidth() / 2).attr('dy', '0.35em')
    .attr('text-anchor', 'end').attr('fill', TEXT_SOFT).attr('font-family', 'var(--sans)').attr('font-size', 11)
    .text((d) => volumeName(d));

  const cols = g.selectAll('g.col').data(ids).join('g').attr('class', 'col')
    .attr('transform', (d) => `translate(${x(d) + x.bandwidth() / 2},-6) rotate(-55)`);
  cols.append('circle').attr('cx', 4).attr('cy', 0).attr('r', 3).attr('fill', (d) => communityColor(graph, d));
  cols.append('text')
    .attr('fill', TEXT_FAINT).attr('font-family', 'var(--sans)').attr('font-size', fontSize)
    .each(function (d, i) { stackLines(d3.select(this), lines[i], 11); });

  g.append('rect').attr('x', -0.5).attr('y', -0.5).attr('width', inner.width + 1).attr('height', volumes.length * cell + 1)
    .attr('fill', 'none').attr('stroke', INK_EDGE);
}

/** "Bd03_G-Inn" -> "Bd. 3 · G–Inn". */
function volumeName(v) {
  const m = /^Bd0?(\d+)_(.+)$/.exec(v);
  return m ? `Bd. ${m[1]} · ${m[2].replace('-', '–')}` : v;
}
