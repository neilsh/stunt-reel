# Executable structural layout of the Stunt Island `.SET` scene header.
# Format anchor: [FMT-SET-HEADER] in set.md.
#
# The 96-byte header is verified across all 93 corpus scenes: `magic_tag` is
# 0x08 at 0x0052. `0x53` counts events (six printed set dumps agree); the byte
# at 0x54 is unidentified, observed 0-3. No size model with a 64-byte prop
# stride and a 12-byte event stride is established, and the prop/event table
# start and prop slot numbering are not settled (BK-SET-04, BK-SET-05), so
# bytes after 0x0060 stay raw.
meta:
  id: set
  title: Stunt Island scene definition (`.SET`)
  file-extension: set
  endian: le
seq:
  - id: stunt_name
    type: str
    size: 30
    encoding: ASCII
    doc: Space-padded or NUL-terminated stunt title.
  - id: reserved_header
    size: 9
  - id: recording_mode
    type: u1
  - id: first_take_bonus
    type: u2
  - id: crash_penalty
    type: u2
  - id: vehicle_flags
    type: u1
  - id: reserved_2d
    type: u1
  - id: time_of_day
    type: u2
  - id: reserved_30
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
  - id: reserved_pad
    size: 19
  - id: magic_tag
    type: u1
    valid:
      expr: _ == 0x08
    doc: Structural validation constant `0x08` at byte 0x0052.
  - id: num_events
    -orig-id: event_count
    type: u1
    doc: Number of event records; agrees with the printed count of six sets.
  - id: unknown_54
    type: u1
    doc: Unidentified; observed 0-3. Formerly read as the event count.
  - id: table_header
    size: 11
  - id: rest
    size-eos: true
    doc: |
      Opaque prop, event, and trailing data. The table start is unresolved;
      see BK-SET-04.
