---
summary: "`PLAYONE.EXE` loading a film: the `.ALL` directory read, every chunk preloaded into an LRU cache whose node pool shrinks as the id index grows, what each chunk costs, and the film clock starting on the first timer tick after the load."
sidebar_label: "Film load & chunk cache"
---
# `PLAYONE.EXE`: Loading a Film and Its Archive

* **Binary**: unpatched `PLAYONE.EXE`, image offsets ([`static-tooling.md`](static-tooling.md) § 3); `DS:` offsets are `DGROUP`.
* **Method**: static reading with `mise run re-tool -- disasm` and `xref`, 2026-11-18.
* **Scope**: where the `.ALL` is loaded, the chunk cache it fills, what an added chunk costs, and how the film clock starts; why a later start changes the pages a capture keeps ([`linking.md`](../makeone-exe/linking.md) § 7.2) is open.
* **Evidentiary tier**: `[Established]` for what the code does, read statically; `[Hypothesis]` where a capture's frames are tied to it.

---

## 1. The Load (`0x4B04`)

`[Established]`.
The film dialog's two paths, `0x49C6` and `0x4AD6`, call `0x4B04` after the file dialog `0x0787` with the film's path in `DX`.
It:

1. reads the film into the film struct `DS:0x4888` (`0x3834`), or shows `"Not a valid film"` (`DS:0x0A9A`);
2. copies the path to `DS:0x7FEF`, puts `.ALL` in place of its extension, and evicts every cached chunk (`0x4B59`, `0x4DAD` until carry);
3. opens the `.ALL` (`0x4689`), or shows `"That film does not have a matching .ALL file."` (`DS:0x0A6C`, `0x0A86`);
4. reads the count to `DS:0x7FEC`, then the id table and offsets (`6 × count + 4` bytes) into a segment it allocates, kept at `DS:0x0BD6` ([`all.md`](../formats/all.md) § 2.1 has the layout), and closes the file;
5. builds the id index (section 2) and the node free list (`0x4C0F`);
6. calls the cache lookup `0x4C41` for every chunk, from the last id to the first (`0x4BF1..0x4C06`), so the whole archive passes through the cache before the film starts;
7. looks up palette `0x8042` and copies it, each byte shifted right by 2, to `DS:0x2468` (`0x48BF`).

No step sorts the directory: the index is built from runs of equal high byte in file order.

_Source: [the loader preloads every chunk](../../work/2026-11/609_archive-load-start/journal.md#2026-11-18-the-loader-preloads-every-chunk-and-the-film-clock-starts-on-the-next-timer-tick)._

## 2. The Chunk Cache

`[Established]`.
One 10,000-byte region, `DS:0x58DC..0x7FEB`, holds both the id index and the cache nodes:

| `DS` offset | Holds |
|---|---|
| `0x57DC` | `u16[128]`: per high id byte below `0x80`, the near pointer to that byte's slot array, or 0 |
| `0x58DC..[0x0BD8]` | Slot arrays, one per run of equal high byte in the id table (ids from `0x8000` up included), each `last low byte + 1` words; slot `low byte` holds the chunk's node, or 0 |
| `[0x0BD8]..0x7FEB` | Cache nodes, 10 bytes each: `+0` id, `+2` segment, `+4` flags (bit 15 locked), `+6` previous, `+8` next |
| `0x57C6` | Head of the free node list |
| `0x57C8`, `0x57D2` | Sentinel nodes at the two ends of the MRU list; their links `0x57D0` and `0x57D8` point to the most and the least recently used node |

So the node pool is `(10,000 - index bytes) / 10` nodes, set by how the archive's ids fill the index rather than by its chunk count.

The lookup `0x4C41` takes the id in `AX` and returns the chunk's segment in `ES`:

* **Hit.**
  For an id below `0x8000` it reads the slot through `0x57DC`; for one from `0x8000` up, which has no slot, it walks the MRU list from its head until the id matches (`0x4C8C`).
  A hit moves the node to the head.
* **Miss.**
  It finds the id's position by scanning the id table one word at a time (`repne scasw`, `0x4CAA`), takes the size from the offsets, allocates it (`0x4E05`), reads it (`0x024B`: DOS open by the name at `0x7FEF`, seek, read in pieces of up to `0xFFF0` bytes, close), takes a free node or evicts one (`0x4CF7`), and puts it at the head.
* **Eviction** (`0x4DAD`) walks from the tail past locked nodes, frees the chunk (`0x81A3`), clears its slot, and returns the node to the free list; carry when nothing is left.
* **Allocation** (`0x4E05`) retries the heap allocator `0x8111` after each eviction and, with nothing left to evict, frees the block at `DS:0x474C` once before failing.

A linear scan of the code finds fifteen other call sites of `0x4C41`, among them the `OP_ANIMATE` draw entry (`0x8079`, [`memory-map-main.md`](memory-map-main.md)), so a chunk the preload evicted is read from disk when the film first asks for it.

_Source: [the loader preloads every chunk](../../work/2026-11/609_archive-load-start/journal.md#2026-11-18-the-loader-preloads-every-chunk-and-the-film-clock-starts-on-the-next-timer-tick)._

## 3. What an Added Chunk Costs

The counts below follow from sections 1 and 2 for the own `CTRY.ALL` (147 chunks) and each arm of [`linking.md`](../makeone-exe/linking.md) § 7.2, with ids as `pad-all` assigns them:

* **Index bytes**: 2 × the sum, over runs of equal high byte, of the run's last low byte + 1.
* **Nodes**: `(10,000 - index bytes) / 10`, rounded down.
* **Scan words**: `n (n + 1) / 2` for `n` chunks, since the preload's miss for the chunk at position `k` scans `k` words.
* **MRU steps**: for each id from `0x8000` up, in preload order, the list length then, `min(chunks already loaded, nodes)`.
* **Own chunks evicted**: own chunks outside the first `nodes` ids in table order, the ones the preload loads last; the heap's limit is not modelled.

| Added to own `CTRY.ALL` | Chunks | Index bytes | Nodes | Scan words | MRU steps | Own chunks evicted | Last page frame (§ 7.2) |
|---|---|---|---|---|---|---|---|
| Nothing | 147 | 3,132 | 686 | 10,878 | 21 | 0 | 3,139 |
| 1 chunk, `0xF001` (1 or 60,000 bytes) | 148 | 3,136 | 686 | 11,026 | 28 | 0 | 3,139 |
| 1 chunk, `0x5B01` | 148 | 3,136 | 686 | 11,026 | 21 | 0 | 3,139 |
| 300 chunks of 1 byte | 447 | 3,736 | 626 | 100,128 | 46,971 | 0 | 3,139 |
| 63 chunks, 4,092,524 bytes | 210 | 3,260 | 674 | 22,155 | 2,415 | 0 | 3,144 |
| 2,529 chunks of 1 byte, `0xF001` | 2,676 | 8,210 | 179 | 3,581,826 | 437,834 | 0 | 3,149 |
| 2,529 chunks, 4,092,524 bytes, `0xF001` (#348's padding) | 2,676 | 8,210 | 179 | 3,581,826 | 437,834 | 0 | 3,173 |
| 2,529 chunks, 4,092,524 bytes, `0x5B01` | 2,676 | 8,210 | 179 | 3,581,826 | 21 | 8 | 3,169 |

* **A chunk costs a directory scan, a DOS open and close, and, for an id from `0x8000` up, a walk of the MRU list.**
  The scan grows with the square of the chunk count, which fits a chunk weighing more than its bytes in § 7.2; on 2,529 chunks the preload also evicts 2,497 times, since only 179 nodes are left.
* **`0xF0` ids cost an MRU walk that `0x5B` ids do not**: 437,834 steps against 21.
  This fits the `0x5B01` arm ending 4 frames earlier, but that arm also leaves 8 own chunks evicted at load (`0x7F37`, `0x801E`, `0x8042` and five sound ids), and `0x8042` is reread at once (`0x48BF`), so the 4 frames are not attributed `[Hypothesis]`.
* **CPU work does not account for the bytes arm.**
  The 63-chunk 4 MB arm scans 22,155 words and walks 2,415 steps, about the 1-chunk arm's, yet its last page fell 5 frames later; its 63 reads of about 65,000 bytes and the allocator's evictions are what it adds.
  How the capture's emulator charges time for a DOS read, or for one `repne scasw` word on the capture profile's dynamic core at 45,000 cycles ([`staging.py`](../../python/stunt_reel/tac/staging.py)), was not read, so no count here is converted to frames.

_Source: [the loader preloads every chunk](../../work/2026-11/609_archive-load-start/journal.md#2026-11-18-the-loader-preloads-every-chunk-and-the-film-clock-starts-on-the-next-timer-tick)._

## 4. The Film Clock's Start

`[Established]` for the code; `[Hypothesis]` for the quantum.

* **After the load.**
  The dialog path `0x49C6..0x49ED` calls `0x3A11`, which zeroes the film clock `DS:0x4896`, its fraction `0x4898` and the slice state, sets the speed `DS:0x489C` to `0x100` (one tick per tick, 8.8), and calls `0x0E42`, which zeroes `0x22B8` and `0x22BE` and sets the playback flag `0x2272`; then the main loop's per-frame call `[0x0D7A]` (`0x54B8`) becomes the film step `0x49F9`.
  The path `0x4ACE..0x4AFD` does the same without zeroing `0x22B8`.
  Neither waits on a timer tick or the retrace.
* **The clock.**
  On each timer interrupt (`0x43A5`), while `0x2272` is set, `0x22B8` gains 1 and the film clock gains the speed (`0x43D8..0x43E6`), so the film's tick 1 is the first interrupt after the load returns.
  If the timer keeps its phase across the load, loads that end within one 20 ms timer period start the film clock at the same emulated instant, which would explain why small additions moved nothing (`[Hypothesis]`: no capture timed the start, and whether the timer is reprogrammed during the load was not read; `0x36F7`, which installs the handler and programs the timer, is called from `0x06E8`, `0x5189` and `0x51CC`).
* **The interpolation fraction does not carry the phase.**
  `DS:0x22E0` (`0x3AE4..0x3AF7`) is the film clock's ticks and fraction into the current slice over the slice's length, after the film step `0x3A72` has moved the slice to the one holding the clock (forward from `0x3AFC`, back through `0x3ACF`).
  At speed `0x100` the fraction word stays 0, so `0x22E0`, which drives the interpolations `0x136F` and `0x3E6C`, is the same for the same film tick.
* **Per-frame deltas.**
  `0x136F` stores the film clock's ticks since the previous frame at `DS:0x22DC`, and `0x3712` the `0x22B8` ticks since `0x22BE`; `xref 0x22DC` finds no reader.

_Source: [the loader preloads every chunk](../../work/2026-11/609_archive-load-start/journal.md#2026-11-18-the-loader-preloads-every-chunk-and-the-film-clock-starts-on-the-next-timer-tick)._

## Ruled out

- **A sort of the directory at load.**
  The index is built from runs in file order (section 1; [journal](../../work/2026-11/609_archive-load-start/journal.md#2026-11-18-the-loader-preloads-every-chunk-and-the-film-clock-starts-on-the-next-timer-tick)).
- **The interpolation fraction `0x22E0` as the carrier of the start's phase, at speed `0x100`.**
  At speed `0x100` it is a function of the film tick and the film's slices (section 4; [journal](../../work/2026-11/609_archive-load-start/journal.md#2026-11-18-the-loader-preloads-every-chunk-and-the-film-clock-starts-on-the-next-timer-tick)).

## Open questions

1. What state is stepped per drawn frame rather than per film tick, so that a later start changes what is drawn at a tick?
   Readers of the per-frame deltas (`0x22DC`, `0x22BE`) not found by `xref`, and anything else counting frames, are where to look ([#723](https://github.com/neilsh/stunt-reel/issues/723)).
2. Does the film clock start on the same emulated instant for archives that draw alike, and later by whole timer ticks for those that do not?
   A live log of `0x22B8`, `0x2272` and the emulator frame from the end of `0x4B04` to the first drawn page, on the own and a padded `CTRY.ALL`, would settle the quantum; it needs DOSBox ([#722](https://github.com/neilsh/stunt-reel/issues/722)).
3. What does the 63-chunk 4 MB arm's later start come from, given its small scan and walk counts: the emulator's charge for DOS reads, the allocator's evictions, or the heap's limit?
4. Do the 8 own chunks the `0x5B01` arm evicts at load change its pages beyond its start?
5. What happens when the index fills the region: an archive whose index needs more than 10,000 bytes leaves no node and writes past `0x7FEB` into the count word `0x7FEC`; untested.
