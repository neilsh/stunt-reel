# Executable structural layout of one `.FLM` time slice.
# Format anchor: [FMT-FLM-OPCODES] in flm.md.
#
# `create` re-binds slot flags, so `interp` payload widths depend on state.
# Within one slice the state is threaded through the recursive `opcode` chain
# (max 96 opcodes per slice in the corpus). State between slices cannot cross
# a Kaitai `repeat`, so `stunt_reel.flm_walk` supplies the three masks.
meta:
  id: flm_slice
  title: Stunt Island film time slice (`.FLM`)
  file-extension: flm
  ks-version: 0.11
  endian: le
params:
  - id: moves
    type: u8
    doc: Bit i is set when slot i carries SIF_MOVES at slice start.
  - id: rotates
    type: u8
    doc: Bit i is set when slot i carries SIF_ROTATES at slice start.
  - id: animates
    type: u8
    doc: Bit i is set when slot i carries SIF_ANIMATES at slice start.
seq:
  - id: prev_slice_len
    type: u2
    doc: Distance from the previous slice header; 0 in typical slice 0.
  - id: tick_duration
    type: u1
  - id: first
    type: opcode(moves, rotates, animates)
types:
  opcode:
    doc: |
      One opcode. The upper two bits of `tag` select the class and the low six
      bits carry the object slot. Every class except `reserved` recurses, so the
      chain ends at the `0xFF` slice terminator, whose class-3 `reserved` body
      carries no payload and therefore no successor.
    params:
      - id: moves
        type: u8
      - id: rotates
        type: u8
      - id: animates
        type: u8
    seq:
      - id: tag
        type: u1
      - id: body
        type:
          switch-on: tag >> 6
          cases:
            0: create
            1: interp
            2: control
            3: reserved
  create:
    doc: |
      `[FMT-FLM-OPCODES]` object lifecycle, `0x00`-`0x3F`. Binds the slot flags
      that size later `interp` payloads, filling in the static keyframe for any
      channel that is not driven per tick. A slot may be re-created with a flag
      cleared, so each mask bit is rewritten rather than only accumulated.
    seq:
      - id: type_flags
        type: u1
        doc: |
          `SIF_EXISTS` 0x01, `SIF_DRAW` 0x02, `SIF_SHADOW` 0x04,
          `SIF_MOVES` 0x08, `SIF_ROTATES` 0x10, `SIF_ANIMATES` 0x20.
      - id: shape_id
        type: u2
        if: (type_flags & 0x03) == 0x03
        doc: Bound `.SOD` mesh; present when `SIF_EXISTS` and `SIF_DRAW` are set.
      - id: pos_x
        type: s4
        if: (type_flags & 0x09) == 0x01
        doc: 16.16 fixed-point, present when `SIF_EXISTS` is set and `SIF_MOVES` clear.
      - id: pos_y
        type: s4
        if: (type_flags & 0x09) == 0x01
      - id: pos_z
        type: s4
        if: (type_flags & 0x09) == 0x01
      - id: rot_z
        type: u2
        if: (type_flags & 0x11) == 0x01
        doc: BAM angle; present when `SIF_EXISTS` is set and `SIF_ROTATES` clear.
      - id: rot_x
        type: u2
        if: (type_flags & 0x11) == 0x01
      - id: rot_y
        type: u2
        if: (type_flags & 0x11) == 0x01
      - id: next
        type: opcode(next_moves, next_rotates, next_animates)
    instances:
      bit:
        value: 1 << (_parent.tag & 63)
      next_moves:
        value: _parent.moves - (_parent.moves & bit) + (((type_flags & 0x08) >> 3) * bit)
      next_rotates:
        value: _parent.rotates - (_parent.rotates & bit) + (((type_flags & 0x10) >> 4) * bit)
      next_animates:
        value: _parent.animates - (_parent.animates & bit) + (((type_flags & 0x20) >> 5) * bit)
  interp:
    doc: |
      `[FMT-FLM-OPCODES]` kinematic update, `0x40`-`0x7F`. Payload widths come
      from the slot flags bound by the earlier `create` in the same slice:
      `SIF_MOVES` 12 bytes, `SIF_ROTATES` 6 bytes, `SIF_ANIMATES` 2 bytes, in
      that order. Rotation is streamed `rx, ry, rz`, unlike `create`.
    seq:
      - id: pos_x
        type: s4
        if: ((_parent.moves >> (_parent.tag & 63)) & 1) == 1
      - id: pos_y
        type: s4
        if: ((_parent.moves >> (_parent.tag & 63)) & 1) == 1
      - id: pos_z
        type: s4
        if: ((_parent.moves >> (_parent.tag & 63)) & 1) == 1
      - id: rot_x
        type: u2
        if: ((_parent.rotates >> (_parent.tag & 63)) & 1) == 1
      - id: rot_y
        type: u2
        if: ((_parent.rotates >> (_parent.tag & 63)) & 1) == 1
      - id: rot_z
        type: u2
        if: ((_parent.rotates >> (_parent.tag & 63)) & 1) == 1
      - id: animate
        type: u2
        if: ((_parent.animates >> (_parent.tag & 63)) & 1) == 1
      - id: next
        type: opcode(_parent.moves, _parent.rotates, _parent.animates)
  control:
    doc: |
      Engine events and control commands, `0x80`-`0xBF`. Dispatch is on
      `tag >> 4`, which splits `0x80`-`0x8F`, `0x90`-`0x9F`, `0xA0`-`0xAF`,
      and `0xB0`-`0xBF`.
    seq:
      - id: body
        type:
          switch-on: _parent.tag >> 4
          cases:
            8: var_set
            9: camera(_parent.tag)
            10: before
            11: before
      - id: next
        type: opcode(_parent.moves, _parent.rotates, _parent.animates)
  camera:
    doc: |
      `0x90`-`0x9F`. The tag is passed as a param so both the payload width and
      the embedded slot stay reachable without two `_parent` hops.
    params:
      - id: tag
        type: u1
    seq:
      - id: body
        type:
          switch-on: tag & 0x0F
          cases:
            0: noop
            1: noop
            2: noop
            3: noop
            4: noop
            5: noop
            6: noop
            7: noop
            8: noop
            9: credits
            10: unknown
            11: max_obj
            12: sound
            13: unknown
            14: unknown
            15: unknown
  reserved:
    doc: |
      Class 3, `0xC0`-`0xFF`. Only `0xFF` occurs in the corpus, where it ends
      the slice; no body type recurses, so the chain stops here. The walker
      rejects every other class-3 tag, so no payload is declared.
    seq: []
  var_set:
    doc: '`0x80`-`0x8F`: writes `nextvar[tag & 0x0F]`.'
    seq:
      - id: value
        type: u2
  before:
    doc: '`0xA0`-`0xBF`: records the previous value of `nextvar[tag & 0x1F]`.'
    seq:
      - id: before_value
        type: u2
  max_obj:
    doc: '`0x9B`: sets the maximum active object slot index.'
    seq:
      - id: max_obj
        type: u1
  sound:
    doc: '`0x9C`: dispatches a sound trigger cue.'
    seq:
      - id: audio_flags
        type: u1
        doc: Volume/pan byte; bit 7 appears to be the loop flag (Q-FLM-02).
      - id: sample_id
        type: u2
        doc: Sample resource ID; `0xC000`-`0xCFFF` maps to an `.ALL` sound asset.
  credits:
    doc: '`0x99`: two-line on-screen credit banner, NUL-terminated ASCII.'
    seq:
      - id: line1
        type: strz
        encoding: ASCII
      - id: line2
        type: strz
        encoding: ASCII
  noop:
    doc: 'No payload: `0x90`-`0x98` select a camera view or clear the credits.'
    seq: []
  unknown:
    doc: '`0x9A` and `0x9D`-`0x9F`: not observed in the corpus.'
    seq: []
