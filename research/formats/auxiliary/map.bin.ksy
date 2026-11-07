# Executable structural layout of `MAP.BIN`.
# Format anchor: [FMT-MAP-AREA] in map.md.
#
# The file is the list-head word and the record pool of `SITools/SD.EXE`'s
# terrain editor, saved up to the last record in use (map.md section 2.3):
# 2 + 179 x 30 = 5,372 bytes in every corpus copy.
meta:
  id: map_area
  title: Stunt Island terrain patch table (`MAP.BIN`)
  file-extension: bin
  ks-version: 0.11
  endian: le
doc: |
  `SD.EXE`'s terrain patch pool: a list head, then 30-byte patch records.
  Meaning is in `map.md`.
seq:
  - id: head
    type: s2
    doc: |
      `30 * index` of the first top-level patch, or -1 for none. The build
      walks the patch lists from here.
  - id: patches
    type: patch
    repeat: eos
types:
  patch:
    seq:
      - id: in_use
        type: u1
        doc: |
          Non-zero for a record in use. Free records keep the in-memory forms
          of their links (`2 + 30 * index`, 0 for none) and vertices
          (`4 + 28 * index`).
      - id: block
        type: u1
        doc: |
          Leaf of the `REGIONS.BIN` block tree a top-level patch is compiled
          under; 0 on child patches.
      - id: next
        -orig-id: a
        type: s2
        doc: "`30 * index` of the next patch in the same list, or -1."
      - id: first_child
        -orig-id: b
        type: s2
        doc: |
          `30 * index` of the first of the finer patches that replace this one
          within its split distance, or -1.
      - id: split_distance_x2
        -orig-id: c
        type: s2
        doc: Twice the `SP_GROUND` split distance; read only when `first_child` is set.
      - id: parent
        -orig-id: d
        type: s2
        doc: "`30 * index` of the patch whose `first_child` list holds this one, or -1."
      - id: color
        type: s2
        doc: Mode 13h palette index for flat terrain shading.
      - id: num_verts
        type: s2
        doc: |
          Vertex count, 3..8 in every record in use except patch 22 of one
          community copy, which reads 2; `verify-corpus` reports it.
      - id: vertex_indices
        -orig-id: "v[8]"
        type: u2
        repeat: expr
        repeat-expr: 8
        doc: |
          `ANCHORPT.DAT` record indices; only the first `num_verts` are
          meaningful.
    doc: One 30-byte terrain patch record.
