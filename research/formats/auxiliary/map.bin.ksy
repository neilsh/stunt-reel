# Executable structural layout of `MAP.BIN`.
# Format anchor: [FMT-MAP-AREA] in map.md.
#
# 179 patches of 30 bytes plus a two-byte null terminator (5,372 bytes)
# across the six corpus copies. Field semantics for `num`, `bounds`, and
# `vertex_indices` remain unresolved; only their width is encoded.
meta:
  id: map_area
  title: Stunt Island terrain patch table (`MAP.BIN`)
  file-extension: bin
  ks-version: 0.11
  endian: le
seq:
  - id: patches
    type: patch
    repeat: expr
    repeat-expr: 179
  - id: terminator
    type: u2
    valid:
      expr: _ == 0
    doc: Null word marking the end of the patch table.
types:
  patch:
    seq:
      - id: num
        type: s2
        doc: |
          Observed values are not a 0..178 sequence (the first record is
          540). Kept raw until the field is decoded; see BK-MAP-03.
      - id: pos
        type: s2
        doc: Sector activity word; low byte non-zero marks an active patch.
      - id: bounds
        -orig-id: "a, b, c, d"
        type: s2
        repeat: expr
        repeat-expr: 4
        doc: Bounding box limits or neighboring patch links; unresolved.
      - id: color
        type: s2
        doc: Mode 13h palette index for flat terrain shading.
      - id: num_verts
        type: s2
        doc: |
          Active vertex count of this terrain polygon. 178 of 179 records carry
          3..7; patch 131 reads 8 in every corpus copy and patch 22 of one copy
          reads 2, so the field is not constrained here (BK-MAP-05).
          `verify-corpus` reports those records as anomalies.
      - id: vertex_indices
        -orig-id: "v[7]"
        type: u2
        repeat: expr
        repeat-expr: 7
        doc: |
          Index words for this polygon. Corpus values exceed the 1023 range
          of ANCHORPT point indices, so the indexing rule is unresolved.
    doc: One 30-byte terrain patch record.
