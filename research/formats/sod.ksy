# Executable structural layout of the Stunt Island `.SOD` model header and
# its collision list.
# Format anchor: [FMT-SOD-HEADER] in sod.md.
#
# The ten-byte header is verified across 393 compiled corpus models. Loose
# `.SOD` files in the corpus are ASCII `.objdef` sources; the compiled
# binaries live in `.BIN` files beginning with 0x000C. Operand widths for
# several opcodes remain undecoded, so the bytecode stream is left raw.
# The collision list the header points at is read as PLAYONE's probe walks
# it (sod.md section 2.3).
meta:
  id: sod
  title: Stunt Island procedural model (`.SOD`)
  file-extension: sod
  ks-version: 0.11
  endian: le
doc: |
  A `.SOD` model: the 10-byte header beginning with `OP_ID` (0x000C),
  then display-list bytecode, and the collision list the header names.
  `op_id` stays a `u2` compared with `valid`, not `contents`, because
  callers compare the integer. Meaning is in `sod.md`.
seq:
  - id: op_id
    type: u2
    valid:
      expr: _ == 0x000C
    doc: OP_ID magic word at byte 0x0000.
  - id: bounding_size
    type: u2
  - id: ground_y_offset
    type: s2
  - id: scale_index
    type: u1
    doc: |
      Power-of-2 scale index. The documented table covers 0..17; three
      corpus binaries carry 18, which the Rust parser handles outside the
      table, so the field is not constrained here.
  - id: header_flags
    type: u1
    doc: |
      Bit 0 draws the shape through the view matrix built without the
      camera's yaw, so it turns with the camera's heading (the flat
      OP_IPG type 8 trees set it; playone-exe/sod-vm-generators.md section 8.8).
  - id: collision_meta
    type: u2
    doc: |
      Shape-segment offset of the collision list, 0 for none. PLAYONE loads
      the file two bytes into the shape's segment, so the list starts at
      file offset collision_meta - 2 (sod.md section 2.3).
  - id: bytecode
    size-eos: true
    doc: Opcode stream, beginning with the first 16-bit opcode at 0x000A.
instances:
  collision:
    pos: collision_meta - 2
    type: collision_list
    if: collision_meta != 0
    doc: The collision list the header names.
types:
  collision_list:
    doc: Records up to the one whose type word is 0xFFFF.
    seq:
      - id: records
        type: collision_record
        repeat: until
        repeat-until: _.kind == 0xFFFF
  collision_record:
    seq:
      - id: kind
        type: u2
        doc: 0 cube, 2 box, 4 plane, 0xFFFF the end of the list.
      - id: body
        if: kind != 0xFFFF
        type:
          switch-on: kind
          cases:
            0: collision_cube
            2: collision_box
            4: collision_plane
  collision_cube:
    doc: Type 0, 12 bytes with the type word.
    seq:
      - id: centre
        type: s2
        repeat: expr
        repeat-expr: 3
        doc: x, y, z in the shape's units, DOS axes.
      - id: half_size
        type: s2
      - id: nested
        type: u2
        doc: Shape-segment offset of a nested list, 0 for none.
    instances:
      nested_list:
        io: _root._io
        pos: nested - 2
        type: collision_list
        if: nested != 0
  collision_box:
    doc: Type 2, 16 bytes with the type word.
    seq:
      - id: x_min
        type: s2
      - id: x_max
        type: s2
      - id: y_min
        type: s2
        doc: The box's top, y being down.
      - id: y_max
        type: s2
      - id: z_min
        type: s2
      - id: z_max
        type: s2
      - id: code
        type: u2
        doc: |
          0 plain; 1 to 7 a bucket; 8 the top; above 8 the shape-segment
          offset of a nested list.
    instances:
      nested_list:
        io: _root._io
        pos: code - 2
        type: collision_list
        if: code > 8
  collision_plane:
    doc: Type 4, 12 bytes with the type word.
    seq:
      - id: normal
        type: s2
        repeat: expr
        repeat-expr: 3
      - id: distance
        type: s2
      - id: nested
        type: u2
        doc: Shape-segment offset of a nested list, 0 for none.
    instances:
      nested_list:
        io: _root._io
        pos: nested - 2
        type: collision_list
        if: nested != 0
