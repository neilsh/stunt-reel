# Executable structural layout of the Stunt Island `.SPR` image resource.
# Format anchor: [FMT-SPR-HEADER] in spr.md.
#
# The layout is the one PLAYONE, STUNT and MAKEONE read (spr.md section 2.2):
# three header words, then the body from byte 6. The community PCX2SPR tool
# writes another layout (pixels from byte 4, a zero word after them); this
# schema does not describe it.
meta:
  id: spr
  title: Stunt Island image resource (`.SPR`)
  file-extension: spr
  ks-version: 0.11
  endian: le
doc: |
  An 8-bit image: width, height, an encoding word, then raw or span-coded
  palette indices. Meaning is in `spr.md`.
seq:
  - id: width
    type: u2
    valid:
      expr: _ > 0
    doc: Columns.
  - id: height
    type: u2
    valid:
      expr: _ > 0
    doc: Rows.
  - id: encoding
    type: u2
    doc: |
      0 for raw rows; any other value for span-coded rows (the game's
      images carry 2). PLAYONE's unscaled blitter branches on it at image
      0x7C2E; the OP_ANIMATE blitter (0x7DE6) ignores it and reads raw rows.
  - id: body
    type:
      switch-on: encoding
      cases:
        0: raw_rows
        _: span_rows
types:
  raw_rows:
    seq:
      - id: pixels
        size: _root.width * _root.height
        doc: |
          Row-major palette indices, top row first. PLAYONE's scaled blitter
          (0x7DE6) keys index 0; its unscaled draw copies raw rows whole.
  span_rows:
    seq:
      - id: rows
        type: span_row
        repeat: expr
        repeat-expr: _root.height
  span_row:
    seq:
      - id: spans
        type: span
        repeat: until
        repeat-until: _.count == 0
        doc: Spans left to right; a zero count ends the row.
  span:
    seq:
      - id: count
        type: u1
        doc: Pixels in the span; 0 ends the row.
      - id: x
        type: u2
        if: count != 0
        doc: Column of the span's first pixel.
      - id: pixels
        size: count
        doc: Palette indices drawn from column x; the columns between spans are untouched.
