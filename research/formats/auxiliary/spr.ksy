# Executable structural layout of the Stunt Island `.SPR` billboard raster.
# Format anchor: [FMT-SPR-HEADER] in spr.md.
#
# FileSize = width * height + 6 holds for all four corpus sprites.
meta:
  id: spr
  title: Stunt Island billboard sprite (`.SPR`)
  file-extension: spr
  ks-version: 0.11
  endian: le
doc: |
  A raw 8-bit billboard sprite: dimensions, palette pixels and trailer.
  Meaning is in `spr.md`.
seq:
  - id: width
    type: u2
    valid:
      expr: _ > 0 and _ % 2 == 0
    doc: Horizontal pixel count, even per the format convention.
  - id: height
    type: u2
    valid:
      expr: _ > 0
    doc: Vertical pixel count.
  - id: pixels
    size: width * height
    doc: |
      Row-major Mode 13h palette indices; index 0 is the transparency key.
      PLAYONE's blitter (image 0x7DE6) reads an OP_ANIMATE frame's
      width * height pixels from byte 6, not 4; the 2,815 corpus frames hold a zero
      word at byte 4 and at the end, so both readings see the same picture
      shifted by two pixels (sod-animate.md section 3).
  - id: trailer
    type: u2
    valid:
      expr: _ == 0
    doc: End-of-file terminator word.
