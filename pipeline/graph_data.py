"""All atlas-stage I/O: reads lexikon.db, writes the frontend's artifacts.

Deliberately holds no analysis logic -- positions, communities and metrics
are computed in `analysis.py` and handed back here to be written. Mirrors
the separation the extraction pipeline already keeps between parsing and
resolution.
"""
import json
import logging
import re
import shutil
import sqlite3
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

from .config import Config

# The atlas re-uses the extraction stage's own cross-reference matcher
# rather than restating it; see recover_inline_offsets() for why that
# matters. scripts/ is not a package, so it joins sys.path the same way
# build_lemma_index.py and check_dataset.py already do.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
from parse_entries import (  # noqa: E402
    SUSPENDED_HYPHEN_NEXT_WORDS,
    build_xref_re,
    rejoin_hyphenated_target,
    volume_config,
)
from resolve_xrefs import normalize_key  # noqa: E402

logger = logging.getLogger(__name__)


# --- reading ---------------------------------------------------------------

def connect(db_path: Path) -> sqlite3.Connection:
    if not db_path.exists():
        raise SystemExit(
            f"{db_path} not found. Build it first:\n"
            f"  uv run python scripts/build_db.py\n"
            f"  uv run python scripts/resolve_xrefs.py"
        )
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def load_nodes(conn: sqlite3.Connection) -> list[dict]:
    """One row per mapped entry, in a stable order.

    Ordered by (volume, ordinal) so a node's index in every parallel array
    the frontend receives is reproducible across runs.
    """
    where = "WHERE entry_type != 'redirect'" if Config.EXCLUDE_REDIRECTS else ""
    rows = conn.execute(f"""
        SELECT id, volume, headword_clean, headword, entry_type,
               printed_page_start, pdf_page_start, author_sigil
        FROM entries {where}
        ORDER BY volume, ordinal
    """).fetchall()
    return [
        {
            "id": r["id"],
            "volume": r["volume"],
            # headword_clean is NULL only if clean_text.py never ran.
            "headword": r["headword_clean"] or r["headword"],
            "entry_type": r["entry_type"],
            "printed_page": r["printed_page_start"],
            "pdf_page": r["pdf_page_start"],
            "sigil": r["author_sigil"],
        }
        for r in rows
    ]


def load_edges(conn: sqlite3.Connection, node_ids: set[str]) -> list[tuple[str, str, int]]:
    """The citation graph as (source, target, weight) triples.

    Only references that actually landed on an entry become edges. Self
    loops are dropped (12 corpus-wide, an entry citing itself carries no
    structure), and duplicate directed pairs collapse into a weight --
    53,255 of 55,117 pairs occur once, but a handful are cited up to 8
    times and that repetition is real signal about how tightly two
    articles are bound.
    """
    placeholders = ",".join("?" * len(Config.EDGE_STATUSES))
    rows = conn.execute(f"""
        SELECT entry_id, resolved_entry_id
        FROM resolved_cross_references
        WHERE resolved_entry_id IS NOT NULL
          AND status IN ({placeholders})
    """, Config.EDGE_STATUSES).fetchall()

    weights: dict[tuple[str, str], int] = defaultdict(int)
    for r in rows:
        src, dst = r["entry_id"], r["resolved_entry_id"]
        if src == dst:
            continue
        # A redirect endpoint only appears when redirects are excluded as
        # nodes; resolve_xrefs already chased through them, so this is a
        # handful of edges, not a class of them.
        if src not in node_ids or dst not in node_ids:
            continue
        weights[(src, dst)] += 1
    return [(s, t, w) for (s, t), w in weights.items()]


def load_search_index(conn: sqlite3.Connection, node_index: dict[str, int]) -> list[dict]:
    """Every spelling under which an entry can be looked up.

    Straight out of the `lemmas` table, which build_lemma_index.py built
    for exactly this question -- primary names, the comma-inverted forms
    the book never prints but a reader looks for ("algebraische Logik"),
    both halves of a slash headword, and redirect aliases, which are what
    let "anima" find "Seele" even though no redirect is on the map.
    """
    rows = conn.execute("""
        SELECT l.lemma_key, l.lemma, l.entry_id, l.variant_type, e.headword_clean
        FROM lemmas l JOIN entries e ON e.id = l.entry_id
        ORDER BY l.lemma
    """).fetchall()

    out = []
    for r in rows:
        node = node_index.get(r["entry_id"])
        if node is None:
            # A lemma pointing at an entry that is not on the map. For
            # redirect_alias rows this cannot happen (build_lemma_index
            # records the alias against the article the chase ended on),
            # so anything here is a redirect's own primary row.
            continue
        out.append({
            "k": r["lemma_key"],
            "l": r["lemma"],
            "n": node,
            "v": r["variant_type"],
            # The article the reader actually lands on, so a redirect or
            # inverted hit can be shown as "anima -> Seele".
            "t": r["headword_clean"] or "",
        })
    return out


def load_entry_payloads(conn: sqlite3.Connection, node_index: dict[str, int]) -> dict[str, dict]:
    """The reading-pane content for every mapped entry, keyed by id.

    Carries only what the pane actually renders. The "cited by" list is
    NOT here: the pane reads it off graph.json's edge arrays, which hold
    the same information, so shipping it again cost 0.32 MB a build for
    nothing.
    """
    refs_by_entry = _load_reference_lists(conn, node_index)

    payloads = {}
    for r in conn.execute("""
        SELECT id, volume, headword_clean, headword, entry_type, author_sigil,
               printed_page_start, body_clean, body_text,
               werke_clean, literatur_clean
        FROM entries
    """):
        if r["id"] not in node_index:
            continue
        source_body = r["body_clean"] or r["body_text"]
        body, offsets = reflow_with_offsets(source_body)
        payloads[r["id"]] = {
            "headword": r["headword_clean"] or r["headword"],
            "volume": r["volume"],
            "type": r["entry_type"],
            "sigil": r["author_sigil"],
            "printed_page": r["printed_page_start"],
            "body": body,
            "refs": refs_by_entry.get(r["id"], []),
            # Filled in by attach_inline_offsets(); an entry that fails
            # the gate keeps this null and renders as plain text.
            "marks": None,
            # Whether a bibliography shard fetch is worth making at all.
            "has_bib": bool(r["werke_clean"] or r["literatur_clean"]),
            # Underscore keys are build-time only; write_shards() drops
            # them before anything reaches the browser.
            "_source_body": source_body,
            "_offsets": offsets,
            # Split out by write_shards() into its own shard, never sent
            # with the article itself -- see there for why.
            "_werke": reflow_for_display(r["werke_clean"] or "", keep_paragraphs=False) or None,
            "_literatur": reflow_for_display(r["literatur_clean"] or "", keep_paragraphs=False) or None,
        }
    return payloads


def _load_reference_lists(conn, node_index) -> dict[str, list[dict]]:
    """Every outgoing reference of every entry, INCLUDING the failures.

    Ambiguous and unresolved references are carried through deliberately.
    The resolver recorded candidates and never guessed; a reading pane
    that silently dropped its 2,580 misses would be claiming a certainty
    the dataset does not have.
    """
    out = defaultdict(list)
    for r in conn.execute("""
        SELECT r.entry_id, r.ordinal, r.raw_target, r.status,
               r.resolved_entry_id, c.raw_context,
               e.headword_clean AS target_headword
        FROM resolved_cross_references r
        LEFT JOIN cross_references c
               ON c.entry_id = r.entry_id AND c.ordinal = r.ordinal
        LEFT JOIN entries e ON e.id = r.resolved_entry_id
        ORDER BY r.entry_id, r.ordinal
    """):
        ref = {
            "o": r["ordinal"],
            "raw": r["raw_target"],
            "s": r["status"],
            # Node index of the target, or null when it did not resolve
            # (or resolved onto something not on the map). The target's
            # headword is NOT stored: the frontend already holds every
            # headword in graph.json and looks it up by this index, which
            # saved 1 MB of duplicated strings across the shards.
            "n": node_index.get(r["resolved_entry_id"]) if r["resolved_entry_id"] else None,
        }
        # The reference phrase is only worth carrying when it says more
        # than the arrow-marked word alone -- which is what makes
        # "Philosophie, praktische" resolvable. It equals raw_target on
        # most references, so storing it unconditionally was ~1 MB of
        # repeated strings.
        if r["raw_context"] and r["raw_context"] != r["raw_target"]:
            ref["ctx"] = r["raw_context"]
        out[r["entry_id"]].append(ref)
    return out


# --- paragraph reflow ------------------------------------------------------

# A newline plus whatever whitespace surrounds it, however many.
_BREAK_RE = re.compile(r"[^\S\n]*\n\s*")
_SENTENCE_END = ".!?:;"
# Quotation marks and brackets can trail a sentence's real punctuation, so
# they are stripped before the test. They are NOT themselves sentence
# endings: "die Erkenntnis also nicht >erweitern<" closes a quoted TERM in
# the middle of a clause, and treating the closing mark as a full stop
# left ten articles still broken mid-sentence.
_TRAILING_MARKS = "»«\"'›‹)]}"


def reflow_for_display(text: str, keep_paragraphs: bool = True) -> str:
    """Undo the print edition's line breaks, keep its paragraph breaks.

    `body_clean` still carries the column and page breaks of the printed
    book: 6,214 of its 14,198 line breaks fall in the middle of a
    sentence, so an article renders with a gap after "der Mensch verlangt
    nach einer" and resumes at "sinnvollen Welt". The break is an artifact
    of where the column ended, not something the editors wrote.

    A break is kept only where it plausibly is one -- the text before ends
    a sentence AND the text after starts a new one. Everything else is
    joined back into running prose.

    A hyphen at the break is three different things, and the distinction
    is parse_entries.rejoin_hyphenated_target()'s, not a new one:
      "unbezeich-" + "nete"        a word the typesetter broke; German
                                   hyphenation resumes lowercase, so drop
                                   the hyphen and join tight
      "Ordinal-"   + "und ..."     a SUSPENDED hyphen; the hyphen is the
                                   editors' own and a space follows
      "Leib-"      + "Seele-..."   a compound broken at its own hyphen;
                                   keep the hyphen, join tight

    `keep_paragraphs=False` is for the bibliography, where a break is
    never meaningful: `Werke:`/`Literatur:` is one run of semicolon-
    separated citations, and 2,082 of its 2,582 breaks fall inside a
    single citation ("Colloque Abbaye de Cluny 2 au 9 juillet / 1972,
    Paris 1975"). There every break is closed up.

    This is a DISPLAY transform and lives here, not in the dataset. The
    underlying artifact is still in `body_clean` for every other consumer;
    see docs/atlas.md.
    """
    return reflow_with_offsets(text, keep_paragraphs)[0]


def reflow_with_offsets(text: str, keep_paragraphs: bool = True):
    """As above, plus the map needed to move a character offset onto it.

    Cross-references are located in the ORIGINAL text -- see
    attach_inline_offsets() -- and their spans are then carried across by
    this map, rather than being detected in the reflowed text. Keeping
    detection upstream of formatting is the point: while the arrow was
    still spelled "›" and had to be told apart from a quotation mark by a
    120-character lookahead, reflowing moved text into that window and
    flipped nine articles from "reference" to "quotation". The arrow is
    unambiguous now, but formatting still should not be able to decide
    what counts as a reference.

    Returns (reflowed_text, segments), where segments are
    (original_start, length, new_start) triples covering every run of
    original text that survived, in order.
    """
    if not text:
        return text, []

    parts: list[str] = []
    segments: list[tuple[int, int, int]] = []
    new_len = 0
    # Only the last few characters are ever inspected, so the tail is kept
    # as a short rolling buffer rather than re-joining the output.
    tail = ""
    pos = 0

    def emit(seg: str, origin: int):
        nonlocal new_len, tail
        if seg:
            parts.append(seg)
            segments.append((origin, len(seg), new_len))
            new_len += len(seg)
            tail = (tail + seg)[-32:]

    def glue(seg: str):
        nonlocal new_len
        if seg:
            parts.append(seg)
            new_len += len(seg)

    for match in _BREAK_RE.finditer(text):
        emit(text[pos:match.start()], pos)
        pos = match.end()
        head = text[pos:pos + 1]
        closing = tail.rstrip(_TRAILING_MARKS)

        if not tail or not head:
            glue("\n\n")
        elif tail[-1] == "-":
            first_word = re.match(r"[^\W\d_]+", text[pos:])
            if head.isupper():
                pass                            # "Leib-" + "Seele-Problem"
            elif first_word and first_word.group(0) in SUSPENDED_HYPHEN_NEXT_WORDS:
                glue(" ")                       # "Ordinal-" + "und Kardinalzahlen"
            else:
                # "unbezeich-" + "nete": drop the hyphen from what was
                # already emitted, and shorten that segment to match.
                parts[-1] = parts[-1][:-1]
                origin, length, start = segments[-1]
                segments[-1] = (origin, length - 1, start)
                new_len -= 1
                tail = tail[:-1]
        elif (keep_paragraphs and closing and closing[-1] in _SENTENCE_END
              and (head.isupper() or head.isdigit() or head in "([")):
            glue("\n\n")                        # a break the editors meant
        else:
            glue(" ")                           # the column simply ended

    emit(text[pos:], pos)
    return "".join(parts), segments


def map_offset(segments: list[tuple[int, int, int]], offset: int) -> "int | None":
    """Where `offset` in the original text landed after reflowing.

    None if it fell inside a run that was dropped -- which cannot happen
    for a mark, whose ends are a glyph and a word character.
    """
    for origin, length, start in segments:
        if origin <= offset < origin + length:
            return start + (offset - origin)
        # An end offset may sit exactly one past a segment's last char.
        if offset == origin + length:
            return start + length
    return None


# --- inline reference offsets ---------------------------------------------

def attach_inline_offsets(payloads: dict[str, dict]) -> dict:
    """Locate each body reference inside the CLEANED text, or give up.

    Making "›Konfuzianismus" clickable in the reading pane needs character
    offsets. They cannot be found in the frontend: in Bd01-06 "›" is BOTH
    the cross-reference arrow and the ordinary German opening quotation
    mark, and keying on the glyph alone once turned 22,015 quotations into
    references and 6,148 of them into false edges (ISSUES.md issue #12).
    Bd07/08 spell the arrow "↑" instead. parse_entries.py already solved
    all of this, so its matcher and its quotation discriminator are
    imported rather than re-implemented.

    They also cannot simply be taken from the parse: the parse ran on
    `body_text`, and cleaning shifts every offset after the first change.
    So the same matcher is re-run against `body_clean` and the result is
    accepted only when it agrees with what the parse stored -- same number
    of references, same targets, same order. On any disagreement the entry
    keeps `marks = None` and renders as plain text. Better a paragraph
    without links than a link on the wrong word.
    """
    stats = {"eligible": 0, "linkified": 0, "rejected": 0, "marks": 0}

    for payload in payloads.values():
        refs = payload["refs"]
        if not refs:
            continue
        stats["eligible"] += 1

        cfg = volume_config(payload["volume"])
        # Detected in the ORIGINAL text, so reflowing cannot change which
        # arrows count as references, then carried onto the displayed
        # string through the reflow's own offset map.
        found = _find_marks(payload["_source_body"], cfg)

        # The stored list covers body + Werke: + Literatur: in that order,
        # so the body's references are its leading slice.
        if len(found) > len(refs):
            stats["rejected"] += 1
            continue
        if any(
            normalize_key(f["w"]) != normalize_key(refs[i]["raw"])
            for i, f in enumerate(found)
        ):
            stats["rejected"] += 1
            continue

        segments = payload["_offsets"]
        marks = []
        for i, f in enumerate(found):
            start = map_offset(segments, f["start"])
            end = map_offset(segments, f["end"])
            if start is None or end is None or end <= start:
                marks = None
                break
            marks.append([start, end, i])
        if marks is None:
            stats["rejected"] += 1
            continue

        payload["marks"] = marks
        stats["linkified"] += 1
        stats["marks"] += len(marks)

    return stats


def _find_marks(text: str, cfg: dict) -> list[dict]:
    """Arrow-marked references in `text`, with their character spans.

    Mirrors extract_fields()'s loop step for step -- same matcher, same
    hyphen rejoining -- because the gate above compares the result against
    what that loop stored. Dropping the rejoin rejected 'Prädikator', the
    single most-cited article in the corpus, because the typesetter had
    broken the arrow-marked 'Übersetzung' across a line and the parse put
    it back together while this did not.
    """
    if not text:
        return []
    marks = []
    for m in build_xref_re(cfg).finditer(text):
        word, end = m.group("word"), m.end("word")
        if word.endswith("-"):
            rejoined = rejoin_hyphenated_target(text, word, end)
            if rejoined is not None:
                # The span runs to the end of the continuation, so the
                # link covers the whole broken word rather than the half
                # before the hyphen.
                word, end = rejoined
        # The span covers the arrow and the marked word, not the trailing
        # context: the context runs to a sentence boundary and underlining
        # half a sentence would read as an error.
        marks.append({"start": m.start(), "end": end, "w": word})
    return marks


# --- writing ---------------------------------------------------------------

def write_graph(out_dir: Path, nodes, edges, communities, coords, radii, in_degree, node_index):
    """graph.json -- parallel arrays, not per-node objects.

    4,259 objects with named keys repeat every key 4,259 times; the
    parallel-array form is roughly a third of the size for identical
    content, and the frontend reads it into typed arrays anyway.
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version": Config.SCHEMA_VERSION,
        "ids": [n["id"] for n in nodes],
        "headwords": [n["headword"] for n in nodes],
        "volumes": [n["volume"] for n in nodes],
        "types": [n["entry_type"] for n in nodes],
        "x": [round(c[0], 2) for c in coords],
        "y": [round(c[1], 2) for c in coords],
        "r": [round(v, 2) for v in radii],
        "in_degree": in_degree,
        "community": communities["assignment"],
        "edges": {
            "source": [node_index[s] for s, _, _ in edges],
            "target": [node_index[t] for _, t, _ in edges],
            "weight": [w for _, _, w in edges],
        },
        "communities": communities["meta"],
    }
    path = out_dir / "graph.json"
    path.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    logger.info("wrote %s (%.1f MB)", path.name, path.stat().st_size / 1e6)
    return path


def write_search_index(out_dir: Path, rows: list[dict]) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / "search-index.json"
    path.write_text(
        json.dumps({"schema_version": Config.SCHEMA_VERSION, "rows": rows},
                   ensure_ascii=False, separators=(",", ":")),
        encoding="utf-8",
    )
    logger.info("wrote %s (%d lemmas, %.1f MB)", path.name, len(rows), path.stat().st_size / 1e6)
    return path


def write_shards(out_dir: Path, payloads: dict[str, dict]) -> dict[str, int]:
    """Per-volume shards, fetched lazily on first click.

    Volume is the natural shard key: it is already in every entry id, so
    the frontend derives the shard from the id with a string split and
    needs no lookup table.

    Bibliography goes into a SECOND set of shards. The `Werke:` and
    `Literatur:` blocks are 13.7 MB against the articles' 17.2 MB -- they
    would nearly double every fetch to deliver something most readers
    never scroll to. Split out, opening an article costs ~3 MB and the
    apparatus is fetched only when its section is expanded.
    """
    shard_dir = out_dir / "entries"
    shard_dir.mkdir(parents=True, exist_ok=True)

    by_volume: dict[str, dict] = defaultdict(dict)
    bib_by_volume: dict[str, dict] = defaultdict(dict)
    for entry_id, payload in payloads.items():
        volume = payload["volume"]
        werke, literatur = payload.get("_werke"), payload.get("_literatur")
        # Everything underscored is build scaffolding -- the pre-reflow
        # text and its offset map -- and must not be shipped.
        by_volume[volume][entry_id] = {k: v for k, v in payload.items()
                                       if not k.startswith("_")}
        if werke or literatur:
            bib_by_volume[volume][entry_id] = {"werke": werke, "literatur": literatur}

    sizes = {}
    for volume, entries in sorted(by_volume.items()):
        sizes[volume] = _dump(shard_dir / f"{volume}.json", entries)
        logger.info("wrote %s (%d entries, %.1f MB)", volume, len(entries), sizes[volume] / 1e6)
    for volume, bib in sorted(bib_by_volume.items()):
        size = _dump(shard_dir / f"{volume}.bib.json", bib)
        sizes[f"{volume}.bib"] = size
        logger.info("wrote %s.bib (%d entries, %.1f MB)", volume, len(bib), size / 1e6)
    return sizes


def _dump(path: Path, obj) -> int:
    path.write_text(json.dumps(obj, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    return path.stat().st_size


def write_manifest(out_dir: Path, data: dict) -> Path:
    path = out_dir / "MANIFEST.json"
    data = {
        "schema_version": Config.SCHEMA_VERSION,
        "generated_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        **data,
    }
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def copy_frontend(src: Path, dest: Path):
    """Copy the frontend beside the data so export/viz/ is self-contained.

    The bundle is meant to be servable as-is from any static host, in the
    same spirit as export_dataset.py: the artifact stands alone.
    """
    dest.mkdir(parents=True, exist_ok=True)
    for item in ("index.html", "style.css", "js"):
        s = src / item
        d = dest / item
        if not s.exists():
            continue
        if d.exists():
            shutil.rmtree(d) if d.is_dir() else d.unlink()
        shutil.copytree(s, d) if s.is_dir() else shutil.copy2(s, d)
    logger.info("copied frontend into %s", dest)
