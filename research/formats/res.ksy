# Executable structural layout of the Stunt Island `.RES` container.
# Format anchor: [FMT-RES-HEADER] in res.md.
#
# Structure only: archive profiles (prop name table vs scenery payloads),
# name synthesis, and offset monotonicity are parser policy, not layout.
meta:
  id: res
  title: Stunt Island resource archive (`.RES`)
  file-extension: res
  endian: le
seq:
  - id: magic
    contents: "RS"
    doc: ASCII signature `RS` at byte 0x0000.
  - id: header_word
    type: u2
    doc: |
      Raw bytes 0x0002-0x0003. The Rust parser reads and ignores this word;
      historical sources describe it as `res_index: u8` followed by
      `item_count: u8`. Left raw because neither reading is settled.
  - id: ofs_data
    -orig-id: "ofs[0]"
    type: u4
    valid:
      expr: _ >= 8 and _ % 4 == 0
    doc: |
      Offset of the first data block, which also ends the offset table.
      Must be at least 8 and 4-byte aligned.
instances:
  offsets:
    pos: 4
    type: u4
    repeat: expr
    repeat-expr: (ofs_data / 4) - 1
    doc: |
      Full offset table, where N = (ofs_data / 4) - 1 entries follow the
      first offset at byte 0x0004.
  name_region:
    pos: offsets[0]
    size: offsets[1] - offsets[0]
    doc: Bytes between ofs[0] and ofs[1]; raw bytes, not necessarily names.
  payload_0:
    pos: offsets[1]
    size: offsets[2] - offsets[1]
    if: _root.ofs_data >= 16
    doc: Payload 0, bounded by ofs[1] and ofs[2]. Absent when N < 3.
  payload_1:
    pos: offsets[2]
    size: offsets[3] - offsets[2]
    if: _root.ofs_data >= 20
    doc: Payload 1, bounded by ofs[2] and ofs[3]. Absent when N < 4.
