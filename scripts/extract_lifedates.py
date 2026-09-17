"""Extract birth and death years from biography entries.

The encyclopedia opens every biography with a fixed formula:

    Lipsius, Justus, Overijse 18. Okt. 1547, †Löwen 23. März 1606, niederl. ...
    Platon, Athen (oder Ägina) 428/427 v. Chr., †Athen 348/347 v. Chr., ...
    Thales von Milet, Milet ca. 625 v. Chr., †ca. 547 v. Chr., ...

The dagger is the anchor: the birth year is the last year-like number
before it, the death year the first one after it. Nothing else about the
sentence is parsed -- places, days and months are skipped, not read.

Adds four nullable columns to `entries` (birth_year, birth_bc, death_year,
death_bc) plus `lifedates_extracted`, strictly beside the existing columns.
scripts/export_dataset.py picks them up through its SELECT *.

WHAT IS DELIBERATELY NOT GUESSED. A biography is left without dates when:
  - there is no dagger in the head of the entry (~10% of biographies:
    collectives like Bourbaki, people known only by century, entries
    whose formula the typesetter broke);
  - the year sits in a range or alternative wider than one year
    ("zwischen 500 und 496 v. Chr.", "1420–1490", "998 oder 997");
  - birth is not earlier than death after sign conversion. This is the
    check that catches "384 ... †322" written without any "v. Chr." at
    all (Aristoteles): the text does not say BC, so the pass does not
    say it either. The handful of famous cases this affects are restated
    by hand in MANUAL_LIFEDATES, verified against the printed text,
    which is the same shape as MANUAL_VOLUME_FONT_FIXES upstream.

"428/427 v. Chr." is accepted as 428: the slash form is the source's own
notation for a one-year calendar ambiguity, and reading its first half is
transcription, not inference. Alternatives further apart are omitted.

Two deductions are made, neither of which reads context: a BC death
entails a BC birth ("um 560, †um 480 v. Chr." prints the marker once), and
"287 v. Chr., †ebd. 212" is read as a BC death because the other reading
is a 499-year life.

WHICH ENTRIES. Every non-redirect entry, not only `entry_type =
'biography'`: that column comes from the bibliography apparatus, so
Sokrates (no Werke: block -- he wrote nothing) is a subject_article and
Kant (bespoke bibliography) is unknown. The formula itself is the test:
a dagger in the head, outside parentheses, before any sentence has ended.
That keeps out "Manichäismus, von dem Perser Mani (... 216, †... 276)".

ORDERING: run after scripts/clean_text.py and scripts/build_db.py (which
recreates the whole file, dropping these columns) and before
scripts/export_dataset.py and scripts/build_story.py.

Run via uv:
  uv run python scripts/extract_lifedates.py [--db-path ...] [--verbose]
"""
import argparse
import re
import sqlite3
import sys
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DB_PATH = ROOT / "structured-data" / "lexikon.db"

DAGGER = "†"
# The formula lives in the head of the entry. A dagger beyond this is some
# other use of the sign, not this person's death.
HEAD_WINDOW = 500
# The place of death can be long: "†Neumark, Siebenbürgen (= Maros-
# Vásárhely, heute rumän. Tıˆrgu-Mures¸) 27. Jan. 1860," is 80 characters
# before the year. Measured: no entry gains a wrong year at this width.
DEATH_WINDOW = 120

# One number, optionally with a one-year alternative glued on
# ("428/427", "1265 oder 1266").
NUMBER_RE = re.compile(r"(?<![\d/])(\d{1,4})(?:\s*(?:/|oder)\s*(\d{1,4}))?(?![\d/])")
BC_RE = re.compile(r"\s*v\.\s*Chr\.")
AD_RE = re.compile(r"\s*n\.\s*Chr\.")
# The word or dash that turns a number into one end of a range, or into
# a bound ("†nach 1200") rather than a year.
RANGE_BEFORE_RE = re.compile(r"(?:–|-|—|\bund|\boder|\bbis|\bzwischen|\bnach|\bvor)\s*$")
RANGE_AFTER_RE = re.compile(r"^\s*(?:–|-|—|und|oder|bis)\s*\d")
# A sentence ending before the dagger means the head is prose, not the
# formula ("... Leitung der Stoa. A. hatte viele Schüler ... etwa 130, †").
# The formula's own full stops belong to abbreviations: the lowercase
# ones ("lat. Bodinus", "bzw.", "geb.") are told apart by case, the
# capitalised ones are few enough to list.
SENTENCE_END_RE = re.compile(r"([A-ZÄÖÜ][a-zäöüß]{2,})\.\s+[A-ZÄÖÜ]")
ABBREVIATIONS = {"Jan", "Febr", "Aug", "Sept", "Okt", "Nov", "Dez",
                 "Gouv", "Diöz", "Dep", "Julian", "Prof", "Prov", "Bez", "Kgr"}
MAX_LIFESPAN = 120

# Verified against the printed text. Each of these is an entry whose head
# gives both years without any era marker, so the automatic pass correctly
# refuses it; the reading below is the editors' own, restated.
MANUAL_LIFEDATES: dict[str, tuple[int, bool, int, bool]] = {
    # id: (birth_year, birth_bc, death_year, death_bc)
    "Bd01_A-B:0235:0343": (384, True, 322, True),   # Aristoteles: "384 in Stagira ... †322"
    "Bd02_C-F:0086:0084": (106, True, 43, True),    # Cicero: "3. Jan. 106, †... 7. Dez. 43"
}


@dataclass
class Year:
    value: int
    bc: bool
    approx: bool          # taken from a "428/427" pair
    rejected: str | None  # reason this token cannot be used, if any


def _year_tokens(text: str) -> list[Year]:
    out = []
    for m in NUMBER_RE.finditer(text):
        after = text[m.end():]
        before = text[:m.start()]
        # "13. März", "2. Jh." -- an ordinal, never a year. A four-digit
        # number before a full stop ("†Göttingen 9. Okt. 1950.") is one.
        if after.startswith(".") and len(m.group(1)) <= 2:
            continue
        value = int(m.group(1))
        approx = False
        if m.group(2) is not None:
            alt = int(m.group(2))
            if abs(alt - value) != 1:
                out.append(Year(value, False, False, "alternative wider than one year"))
                continue
            approx = True
        bc = BC_RE.match(after) is not None
        ad = AD_RE.match(after) is not None
        tail = after[BC_RE.match(after).end():] if bc else (
            after[AD_RE.match(after).end():] if ad else after)
        if RANGE_BEFORE_RE.search(before) or RANGE_AFTER_RE.match(tail):
            out.append(Year(value, bc, approx, "part of a range"))
            continue
        if value < 100 and not (bc or ad):
            # A two-digit number without an era marker is a day or a count.
            continue
        out.append(Year(value, bc, approx, None))
    return out


def _death_span(body: str, dagger: int) -> str:
    start = dagger + 1
    end = min(len(body), start + DEATH_WINDOW)
    # Never cut a number in half: "10. Sept. 1941" must not become 194.
    while end < len(body) and body[end - 1].isdigit() and body[end].isdigit():
        end += 1
    return body[start:end]


def extract(body: str) -> tuple[tuple[int, bool, int, bool] | None, str]:
    """Return ((birth, birth_bc, death, death_bc), reason). One of the two
    is always None: dates on success, a reason string on omission."""
    head = body[:HEAD_WINDOW]
    idx = head.find(DAGGER)
    if idx < 0:
        return None, "no dagger in head"
    lead = head[:idx]
    if lead.count("(") > lead.count(")"):
        return None, "dagger inside parentheses"
    if any(m.group(1) not in ABBREVIATIONS for m in SENTENCE_END_RE.finditer(lead)):
        return None, "sentence ends before dagger"
    before = _year_tokens(lead)
    after = _year_tokens(_death_span(body, idx))
    if not before:
        return None, "no birth year before dagger"
    if not after:
        return None, "no death year after dagger"
    birth, death = before[-1], after[0]
    if birth.rejected:
        return None, f"birth: {birth.rejected}"
    if death.rejected:
        return None, f"death: {death.rejected}"
    # "um 560, †um 480 v. Chr.": the marker is printed once, on the death.
    # Nobody is born after dying, so a BC death entails a BC birth.
    birth_bc = birth.bc or death.bc
    # "287 v. Chr., †ebd. 212": the only reading with a human lifespan.
    death_bc = death.bc or (birth_bc and birth.value + death.value > MAX_LIFESPAN)
    b = -birth.value if birth_bc else birth.value
    d = -death.value if death_bc else death.value
    if b >= d:
        return None, "birth not before death (era marker missing?)"
    if d - b > MAX_LIFESPAN:
        return None, "implausible lifespan"
    return (birth.value, birth_bc, death.value, death_bc), ""


SCHEMA = """
ALTER TABLE entries ADD COLUMN birth_year INTEGER;
ALTER TABLE entries ADD COLUMN birth_bc INTEGER;
ALTER TABLE entries ADD COLUMN death_year INTEGER;
ALTER TABLE entries ADD COLUMN death_bc INTEGER;
ALTER TABLE entries ADD COLUMN lifedates_extracted INTEGER NOT NULL DEFAULT 0;
"""


def ensure_columns(conn: sqlite3.Connection) -> None:
    present = {r[1] for r in conn.execute("PRAGMA table_info(entries)")}
    if "lifedates_extracted" in present:
        return
    conn.executescript(SCHEMA)


def run(db_path: Path, verbose: bool = False) -> None:
    conn = sqlite3.connect(str(db_path))
    ensure_columns(conn)
    conn.execute("UPDATE entries SET birth_year=NULL, birth_bc=NULL, "
                 "death_year=NULL, death_bc=NULL, lifedates_extracted=0")

    rows = list(conn.execute(
        "SELECT id, headword, entry_type, COALESCE(body_clean, body_text) FROM entries "
        "WHERE entry_type != 'redirect' ORDER BY volume, ordinal"))

    updates = []
    dated_by_type: Counter[str] = Counter()
    reasons: Counter[str] = Counter()
    suspicious = []
    manual_used = 0
    for entry_id, headword, entry_type, body in rows:
        if entry_id in MANUAL_LIFEDATES:
            dates = MANUAL_LIFEDATES[entry_id]
            manual_used += 1
        else:
            dates, reason = extract(body)
            if dates is None:
                # Only a biography that failed is worth a reason; a concept
                # article without a dagger is the normal case.
                if entry_type == "biography" or reason != "no dagger in head":
                    reasons[reason] += 1
                if reason.startswith(("birth not before", "implausible")):
                    suspicious.append((entry_id, headword, body[:120].replace("\n", " ")))
                if verbose and entry_type == "biography":
                    print(f"  omit {entry_id} {headword!r}: {reason}")
                continue
        dated_by_type[entry_type] += 1
        updates.append((*dates, entry_id))

    conn.executemany(
        "UPDATE entries SET birth_year=?, birth_bc=?, death_year=?, death_bc=?, "
        "lifedates_extracted=1 WHERE id=?", updates)
    conn.commit()
    biographies = conn.execute(
        "SELECT COUNT(*) FROM entries WHERE entry_type = 'biography'").fetchone()[0]
    conn.close()

    print(f"[lifedates] {len(updates)} entries dated, {manual_used} from MANUAL_LIFEDATES")
    for entry_type, n in dated_by_type.most_common():
        share = f" ({n / biographies:.1%} of biographies)" if entry_type == "biography" else ""
        print(f"            {entry_type:16s} {n:5d}{share}")
    for reason, n in reasons.most_common():
        print(f"            omitted, {reason:45s} {n:5d}")
    if suspicious:
        print(f"[lifedates] {len(suspicious)} entries with impossible dates -- "
              f"probably an era marker missing; candidates for MANUAL_LIFEDATES:")
        for entry_id, headword, head in suspicious:
            print(f"            {entry_id}  {headword}: {head}")
    print(f"[lifedates] done -> {db_path}")


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--db-path", default=str(DEFAULT_DB_PATH))
    ap.add_argument("--verbose", action="store_true", help="print every omission")
    args = ap.parse_args()
    run(Path(args.db_path), verbose=args.verbose)


if __name__ == "__main__":
    main()
