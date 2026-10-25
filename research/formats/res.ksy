# Executable structural layout of the Stunt Island `.RES` container.
# Format anchor: [FMT-RES-HEADER] in res.md.
#
# Structure only: archive profiles (prop name table vs scenery payloads),
# name synthesis, and offset monotonicity are parser policy, not layout.
# The header word is decoded: byte 0x0002 is the archive slot index and byte
# 0x0003 is (ofs_data / 4) - 2 across the 20 corpus archives.
# `item_count` keeps the name the header uses instead of the style guide's
# `num_segments`, which KSC therefore advises on every compile.
meta:
  id: res
  title: Stunt Island resource archive (`.RES`)
  file-extension: res
  ks-version: 0.11
  endian: le
doc: |
  A `.RES` archive: `RS` magic, resource index, offset table and named
  items. Meaning is in `res.md`.
seq:
  - id: magic
    contents: "RS"
    doc: ASCII signature `RS` at byte 0x0000.
  - id: res_index
    type: u1
    doc: |
      Archive slot index at byte 0x0002. Equals the index listed in res.md
      section 3.3 for every retail archive in the corpus: SCENERY1-SCENERY6
      carry 0x02-0x07, ACTORS 0x3B, MILITARY 0x3E, and VEHICLES 0x41. The
      engine forms resource ids as `(res_index << 8) | item_index`.
  - id: item_count
    type: u1
    doc: |
      Declared directory entry count at byte 0x0003. Equals
      `(ofs_data / 4) - 2` in all 20 corpus archives, which is the number of
      data regions after the directory: the name table plus payloads in prop
      archives, payloads only in scenery archives. Whether a prop archive's
      title string is included is not settled, so the relation is documented
      rather than constrained.
  - id: ofs_data
    -orig-id: "ofs[0]"
    type: u4
    valid:
      expr: _ >= 8 and _ % 4 == 0
    doc: |
      Offset of the first data block, which also ends the offset table.
      Must be at least 8 and 4-byte aligned.
  - id: offset_table
    size: ofs_data - 8
    doc: |
      Offset words after the first, bytes 0x0008 through `ofs_data - 1`.
      Declared only to place `segments` at the first data block; index them
      through the `offsets` instance.
  - id: segments
    type: segment(_index)
    repeat: expr
    repeat-expr: item_count
    doc: |
      Data regions between consecutive offsets, starting at `ofs_data`.
      Region 0 is the ASCII name table in prop archives and the first payload
      in scenery archives; choosing a profile is parser policy (res.md 3.1),
      so every region stays raw bytes.
instances:
  offsets:
    pos: 4
    type: u4
    repeat: expr
    repeat-expr: (ofs_data / 4) - 1
    doc: |
      Full offset table, where N = (ofs_data / 4) - 1 entries follow the
      first offset at byte 0x0004.
types:
  segment:
    params:
      - id: i
        type: u1
    seq:
      - id: body
        size: _root.offsets[i + 1] - _root.offsets[i]
    doc: Raw bytes of data region `i`.
