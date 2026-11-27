# Journal

## 2026-11-27: Pair a page by the slot clock minus the ticks word

**Question.**
Does scoring each reference page against the render at `slot_clock - slot_ticks` (the state one slot pass back, rule `R` of [the plan](https://github.com/neilsh/stunt-reel/issues/1163#issuecomment-7210402368)) beat the tag pairing `film_tick - 1` through the real scoring path, and what do the repo's pins become?

**Method.**
The window pass of the capture harness now reads `DS:0x4220` and `DS:0x1C62` (Patch 3; `0x489A` and `0x22DC` unpatched) in the step that reads the page and writes them to `meta.json` as `slot_clock` and `slot_ticks`.
All seven reference films were recaptured with it (stubbed Patch 3, dosbox-automation, `mise run capture-ref -- --out`) and swapped into the data root.
The scorer pairs a page with render tick `slot_clock - slot_ticks + 1` (`CapturedFrame::render_tick`; the store keys state `T - 1` at `T`), and with its tag when a capture has no words.
Rendered on lavapipe (`mise run parity -- --software-only`) on the tree that adds the change, then `mise run parity-repin`.
The control is the same render scored by tag: the pins before the change, which equal the tag-paired scores.

**Result.**
Replay: every recapture is index-identical to its reference on every page (compared on rows 0..184, with equal palettes: CTRY 121, INTRO 347, LAND 103, BALLOON 108, TRAINTNL 112, BOMB 339, LOCATION 745), and the logged words equal the earlier scratch recaptures' on every page.
`slot_clock` is the tag or one below it on every page, and `global_tick` equals `film_tick` on every page of all seven films, so no kept page carries a speed other than one clock unit per tick or a pause.
[`pairs.csv`](pairs.csv) lists each page's words; the table counts them.

| Film | Pages | `slot_ticks` 0 / 1 / 2 / 3 | Render tick minus tag: -2 / -1 / 0 / +1 |
|---|---|---|---|
| LOCATION | 745 | 280 / 446 / 19 / 0 | 2 / 112 / 509 / 122 |
| INTRO | 347 | 142 / 182 / 20 / 3 | 13 / 50 / 186 / 98 |
| BOMB | 339 | 109 / 220 / 10 / 0 | 0 / 72 / 205 / 62 |
| CTRY | 121 | 43 / 78 / 0 / 0 | 0 / 2 / 102 / 17 |
| BALLOON | 108 | 46 / 62 / 0 / 0 | 0 / 3 / 83 / 22 |
| LAND | 103 | 44 / 54 / 5 / 0 | 1 / 7 / 82 / 13 |
| TRAINTNL | 112 | 17 / 91 / 4 / 0 | 0 / 33 / 79 / 0 |

The ticks word never exceeded 3 (INTRO's three pages) and never exceeded the clock; the harness's tag fallback was not used on any reference page.

Scores (`mean_ssim_scored`, lavapipe, `llvmpipe (LLVM 20.1.2, 256 bits)`; before is the pin on `main` at `cb3c78a`, which scores by tag):

| Film | Scored | Before | After | Change |
|---|---|---|---|---|
| LOCATION | 732 | 0.8979050 | 0.9168177 | +0.0189127 |
| INTRO | 209 | 0.9069152 | 0.9230571 | +0.0161419 |
| BOMB | 316 | 0.9110406 | 0.9216132 | +0.0105726 |
| LAND | 97 | 0.9341244 | 0.9418392 | +0.0077148 |
| TRAINTNL | 112 | 0.9159914 | 0.9220619 | +0.0060705 |
| CTRY | 114 | 0.9442895 | 0.9458880 | +0.0015985 |
| BALLOON | 107 | 0.9080578 | 0.9093599 | +0.0013021 |

The scored-frame-weighted gain over the seven films' 1,687 scored frames is +0.0132; the unweighted film mean gains +0.0089.
The plan's offline figures on `cb3c78a` ([results comment](https://github.com/neilsh/stunt-reel/issues/1163#issuecomment-7210719075)) agree within 0.0001 on six films (they leave out the first and last page and tick 12, so their page counts are one or two lower); TRAINTNL is +0.0061 here over 112 scored pages against +0.0056 over 110 there.
IoU rises on all seven films, by 0.0001 to 0.0016.

The variants the plan names, scored through the same scorer by giving each page's state the variant's value ([`variants-output.txt`](variants-output.txt); the HUD ticks and the lead-frame logs they need were in the thread's scratch row files, not in `meta.json`, so they cover the five films with those logs, not BOMB or LAND; the mean over the pages scored in all four arms):

| Film | Pages | Tag | `R` | `R_hud` (`h - dct`) | `R_prev` |
|---|---|---|---|---|---|
| LOCATION | 732 | 0.8979 | 0.9168 | 0.9142 | 0.9139 |
| INTRO | 209 | 0.9069 | 0.9231 | 0.9206 | 0.9196 |
| CTRY | 114 | 0.9443 | 0.9459 | 0.9438 | 0.9442 |
| BALLOON | 107 | 0.9081 | 0.9094 | 0.9092 | 0.9092 |
| TRAINTNL | 111 | 0.9167 | 0.9223 | 0.9223 | 0.9223 |

`R` is above both on four of the five and equal to them at four places on TRAINTNL; BALLOON's margin is 0.0002.
Neither is adopted; they were fixed as variants before the run.

**Verdict.**
Adopted: `R`, by the plan's bar (the gain on every film, the seven-film frame mean far above the +0.004 floor).
The speed check is a proxy: `global_tick` equal to `film_tick` says the film clock advanced as the timer did at each kept page, not that a speed word was read; a film that changed speed mid-run between kept pages would still pass if it changed back.
The `dct` table above is counts only; the cause of its values stays `[Hypothesis]`.
Not run here: the GPU-class check, which needs Legion.

**Lives in.**
[`capture.md` § 4](../../../research/playone-exe/capture.md#4-observed-results), [`probes.md` § 6](../../../research/parity/probes.md#6-timing-hypotheses-post-hoc-retime), [`evidence-limits.md` § 3](../../../research/parity/evidence-limits.md#3-what-is-not-yet-evidence), [`film-load.md` § 5](../../../research/playone-exe/film-load.md#5-what-a-drawn-frame-steps) and [ADR 0057](../../../docs/adr/0057-a-captured-page-is-paired-by-the-slot-pass-before-the-one-that-drew-it.md).
