/**
 * Boot for geschichte.html: load, derive the figures the prose cites,
 * fill them in, draw the charts.
 *
 * Every number in the text comes from here, never from the HTML: a
 * <span data-fill="key"> is replaced by values[key]. The prose is written
 * in geschichte.md, where {key} becomes that span (build_story_html.py),
 * around the numbers, so a rebuilt corpus changes the figures but not the
 * sentences -- and if a claim stops being true the caption says so
 * (see the "claim" entries below).
 */
import { renderAmbiguityExplorer } from './charts/ambiguity-explorer.js';
import { renderBioTimeline } from './charts/bio-timeline.js';
import { renderCommunityChord } from './charts/community-chord.js';
import { renderHubBar } from './charts/hub-bar.js';
import { renderHubBridgeScatter } from './charts/hub-bridge-scatter.js';
import { renderVolumeHeatmap } from './charts/volume-heatmap.js';
import { communityLabel, findByHeadword, fmt, loadStory } from './story-data.js';

const ASIA_ANCHOR = 'Philosophie, indische';

function derive(graph, story) {
  const v = {};
  const c = story.corpus;
  const deg = graph.in_degree;
  const n = deg.length;
  const hw = graph.headwords;
  const comm = graph.community;
  const person = story.person;

  v.entries = fmt.int(c.entries);
  v.references = fmt.int(c.references);
  v.resolvedPct = fmt.pct(c.resolved_share);
  v.nodes = fmt.int(c.nodes);
  v.edges = fmt.int(c.directed_edges);
  v.communities = fmt.int(c.communities);
  v.persons = fmt.int(d3.sum(person));
  v.personsPct = fmt.pct(d3.sum(person) / n, 0);
  v.volumes = fmt.int(c.volumes.length);

  // --- Kapitel 1 ---
  const hubs = story.hub_ranking;
  v.hubN = fmt.int(hubs.n);
  v.personsInTop = hubs.persons_in_top === 0 ? 'keine einzige' : fmt.int(hubs.persons_in_top);
  v.topHub = hw[hubs.nodes[0]];
  v.topHubDeg = fmt.int(deg[hubs.nodes[0]]);
  v.hub2 = hw[hubs.nodes[1]]; v.hub2Deg = fmt.int(deg[hubs.nodes[1]]);
  v.hub3 = hw[hubs.nodes[2]]; v.hub3Deg = fmt.int(deg[hubs.nodes[2]]);
  v.topPerson = hw[hubs.top_persons[0]];
  v.topPersonDeg = fmt.int(deg[hubs.top_persons[0]]);
  for (const name of ['Leibniz', 'Kant', 'Hegel', 'Popper', 'Kripke', 'Aristoteles', 'Platon', 'Pythagoreer']) {
    const i = findByHeadword(graph, name);
    v[`deg${name}`] = i === null ? '–' : fmt.int(deg[i]);
  }
  v.median = fmt.int(hubs.median_in_degree);
  v.uncited = fmt.int(hubs.uncited);
  v.uncitedPct = fmt.pct(hubs.uncited / n, 0);
  v.uncitedPersonsPct = fmt.pct(hubs.uncited_persons / hubs.uncited, 0);
  v.lastHubDeg = fmt.int(deg[hubs.nodes[hubs.nodes.length - 1]]);

  // --- Kapitel 2 ---
  const cg = story.community_graph;
  const sizes = graph.communities;
  v.largestComm = communityLabel(graph, sizes[0].id);
  v.largestSize = fmt.int(sizes[0].size);
  v.smallestComm = communityLabel(graph, sizes[sizes.length - 1].id);
  v.smallestSize = fmt.int(sizes[sizes.length - 1].size);
  const total = d3.sum(cg.matrix, (row) => d3.sum(row));
  v.internalPct = fmt.pct(d3.sum(cg.matrix, (row, i) => row[i]) / total, 0);
  let best = null;
  cg.matrix.forEach((row, i) => row.forEach((w, j) => {
    if (i !== j && w >= 60) {
      const ratio = w / Math.max(1, cg.matrix[j][i]);
      if (!best || ratio > best.ratio) best = { i, j, w, back: cg.matrix[j][i], ratio };
    }
  }));
  v.flowFrom = communityLabel(graph, best.i);
  v.flowTo = communityLabel(graph, best.j);
  v.flowW = fmt.int(best.w);
  v.flowBack = fmt.int(best.back);
  v.flowRatio = fmt.ratio(best.ratio);
  const h = story.volume_community_heatmap;
  v.cramersV = fmt.two(h.cramers_v);
  v.chi2 = fmt.int(h.chi2);
  v.dof = fmt.int(h.dof);
  v.heatN = fmt.int(h.n);
  v.unassigned = fmt.int(d3.sum(h.unassigned_by_volume));

  // --- Kapitel 3 ---
  const bt = story.hub_bridge_scatter.betweenness;
  const byBt = d3.range(n).sort((a, b) => bt[b] - bt[a]);
  const byDeg = d3.range(n).sort((a, b) => deg[b] - deg[a]);
  const btRank = new Map(byBt.map((i, r) => [i, r + 1]));
  const degRank = new Map(byDeg.map((i, r) => [i, r + 1]));
  v.btTop = hw[byBt[0]];
  v.btTopDegRank = fmt.int(degRank.get(byBt[0]));
  const rat = findByHeadword(graph, 'Rationalität');
  v.ratBtRank = rat === null ? '–' : fmt.int(btRank.get(rat));
  v.ratDegRank = rat === null ? '–' : fmt.int(degRank.get(rat));
  v.ratDeg = rat === null ? '–' : fmt.int(deg[rat]);
  const bud = findByHeadword(graph, 'Philosophie, buddhistische');
  v.budBtRank = bud === null ? '–' : fmt.int(btRank.get(bud));
  v.budDegRank = bud === null ? '–' : fmt.int(degRank.get(bud));
  v.budDeg = bud === null ? '–' : fmt.int(deg[bud]);

  const asiaNode = findByHeadword(graph, ASIA_ANCHOR);
  const asia = asiaNode === null ? -1 : comm[asiaNode];
  const e = graph.edges;
  const extIn = new Map();
  let extOut = 0;
  let extInTotal = 0;
  for (let k = 0; k < e.source.length; k++) {
    const s = e.source[k]; const t = e.target[k]; const w = e.weight[k];
    if (comm[s] === asia && comm[t] !== asia) extOut += w;
    if (comm[t] === asia && comm[s] !== asia) { extInTotal += w; extIn.set(t, (extIn.get(t) || 0) + w); }
  }
  const top3 = [...extIn.entries()].sort((a, b) => b[1] - a[1]).slice(0, 3);
  v.asiaLabel = communityLabel(graph, asia);
  v.asiaSize = fmt.int(comm.filter((x) => x === asia).length);
  v.asiaOut = fmt.int(extOut);
  v.asiaIn = fmt.int(extInTotal);
  v.asiaRatio = fmt.ratio(extOut / Math.max(1, extInTotal));
  v.asiaTop3Pct = fmt.pct(d3.sum(top3, (d) => d[1]) / Math.max(1, extInTotal), 0);
  v.asiaTop3 = top3.map((d) => hw[d[0]]).join(', ');
  v.asiaInEntries = fmt.int(extIn.size);

  // --- Kapitel 4 ---
  const ld = story.lifedates;
  v.dated = fmt.int(ld.coverage.dated_total);
  v.datedBio = fmt.int(ld.coverage.dated_biographies);
  v.bioTotal = fmt.int(ld.coverage.total_biographies);
  v.datedPct = fmt.pct(ld.coverage.dated_biographies / ld.coverage.total_biographies, 0);
  v.datedOther = fmt.int(ld.coverage.dated_total - ld.coverage.dated_biographies);
  const eras = new Map(ld.eras.map((x) => [x.key, x.count]));
  const lives = ld.entries;
  for (const [key, name] of [['antike', 'Antike'], ['mittelalter', 'Mittelalter'], ['fruehe_neuzeit', 'Frueh'], ['neunzehntes', 'Neunzehn'], ['zwanzigstes', 'Zwanzig']]) {
    v[`era${name}`] = fmt.int(eras.get(key));
    v[`era${name}Pct`] = fmt.pct(eras.get(key) / lives.length, 0);
  }
  const eraOf = (y) => (y < 500 ? 'antike' : y < 1450 ? 'mittelalter' : y < 1800 ? 'fruehe_neuzeit' : y < 1900 ? 'neunzehntes' : 'zwanzigstes');
  const eraComm = d3.rollup(lives, (g) => d3.rollup(g, (m) => m.length, (d) => comm[d.node]), (d) => eraOf(d.birth));
  for (const [key, name] of [['antike', 'Antike'], ['mittelalter', 'Mittelalter'], ['fruehe_neuzeit', 'Frueh'], ['zwanzigstes', 'Zwanzig']]) {
    const m = eraComm.get(key);
    const top = [...m.entries()].sort((a, b) => b[1] - a[1])[0];
    v[`era${name}Top`] = communityLabel(graph, top[0]);
    v[`era${name}TopPct`] = fmt.pct(top[1] / d3.sum(m.values()), 0);
  }
  const rows = [...d3.group(lives, (d) => comm[d.node]).entries()].filter(([k]) => k >= 0)
    .map(([k, g]) => ({ k, median: d3.median(g, (d) => d.birth) })).sort((a, b) => a.median - b.median);
  v.firstRow = communityLabel(graph, rows[0].k);
  v.firstMedian = fmt.year(Math.round(rows[0].median));
  v.lastRow = communityLabel(graph, rows[rows.length - 1].k);
  v.lastMedian = fmt.year(Math.round(rows[rows.length - 1].median));
  const longest = d3.greatest(lives, (d) => d.death - d.birth);
  v.longestLife = hw[longest.node];
  v.longestSpan = fmt.int(longest.death - longest.birth);
  v.longestYears = fmt.life(longest.birth, longest.death);
  const hegel = findByHeadword(graph, 'Hegel');
  v.hegelComm = hegel === null ? '–' : communityLabel(graph, comm[hegel]);

  // --- Kapitel 5 ---
  const amb = story.ambiguity;
  v.ambiguous = fmt.int(amb.total_ambiguous);
  v.ambiguousPct = fmt.pct(amb.total_ambiguous / c.references);
  v.ambTerms = fmt.int(amb.distinct_terms);
  v.topTerm = amb.terms[0].display;
  v.topTermCount = fmt.int(amb.terms[0].citation_count);
  v.topTermCands = fmt.int(amb.terms[0].candidate_count);
  v.topTermList = amb.terms[0].candidates.map((x) => x.headword).join(', ');
  v.homonyms = fmt.int(amb.homonyms.length);
  v.homonymsTriple = fmt.int(amb.homonyms.filter((x) => x.count >= 3).length);
  v.homonymTripleNames = amb.homonyms.filter((x) => x.count >= 3).map((x) => x.entries[0].headword.split(',')[0]).join(', ');
  v.aliasTop = hw[story.aliases[0].node];
  v.aliasTopCount = fmt.int(story.aliases[0].aliases.length);
  v.aliasTopList = story.aliases[0].aliases.join(', ');
  v.unresolved = fmt.int(c.references_by_status.unresolved || 0);

  v.generated = story.generated_utc.slice(0, 10);
  return v;
}

function fill(values) {
  for (const el of document.querySelectorAll('[data-fill]')) {
    const key = el.dataset.fill;
    if (key in values) el.textContent = values[key];
    else el.textContent = '?';
  }
}

async function boot() {
  const loading = document.getElementById('loading');
  let graph; let story;
  try {
    ({ graph, story } = await loadStory());
  } catch (err) {
    loading.innerHTML = `<p>Keine Daten unter <code>data/</code>.</p>` +
      `<p class="hint">Erst <code>build_atlas.py --dev</code>, dann <code>build_story.py --dev</code> ausführen.</p>`;
    throw err;
  }
  fill(derive(graph, story));
  loading.hidden = true;

  const charts = [
    ['fig-hubs', renderHubBar],
    ['fig-chord', renderCommunityChord],
    ['fig-heatmap', renderVolumeHeatmap],
    ['fig-scatter', renderHubBridgeScatter],
    ['fig-strata', renderBioTimeline],
    ['fig-ambiguity', renderAmbiguityExplorer],
  ];
  const draw = () => {
    for (const [id, render] of charts) render(document.getElementById(id), graph, story);
  };
  draw();
  let timer = null;
  let lastWidth = window.innerWidth;
  window.addEventListener('resize', () => {
    if (window.innerWidth === lastWidth) return;
    lastWidth = window.innerWidth;
    clearTimeout(timer);
    timer = setTimeout(draw, 180);
  });

  document.querySelector('.story-progress').hidden = false;
  const bar = document.querySelector('.story-progress i');
  const onScroll = () => {
    const doc = document.documentElement;
    const max = doc.scrollHeight - doc.clientHeight;
    bar.style.width = `${max > 0 ? (100 * doc.scrollTop) / max : 0}%`;
  };
  document.addEventListener('scroll', onScroll, { passive: true });
  onScroll();
}

boot();
