/**
 * Kapitel 1: the most-cited entries, with persons told apart from concepts.
 *
 * Two bar lists side by side on wide screens, stacked on narrow ones: the
 * top of the whole ranking (which contains no person at all) and the top
 * persons on their own scale, so that the second list is legible rather
 * than a row of slivers under the first.
 */
import { communityColor, communityLabel, entryUrl, fmt } from '../story-data.js';
import { ACCENT, ACCENT_COOL, TEXT_FAINT, TEXT_SOFT, escapeHtml, interactive, mount, shortLabel } from './chart-common.js';

const ROW = 22;

export function renderHubBar(container, graph, story) {
  container.innerHTML = '';
  const hubs = story.hub_ranking;
  const wrap = d3.select(container).append('div').attr('class', 'hub-grid');
  const all = wrap.append('div').attr('class', 'hub-col');
  const persons = wrap.append('div').attr('class', 'hub-col');

  all.append('p').attr('class', 'fig-sub').text(`Die ${hubs.n} meistzitierten Einträge`);
  persons.append('p').attr('class', 'fig-sub').text(`Die ${hubs.top_persons.length} meistzitierten Personen`);

  const max = graph.in_degree[hubs.nodes[0]];
  bars(all.node(), graph, story, hubs.nodes, max);
  bars(persons.node(), graph, story, hubs.top_persons, max);
}

function bars(container, graph, story, nodes, max) {
  const margin = { top: 4, right: 44, bottom: 4, left: 168 };
  const { g, inner } = mount(container, { height: nodes.length * ROW + margin.top + margin.bottom, margin });
  const x = d3.scaleLinear().domain([0, max]).range([0, inner.width]);
  const y = d3.scaleBand().domain(nodes).range([0, nodes.length * ROW]).paddingInner(0.3);

  const row = g.selectAll('g.row').data(nodes).join('g').attr('class', 'row')
    .attr('transform', (d) => `translate(0,${y(d)})`);

  row.append('rect')
    .attr('x', -margin.left).attr('y', -y.paddingInner() * y.step() / 2)
    .attr('width', inner.width + margin.left + margin.right).attr('height', y.step())
    .attr('fill', 'transparent');

  row.append('rect')
    .attr('x', 0).attr('width', (d) => Math.max(2, x(graph.in_degree[d])))
    .attr('height', y.bandwidth()).attr('rx', 2)
    .attr('fill', (d) => (story.person[d] ? ACCENT_COOL : ACCENT))
    .attr('fill-opacity', 0.85);

  row.append('circle')
    .attr('cx', -margin.left + 6).attr('cy', y.bandwidth() / 2).attr('r', 3.5)
    .attr('fill', (d) => communityColor(graph, graph.community[d]));

  row.append('text')
    .attr('x', -margin.left + 16).attr('y', y.bandwidth() / 2).attr('dy', '0.35em')
    .attr('fill', TEXT_SOFT).attr('font-family', 'var(--serif)').attr('font-size', 13)
    .text((d) => shortLabel(graph.headwords[d], 22));

  row.append('text')
    .attr('x', (d) => x(graph.in_degree[d]) + 6).attr('y', y.bandwidth() / 2).attr('dy', '0.35em')
    .attr('fill', TEXT_FAINT).attr('font-family', 'var(--sans)').attr('font-size', 11)
    .attr('font-variant-numeric', 'tabular-nums')
    .text((d) => fmt.int(graph.in_degree[d]));

  interactive(row, {
    html: (d) => `<b>${escapeHtml(graph.headwords[d])}</b><br>` +
      `${fmt.int(graph.in_degree[d])} eingehende Verweise · ` +
      `${story.person[d] ? 'Person' : 'Sachartikel'}<br>` +
      `<i style="background:${communityColor(graph, graph.community[d])}"></i>` +
      `${escapeHtml(communityLabel(graph, graph.community[d]))}`,
    href: (d) => entryUrl(graph, d),
  });
}
