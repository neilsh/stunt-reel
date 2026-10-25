# Executable structural layout of the Stunt Island `.SOD` model header.
# Format anchor: [FMT-SOD-HEADER] in sod.md.
#
# The ten-byte header is verified across 393 compiled corpus models. Loose
# `.SOD` files in the corpus are ASCII `.objdef` sources; the compiled
# binaries live in `.BIN` files beginning with 0x000C. Operand widths for
# several opcodes remain undecoded, so the bytecode stream is left raw.
meta:
  id: sod
  title: Stunt Island procedural model (`.SOD`)
  file-extension: sod
  ks-version: 0.11
  endian: le
doc: |
  A `.SOD` model: the 10-byte header beginning with `OP_ID` (0x000C),
  then display-list bytecode. `op_id` stays a `u2` compared with
  `valid`, not `contents`, because callers compare the integer. Meaning
  is in `sod.md`.
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
    doc: Bit 0 marks flat shading.
  - id: collision_meta
    type: u2
  - id: bytecode
    size-eos: true
    doc: Opcode stream, beginning with the first 16-bit opcode at 0x000A.
