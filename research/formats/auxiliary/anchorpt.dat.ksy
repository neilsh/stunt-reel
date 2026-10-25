# Executable structural layout of `ANCHORPT.DAT`.
# Format anchor: [FMT-MAP-ANCHORPT] in map.md.
#
# Exactly 1024 records of 28 bytes (28,672 bytes) across the four corpus
# copies; positions are followed by eleven raw scalars.
meta:
  id: anchorpt
  title: Stunt Island terrain anchor points (`ANCHORPT.DAT`)
  file-extension: dat
  ks-version: 0.11
  endian: le
doc: |
  The fixed 1,024-record `ANCHORPT.DAT` anchor table. Meaning is in
  `map.md`.
seq:
  - id: points
    type: point
    repeat: expr
    repeat-expr: 1024
types:
  point:
    seq:
      - id: x
        type: s2
      - id: y
        type: s2
        doc: Topographic elevation.
      - id: z
        type: s2
      - id: scalars
        -orig-id: "f[11]"
        type: s2
        repeat: expr
        repeat-expr: 11
        doc: |
          Surface normal components, elevation tap slopes, and ground
          clamping scalars. Individual meanings remain partially decoded.
    doc: One 28-byte terrain anchor record.
