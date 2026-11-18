# Journal: why `PLAYONE`'s archive load time changes its pages

## 2026-11-18: the loader preloads every chunk, and the film clock starts on the next timer tick

- **Question**: Where does `PLAYONE.EXE` load the `.ALL`, what does it do per chunk, why do ids in `0x5B` cost less than in `0xF0`, what quantises the film's start, and why does the start's phase change what is drawn at a tick ([#609](https://github.com/neilsh/stunt-reel/issues/609); [`linking.md`](../../../research/makeone-exe/linking.md) § 7.2 and open question 8)?
- **Method**: Static reading of the unpatched load image (`build/re/playone.img` in the data root) at `origin/main` of 2026-11-18, image offsets throughout:
  - `mise run re-tool -- xref --string '.ALL'` found the string `"That film does not have a matching .ALL file."` (`DS:0x0A6C`, `0x0A86`); `xref 0x0A6C` led to its one user, the film loader `0x4B04`.
  - `re-tool -- disasm` over `0x4B04..0x4E40` (loader, cache lookup, eviction, allocation), `0x024B..0x02B0` (chunk read), `0x49C0..0x4A10` and `0x4AC0..0x4B04` (the two callers), `0x3A11..0x3A71` (film clock reset), `0x0E42..0x0E5F`, `0x43A5..0x43FC` (the INT 8 path), `0x3AE4..0x3AF7` and `0x136F..0x1381` (per-frame fraction and delta), `0x5441..0x54BC` (main loop).
  - `re-tool -- xref` of `0x22B8`, `0x4896`, `0x489C`, `0x22BE`, `0x22DC`, `0x22E0`, `0x474C`, `0x0D7A`; near calls to the loader routines by a one-off iced-x86 scan of image `0x0000..0x823F`.
  - A one-off model over the own `CTRY.ALL` (`captures/vault-ctry/archives/CTRY.ALL`, 147 chunks, ids `0x0107..0xC56A`) and the ids `pad_all.inert_ids` gives each #482 arm: the index size, the node pool, the preload's directory-scan words and MRU-list steps, and which own chunks are still cached after the preload (formulas in [`film-load.md`](../../../research/playone-exe/film-load.md) § 3).
- **Result**:
  - The loader `0x4B04` flushes the cache, opens the `.ALL`, reads its count and directory, builds an index by high id byte in `DS:0x57DC..0x7FEB`, hands the rest of that 10,000-byte region to a free list of 10-byte cache nodes, then calls the cache lookup `0x4C41` for every chunk from last to first (`0x4BF1..0x4C06`).
    A lookup that misses scans the id table word by word (`repne scasw`, `0x4CAA`), allocates (`0x4E05`, evicting the least recently used chunk until it fits), and reads the chunk with its own DOS open, seek, read and close (`0x024B`); when no node is free it evicts one (`0x4CF7`).
    Ids from `0x8000` up have no index slot: their lookup walks the MRU list from its head (`0x4C8C`).
  - Model, per arm (own `CTRY.ALL` plus the arm):

    | Arm | Chunks | Index bytes | Nodes | Scan words | MRU steps | Own chunks evicted (node pool; heap not modelled) |
    |---|---|---|---|---|---|---|
    | own | 147 | 3,132 | 686 | 10,878 | 21 | 0 |
    | 1 × 1 byte, `0xF001` | 148 | 3,136 | 686 | 11,026 | 28 | 0 |
    | 1 × 1 byte, `0x5B01` | 148 | 3,136 | 686 | 11,026 | 21 | 0 |
    | 300 × 1 byte | 447 | 3,736 | 626 | 100,128 | 46,971 | 0 |
    | 63 chunks, 4,092,524 bytes | 210 | 3,260 | 674 | 22,155 | 2,415 | ? |
    | 2,529 chunks of 1 byte, `0xF001` | 2,676 | 8,210 | 179 | 3,581,826 | 437,834 | 0 |
    | 2,529 chunks, 4,092,524 bytes, `0xF001` (#348's padding) | 2,676 | 8,210 | 179 | 3,581,826 | 437,834 | ? |
    | 2,529 chunks, 4,092,524 bytes, `0x5B01` | 2,676 | 8,210 | 179 | 3,581,826 | 21 | 8 or more |

    The 4 MB arms likely also evict for want of heap (its size was not read), least recently loaded first (the padding in `0xF001` arms, the own chunks from `0x7F37` up in the `0x5B01` arm), which the model leaves out, so their cells are `?` or a lower bound.
    The `0x5B01` arm's own chunks evicted by the node pool are `0x7F37`, `0x801E`, `0x8042` and the sound ids `0xC010`, `0xC302`, `0xC319`, `0xC31E`, `0xC56A`.
    The 60,000-byte arm has the 1-chunk arm's counts.
  - The dialog path `0x49C6..0x49ED` runs the loader, resets the film clock (`0x3A11`), sets the speed `DS:0x489C` to `0x100`, and calls `0x0E42`, which zeroes `0x22B8` and `0x22BE` and sets the playback flag `0x2272`; the second path `0x4ACE..0x4AFD` clears `0x2272` (`0x4AD1`) before its dialog and load, does the same steps without `0x0E42`, and sets `0x2272` at `0x4AFD`.
    Neither waits on a tick or the retrace.
    The INT 8 path (`0x43A5`) increments `0x22B8` and adds the speed (8.8 ticks) to the film clock `0x4896:0x4898` on each interrupt while `0x2272` is set.
  - The interpolation fraction `DS:0x22E0` (`0x3AE4..0x3AF7`) is the film clock's ticks and fraction word into the slice over the slice length; at speed `0x100` the fraction word stays 0 after `0x3A11`, so the fraction is a function of the film clock's tick.
    `0x136F` and `0x3712` store per-frame tick deltas at `DS:0x22DC`; `xref 0x22DC` finds no reader.
- **Verdict**:
  - Where and what per chunk: adopted (static reading). Load cost grows with each chunk (a scan of the id table, a DOS open and close) and, for ids from `0x8000` up, with a walk of the MRU list; bytes add read and eviction work.
  - Why `0x5B` ids cost less than `0xF0`: the MRU walk is a candidate (437,834 steps for `0xF001`, 21 for `0x5B01`), not adopted: the two arms also differ in node-pool evictions (8 own chunks in the `0x5B01` arm) and, unmodelled, in heap evictions.
  - Start quantisation: the film clock counts from the first timer interrupt after the load returns; that this is the quantum (loads ending within one 20 ms timer period start alike) is a `[Hypothesis]`: no capture timed it, and whether the timer's phase survives the load was not read.
  - The 63-chunk 4 MB arm has a small CPU cost in the model yet moved the last page 5 frames, so the model's CPU work alone does not account for the load-time shift; open.
  - The fraction `0x22E0` carrying the start's phase into the drawing: rejected statically at speed `0x100`. What steps per drawn frame is open.
- **Lives in**: [`film-load.md`](../../../research/playone-exe/film-load.md); [`linking.md`](../../../research/makeone-exe/linking.md) § 7.2 and open questions 5 and 8.
