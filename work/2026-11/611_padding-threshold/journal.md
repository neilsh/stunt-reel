# Journal: how much `.ALL` padding changes `PLAYONE`'s pages

## 2026-11-18: pages change once the film runs a whole film tick late

- **Question**: Between the arms of [#482](../482_archive-property-pages/journal.md#2026-11-16-content-does-not-count-chunk-count-bytes-and-ids-do-once-the-film-runs-later), where do `PLAYONE`'s pages on `CTRY.FLM` start to change, for one-byte chunks (300 to 2,529) and for bytes in a few chunks (60,000 to 4,092,524), and do the changes come in steps of the last page's `emu_frame` moving by one frame ([#611](https://github.com/neilsh/stunt-reel/issues/611))?
- **Method**: In a cloud session (dosbox-automation, headless), at `6ef27300` and `15a615e` (no change to `pad-all`, `capture-ref` or `capture-compare` between them), unpatched build, in `<data root>/bench/vault-ctry/611/unpatched/`:
  - `make-all --game-root <data root>/builds/unpatched` rebuilt the own `CTRY.ALL`, byte-equal to #348's (`cb0e26a8…`), so the unpatched tree boots in a cloud session.
  - Each arm is the own archive plus `pad-all --inert COUNT BYTES` (ids from `0xF001`, zeros), on two axes: COUNT one-byte chunks (300, 350, 362, 368, 375, 400, 450, 500, 550, 600, 900, 1,200, 1,500, 1,800, 2,100, 2,529), and 63 chunks of BYTES in all (60,000, 100,000, 125,000, 131,250, 137,500, 150,000, 200,000, 275,000, 350,000, 425,000, 500,000, 750,000, 1,000,000, 2,000,000, 3,000,000, 4,092,524); a coarse grid, then bisection.
  - One `capture-ref --archive <arm>.ALL` each (sound stubbed by default), plus the own archive twice (`own-1`, `own-2`): 34 captures. `capture-compare --shift 2` against `own-1` (`compare.txt`), and one-off scripts beside the captures: page hashes for every pair (`pairs.py`, `pairs.txt`), captures grouped by page hashes and by their `(film_tick, emu_frame)` sequence (`classes.py`, `classes.txt`), and each capture's mean `emu_frame` offset against `own-1` on shared ticks (`offset.py`, `offsets.txt`), converted to film ticks at 70.086 emulator frames (DOSBox's Mode 13h rate) per 50 film ticks a second.
- **Result**:
  - The cloud repeats #482's local captures: `own-2` matches `own-1` on all 121 pages, and the 300-chunk, 2,529-chunk, 63 × 60,000 and 63 × 4,092,524 arms give #482's identical-page counts and last-page frames (121 of 121 at 3,139 twice, 39 of 106 at 3,149, 61 of 110 at 3,144); the pages were not compared with the local captures byte for byte.
  - The 34 captures fall into 9 classes. Within a class every pair draws identical pages on every shared tick (105 pairs); across classes no pair does (456 pairs). Grouping by the `(film_tick, emu_frame)` sequence of the kept pages gives the same 9 classes.

    | Delay against own (mean offset) | Arms | Last page frame | Identical pages with own |
    |---|---|---|---|
    | 0 ticks (0 frames) | own twice; 300, 350, 362 chunks; 63 chunks of 60,000 to 131,250 bytes (4 arms) | 3,139 | 121 of 121 |
    | 1 tick (1.350 frames) | 368 chunks; 63 chunks of 137,500 and 150,000 bytes | 3,141 | 39 of 103 |
    | 1 tick (1.356 frames) | 375 to 600 chunks (6 arms); 63 chunks of 200,000 to 500,000 bytes (5 arms) | 3,141 | 36 of 104 |
    | 2 ticks (2.802) | 900 chunks | 3,142 | 39 of 106 |
    | 3 ticks (4.200) | 63 chunks of 750,000 to 4,092,524 bytes (5 arms) | 3,144 | 61 of 110 |
    | 4 ticks (5.632) | 1,200 and 1,500 chunks | 3,145 | 37 of 106 |
    | 5 ticks (6.992) | 1,800 chunks | 3,146 | 109 of 118 |
    | 6 ticks (8.383) | 2,100 chunks | 3,148 | 36 of 107 |
    | 7 ticks (9.811) | 2,529 chunks | 3,149 | 39 of 106 |

  - Thresholds: pages change between 362 and 368 one-byte chunks, and between 131,250 and 137,500 bytes in 63 chunks. Every mean offset is within 0.04 film tick of a whole number (0.96 to 7.00 ticks), and every arm that changed pages is at least one tick late. Bytes in 63 chunks take the delay from 1 tick (500,000) to 3 (750,000), and 750,000 to 4,092,524 bytes all sit at 3.
  - The last page moves 2, 3, 5, 6, 7, 9 and 10 frames for delays of 1 to 7 ticks, never 1 frame; and the two 1-tick classes share last frame 3,141 yet differ in 29 of 113 pages.
    They draw 111 of those 113 ticks on the same emulator frame, and 27 of the 29 differing pages are drawn at the same tick on the same frame; their kept ticks differ by one in 8 places (12, 89, 145 … against 13, 90, 144 …).
  - Classes 5 ticks apart (7.009 frames, nearly a whole number) share most pages: 109 of 118 (0 and 5 ticks), 100 of 113 (the 375-chunk class and 6), 110 of 117 (2 and 7), 79 of 111 (the 368-chunk class and 6). The two 1-tick classes share 84 of 113. Every other pair of classes shares 36 to 61 pages of 100 to 111.
- **Verdict**:
  - Thresholds: adopted, CTRY unpatched only: 368 one-byte chunks and 137,500 bytes in 63 chunks are the smallest arms tried that change pages, 362 and 131,250 the largest that do not.
  - Steps of one frame in the last page: rejected. The drawn frames come late by whole film ticks, 20 ms or 1.40 frames, and pages change at the first tick; and the step from the 368-chunk to the 375-chunk class changes pages with the last page on the same frame.
  - #482's rule that two captures draw alike exactly when their last page falls on the same frame: rejected by the two 1-tick classes. In these 34 captures, two draw alike exactly when every kept page falls on the same emulator frame.
  - What is drawn at a film tick as a function of that tick and the frame it is drawn on: rejected, by the 27 pages of the 1-tick classes. What differs between them is which ticks were drawn before; that the drawing carries state from one drawn frame to the next is a `[Hypothesis]` ([`film-load.md`](../../../research/playone-exe/film-load.md) open question 1).
  - That the film clock starts whole timer ticks later as the load grows, and that what is drawn follows the clock's phase against the 70 Hz frame (5 ticks apart is nearly 7 frames, and such classes share most pages): `[Hypothesis]`; the offsets are from kept pages, not a log of the clock's start.
- **Lives in**: [`linking.md`](../../../research/makeone-exe/linking.md) § 7.2, Ruled out, and open question 8.
