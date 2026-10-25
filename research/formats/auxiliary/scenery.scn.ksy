# Executable structural layout of `SCENERY.scn`.
# Format anchor: [FMT-MAP-SCENERY] in map.md.
#
# Both corpus copies are 118,236 bytes: 29,559 little-endian 32-bit words
# addressed by word index. Node records live in this array and reference
# children by half-word index, so only the array layout is encoded here.
meta:
  id: scenery
  title: Stunt Island BSP scenery graph (`SCENERY.scn`)
  file-extension: scn
  ks-version: 0.11
  endian: le
doc: |
  The 32-bit word array of the `SCENERY.scn` BSP tree. Meaning is in
  `map.md`.
seq:
  - id: words
    type: u4
    repeat: eos
    doc: |
      Precompiled graph words. Word index 1 is the root node; child
      pointers are half-word indices into this array.
