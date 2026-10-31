# Investigation: plan items 6.1 (tear rule) and 6.2 (fade DAC), 2026-10-31

Nothing tracked was edited, staged or committed. Scratch scripts and raw outputs sit beside this file in the scratchpad
(`drv.py`, `drv2.py`, `tear.lua`, `tear2.lua`, `fade.lua`, `an2.py`, `fade_an2.py`, `t2_ctry.json`, `t2_intro.json`,
`fade.json`, `fade.avi`). All runs: the committed `capture` profile (dynamic core, 45,000 cycles), unpatched `PLAYONE.EXE`,
`CTRY.FLM` and `INTRO.FLM` staged by `staging.stage_play`.

## 1. Item 6.1: tears

### 1.1 Can a page dumped in the frame callback be torn? Yes. `[Supported Inference]` for the mechanism, `[Bounded Observation]` for the rate

* The callback is a Lua step on the emulation thread at an emulated-frame boundary, with the guest stopped between two
  instructions. The boundary is set by emulated time, not by PLAYONE. The `A000` update (`0x738C`, `repe cmpsw`/`rep movsw`
  then sprites, no retrace wait) takes tens of thousands of guest cycles, so a boundary can land inside it. Being inside the
  callback does not help: the callback sees whatever the copy had written so far.
* The game keeps two full composed pages (segments in `DS:0x22CA` and `DS:0x22CC`, here `0x336B` and `0x430B`, swapped every
  render). After a finished copy rows 0..191 of `A000` equal one of them (rows 192..199 are the button bar and cursor, drawn
  on `A000` directly). A page is torn when it has rows equal to only buffer A and rows equal to only buffer B. This needs no
  video: the game's own buffers are the ground truth. Spot check on 40 consecutive frames (row level): torn pages show a
  clean split, top rows from one buffer and the rest from the other, with one half-written row between.
* Measured over the whole film, every emulated frame, in the same Lua step that would dump the page (8-row bands, so tears
  smaller than about one band are missed; row level on `CTRY.FLM` found 71 torn against 66 by bands):

  | | frames | changed film frames torn | all frames torn | picked frames of reference `004` torn |
  |---|---|---|---|---|
  | `CTRY.FLM` | 1,908 | 4.1% (66 by bands, 71 by rows = 4.4%) | 3.5% | 3 of 121 by bands, 4 of 121 by rows |
  | `INTRO.FLM` | 5,384 | 2.9% (127) | 2.4% | 7 of 346 |

  Torn picked frames in `004` (emulated frame, tick, bands from buffer A / B out of 24): CTRY 1677 (1/3), 1816 (15/4), 1986
  (15/4), plus 1662 (2 rows of 192, row level only); INTRO 3382, 4604, 5053, 5068, 5269, 5284, 5794. The replay is
  deterministic: all 467 reference frames read the same film tick as `meta.json`, so the frame numbers are exactly the dumped frames.
  In every CTRY case frame f+1 is clean (one torn pair out of 71).
* The rate is a fraction of a frame spent copying, so it should scale as 1/cycles. The earlier REST snapshots at 7,000 cycles
  gave 10 of 97 (about 10%); 45,000 cycles gives 2.4 to 4%. That fits, but it was not swept.
* So the committed references `004` contain about 2 to 3% torn pages (10 frames), three or four of them large (30 to 100 rows).

### 1.2 The written rule is the wrong tool `[Supported Inference]`

The rule in `method.md` § 3.1 (match some video frame in f-2..f+4) needs an AVI per film and decodes ambiguously, because
the video is scanned out line by line while the emulator runs (a video frame can itself mix two renders). Measured in the
fade run below: 7 of 30 consecutive page/video pairs disagree by 300 to 2,300 pixels with the page read at the best alignment, which is
page-versus-scanout skew, not a bad page. The buffer test is cheaper (3 reads, 24 string compares only when the page matches
neither buffer), exact for the game's own buffers, and runs in the trace pass.

### 1.3 Recommendation: flag tears in the trace and let `pick` skip them (this is "retry at f+1", with no video)

Files and functions:
* [`luagen.py`](../../../python/stunt_reel/tac/luagen.py) `script()`: per frame read `DS:0x22CA`/`0x22CC`, read both buffers, test
  `a:sub(1,61440)` against each; only if it matches neither, compare 24 bands of 2,560 bytes (`tear2.lua` is the working
  draft). Add the result to the trace entry. Make the last field a bitmask (bit0 page changed, bit1 torn, bit2 working palette
  changed). Dump passes also emit `t<f>` for each dumped frame, computed in the same step as the page. Add the two buffer
  offsets to [`playone.py`](../../../python/stunt_reel/tac/playone.py) next to `WORKING_PALETTE_OFFSET`.
* [`plan.py`](../../../python/stunt_reel/tac/plan.py): `decode_trace` accepts 0..7 and fills `TraceEntry.torn`/`palette_changed`;
  `pick_every` and `pick_ticks` skip torn frames (the next changed frame wins, which is f+1 in practice); `decode_dumps`/
  `dump_pass` raise `PlanDivergence` if a dumped page was torn in its own pass (jitter films such as `COUNT.FLM`).
* [`framebuffer.py`](../../../python/stunt_reel/tac/framebuffer.py): record `torn_skipped` (count) in `meta.json` diagnostics. No format change otherwise.
* Tests: `tests/test_tac_plan.py` (trace decodes the mask; pick skips a torn frame and takes the next; dump of a torn page
  diverges), `tests/test_tac_luagen.py` (script reads both buffers, compares bands, has no per-byte loop; instruction-limit
  guard stays a live-only check), `tests/test_tac_framebuffer.py` if present.
* Docs: rewrite `method.md` § 3.1 "Tears" to the video-free rule; add § 4.5 to `capture-dosbox-automation.md` with the table
  above; tick 6.1 in the plan and drop "tears go unflagged" from Open Questions.

Risks: (1) the instruction budget. A row-level loop (192 iterations) died with "instruction limit exceeded" on both films; bands
fit 5,384 frames. (2) Bands miss tears under about 8 rows (1 of 71 on CTRY; 2 rows), harmless for scoring, but try 4-row bands. (3) Only
`CTRY`/`INTRO` were measured; a film that does not double-buffer through these two segments would read all pages as torn or
never torn; `mise run batch-parity` should log the torn rate per film as a smoke test. (4) Skipping moves a pick by one
frame, so reference ticks shift slightly versus `004`: promote only after a rescore.

Evidence that confirms it: recapture both films with the change and (a) the trace flags the same frame numbers as this
investigation (127 and 66), (b) zero dumped pages torn when re-tested at dump time, (c) `parity` on the new capture is no
lower; the previously torn picks (CTRY 1816, 1986) should gain SSIM on their tick. (d) The same torn-flag run at 7,000 cycles
should show about 6x the rate (confirms the 1/cycles reading).

## 2. Item 6.2: fade DAC and the palette lead

### 2.1 What the DAC does `[Bounded Observation]`, one fade, `CTRY.FLM`, 5 palette steps

Run: `capture_start()` at frame 1275, working palette read every frame 2680..2729, page 2690..2729, lossless AVI decoded with
ffmpeg, compared per palette half (indices < 128 against indices >= 128) with `round(v*255/63)`.

* The best page-to-video alignment is video frame f-1276 for the page read at f (total mismatch 8,450 pixels against 22,493 and
  51,013 for the alignments one frame later). In that alignment, for every one of the 5 steps (working palette first differs at
  frame c), the mismatch is exactly 0 for these models and no others:
  * k = f-c = 0: DAC is the old palette in both halves
  * k = 1: low half new, high half old (the mixed state, 5 of 5)
  * k = 2: new in both halves (some k=2 and k=3 frames show page-versus-video content mismatches instead)
  So the visible DAC for page f is `low = W(f-1)`, `high = W(f-2)`.
* This answers the palette-lead question: the working palette leads the low half by 1 frame and the high half by 2 frames.
  The two earlier notes (0 against about 2) differ only in which half and which video alignment they used. Testing the working
  palette at f-2 is right for the high half (exact), f-1 for the low half.
* One step is two bad frames (k = 0 and 1). CTRY steps came every 7 to 9 frames in this window.

### 2.2 How many frames in the references are exposed? `[Bounded Observation]`

* Palette differs from the previous captured frame: CTRY `004` 30 of 121 frames (31 distinct palettes, all steps change 194 to 238
  entries, always both halves); INTRO `004` 18 of 346 (16 distinct; four whole-palette cuts at ticks 763, 1528, 2057, 3488 and a
  14-step fade at 3500..3646). That count overstates it: a capture is wrong only at k = 0 or 1.
* From a fresh per-frame trace (ticks equal to `004` on all 467 frames), picked frames with the working palette changed at f
  or f-1: **0 of 121 (CTRY) and 0 of 346 (INTRO)**. CTRY has 64 palette-change frames and INTRO 65, but the page rarely changes
  in those two frames (15 of 64 at c and 2 at c+1 for CTRY; 2 of 65 and 0 for INTRO), and `pick` only takes changed pages. Only 17 of
  1,618 (CTRY) and 2 of 4,367 (INTRO) candidate frames are in the window.
* So in the current references the working palette is the DAC for every page. The scorer would only be wrong on a different
  film or stride.

### 2.3 Options

| | correctness | cost | capture format / scorer |
|---|---|---|---|
| (a) read the DAC in the callback | exact | no Lua API found: `dosbox.exe` exposes `mem_read`, `mem_read_word`, `key`, `mouse_*`, `capture_*`, `screen_*`, no port or palette reader; REST has `GET /io/port` (read only, cannot set the DAC read index, about 5.75 s per palette, not frame-locked) | would need no format change, but not available |
| (b) rebuild from W(f-1), W(f-2) | exact for this model, one fade measured | Lua keeps the last two palettes (one 768-byte compare per frame) and dumps them with the page, or the trace stores the change flag and a dump pass reads f-2 and f-1 | `palettes_NNNN.json` stays 256 RGB (the scorer's `read_palette` and `fade_level` take it as is); `meta.json` could add `"palette_source": "dac-model"` and `palette_lag` per frame; the Rust scorer is unchanged |
| (c) scorer | impossible without extra data: the scorer sees one final palette per frame and no history | | would need new per-frame fields in `meta.json` and Rust changes in `parity/mod.rs`/`compare.rs` |
| (d) skip frames at k = 0 or 1 | exact (the pages kept are right); costs about 1% of candidates | one more trace bit (above); no extra dumps | none |

### 2.4 Recommendation: (d) now, (b) only if a film needs the skipped frames

* Put the `palette_changed` bit in the same trace mask as the tear bit (section 1.3) and make `pick` skip frame f when it is set
  at f or f-1. Keep `"palette_source": "working"`, which is now true for every kept page, and add a diagnostic
  `palette_lag_skipped` count. No new files, no scorer change.
* If a later film (a long fade with a static scene, where every candidate page is in the window) leaves too few frames, add (b):
  `plan.dac_palette(w1, w2)` returning `low = w1[:384] + w2[384:]` and a dump of `c<f-1>`, `c<f-2>`; keep `palettes_NNNN.json`
  as the computed DAC and the raw working palette in an optional `working_NNNN.json`.
* Tests: `tests/test_tac_plan.py` (pick skips c and c+1, keeps c-1 and c+2); a doc test row in `method.md` § 3.1 replacing the
  "can pair with either palette" sentence with the measured lag.
* Risks: the model rests on one fade of one film (5 steps, 25 frames with exact zero mismatch). Not verified on an `INTRO`
  fade at this cycle count, and the two-frame lag could be cycle-dependent (it rests on retrace timing, 70 Hz, so should not be).
  Evidence that confirms it: rerun `fade.lua` on `INTRO.FLM` frames 6140..6400 and at a second cycle setting; expect the same
  0/1/2 pattern; add `INTRO` fade steps to `capture-dosbox-automation.md` § 4.5.

## 3. Open and not done

* The retry rule was not implemented (not asked, and tracked files were off-limits). The numbers above come from scratch Lua.
* Torn rate versus cycles was not swept; the fade DAC model was not run on `INTRO`; other films were not checked for the same two buffers.
* The effect of a torn reference on the SSIM score was not measured (the four large CTRY and many INTRO tears could be compared
  to their f+1 neighbours once the flag exists).
