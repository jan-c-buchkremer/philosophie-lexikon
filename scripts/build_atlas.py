"""Build the 2D atlas artifacts from structured-data/lexikon.db.

Thin CLI over pipeline/; all logic lives in the package.

  uv run python scripts/build_atlas.py                    # -> export/viz/
  uv run python scripts/build_atlas.py --dev              # -> viz/data/
  uv run python scripts/build_atlas.py --start-from layout

Stages: load -> communities -> layout -> metrics -> shard -> export.
Each caches its result under .atlas-cache/, so re-tuning the layout or the
Leiden resolution does not re-read the database or re-shard 17 MB of text.

Then serve it:
  uv run python -m http.server -d export/viz 8000
"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from pipeline.atlas_builder import STAGES, AtlasBuilder, configure_logging  # noqa: E402


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--start-from", choices=STAGES, default="load",
                    help="resume from a cached stage instead of rebuilding everything")
    ap.add_argument("--dev", action="store_true",
                    help="write data into viz/data/ and skip the frontend copy, "
                         "so the frontend can be iterated on in place")
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args()

    configure_logging(verbose=not args.quiet)
    builder = AtlasBuilder(dev=args.dev)
    builder.run(start_from=args.start_from)

    manifest = json.loads((builder.data_dir / "MANIFEST.json").read_text(encoding="utf-8"))
    counts = manifest["counts"]
    inline = manifest["inline_references"]
    print(f"\n{counts['nodes']} nodes, {counts['directed_edges']} edges, "
          f"{counts['communities']} communities, "
          f"{inline['coverage']:.1%} of articles inline-linked -> {builder.out_dir}")


if __name__ == "__main__":
    main()
