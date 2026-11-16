# Journal: which archive property changes `PLAYONE`'s pages

## 2026-11-16: content does not count; chunk count, bytes and ids do once the film runs later

- **Question**: Which of chunk count, chunk size, ids and content, varied alone from the own archive or from #348's inert padding, changes the pages `PLAYONE` draws on `CTRY.FLM`, and how little is enough ([#482](https://github.com/neilsh/stunt-reel/issues/482); [`linking.md`](../../../research/makeone-exe/linking.md) open question 8)?
- **Method**: At `03356d6e` plus `pad-all --fill` (this branch), unpatched build, in `<data root>/bench/vault-ctry/482/unpatched/` (archive hashes in `arms.txt`, comparisons in `compare-r1.txt` to `compare-r3.txt`):
  - Every arm is #348's own `CTRY.ALL` (`cb0e26a8…`, 147 chunks, 124,925 payload bytes) plus `mise run pad-all -- --inert COUNT BYTES`, ids from `0xF001` (after every id the film has) unless `--first-id 0x5B01` (between its `0x1F` and `0x7F` ids), zero-filled unless `--fill 0xFF`.
  - One `capture-ref --film corpus/stuntisl/VAULT/CTRY.FLM --game-root <data root>/builds/unpatched --archive <arm>.ALL` each, sound stubbed by default, then `capture-compare --shift 2` against a fresh `own-1` or, for the ids and content arms, #348's `padding-1` (2,529 chunks, 4,092,524 bytes, `0xF001`, zeros).
  - "Last page" is the `emu_frame` (the emulator frame the page was dumped on) of the page at film tick 1,333, the last; the first page kept differs between arms, so it is not compared.
  - TOD confirms the content arm: #348's TOD padding (2,623 chunks, 4,138,716 bytes) refilled with `0xFF`, in `bench/vault-tod/482/unpatched/`.
  - Ten captures in all: eight arms and an own recapture on CTRY, one arm on TOD.
- **Result**:

  | Arm (added to own) | Compared with | Identical pages | Last page `emu_frame` |
  |---|---|---|---|
  | own, recaptured | #348 `own-1` | 121 of 121 | 3,139 (both) |
  | 1 chunk, 1 byte, `0xF001` | own | 121 of 121 | 3,139 |
  | 1 chunk, 1 byte, `0x5B01` | own | 121 of 121 | 3,139 |
  | 300 chunks, 300 bytes | own | 121 of 121 | 3,139 |
  | 1 chunk, 60,000 bytes | own | 121 of 121 | 3,139 |
  | 63 chunks, 4,092,524 bytes | own | 61 of 110 | 3,144 |
  | 2,529 chunks, 2,529 bytes | own | 39 of 106 | 3,149 |
  | 2,529 chunks, 4,092,524 bytes, `0x5B01` | padding | 56 of 109 | 3,169 against 3,173 |
  | 2,529 chunks, 4,092,524 bytes, `0xFF` | padding | 122 of 122 | 3,173 (both) |
  | TOD: 2,623 chunks, 4,138,716 bytes, `0xFF` | TOD padding | 129 of 129 | 3,279 (both) |

  - Palettes are equal on every paired tick of every pair. No differing page matches the other capture's page within 2 ticks, and every pair that differs also keeps different ticks (11 to 17 ticks only in one capture).
  - Against `own-1`, the ids arm has 32 of 105 pages identical. #348's captures fit the same pattern: props (2,529 chunks, 4,092,524 bytes of shapes) end at 3,167, padding at 3,173, own at 3,139; on TOD own ends at 3,246 and padding at 3,279.
  - Over 13 CTRY captures (these nine, #348's props and padding, #301's `superset-bare` and `own-2`), hashed page by page with a one-off script, two captures drew identical pages on every shared tick exactly when their last page fell on the same emulator frame: 3,139 (own twice and the four small arms, one hash), 3,167 (props and `superset-bare`, whose first page is at tick 1 against 2) and 3,173 (padding and its `0xFF` refill); 3,144, 3,149 and 3,169 hold one capture each.
- **Verdict**:
  - Content: rejected, on both films: zero and `0xFF` padding of one count, sizes and ids draw identical pages.
  - Chunk count, chunk bytes and ids: each changes pages varied alone, so none of them is the one property (adopted). 2,529 one-byte chunks (2.5 KB) change more pages than 63 chunks of 4 MB, and 300 one-byte chunks or one 60,000-byte chunk change none; the threshold lies between 300 and 2,529 chunks and between 60,000 and 4,092,524 bytes, not bisected.
  - Whether pages change tracks one quantity in every capture: how late the last page is drawn in emulator frames. More chunks or bytes push it later, and ids in `0x5B` push it 4 frames less than in `0xF0`. That the archive's load time sets when the film starts against the emulator's frame clock, and so which ticks get drawn, is a `[Supported Inference]`: no capture timed the load itself or the film clock's start.
- **Lives in**: [`linking.md`](../../../research/makeone-exe/linking.md) § 7.2, Ruled out, and open questions 5 and 8.
