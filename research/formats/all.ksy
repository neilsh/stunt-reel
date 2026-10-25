# Executable structural layout of the Stunt Island `.ALL` movie bundle.
# Format anchor: [FMT-ALL-CHUNKS] in all.md.
#
# Layout verified against the 289 `.ALL` files in corpus/siarchive/:
# the directory holds `num_chunk_ids + 1` offsets, the first equals the header
# size (6 * num_chunk_ids + 6), and the last is the file-size sentinel. Chunk
# classification (palette / SOD / FILM / audio) is parser policy, not layout.
meta:
  id: all
  title: Stunt Island movie bundle (`.ALL`)
  file-extension: all
  ks-version: 0.11
  endian: le
doc: |
  A `.ALL` movie bundle: chunk count, chunk ids and offsets, then the
  chunk payloads. Meaning is in `all.md`.
seq:
  - id: num_chunk_ids
    type: u2
    doc: Number of resource chunks declared by the directory.
  - id: chunk_ids
    type: u2
    repeat: expr
    repeat-expr: num_chunk_ids
    doc: 16-bit resource identifier, one per chunk.
instances:
  len_header:
    value: 6 * num_chunk_ids + 6
    doc: |
      End of the directory and start of the first payload. Equals
      2 + 2 * num_chunk_ids (ids) + 4 * (num_chunk_ids + 1) (offsets).
  offsets:
    pos: 2 + 2 * num_chunk_ids
    type: u4
    repeat: expr
    repeat-expr: num_chunk_ids + 1
    doc: |
      Byte offset of every chunk start, plus a trailing sentinel equal to
      the file size for intact archives.
