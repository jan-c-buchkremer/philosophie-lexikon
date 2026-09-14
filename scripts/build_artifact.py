"""Flatten the atlas into ONE self-contained HTML file.

For hosts that cannot serve sibling files. A published Claude Artifact is
the case this was written for: its CSP blocks fetch/XHR entirely, so the
shard architecture cannot work there, and the whole page must fit in 16 MB.

What that costs, and why it is still worth shipping:

  * The `Werke:`/`Literatur:` apparatus is LEFT OUT -- 14 MB, and most of
    it never gets opened. `has_bib` is forced false so the section does
    not offer itself and then come up empty.
  * `cited_by` is dropped: the reading pane derives that list from the
    edge arrays in graph.json and never reads the field. (It is dead
    weight in the served shards too.)
  * The articles are gzipped and base64'd, ~24 MB down to ~10.7 MB, and
    inflated in the browser with DecompressionStream.

Everything else is the same code: the modules are concatenated with their
import/export lines stripped, and `window.__ATLAS_DATA` makes data.js read
from the page instead of the network.

  uv run python scripts/build_artifact.py [--out export/atlas.html]
"""
import argparse
import base64
import gzip
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
VIZ = ROOT / "viz"
DATA = VIZ / "data"
DEFAULT_OUT = ROOT / "export" / "atlas.html"

# Artifacts cap the rendered page at 16 MB; stop short of it rather than
# discover the limit at publish time.
SIZE_LIMIT = 15.4 * 1024 * 1024

# Concatenation order: definitions before the module that boots them.
MODULES = ("format.js", "data.js", "atlas.js", "search.js", "sidebar.js", "filters.js", "main.js")

IMPORT_RE = re.compile(r"^import\s.*?;\s*$", re.MULTILINE)
EXPORT_RE = re.compile(r"^export\s+(?=class|const|function|async)", re.MULTILINE)


def flatten_modules() -> str:
    """One module script from the module files, imports resolved by position."""
    parts = []
    for name in MODULES:
        source = (VIZ / "js" / name).read_text(encoding="utf-8")
        source = IMPORT_RE.sub("", source)
        source = EXPORT_RE.sub("", source)
        parts.append(f"/* ---- {name} ---- */\n{source.strip()}\n")
    return "\n".join(parts)


def page_markup() -> str:
    """The body of viz/index.html, without its own script tags.

    An Artifact supplies the document shell, so this file must contribute
    markup only -- no doctype, html, head or body of its own.
    """
    html = (VIZ / "index.html").read_text(encoding="utf-8")
    body = html.split("<body>", 1)[1].split("</body>", 1)[0]
    return re.sub(r"\s*<script\b.*?</script>", "", body, flags=re.DOTALL).strip()


def build_entries():
    """Every article, minus what the standalone page cannot use."""
    entries = {}
    for shard in sorted((DATA / "entries").glob("*.json")):
        if shard.name.endswith(".bib.json"):
            continue
        for entry_id, payload in json.loads(shard.read_text(encoding="utf-8")).items():
            payload.pop("cited_by", None)     # derived from graph.json
            payload["has_bib"] = False        # no bibliography in the bundle
            entries[entry_id] = payload
    raw = json.dumps(entries, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return gzip.compress(raw, 9), len(raw)


def script_safe(json_text: str) -> str:
    """Make a JSON payload safe to sit inside a <script> element.

    Two hazards:

    * `</` would close the element early, so it becomes `<\\/` -- still
      valid JSON, since `\\/` is an escaped solidus.
    * The corpus contains 17,886 U+FFFD characters, one for every glyph
      the source PDFs' font tables could not decode. They are kept on
      purpose (a visible gap beats a confident wrong letter) but a literal
      one in the page is rejected on publish, and an HTML entity would not
      help: entities are not parsed inside a <script>. Re-dumping with
      ensure_ascii writes them as JSON `\\ufffd` escapes, which parse back
      to exactly the same character.
    """
    ascii_only = json.dumps(json.loads(json_text), ensure_ascii=True,
                            separators=(",", ":"))
    return ascii_only.replace("</", "<\\/")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", default=str(DEFAULT_OUT))
    args = ap.parse_args()

    if not (DATA / "graph.json").exists():
        raise SystemExit("no data. Run: uv run python scripts/build_atlas.py --dev")

    graph = (DATA / "graph.json").read_text(encoding="utf-8")
    search = (DATA / "search-index.json").read_text(encoding="utf-8")
    entries_gz, entries_raw = build_entries()
    entries_b64 = base64.b64encode(entries_gz).decode("ascii")

    css = (VIZ / "style.css").read_text(encoding="utf-8")

    html = f"""<title>Atlas der Enzyklopädie</title>
<style>
{css}
/* The bundle inflates ~10 MB of articles before the map can be drawn, so
   the loading screen is a real wait here, not a flash. */
.loading .progress {{ font-size: 12.5px; color: var(--text-faint); }}
</style>

{page_markup()}

<script src="https://cdnjs.cloudflare.com/ajax/libs/d3/7.9.0/d3.min.js"></script>
<script id="atlas-graph" type="application/json">{script_safe(graph)}</script>
<script id="atlas-search" type="application/json">{script_safe(search)}</script>
<script id="atlas-entries" type="text/plain">{entries_b64}</script>
<script type="module">
const note = document.querySelector('#loading p');

function readJSON(id) {{
  return JSON.parse(document.getElementById(id).textContent);
}}

/** Inflate the base64'd gzip payload the page carries. */
async function readEntries() {{
  if (typeof DecompressionStream === 'undefined') {{
    throw new Error('Dieser Browser unterstützt DecompressionStream nicht.');
  }}
  if (note) note.textContent = 'Artikeltexte werden entpackt …';
  const b64 = document.getElementById('atlas-entries').textContent.trim();
  const bin = new Uint8Array(b64.length * 3 / 4 | 0);
  const raw = atob(b64);
  for (let i = 0; i < raw.length; i++) bin[i] = raw.charCodeAt(i);
  const stream = new Blob([bin.subarray(0, raw.length)])
    .stream()
    .pipeThrough(new DecompressionStream('gzip'));
  return JSON.parse(await new Response(stream).text());
}}

let entriesPromise = null;
window.__ATLAS_DATA = {{
  'graph.json': async () => readJSON('atlas-graph'),
  'search-index.json': async () => readJSON('atlas-search'),
  entries: () => (entriesPromise ||= readEntries()),
}};

// The articles are wanted the moment anything is clicked, and inflating
// them takes a second or two, so it starts now rather than on first use.
window.__ATLAS_DATA.entries().catch((error) => console.error(error));

{flatten_modules()}
</script>
"""

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(html, encoding="utf-8")
    size = out.stat().st_size

    print(f"articles   {entries_raw / 1e6:6.2f} MB -> {len(entries_gz) / 1e6:.2f} MB gz "
          f"-> {len(entries_b64) / 1e6:.2f} MB base64")
    print(f"graph      {len(graph.encode()) / 1e6:6.2f} MB")
    print(f"search     {len(search.encode()) / 1e6:6.2f} MB")
    print(f"\n{out}  {size / 1024 / 1024:.2f} MB")
    if size > SIZE_LIMIT:
        print(f"TOO BIG for an Artifact (limit 16 MB, budget {SIZE_LIMIT / 1024 / 1024:.1f})")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
