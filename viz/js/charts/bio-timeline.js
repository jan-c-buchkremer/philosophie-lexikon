/**
 * Kapitel 4: every dated life, one layer per region.
 *
 * A region is a row, a person a thin line from birth to death, and the
 * rows are sorted by the median birth year of their members. Nothing
 * about time went into the clustering, so if the rows form a staircase
 * the citation structure has recovered the periodisation by itself.
 */
import { communityColor, communityLabel, entryUrl, fmt } from '../story-data.js';
import { INK_EDGE, TEXT_FAINT, TEXT_SOFT, escapeHtml, mount, styleAxis, tip } from './chart-common.js';

const ERAS = [
  { key: 'antike', label: 'Antike', to: 500 },
  { key: 'mittelalter', label: 'Mittelalter', to: 1450 },
  { key: 'fruehe_neuzeit', label: 'Frühe Neuzeit', to: 1800 },
  { key: 'neunzehntes', label: '19. Jh.', to: 1900 },
  { key: 'zwanzigstes', label: '20. Jh.', to: null },
];

export function renderBioTimeline(container, graph, story) {
  const lives = story.lifedates.entries;
  const byComm = d3.group(lives, (d) => graph.community[d.node]);
  const rows = [...byComm.entries()]
    .filter(([c]) => c >= 0)
    .map(([c, members]) => ({ c, members, median: d3.median(members, (d) => d.birth) }))
    .sort((a, b) => a.median - b.median);

  const narrow = container.getBoundingClientRect().width < 640;
  const rowH = narrow ? 26 : 34;
  const margin = { top: 34, right: 34, bottom: 30, left: narrow ? 112 : 236 };
  const { g, inner } = mount(container, { height: rows.length * rowH + margin.top + margin.bottom, margin });

  // A piecewise-linear clock: each era gets width by how many lives it
  // holds, so the 19th century is not a sliver. The era bands and the
  // tick marks make the stretching visible rather than hiding it.
  const stops = [-650, 500, 1450, 1800, 1900, 2030];
  const widths = [0.13, 0.15, 0.28, 0.23, 0.21];
  const cum = widths.reduce((acc, w) => [...acc, acc[acc.length - 1] + w], [0]);
  const x = d3.scaleLinear().domain(stops).range(cum.map((f) => f * inner.width));
  const y = d3.scaleBand().domain(rows.map((r) => r.c)).range([0, rows.length * rowH]);

  // Era bands behind everything.
  let from = stops[0];
  ERAS.forEach((era, i) => {
    const to = era.to ?? stops[stops.length - 1];
    g.append('rect').attr('x', x(from)).attr('y', -margin.top + 22).attr('width', x(to) - x(from)).attr('height', rows.length * rowH + margin.top - 22)
      .attr('fill', i % 2 ? 'rgba(255,255,255,0.025)' : 'transparent');
    g.append('text').attr('x', (x(from) + x(to)) / 2).attr('y', -margin.top + 14).attr('text-anchor', 'middle')
      .attr('fill', TEXT_FAINT).attr('font-family', 'var(--sans)').attr('font-size', 10.5).attr('letter-spacing', '0.06em')
      .text(era.label.toUpperCase());
    from = to;
  });

  styleAxis(g.append('g').attr('transform', `translate(0,${rows.length * rowH})`)
    .call(d3.axisBottom(x).tickValues([-500, 0, 500, 1000, 1450, 1600, 1700, 1800, 1850, 1900, 1950, 2000]).tickFormat(fmt.year)));

  const row = g.selectAll('g.row').data(rows).join('g').attr('class', 'row')
    .attr('transform', (r) => `translate(0,${y(r.c)})`);
  row.append('line').attr('x1', 0).attr('x2', inner.width).attr('y1', rowH).attr('y2', rowH).attr('stroke', INK_EDGE).attr('stroke-opacity', 0.5);

  const label = row.append('g').attr('transform', `translate(${-margin.left},${rowH / 2})`);
  label.append('circle').attr('cx', 6).attr('r', 3.5).attr('fill', (r) => communityColor(graph, r.c));
  label.append('text').attr('x', 16).attr('dy', '0.35em')
    .attr('fill', TEXT_SOFT).attr('font-family', 'var(--sans)').attr('font-size', narrow ? 9.5 : 11)
    .text((r) => shorten(communityLabel(graph, r.c), narrow ? 16 : 34));
  row.append('text').attr('x', inner.width + 8).attr('y', rowH / 2).attr('dy', '0.35em')
    .attr('fill', TEXT_FAINT).attr('font-family', 'var(--sans)').attr('font-size', 10).attr('font-variant-numeric', 'tabular-nums')
    .text((r) => r.members.length);

  // Lives: one line each, jittered within the row by a stable hash so the
  // picture does not change between renders.
  const jitter = (d) => ((d.node * 2654435761) % 1000) / 1000;
  const pad = 5;
  row.each(function (r) {
    const color = communityColor(graph, r.c);
    d3.select(this).append('g').selectAll('line').data(r.members).join('line')
      .attr('x1', (d) => x(d.birth)).attr('x2', (d) => x(d.death))
      .attr('y1', (d) => pad + jitter(d) * (rowH - 2 * pad)).attr('y2', (d) => pad + jitter(d) * (rowH - 2 * pad))
      .attr('stroke', color).attr('stroke-opacity', 0.55).attr('stroke-width', 1.6).attr('stroke-linecap', 'round');
  });

  // The median birth year: the step of the staircase.
  row.append('line').attr('x1', (r) => x(r.median)).attr('x2', (r) => x(r.median)).attr('y1', 2).attr('y2', rowH - 2)
    .attr('stroke', '#e8e6e1').attr('stroke-width', 1.5).attr('stroke-opacity', 0.9);

  // Hover: the nearest life in the row under the cursor.
  const halo = g.append('rect').attr('height', 6).attr('rx', 3).attr('fill', 'none').attr('stroke', '#e8e6e1').attr('stroke-width', 1).style('display', 'none');
  g.append('rect').attr('width', inner.width).attr('height', rows.length * rowH).attr('fill', 'transparent').style('cursor', 'crosshair')
    .on('mousemove', (event) => {
      const [mx, my] = d3.pointer(event);
      const r = rows[Math.min(rows.length - 1, Math.max(0, Math.floor(my / rowH)))];
      const yIn = my - y(r.c);
      const best = d3.least(r.members, (d) => {
        const ly = pad + jitter(d) * (rowH - 2 * pad);
        const dx = mx < x(d.birth) ? x(d.birth) - mx : mx > x(d.death) ? mx - x(d.death) : 0;
        return Math.hypot(dx, (yIn - ly) * 1.5);
      });
      if (!best) return;
      const ly = y(r.c) + pad + jitter(best) * (rowH - 2 * pad);
      halo.style('display', null).attr('x', x(best.birth) - 3).attr('y', ly - 3).attr('width', x(best.death) - x(best.birth) + 6);
      tip.show(event, `<b>${escapeHtml(graph.headwords[best.node])}</b> · ${fmt.life(best.birth, best.death)}<br>` +
        `<i style="background:${communityColor(graph, r.c)}"></i>${escapeHtml(communityLabel(graph, r.c))}`);
      halo.datum(best);
    })
    .on('mouseleave', () => { halo.style('display', 'none'); tip.hide(); })
    .on('click', () => { const d = halo.datum(); if (d) window.location.href = entryUrl(graph, d.node); });

  d3.select(container).append('p').attr('class', 'fig-legend')
    .html('<span><i style="background:#e8e6e1;width:2px;height:12px;border-radius:0"></i>Median des Geburtsjahrs der Region</span>' +
      '<span>Zeilen nach diesem Median sortiert · Zahl am Zeilenende: datierte Personen der Region</span>');
  return rows;
}

function shorten(s, max) {
  return s.length > max ? `${s.slice(0, max - 1)}…` : s;
}
