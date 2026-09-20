/**
 * What every chart on the essay page shares: an SVG sized to its
 * container, one tooltip, and the recessive axis styling.
 *
 * Charts are re-rendered from scratch on resize (see story-main.js); they
 * are cheap enough that keeping them stateless is simpler than updating.
 */

export const NEUTRAL = '#5b6472';
export const INK_EDGE = '#262a35';
export const TEXT_SOFT = '#a2a7b4';
export const TEXT_FAINT = '#6f7686';
export const ACCENT = '#ffb86b';
export const ACCENT_COOL = '#7ec8e3';

/** An SVG filling the container's width at the requested height. */
export function mount(container, { height, margin }) {
  container.innerHTML = '';
  const width = Math.max(320, container.getBoundingClientRect().width);
  const svg = d3
    .select(container)
    .append('svg')
    .attr('width', width)
    .attr('height', height)
    .attr('viewBox', `0 0 ${width} ${height}`)
    .attr('role', 'img');
  const inner = {
    width: width - margin.left - margin.right,
    height: height - margin.top - margin.bottom,
  };
  const g = svg.append('g').attr('transform', `translate(${margin.left},${margin.top})`);
  return { svg, g, width, height, inner };
}

export function styleAxis(sel) {
  sel.selectAll('path, line').attr('stroke', INK_EDGE);
  sel.selectAll('text').attr('fill', TEXT_FAINT).attr('font-family', 'var(--sans)').attr('font-size', 11);
  return sel;
}

export function gridLines(g, scale, orientation, length, ticks = scale.ticks ? scale.ticks(5) : scale.domain()) {
  const lines = g.append('g').attr('class', 'grid');
  for (const t of ticks) {
    const v = scale(t);
    if (orientation === 'x') {
      lines.append('line').attr('x1', v).attr('x2', v).attr('y1', 0).attr('y2', length);
    } else {
      lines.append('line').attr('x1', 0).attr('x2', length).attr('y1', v).attr('y2', v);
    }
  }
  lines.selectAll('line').attr('stroke', INK_EDGE).attr('stroke-opacity', 0.6);
  return lines;
}

/** One tooltip for the page. */
const tip = (() => {
  let el = null;
  function ensure() {
    if (!el) {
      el = document.createElement('div');
      el.className = 'story-tip';
      el.hidden = true;
      document.body.appendChild(el);
    }
    return el;
  }
  return {
    show(event, html) {
      const node = ensure();
      node.innerHTML = html;
      node.hidden = false;
      this.move(event);
    },
    move(event) {
      const node = ensure();
      const pad = 14;
      const rect = node.getBoundingClientRect();
      let x = event.clientX + pad;
      let y = event.clientY + pad;
      if (x + rect.width > window.innerWidth - 8) x = event.clientX - rect.width - pad;
      if (y + rect.height > window.innerHeight - 8) y = event.clientY - rect.height - pad;
      node.style.left = `${x}px`;
      node.style.top = `${y}px`;
    },
    hide() {
      if (el) el.hidden = true;
    },
  };
})();

export { tip };

export function escapeHtml(s) {
  return String(s).replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
}

/** Attach hover + click-through to a selection of marks. */
export function interactive(selection, { html, href }) {
  selection
    .style('cursor', href ? 'pointer' : 'default')
    .on('mouseenter', (event, d) => tip.show(event, html(d)))
    .on('mousemove', (event) => tip.move(event))
    .on('mouseleave', () => tip.hide());
  if (href) selection.on('click', (event, d) => { window.location.href = href(d); });
  return selection;
}

/** Shorten a headword for a direct label. */
export function shortLabel(s, max = 26) {
  return s.length > max ? `${s.slice(0, max - 1)}…` : s;
}

/** Break a long region name into two lines at the conjunction nearest its middle. */
export function labelLines(label) {
  if (label.length <= 24) return [label];
  const cut = d3.least([...label.matchAll(/ & |, /g)], (m) => Math.abs(m.index - label.length / 2));
  return cut ? [label.slice(0, cut.index + cut[0].length).trimEnd(), label.slice(cut.index + cut[0].length)] : [label];
}

/** Fill a <text> with `lines` as tspans, centred on the baseline the way a single line at dy 0.35em is. */
export function stackLines(text, lines, x = 0) {
  text.selectAll('tspan').data(lines).join('tspan')
    .attr('x', x).attr('dy', (l, i) => (i === 0 ? `${0.35 - 0.55 * (lines.length - 1)}em` : '1.1em')).text((l) => l);
}

/** Widest of `strings` in the chart sans face at `fontSize`, measured in a throwaway svg. */
export function textWidth(container, strings, fontSize) {
  const svg = d3.select(container).append('svg');
  const probe = svg.append('text').attr('font-family', 'var(--sans)').attr('font-size', fontSize);
  const width = d3.max(strings, (str) => probe.text(str).node().getComputedTextLength()) || 0;
  svg.remove();
  return width;
}
