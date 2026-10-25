# Executable structural layout of the Stunt Island `.SIO` slice mesh.
# Format anchor: [FMT-SIO-RECORDS] in sio.md.
#
# Verified against all eight SLICE models in corpus/siarchive/SITools/Slice/:
# every stream is a one-byte opcode tag dispatch over 9-byte vertex and
# 7-byte midpoint records, ending in the four-byte `FF FF 00 00` sentinel.
# The tag is one byte, so the sentinel's leading `0xFFFF` word is the
# terminator tag followed by the first filler byte.
meta:
  id: sio
  title: Stunt Island SLICE point cloud (`.SIO`)
  file-extension: sio
  endian: le
seq:
  - id: magic
    contents: [0x53, 0x64, 0x73, 0x01]
    doc: ASCII `Sds` followed by format revision byte 0x01.
  - id: revision
    contents: [0x00, 0x00, 0x00, 0x00]
    doc: Four zero revision and flag bytes.
  - id: grid_magnification
    type: u1
    doc: SLICE authoring grid magnification scalar (`MAG:m`).
  - id: records
    type: record
    repeat: until
    repeat-until: _.tag == 0xff
    doc: Tagged geometry records, terminated by the `0xFF` tag.
types:
  record:
    seq:
      - id: tag
        type: u1
        doc: |
          Record tag: 0x12 vertex, 0x06 midpoint, 0xFF terminator.
      - id: body
        type:
          switch-on: tag
          cases:
            0x12: vertex
            0x06: midpoint
            0xff: eof_marker
    doc: One tagged record; unknown tags fail to parse.
  vertex:
    seq:
      - id: vertex_id
        type: u2
        doc: Unique 1-based vertex handle index.
      - id: coord_x
        type: s2
      - id: coord_y
        type: s2
      - id: coord_z
        type: s2
    doc: Explicit 3D vertex; nine bytes including the one-byte tag.
  midpoint:
    seq:
      - id: dest_id
        type: u2
        doc: Handle assigned to the computed midpoint vertex.
      - id: src1_id
        type: u2
      - id: src2_id
        type: u2
    doc: Midpoint vertex; seven bytes including the one-byte tag.
  eof_marker:
    seq:
      - id: filler
        contents: [0xff, 0x00, 0x00]
        doc: Remaining bytes of the `FF FF 00 00` sentinel.
    doc: Terminator payload, completing `FF FF 00 00`.
