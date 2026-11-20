# Journal: when `PLAYONE`'s film clock starts against the emulator frame

## 2026-11-18: archives that draw alike start the film clock on the same timer interrupt

- **Question**: Does the film clock start on the same emulated instant for archives that draw alike, and later by whole timer ticks for those that do not ([#722](https://github.com/neilsh/stunt-reel/issues/722); [`film-load.md`](../../../research/playone-exe/film-load.md) open question 2)?
- **Method**: At `75b9106a`, in a cloud session on dosbox-automation 0.85.1 (headless), unpatched build, in `<data root>/bench/vault-ctry/722/unpatched/`:
  - The own `CTRY.ALL` rebuilt with `mise run make-all -- --film corpus/stuntisl/VAULT/CTRY.FLM --game-root <data root>/builds/unpatched` (`cb0e26a8…`, #482's own), and the nine arms of [#482](../482_archive-property-pages/journal.md#2026-11-16-content-does-not-count-chunk-count-bytes-and-ids-do-once-the-film-runs-later) remade from it with `mise run pad-all -- own.ALL -o <arm>.ALL --inert COUNT BYTES [--first-id 0x5B01] [--fill 0xFF]` (hashes in `arms.txt`).
  - One run per arm of a one-off script, `trace_start.py` (kept beside the logs), that stages `CTRY.FLM` with the arm as captures do (sound stubbed), presses the dialog keys on the frames a capture does (Enter down on frame 1,270), and reads on every emulator frame from 1,200 until the film clock has held for 60 frames: `DS:0x22B8`, `DS:0x2272`, `DS:0x4896`, `DS:0x22BA`, the chunk count `DS:0x7FEC`, and whether the `A000` page changed since the previous frame.
    The logs are `trace-<arm>/trace.csv`; `summarise.py` turns them into `start-table.csv`.
  - The emulator cannot stop at an address, so the loader's return is read as the first frame on which `0x2272` is set: `0x0E42` sets it after `0x4B04` returns ([`film-load.md`](../../../research/playone-exe/film-load.md) § 4).
    `0x22BA` counts every timer interrupt, playback or not, and `0x22B8` counts the same interrupts while `0x2272` is set, so `0x22BA - 0x22B8 + 1` on any playing frame is the interrupt that was the film's tick 1.
    "First drawn page" is the first frame whose page changed with the film clock at 1 or more; "last page" is the first changed frame with the film clock at 1,333 or more, the tick of #482's last kept page.
- **Result**:

  | Arm (added to own) | Chunks | `0x2272` first set | First `0x22B8 = 1` | Tick 1 on interrupt | First drawn page (tick) | Last page frame | #482 last page |
  |---|---|---|---|---|---|---|---|
  | Nothing | 147 | 1,271 | 1,272 | 904 | 1,274 (2) | 3,139 | 3,139 |
  | 1 chunk, 1 byte, `0xF001` | 148 | 1,271 | 1,272 | 904 | 1,274 (2) | 3,139 | 3,139 |
  | 1 chunk, 1 byte, `0x5B01` | 148 | 1,271 | 1,272 | 904 | 1,274 (2) | 3,139 | 3,139 |
  | 300 chunks, 300 bytes | 447 | 1,272 | 1,272 | 904 | 1,274 (2) | 3,139 | 3,139 |
  | 1 chunk, 60,000 bytes | 148 | 1,271 | 1,272 | 904 | 1,274 (2) | 3,139 | 3,139 |
  | 63 chunks, 4,092,524 bytes | 210 | 1,276 | 1,276 | 907 | 1,276 (1) | 3,144 | 3,144 |
  | 2,529 chunks, 2,529 bytes | 2,676 | 1,281 | 1,282 | 911 | 1,284 (2) | 3,149 | 3,149 |
  | 2,529 chunks, 4,092,524 bytes (#348's padding) | 2,676 | 1,304 | 1,306 | 928 | 1,307 (2) | 3,173 | 3,173 |
  | the same, ids from `0x5B01` | 2,676 | 1,301 | 1,302 | 925 | 1,304 (3) | 3,169 | 3,169 |
  | the same, filled with `0xFF` | 2,676 | 1,304 | 1,306 | 928 | 1,307 (2) | 3,173 | 3,173 |

  - Every arm's chunk count is in `0x7FEC` on frame 1,271, so every load starts between frames 1,270 and 1,271; until `0x2272` is first set it reads 0 on every frame from 1,200, and `0x22B8` and `0x4896` read 0.
  - `0x22BA - 0x22B8` is constant from the first set frame to the end of the trace in every arm.
  - `0x22BA` reads the same on every frame in all ten traces, through the load and the film, except 3 frames of the 2,529-chunk 1-byte arm (1,591, 1,598, 2,616), where it reads one less than the own arm's.
  - The 300-chunk arm sets `0x2272` one frame later than the own archive, before the next interrupt; from frame 1,272 its `0x22B8`, `0x2272`, `0x4896` and page-changed columns equal the own arm's on every frame.
    The three one-chunk arms' equal the own arm's on every frame, and the `0xFF` refill's equal #348's padding's.
  - Tick 1 is 3, 7, 24, 21 and 24 interrupts later than the own archive's in the arms whose last page is 5, 10, 34, 30 and 34 frames later; at 70.087 / 50 frames per tick those tick shifts are 4.2, 9.8, 33.6, 29.4 and 33.6 frames, each within one frame of the shift seen.
  - Each arm's last page frame here equals #482's, from that issue's captures.
- **Verdict**: Adopted, on one film and one build.
  The five arms #482 found to draw the own archive's pages start the film clock on the same timer interrupt (904), one of them after a load that ended a frame later; the five that draw differently start whole interrupts later (3 to 24), and #348's padding and its `0xFF` refill, which draw alike, start on the same one (928).
  The timer kept its phase through every load to within a frame, so the same interrupt is the same emulated instant to that resolution.
  So the timer tick is the quantum of the start, and the start's interrupt accounts for each arm's last-page frame.
  Why a start whole ticks later changes what is drawn at a film tick is still open ([`film-load.md`](../../../research/playone-exe/film-load.md) open question 1).
- **Lives in**: [`film-load.md`](../../../research/playone-exe/film-load.md) § 6, § 4 and open question 2; [`linking.md`](../../../research/makeone-exe/linking.md) § 7.2; [`memory-map.md`](../../../research/playone-exe/memory-map.md) row `0x22BA`.
