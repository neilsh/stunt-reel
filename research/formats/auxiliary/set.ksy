meta:
  id: set
  title: Stunt Island scene definition (`.SET`)
  file-extension: set
  ks-version: 0.11
  endian: le
doc: |
  A `.SET` file is an 84-byte environment header, then `num_events`
  67-byte event records, then 64-byte prop records to end of file:
  `size = 0x54 + 67 * num_events + 64 * prop_count`. Meaning, units and
  evidence are in `set.md` ([FMT-SET-HEADER]).
seq:
  - id: stunt_name
    size: 30
    type: str
    encoding: ASCII
    doc: Space-padded or NUL-terminated stunt title.
  - id: reserved1
    size: 9
  - id: recording_mode
    type: u1
  - id: first_take_bonus
    type: u2
  - id: crash_penalty
    type: u2
  - id: vehicle_flags
    type: u1
  - id: reserved2
    type: u1
  - id: time_of_day
    type: u2
  - id: reserved3
    type: u1
  - id: default_camera
    type: u1
  - id: weapon_type
    type: u1
  - id: max_takes
    type: u1
  - id: take_penalty
    type: u2
  - id: reserved_settings
    size: 8
  - id: initial_view_mode
    type: u1
  - id: reserved4
    size: 19
  - id: magic
    contents: [0x08]
    doc: Structural validation constant.
  - id: num_events
    type: u1
    doc: Count of 67-byte event records that follow the header.
  - id: events
    type: event
    repeat: expr
    repeat-expr: num_events
    doc: Trigger rules, in file order.
  - id: props
    size: 64
    repeat: eos
    doc: Prop records; their fields are not part of this schema.
instances:
  prop_count:
    value: props.size
    doc: Prop records present, derived from the remaining file length.
types:
  event:
    doc: |
      One 67-byte trigger rule: an 11-byte IF clause, two 3-byte AND
      qualifiers, then eight 7-byte THEN slots. Operator bytes are raw
      codes; the value tables are in `set.md` 3.6.
    seq:
      - id: if_type
        type: u1
      - id: if_object_1
        type: u1
      - id: if_object_2
        type: u1
      - id: if_operand
        type: u2
      - id: and_1_type
        type: u1
      - id: and_1_operand
        type: u2
      - id: and_2_type
        type: u1
      - id: and_2_operand
        type: u2
      - id: then_slots
        type: then_slot
        repeat: expr
        repeat-expr: 8
        doc: Eight fixed slots; an unused slot has `action_type` 0.
  then_slot:
    doc: One 7-byte THEN slot.
    seq:
      - id: action_type
        type: u1
      - id: target
        type: u1
      - id: secondary_operand
        type: u1
      - id: operand
        type: u2
      - id: sound_volume
        type: u1
      - id: sound_routing
        type: u1
