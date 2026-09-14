"""Atlas pipeline -- turns structured-data/lexikon.db into a navigable 2D map.

Stage separation mirrors the extraction pipeline's own discipline: I/O lives
in `graph_data`, numerics live in `analysis`, and `atlas_builder` only
sequences them. See docs/atlas.md.
"""
