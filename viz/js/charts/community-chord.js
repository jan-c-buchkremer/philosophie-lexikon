/**
 * Kapitel 2: which regions cite which, as a directed chord diagram.
 *
 * The diagonal (a region citing itself) is left out of the ribbons: it is
 * three quarters of all references and would drown the flows between
 * regions, which are the point here. Hovering a region keeps only its
 * ribbons; the list beside the ring names the strongest one-way flows.
 */
import { communityColor, communityLabel, fmt } from '../story-data.js';
import { INK_EDGE, TEXT_FAINT, TEXT_SOFT, escapeHtml, tip } from './chart-common.js';

export function renderCommunityChord(container, graph, story) {
  container.innerHTML = '';
  const cg = story.community_graph;
  const k = cg.matrix.length;
  const matrix = cg.matrix.map((row, i) => row.map((v, j) => (i === j ? 0 : v)));

  const wrap = d3.select(container).append('div').attr('class', 'chord-grid');
  const ringBox = wrap.append('div').attr('class', 'chord-ring');
  const side = wrap.append('div').attr('class', 'chord-side');

  const width = Math.max(320, Math.min(640, ringBox.node().getBoundingClientRect().width));
  // Room for the longest label at the horizontal positions, where it
  // cannot lean away from its neighbours.
  const outer = width / 2 - (width < 480 ? 74 : 124);
  const innerR = outer - 12;
  const svg = ringBox.append('svg').attr('width', width).attr('height', width)
    .attr('viewBox', `${-width / 2} ${-width / 2} ${width} ${width}`).attr('role', 'img');

  const chord = d3.chordDirected().padAngle(0.03).sortSubgroups(d3.descending).sortChords(d3.descending);
  const chords = chord(matrix);
  const arc = d3.arc().innerRadius(innerR).outerRadius(outer);
  const ribbon = d3.ribbonArrow().radius(innerR - 2).padAngle(1 / innerR);

  const ribbons = svg.append('g').attr('fill-opacity', 0.55).selectAll('path').data(chords).join('path')
    .attr('d', ribbon)
    .attr('fill', (d) => communityColor(graph, d.source.index))
    .attr('stroke', 'none');

  const groups = svg.append('g').selectAll('g').data(chords.groups).join('g');
  groups.append('path').attr('d', arc)
    .attr('fill', (d) => communityColor(graph, d.index))
    .attr('stroke', INK_EDGE);

  groups.append('text')
    .each((d) => { d.angle = (d.startAngle + d.endAngle) / 2; })
    .attr('dy', '0.35em')
    .attr('transform', (d) => `rotate(${(d.angle * 180) / Math.PI - 90}) translate(${outer + 8}) ${d.angle > Math.PI ? 'rotate(180)' : ''}`)
    .attr('text-anchor', (d) => (d.angle > Math.PI ? 'end' : 'start'))
    .attr('fill', TEXT_SOFT).attr('font-family', 'var(--sans)').attr('font-size', width < 480 ? 9 : 10.5)
    .text((d) => {
      const label = communityLabel(graph, d.index);
      return width < 480 && label.length > 18 ? `${label.slice(0, 17)}…` : label;
    });

  const outgoing = matrix.map((row) => d3.sum(row));
  const incoming = matrix[0].map((_, j) => d3.sum(matrix, (row) => row[j]));

  function focus(i) {
    ribbons.attr('fill-opacity', (d) => (i === null || d.source.index === i || d.target.index === i ? 0.7 : 0.05));
    groups.attr('opacity', (d) => (i === null || d.index === i || matrix[i][d.index] > 0 || matrix[d.index][i] > 0 ? 1 : 0.3));
  }

  groups
    .style('cursor', 'default')
    .on('mouseenter', (event, d) => {
      focus(d.index);
      tip.show(event, `<b>${escapeHtml(communityLabel(graph, d.index))}</b><br>` +
        `${fmt.int(graph.communityById.get(d.index).size)} Einträge<br>` +
        `zitiert andere Regionen ${fmt.int(outgoing[d.index])}× · wird ${fmt.int(incoming[d.index])}× zitiert`);
    })
    .on('mousemove', (event) => tip.move(event))
    .on('mouseleave', () => { focus(null); tip.hide(); });

  ribbons
    .on('mouseenter', (event, d) => {
      tip.show(event, `<b>${escapeHtml(communityLabel(graph, d.source.index))}</b> → ` +
        `<b>${escapeHtml(communityLabel(graph, d.target.index))}</b><br>` +
        `${fmt.int(d.source.value)} Verweise · zurück ${fmt.int(matrix[d.target.index][d.source.index])}`);
    })
    .on('mousemove', (event) => tip.move(event))
    .on('mouseleave', () => tip.hide());

  // The strongest one-way flows, for the reader who wants numbers.
  const pairs = [];
  for (let i = 0; i < k; i++) for (let j = 0; j < k; j++) if (i !== j && matrix[i][j] >= 60) {
    pairs.push({ i, j, w: matrix[i][j], back: matrix[j][i], ratio: matrix[i][j] / Math.max(1, matrix[j][i]) });
  }
  pairs.sort((a, b) => b.ratio - a.ratio);
  side.append('p').attr('class', 'fig-sub').text('Die einseitigsten Beziehungen');
  side.append('p').attr('class', 'fig-note').text('Verweise von A nach B gegen die Rückrichtung, unter allen Paaren mit mindestens 60 Verweisen.');
  const list = side.append('ol').attr('class', 'flow-list');
  const item = list.selectAll('li').data(pairs.slice(0, 7)).join('li');
  item.append('span').attr('class', 'flow-from')
    .html((d) => `<i style="background:${communityColor(graph, d.i)}"></i>${escapeHtml(communityLabel(graph, d.i))}`);
  item.append('span').attr('class', 'flow-arrow').text('→');
  item.append('span').attr('class', 'flow-to')
    .html((d) => `<i style="background:${communityColor(graph, d.j)}"></i>${escapeHtml(communityLabel(graph, d.j))}`);
  item.append('b').text((d) => `${fmt.int(d.w)} : ${fmt.int(d.back)}`);
  item.on('mouseenter', (event, d) => {
    ribbons.attr('fill-opacity', (r) => (r.source.index === d.i && r.target.index === d.j) || (r.source.index === d.j && r.target.index === d.i) ? 0.85 : 0.05);
  }).on('mouseleave', () => focus(null));

  side.append('p').attr('class', 'fig-note').style('color', TEXT_FAINT)
    .text(`Innerhalb der eigenen Region bleiben ${fmt.pct(d3.sum(cg.matrix, (row, i) => row[i]) / d3.sum(cg.matrix, (row) => d3.sum(row)), 0)} aller Verweise.`);
}
