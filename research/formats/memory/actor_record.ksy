# Executable layout of one 64-byte actor entry in the runtime actor chain (Layout A).
# Memory anchor: [MEM-ACTOR-TABLE] in research/playone-exe/memory-map.md.
#
# Evidentiary tier [Hypothesis]: this layout comes from the offline mock, not from a
# live read of PLAYONE.EXE. Scalars stay raw; derived values (16.16 metres, BAM) are
# `instances` so that the schema, not the caller, owns the field widths and offsets.
meta:
  id: actor_record
  title: Runtime actor chain entry (64 bytes)
  endian: le
seq:
  - id: actor_id
    type: u4
    doc: Actor channel id within the .FLM choreography.
  - id: model_name_raw
    size: 8
    doc: Bound .SOD asset name, NUL-terminated ASCII, NUL-padded.
  - id: pos_raw
    type: s4
    repeat: expr
    repeat-expr: 3
    doc: World position X, Y, Z as signed 16.16 fixed point.
  - id: rotation
    type: f4
    repeat: expr
    repeat-expr: 4
    doc: Rotation quaternion qx, qy, qz, qw.
  - id: state_mask
    type: u2
  - id: joint_count
    type: u2
  - id: joints
    type: joint
    repeat: expr
    repeat-expr: 4
    doc: Joint slots; only the first joint_count (at most 4) are meaningful.
  - id: next_off
    type: u2
    doc: Offset half of the next-actor far pointer.
  - id: next_seg
    type: u2
    doc: Segment half of the next-actor far pointer; both halves zero ends the chain.
instances:
  pos_meters:
    value: '[pos_raw[0] / 65536.0, pos_raw[1] / 65536.0, pos_raw[2] / 65536.0]'
types:
  joint:
    seq:
      - id: sub_id
        type: u2
      - id: bam
        type: u2
