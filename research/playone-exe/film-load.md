---
summary: "`PLAYONE.EXE` loading a film: the `.ALL` directory read, every chunk preloaded into an LRU cache whose node pool shrinks as the id index grows, what each chunk costs, the film clock starting on the first timer tick after the load, so archives that draw alike start on the same interrupt and later ones whole ticks later, and the per-frame probe that sweeps from each slot's position at the previous drawn frame, whose results in `CTRY.FLM` did not change at any probed frame of two live runs, while its padded-archive pages differ at the propeller and the viewpoint; the slots are placed by the fraction the film step sets from its clock reading and the HUD shows the clock after the render, and on 12 of the 23 viewpoint pages, on peaked score curves, the two archives' scenes are a tick apart at one tag."
sidebar_label: "Film load & chunk cache"
---
# `PLAYONE.EXE`: Loading a Film and Its Archive

* **Binary**: unpatched `PLAYONE.EXE`, image offsets ([`static-tooling.md`](static-tooling.md) § 3); `DS:` offsets are `DGROUP`.
* **Method**: static reading with `mise run re-tool -- disasm` and `xref`, 2026-11-18 and 2026-11-24 (section 5's clock readings also by a recursive descent over direct calls); section 6 is a per-frame memory log on dosbox-automation, and section 5's live runs use DOSBox-X's debugger.
* **Scope**: where the `.ALL` is loaded, the chunk cache it fills, what an added chunk costs, how the film clock starts, and what the per-frame call steps per drawn frame rather than per film tick (section 5); whether that is why a later start changes the pages a capture keeps ([`linking.md`](../makeone-exe/linking.md) § 7.2) is open.
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
* **Own chunks evicted by the node pool**: own chunks outside the first `nodes` ids in table order, the ones the preload loads last.
  Evictions for want of heap are not modelled: an arm adding megabytes likely also evicts at load, the heap's size being unread, least recently loaded first, which is the padding in the `0xF001` arms and the own chunks from `0x7F37` up in the `0x5B01` arm; so the cells of the three 4 MB arms are `?` or a lower bound.

| Added to own `CTRY.ALL` | Chunks | Index bytes | Nodes | Scan words | MRU steps | Own chunks evicted (node pool; heap not modelled) | Last page frame (§ 7.2) |
|---|---|---|---|---|---|---|---|
| Nothing | 147 | 3,132 | 686 | 10,878 | 21 | 0 | 3,139 |
| 1 chunk, `0xF001` (1 or 60,000 bytes) | 148 | 3,136 | 686 | 11,026 | 28 | 0 | 3,139 |
| 1 chunk, `0x5B01` | 148 | 3,136 | 686 | 11,026 | 21 | 0 | 3,139 |
| 300 chunks of 1 byte | 447 | 3,736 | 626 | 100,128 | 46,971 | 0 | 3,139 |
| 63 chunks, 4,092,524 bytes | 210 | 3,260 | 674 | 22,155 | 2,415 | ? | 3,144 |
| 2,529 chunks of 1 byte, `0xF001` | 2,676 | 8,210 | 179 | 3,581,826 | 437,834 | 0 | 3,149 |
| 2,529 chunks, 4,092,524 bytes, `0xF001` (#348's padding) | 2,676 | 8,210 | 179 | 3,581,826 | 437,834 | ? | 3,173 |
| 2,529 chunks, 4,092,524 bytes, `0x5B01` | 2,676 | 8,210 | 179 | 3,581,826 | 21 | 8 or more | 3,169 |

* **A chunk costs a directory scan, a DOS open and close, and, for an id from `0x8000` up, a walk of the MRU list.**
  The scan grows with the square of the chunk count, which fits a chunk weighing more than its bytes in § 7.2; on 2,529 chunks the preload also evicts at least 2,497 times, since 179 nodes are left.
* **`0xF0` ids cost an MRU walk that `0x5B` ids do not**: 437,834 steps against 21.
  This fits the `0x5B01` arm ending 4 frames earlier, but the two arms also differ in node-pool evictions (the `0x5B01` arm evicts 8 own chunks at load, `0x7F37`, `0x801E`, `0x8042` and five sound ids, and `0x8042` is reread at once by `0x48BF`) and, unmodelled, in heap evictions, so the 4 frames are not attributed `[Hypothesis]`.
* **CPU work does not account for the bytes arm.**
  The 63-chunk 4 MB arm scans fewer words and walks fewer steps (22,155 and 2,415) than the 300-chunk arm (100,128 and 46,971), which started on time (last page 3,139), yet its last page fell 5 frames later; its 63 reads of about 65,000 bytes and the allocator's evictions are what it adds.
  How the capture's emulator charges time for a DOS read, or for one `repne scasw` word on the capture profile's dynamic core at 45,000 cycles ([`staging.py`](../../python/stunt_reel/tac/staging.py)), was not read, so no count here is converted to frames.

_Source: [the loader preloads every chunk](../../work/2026-11/609_archive-load-start/journal.md#2026-11-18-the-loader-preloads-every-chunk-and-the-film-clock-starts-on-the-next-timer-tick)._

## 4. The Film Clock's Start

`[Established]` for the code; section 6 times the start live.

* **After the load.**
  The dialog path `0x49C6..0x49ED` calls `0x3A11`, which zeroes the film clock `DS:0x4896`, its fraction `0x4898` and the slice state, sets the speed `DS:0x489C` to `0x100` (one tick per tick, 8.8), and calls `0x0E42`, which zeroes `0x22B8` and `0x22BE` and sets the playback flag `0x2272`; then the main loop's per-frame call `[0x0D7A]` (`0x54B8`) becomes the film step `0x49F9`.
  The path `0x4ACE..0x4AFD` clears the playback flag `0x2272` (`0x4AD1`) before its dialog and load, then runs the loader, `0x3A11` and the speed as above and sets the flag at `0x4AFD`, without zeroing `0x22B8`.
  On the `0x4ACE` path no tick is counted during the load.
  The dialog path does not clear `0x2272` first, so whether ticks count during its load was not read statically; it zeroes the clock and `0x22B8` after the load either way.
  On a capture's first film the flag reads 0 through the whole load (section 6).
  Neither waits on a timer tick or the retrace.
* **The clock.**
  On each timer interrupt (`0x43A5`), while `0x2272` is set, `0x22B8` gains 1 and the film clock gains the speed (`0x43D8..0x43E6`), so the film's tick 1 is the first interrupt after the load returns.
  The timer keeps its phase across the load, so loads that end between the same two interrupts start the film clock at the same emulated instant (section 6).
  The code that installs the handler and programs the timer, `0x36F7`, is called from `0x06E8`, `0x5189` and `0x51CC`; which of them runs during a load was not read.
* **The interpolation fraction does not carry the phase.**
  `DS:0x22E0` (`0x3AE4..0x3AF7`) is the film clock's ticks and fraction into the current slice over the slice's length, after the film step `0x3A72` has moved the slice to the one holding the clock (forward from `0x3AFC`, back through `0x3ACF`).
  At speed `0x100` the fraction word stays 0, so `0x22E0`, which drives the interpolations `0x136F` and `0x3E6C`, is the same for the same film tick.
* **Per-frame deltas.**
  `0x136F` stores the film clock's ticks since the previous frame at `DS:0x22DC`, and `0x3712` the `0x22B8` ticks since `0x22BE`; `xref 0x22DC` finds no reader.

_Source: [the loader preloads every chunk](../../work/2026-11/609_archive-load-start/journal.md#2026-11-18-the-loader-preloads-every-chunk-and-the-film-clock-starts-on-the-next-timer-tick)._

## 5. What a Drawn Frame Steps

`[Established]` for the code, read statically ([#723](https://github.com/neilsh/stunt-reel/issues/723)); `[Bounded Observation]` for the live run and the captures, where noted ([#779](https://github.com/neilsh/stunt-reel/issues/779)).

* **Each slot keeps its position at the previous pass.**
  `0x136F` clears bit 0 of byte `+0` of every slot of the struct in `SI` (`0x13B4..0x13C2`), then calls `0x1423` for each slot whose bit is still clear (`0x13C5..0x13DC`).
  `0x1423` sets the bit, copies the position `+0x04..+0x0F` to `+0x24..+0x2F`, and then moves the slot: through `0x3E63` to the interpolation `0x3E6C` when byte `+0` bit 7 is set, otherwise through the word at `+0x30`, which the one instruction naming it sets to 0 (`0x37D8`).
  So `+0x24..+0x2F` holds where the slot was when `0x136F` last ran on that struct: on the film step's path (`0x4A17`), at the previous drawn frame.
  The two other calls of `0x136F` (`0x3B6E`, `0x3BAD`) are on the step's path for a zero-length slice while `DS:0x2281` is set (`0x3B0F..0x3B14`, `0x3B2C`), and the snapshot copy `0x39AE` copies each slot's words `+0x00..+0x17`, leaving `+0x24` as it was.
* **The probe sweeps from there.**
  For each moving slot, `0x1463` has `0x14D5` build the probe's sphere at `DS:0x22F4` ([`memory-map.md`](memory-map.md)): centred midway between `+0x04` and `+0x24`, with a radius of the largest half-displacement on an axis plus the shape's radius.
  The probe `0x240A` tests that sphere at the splits `0x24B8` and `0x24C2`, the cubes `0x2547` and the object nodes `0x257A`, and the box walk entered at `0x26D0` takes both the current and the `+0x24` position relative to the object (`0x2762..0x2808`).
  When the box walk returns carry (`0x25D2`), `0x25D7` reloads `SP` from `DS:0x2340`, saved at the probe's entry, so the probe returns without visiting the rest of the scenery tree, and a ground leaf later in walk order does not store its plane at `+0x1E`.
  So the ground plane `+0x1E` and the box top `+0x20/+0x22`, which the shadow draw reads ([`sod-vm-frame.md` § 9.1](sod-vm-frame.md#91-the-actor-shadow-draw)), depend on where the slot was at the previous drawn frame as well as on the film tick.
* **In `CTRY.FLM` the sweep changes nothing (`[Bounded Observation]`, DOSBox-X's debugger, unpatched build, the own and #348's padded `CTRY.ALL`, one run each, 2026-11-19).**
  A break at `0x1492`, just before `0x1463` calls the probe, saw one probed slot (`DS:0x393A`) up to tick 850 and none after; on 141 of 182 (own) and 164 of 207 (padded) consecutive hits its `+0x24..+0x2F` was the previous hit's `+0x04..+0x0F`, and every other pair was 4 or more ticks apart, a frame unhit between.
  Its `+0x1C`, `+0x1E`, `+0x20` and `+0x22` read 0, `0x033C`, 0 and 0 at every hit (own: ticks 52 to 849; padded: 5 to 850, its tick-0 hit, before any probe, reading 0 in all four): one ground leaf's plane and no box, whatever the previous frame.
  These are DOSBox-X's frames, not the captures' (hits mostly 3 ticks apart, up to 24), so they cannot be paired with the captures' pages; the conclusion below rests on the results being constant and on the pages' classification.
* **What differs on CTRY's padded-archive pages (`[Bounded Observation]`, #348's own and padded captures, 111 paired ticks).**
  Outside the HUD clock 52 pages differ, classified by eye: 28 at the propeller, on the aircraft and in its shadow; 23 along edges across the whole view, a viewpoint a pixel or so apart; one by 14 pixels near an object's tip.
  None differs at the shadow alone, so the sweep is not what changes these pages ([`linking.md`](../makeone-exe/linking.md) § 7.2).
  If the biplane's propeller is a stock `ROTZ` on operand `0x14` (not checked), its angle is the angle bank's word `0x14`, the previous drawn frame's var 10 ([`angle-bank.md`](angle-bank.md)), so a frame drawn after another schedule draws it at another angle (`[Hypothesis]`).
  On 15 of the 23 viewpoint pages the HUD clock reads the same in both captures.
* **The slots and the HUD clock come from different readings of the clock (`[Established]` for the readings named, read statically, [#826](https://github.com/neilsh/stunt-reel/issues/826)).**
  Between the film step's call (`0x4A07`) and the HUD's read, the direct-call trace found four reads of the clock `DS:0x4896` as `[reg + 0x0E]` with the register holding `0x4888`:
  - the film step at `0x3A88`, which moves the slice and sets the fraction `0x22E0` (`0x3AE4..0x3AF7`), which the slot pass `0x136F` (`0x1381`) and the interpolation `0x3E6C` (`0x3E76`) read;
  - the slot pass at `0x1370` (`0x13EA` with `SI = 0x4888`), which stores only the ticks since its previous run (`0x22DC`, no reader by address) and the clock at `DS:0x489A` (field `+0x12`); the clock minus the ticks word is the previous slot pass's clock, and a page kept at the next frame scores best, on a film's mean, against the state at that clock ([`capture.md` § 4](capture.md#4-observed-results), `[Bounded Observation]`);
  - the angle bank's fill at `0x1DCA` (`0x1D96`, from `0x0F77` in the render step `0x0EE9`), which writes bank word `0x10` as `clock << 12` ([`angle-bank.md`](angle-bank.md));
  - `0x40C5`, in `0x40AC`, which stores a clock delta through `[0x4888]` and is reached from the slot pass at `0x141F` when the deferred-call queue is not empty and byte `0x2276` is set, and from the film step at `0x3BB0`.
  The film step also reads `[0x4896]` directly at `0x3B37` on its zero-length-slice path.
  After `0x0EE9`, `0x4A38` reads the clock again and passes it to the HUD clock's draw `0x33C3`.
  The recursive descent followed direct near calls and jumps from the film step and from `0x4FCD`, `0x13EA`, `0x1151`, `0x11F8` and `0x0EE9` (3,806 instructions).
  It checked `0x4896` operands and `+0x0E` displacements.
  The other `+0x0E` reads it found sit beside `+0x04`, `+0x08` and `+0x0C` reads of a 32-bit position.
  It does not follow the 78 far calls (most into segment `0x0824`), word-table calls and register calls it met, so a reader through those is not excluded.
  So a drawn frame's slots, the camera's object among them, are placed by the fraction from the film step's reading; the angle bank's word `0x10` is a later reading within the render; and the HUD shows the clock after the render, later by the timer interrupts that fell while the frame was composed.
* **That gap varies per frame, and the camera's eye and angles carried no state between frames (`[Bounded Observation]`, DOSBox-X's debugger, unpatched build, the own and #348's padded `CTRY.ALL`, sound stubbed, one run each, 2026-11-24).**
  The HUD's tick less the film step's was 2, 3 or 4 on 112, 212 and 72 of the own run's 396 drawn frames, and 1 to 5 on the padded run's 418 (139, 196 and 79 of them 2, 3 and 4).
  The camera's 24-byte record at `0x1251` (eye and angles) was equal in both runs at all 195 film-step ticks both drew, about half of each run's frames, and at 56 of the 201 HUD ticks both drew the two runs' film-step ticks were one apart.
  These are DOSBox-X's frames, drawn 2 to 5 ticks apart, and they do not pair with the captures' pages ([`capture-dosbox-automation.md`](capture-dosbox-automation.md) § 2 has the captures' HUD 0 to 3 ticks behind the live tick).
* **On 12 of the 23 viewpoint pages the curves fit a one-tick shift (`[Bounded Observation]`, fresh unpatched captures of the own and the padded archive, sound stubbed, one each, which reproduce #348's 111 shared ticks and 42 identical pages and #779's 52 differing ones).**
  Each capture was scored against one render of the own archive relabelled to offsets -3 to +2, every score with `--waive-archive-conflict`, and the padded page's index-agreement curve was matched to the own page's at shifts of -2 to +2 ticks.
  The padded capture's archive differs from the render's, so its curve can sit lower than the own capture's whatever its tick; the match takes the curves' shape over offsets, and where a curve is nearly flat a level offset between the arms can pass for a shift.
  28 of the 29 other differing pages (the propeller's and 837) fit shift 0 and 716, nearly flat, is undecided, so the score separates a one-tick step where the camera moves.
  Of the 23 viewpoint pages, 12 fit a shift of one tick on peaked curves (the padded page later on 7 and earlier on 5), and 3 more (1145, 1189, 1212) fit one on near-flat curves, moving at most 2.1 thousandths between offsets, with fit errors of 0.20 to 0.24 thousandths, the size of the propeller pages' errors at shift 0; 6 are undecided, 2 unscored, and none fits 0 or 2.
  Of the 15 at an equal HUD clock, 5 fit a one-tick shift on peaked curves and 3 on near-flat ones, 6 are undecided and 1 is unscored.
  On the 5 peaked pages with an equal HUD clock, a one-tick shift between the scenes is consistent with the varying lag observed in DOSBox-X.
  The other 7 peaked pairs have different HUD clocks.
  Across the 12 peaked pairs, parity's `t - 1` pairs at least one page in each pair with a render a tick off its scene.
  The shift is relative: no page was dated by the film step's clock.
* **The pair test does not run.**
  `0x1463` calls `0x1588` for pairs of slots when `DS:0x2282` is set (`0x149A`), but `0x2282` is 0 in the load image (image `0xF792`) and the one instruction that writes it stores 0 (`0x49C1`).
  Its hit path (`0x16C2`) and the probe's (`0x25EE`) both go to `0x4B03`, a bare `ret`.
* **No frame counter.**
  The per-frame call `0x49F9` calls `0x62E7`, the film step `0x3A72`, `0x4FCD` when the speed `0x489C` is 0, `0x13EA` with `SI = 0x4888`, the clip setup `0x1151` (`0`, `0`, `0x140`, `0xB9`), `0x11F8`, the render step `0x0EE9`, `0x33C3` with the film clock, `[0x225A]` and `0x31C0` (`0x49F9..0x4A52`); none of its instructions increments a word in memory.
  `0x13EA` runs `0x136F`, the slot update `0x1463`, then the deferred-call queue: `DS:0x2366` entries of a handler and an `SI` at `DS:0x2368`, at most 64, pushed by `0x144A` and counted down to 0 as each runs (`0x1405..0x1416`), so the queue is empty at the end of each frame and carries nothing to the next.
  In the main code below image `0x8240`, the `inc` and `dec` instructions on a fixed `DGROUP` word or byte serve the INT 8 path (`0x22BA`, `0x22B8`, and the countdown `0x0BD4` at `0x449A`), the one-tick step of a stopped film (`0x4896`, `0x4A8B`, `0x4A9D`), the deferred-call queue (`0x2366`), a list of up to 100 rectangles (`0x546`, appended at `0x4854..0x4879`), loop counts in `0x66D8..0x78AB` (`0x0DEC`, `0x1092`, `0x10C6`), a count after a string scan (`0x4EA`, `0x090F`) and one beside a DOS call (`0x2230`, `0x016C`); none of these is a count of drawn frames.
* **`0x22DC` and `0x3712` have no direct reference.**
  `mise run re-tool -- xref 0x22DC --code-end 0xFFFF` finds the two stores (`0x137B`, `0x371F`) and nothing else, and the word `0x22DC` occurs in the unpacked image's bytes only inside those two instructions, so no table or immediate holds its address; a reader would have to form it by arithmetic.
  The word `0x3712` occurs nowhere in the image, and `disasm 0x0 0xD510` holds no near call or jump to it, so `0x3712`, the one user of `0x22BE` besides its zeroing at `0x0E4E`, is not reached by any direct reference.
* **`0x22BA` feeds input timing, not the film.**
  The INT 8 path counts it on every interrupt, playback or not (`0x43A5`).
  Its readers are `0x5552`, which sets `DS:0x0D98` when 10 or fewer ticks passed since `DS:0x0D90` was last set and then sets it, and `0x5B4A`/`0x5B66`, a timer at `DS:0x0D90` that calls `[si + 8]` 20 ticks after it is armed, then every 3; `[Hypothesis]` that both are the menu's click and key repeat.
* **The streamer's phase follows the timer.**
  `0xB58D` is `OP_IPG` type 6, the streamer, reached through the subtype table `work:0x1954` (`mise run re-tool -- vm-handler 0x63`; [`sod-vm-generators.md`](sod-vm-generators.md)).
  It sets `ES = 0x0D51` (`DGROUP`) and reads `0x22B8` (`0xB5A6`) for a phase with a period of 64 timer ticks.
  `0x22B8` is zeroed by `0x0E42` at the start and advanced once per tick by the INT 8 path while `0x2272` is set (section 4), so the phase is not stepped per drawn frame; at speed `0x100` with no pause it equals the film tick, and whether a pause or a slower speed lets the two part was not traced.
* **A second clock.**
  The INT 8 path also adds the speed `DS:0x475E` to `0x4758:0x475A` (`0x43B4..0x43D2`); `0x0E48` copies `0x4758` to `0x475C`, which nothing else uses as an operand, and `0x3B33`/`0x3BB8` save and restore it around the two other calls of `0x136F`.
  It is a timer-driven clock, like the film clock.

_Source: [the slot pass keeps each slot's previous position](../../work/2026-11/723_frame-stepped-state/journal.md#2026-11-18-the-slot-pass-keeps-each-slots-previous-position-and-the-probe-sweeps-from-it); [the per-frame call steps no frame counter](../../work/2026-11/723_frame-stepped-state/journal.md#2026-11-18-the-per-frame-call-steps-no-frame-counter); [the probe's results held at every probed frame](../../work/2026-11/779_carried-draw-state/journal.md#2026-11-19-the-probes-results-held-at-every-probed-frame-pages-differ-at-the-propeller-and-the-viewpoint); [the film step reads the clock before the render](../../work/2026-11/826_ctry-padded-viewpoint/journal.md#2026-11-24-the-film-step-reads-the-clock-before-the-render-and-the-hud-reads-it-after); [HUD minus scene tick varies](../../work/2026-11/826_ctry-padded-viewpoint/journal.md#2026-11-24-hud-minus-scene-tick-varies-from-frame-to-frame-under-dosbox-x); [the arms' scenes are one tick apart](../../work/2026-11/826_ctry-padded-viewpoint/journal.md#2026-11-24-on-12-viewpoint-pages-the-two-arms-scenes-are-one-tick-apart)._

## 6. The Start Against the Emulator Frame

`[Bounded Observation]`: `CTRY.FLM`, unpatched build, the own `CTRY.ALL` and the nine arms of [`linking.md`](../makeone-exe/linking.md) § 7.2, one run each on dosbox-automation in a cloud session, 2026-11-18 ([#722](https://github.com/neilsh/stunt-reel/issues/722)).

A Lua script read `DS:0x22B8`, `0x2272`, `0x4896`, `0x22BA` and `0x7FEC` on every emulator frame, pressing the dialog keys on the frames a capture does.
`0x22BA` counts every timer interrupt, so `0x22BA - 0x22B8 + 1` on a playing frame is the interrupt that was the film's tick 1.

| Added to own `CTRY.ALL` | `0x2272` first set (frame) | Film tick 1 on interrupt | Ticks after own | Last page frame |
|---|---|---|---|---|
| Nothing; 1 chunk (`0xF001` or `0x5B01`, 1 byte; 60,000 bytes) | 1,271 | 904 | 0 | 3,139 |
| 300 chunks of 1 byte | 1,272 | 904 | 0 | 3,139 |
| 63 chunks, 4,092,524 bytes | 1,276 | 907 | 3 | 3,144 |
| 2,529 chunks of 1 byte, `0xF001` | 1,281 | 911 | 7 | 3,149 |
| 2,529 chunks, 4,092,524 bytes, `0xF001` (#348's padding, zero or `0xFF` fill) | 1,304 | 928 | 24 | 3,173 |
| 2,529 chunks, 4,092,524 bytes, `0x5B01` | 1,301 | 925 | 21 | 3,169 |

* **Every load starts on the same frame.**
  The chunk count is in `0x7FEC` on frame 1,271 in every arm, one frame after Enter goes down; until the load ends `0x2272`, `0x22B8` and the film clock read 0, so no tick is counted during it.
* **The timer keeps its phase through the load.**
  `0x22BA` reads the same on every frame in all ten runs, load and film, except 3 frames of one arm (2,529 one-byte chunks) where it reads one less; so an interrupt falls on the same emulated instant, to a frame, whatever the archive.
* **Archives that draw alike start on the same interrupt; the others start whole ticks later.**
  The arms that draw the own archive's pages ([`linking.md`](../makeone-exe/linking.md) § 7.2) start on interrupt 904, the 300-chunk arm though its flag is set a frame later; each arm that draws differently starts 3 to 24 interrupts later, and #348's padding and its `0xFF` refill, which draw alike, start on the same one.
  So the timer tick is the quantum of the start.
* **The start accounts for the last page's frame.**
  Each arm's last page is as many frames later as its start, converted at 70.087 / 50 frames per tick, to within one frame (3 ticks, 4.2 frames, against 5; 24 ticks, 33.6, against 34), and each equals the last-page frame of § 7.2's captures.
  On 12 of CTRY's padded-archive viewpoint pages the two arms' scenes are a tick apart at one tag (section 5); whether the later start does that by setting each frame's lag is open question 1.

_Source: [archives that draw alike start the film clock on the same timer interrupt](../../work/2026-11/722_playone-start-timer-tick/journal.md#2026-11-18-archives-that-draw-alike-start-the-film-clock-on-the-same-timer-interrupt)._

## Ruled out

- **A sort of the directory at load.**
  The index is built from runs in file order (section 1; [journal](../../work/2026-11/609_archive-load-start/journal.md#2026-11-18-the-loader-preloads-every-chunk-and-the-film-clock-starts-on-the-next-timer-tick)).
- **The interpolation fraction `0x22E0` as the carrier of the start's phase, at speed `0x100`.**
  At speed `0x100` it is a function of the film tick and the film's slices (section 4; [journal](../../work/2026-11/609_archive-load-start/journal.md#2026-11-18-the-loader-preloads-every-chunk-and-the-film-clock-starts-on-the-next-timer-tick)).
- **A frame counter or a reader of the per-frame deltas, by address, as the carrier of the start's phase.**
  The film step increments no word, `0x22DC` has no reader by address, `0x22BA` feeds input timing, and the deferred-call queue empties every frame (section 5; [journal](../../work/2026-11/723_frame-stepped-state/journal.md#2026-11-18-the-per-frame-call-steps-no-frame-counter)).
- **A film clock that starts at the same instant for every archive, or that counts during the load.**
  Archives that draw differently start whole timer ticks later, and no tick counts until the load ends (section 6; [journal](../../work/2026-11/722_playone-start-timer-tick/journal.md#2026-11-18-archives-that-draw-alike-start-the-film-clock-on-the-same-timer-interrupt)).
- **The probe's sweep from the previous frame as what changes CTRY's padded-archive pages.**
  Its results stayed the same at every probed frame of both arms, and no differing page differs at the shadow alone (section 5; [journal](../../work/2026-11/779_carried-draw-state/journal.md#2026-11-19-the-probes-results-held-at-every-probed-frame-pages-differ-at-the-propeller-and-the-viewpoint)).
- **The pair test `0x1588` as per-frame state.**
  It runs only while `DS:0x2282` is set, but the load image holds 0 there and the one instruction that writes it stores 0; its hit path is a bare `ret` (section 5; [journal](../../work/2026-11/723_frame-stepped-state/journal.md#2026-11-18-the-slot-pass-keeps-each-slots-previous-position-and-the-probe-sweeps-from-it)).
- **The camera's eye and angles carrying state between frames, in two DOSBox-X runs of CTRY.**
  The 24-byte camera record was equal in the own and padded runs at all 195 film-step ticks both drew (about half of each run's frames), and no viewpoint page decides a shift of 0 against the other archive's page; other view state, and frames at ticks only one run drew, were not compared (section 5; [live runs](../../work/2026-11/826_ctry-padded-viewpoint/journal.md#2026-11-24-hud-minus-scene-tick-varies-from-frame-to-frame-under-dosbox-x), [pages](../../work/2026-11/826_ctry-padded-viewpoint/journal.md#2026-11-24-on-12-viewpoint-pages-the-two-arms-scenes-are-one-tick-apart)).

## Open questions

1. How many ticks does the scene trail a capture's tag on each kept page, and are the 6 undecided viewpoint pages (67, 507, 804, 980, 991, 1167) a tick apart too (section 5)?
   The gap was measured only on DOSBox-X's frames; dating a capture's pages needs the film step's clock logged in the capture run itself, which would also show how a start whole ticks later (section 6) changes each frame's lag, and would settle the 3 near-flat pages (1145, 1189, 1212).
   The clock readings were found over direct calls only; the far, word-table and register calls from the frame were not read for a clock read, and whether the angle bank's later reading (`0x1DCA`) moves anything the viewpoint pages show was not checked.
2. What does the 63-chunk 4 MB arm's later start come from, given its small scan and walk counts: the emulator's charge for DOS reads, the allocator's evictions, or the heap's limit?
   Its load ends 5 frames after the own archive's and starts the film 3 ticks later (section 6).
3. Do the own chunks the `0x5B01` arm evicts at load, 8 by the node pool and any more for want of heap, change its pages beyond its start?
4. What happens when the index fills the region?
   As read, an index of more than 10,000 bytes is written past `0x7FEB` into the count word `0x7FEC`, and `0x4C0F`'s node count, `(0x7FEC - [0x0BD8]) / 10` unsigned, wraps (an index of exactly 10,000 bytes gives 0, which `loop` runs 65,536 times), so the free-list build writes far past the region; untested.
