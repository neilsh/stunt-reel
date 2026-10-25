# Executable structural layout of the Stunt Island `.SET` scene header.
# Format anchor: [FMT-SET-HEADER] in set.md.
#
# The 96-byte header is verified across all 93 corpus scenes: `magic_tag` is
# 0x08 at 0x0052. `0x53` counts events (six printed set dumps agree); the byte
# at 0x54 is unidentified, observed 0-3.
#
# Body (BK-SET-05): the event table comes first.
#   size = 0x54 + 67 * events + 64 * props
# i.e. an 84-byte header, then `events` event records of 67 bytes, then 64
# bytes per prop with every prop stored. Verified against the six printed
# dumps and all 35 loose corpus sets; 0x54 + 67*events lands on the prop table
# in each. Event fields are mapped by byte flipping through TYPESET; see
# set.md 3.5.
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
  - id: rest
    size-eos: true
    doc: |
      Records and trailer: `props - 1` prop records of 64 bytes, then `events`
      event records of 64 bytes, then 3 bytes per event after the first. The
      event record's fields are only partly mapped; see set.md 3.5.
