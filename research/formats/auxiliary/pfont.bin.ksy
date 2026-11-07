# Executable structural layout of PLAYONE.EXE's proportional font, PFONT.BIN.
# Meaning, evidence and the drawing rule are in pfont.md.
#
# FileSize = 128 + 128 * 8 = 1152 holds for every PFONT.BIN in the corpus.
meta:
  id: pfont
  title: Stunt Island proportional bitmap font (`PFONT.BIN`)
  file-extension: bin
  ks-version: 0.11
  endian: le
doc: |
  A width table and 128 one-bit glyphs of 8 rows, one per 7-bit character code.
  Meaning is in `pfont.md`.
seq:
  - id: widths
    type: u1
    repeat: expr
    repeat-expr: 128
    doc: Advance of each character in pixels, spacing included; 0 for an unused code.
  - id: glyphs
    type: glyph
    repeat: expr
    repeat-expr: 128
    doc: Glyph rows, indexed by character code.
types:
  glyph:
    seq:
      - id: rows
        type: u1
        repeat: expr
        repeat-expr: 8
        doc: One byte per row, top first; bit 7 is the leftmost pixel.
