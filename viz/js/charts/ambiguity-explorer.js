/**
 * Kapitel 5: the references the resolver would not decide.
 *
 * Three lists, all plain DOM: the contested terms (one word, several
 * articles it could mean), the shared names (one surname, several people),
 * and the mirror image -- one article reachable under many names.
 */
import { communityColor, entryUrl, fmt } from '../story-data.js';
import { escapeHtml } from './chart-common.js';

export function renderAmbiguityExplorer(container, graph, story) {
  container.innerHTML = '';
  const amb = story.ambiguity;
  const root = d3.select(container).append('div').attr('class', 'amb-grid');

  // --- contested terms ---
  const terms = root.append('div').attr('class', 'amb-col amb-terms');
  terms.append('p').attr('class', 'fig-sub').text('Umstrittene Begriffe');
  terms.append('p').attr('class', 'fig-note').text('Verweise, die auf mehrere Artikel zugleich passen. Ein Klick zeigt die Kandidaten.');
  const list = terms.append('ol').attr('class', 'amb-list');
  const detail = terms.append('div').attr('class', 'amb-detail');
  const maxCount = amb.terms[0].citation_count;

  const items = list.selectAll('li').data(amb.terms.slice(0, 14)).join('li');
  items.append('span').attr('class', 'amb-term').text((d) => d.display);
  items.append('span').attr('class', 'amb-bar')
    .append('i').style('width', (d) => `${(100 * d.citation_count) / maxCount}%`);
  items.append('b').text((d) => `${fmt.int(d.citation_count)}× · ${d.candidate_count} Kandidaten`);

  function show(term) {
    items.classed('is-on', (d) => d === term);
    detail.html('');
    detail.append('p').attr('class', 'amb-head')
      .html(`<b>${escapeHtml(term.display)}</b> steht ${fmt.int(term.citation_count)}× hinter einem Verweispfeil` +
        (term.forms.length > 1 ? ` (auch als ${term.forms.slice(1).map((f) => `„${escapeHtml(f)}“`).join(', ')})` : '') +
        ` und könnte jedes Mal einen dieser ${term.candidate_count} Artikel meinen:`);
    const ul = detail.append('ul').attr('class', 'amb-cands');
    const li = ul.selectAll('li').data(term.candidates).join('li');
    li.append('i').style('background', (c) => (c.node === null ? 'transparent' : communityColor(graph, graph.community[c.node])));
    li.append('a')
      .attr('href', (c) => (c.node === null ? null : entryUrl(graph, c.node)))
      .classed('is-dead', (c) => c.node === null)
      .text((c) => c.headword);
    li.append('span').text((c) => volumeShort(c.volume));
  }
  items.on('click', (event, d) => show(d));
  show(amb.terms[0]);

  // --- shared names ---
  const names = root.append('div').attr('class', 'amb-col');
  names.append('p').attr('class', 'fig-sub').text('Ein Name, mehrere Menschen');
  names.append('p').attr('class', 'fig-note')
    .text(`${fmt.int(amb.homonyms.length)} Lemmata werden von mehreren Einträgen als Hauptname beansprucht. Die Dreifachen:`);
  const triple = amb.homonyms.filter((h) => h.count >= 3);
  const hl = names.append('ul').attr('class', 'amb-names');
  const hi = hl.selectAll('li').data(triple).join('li');
  hi.append('b').text((h) => titleCase(h.key));
  const inner = hi.append('span');
  inner.selectAll('a').data((h) => h.entries).join('a')
    .attr('href', (e) => (e.node === null ? null : entryUrl(graph, e.node)))
    .text((e) => e.display || e.headword);
  names.append('p').attr('class', 'fig-note')
    .text('Und zweifach unter anderem: ' + amb.homonyms.filter((h) => h.count === 2).slice(0, 14).map((h) => titleCase(h.key)).join(', ') + ' …');

  // --- one article, many names ---
  const alias = root.append('div').attr('class', 'amb-col');
  alias.append('p').attr('class', 'fig-sub').text('Eine Sache, viele Namen');
  alias.append('p').attr('class', 'fig-note').text('Artikel, die unter den meisten Verweisnamen erreichbar sind.');
  const al = alias.append('ul').attr('class', 'amb-names');
  const ai = al.selectAll('li').data(story.aliases.slice(0, 8)).join('li');
  ai.append('b').append('a').attr('href', (a) => entryUrl(graph, a.node)).text((a) => graph.headwords[a.node]);
  ai.append('span').text((a) => a.aliases.join(' · '));
}

function volumeShort(v) {
  const m = /^Bd0?(\d+)_/.exec(v);
  return m ? `Bd. ${m[1]}` : v;
}

function titleCase(key) {
  return key.replace(/(^|\s)(\p{L})/gu, (m, sp, ch) => sp + ch.toUpperCase());
}
