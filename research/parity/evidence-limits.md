---
summary: "Lists what the parity scores do not yet establish: film coverage, metric caveats, the non-deterministic reference, GPU and lavapipe differences, what a render's memory goes to, and what dosbox-automation captures can and cannot show."
---

# Parity Method: What Is Not Yet Evidence

The limits on reading a parity score, kept beside the method in [`method.md`](method.md) and the metric behaviour in [`metric-bench.md`](metric-bench.md).
Terms are those of [`GLOSSARY.md`](../../GLOSSARY.md).

## 3. What is not yet evidence

* **Films covered.**
  Seven films are reference films (`references.toml`); rows before 2026-11-07 are `CTRY.FLM` alone unless they say otherwise, and no row says anything about films outside those seven (`[Unknown]`).
* **Metric caveats.**
  SSIM is sensitive to a misplaced thin object and to flat-area luminance; mask IoU is blind to shading and to anything inside the mask.
  A disagreement between the two is a prompt to read the sheets, not a verdict (`[Supported Inference]`).
* **End hold.**
  The 18 `CTRY.FLM` end-hold captures are the faded tail (fade level 0 at tick 1337), not the scene: unfaded renders pulled the 140-frame mean to 0.495, and with the modelled fade it is 0.667.
  The fade floor excludes them; quote `mean_ssim_scored` with its scored-frame count.
* **Fade mechanism.**
  The fade is authored as film variable 14 (palette brightness) and applied by `PLAYONE` to palette entries 0–239 ([`../playone-exe/palette-fade.md`](../playone-exe/palette-fade.md), Q-FLM-09).
  The renderer applies vars 13–15 itself and reproduces the live DAC exactly in 128 of 140 `CTRY.FLM` captures; the other 12 are one 6-bit level off, which is clock jitter and rounding, not a lag ([`palette-fade.md` § 5](../playone-exe/palette-fade.md)).
  Raw IoU over all frames falls in the near-black tail, where the render shows no shapes to mask; those frames are not scored.
* **Sparse sampling.** 140 captures over 1,342 ticks is roughly one frame per 11 ticks (`[Bounded Observation]`); motion between samples is unobserved.
* **The reference is not deterministic at a fixed tick (`[Bounded Observation]`, 2026-10-22, four DOSBox-X capture sets of `CTRY.FLM`, one machine).**
  On frames sharing an exact `film_tick` the sets agreed with each other at SSIM 0.939 to 0.997; the cause is not identified (`[Hypothesis]`: state that is not the film clock, such as the cursor or wall-clock effects).
  A parity score above about 0.95 cannot be told from that noise, so the 0.88 and 0.90 gates are reachable but the ceiling is not 1.0.
  The sets also started 9 or 10 ticks in and drifted by 0 to 2 ticks from each other, so always match on `film_tick`, never by ordinal across sets.
  Our headline moved by 0.006 across the four sets (0.001 after the unlit change); the same capture set and render give identical scores.
  Quote SSIM to two decimals and treat differences under 0.01 between runs as noise only when the capture set differs.
  _Source: [2026-10-22: recapture variance of four CTRY.FLM capture sets](../../work/2026-11/distill-method/journal.md#2026-10-22-recapture-variance-of-four-ctryflm-capture-sets)._
* **The 0.002 adoption floor is a policy bound, not a noise model (`[Bounded Observation]`, 2026-11-07, `740c608`).**
  Three binaries of one revision rendered all seven reference films to byte-identical render trees on one machine and GPU (RTX 4070), as the bench's build floor ([§ 2.2](metric-bench.md#22-the-metric-bench)) found on `CTRY.FLM`.
  The 2026-10 spread of 0.7706 to 0.7718 on `CTRY.FLM` ([`probes.md`](probes.md) § 5) has not recurred; its cause is unknown.
  Recapture noise (§ 2.2.1) is the larger term.
  _Source: [2026-11-07](../../work/2026-11/distill-method/journal.md#2026-11-07-recapture-noise-the-build-floor-and-lavapipe); [2026-11-15](../../work/2026-11/265_lavapipe-parity/journal.md#2026-11-15-lavapipe-beside-the-gpu-on-one-crates-tree)._
* **The target-frame bounds are policy bounds too, set by rescoring known cases (`[Bounded Observation]`, 2026-11-12, one run per case).**
  The adoption rule's +0.010 target bar, 0.025 per-frame bound and 3-frame minimum ([`loop-rules.md`](../../.agents/skills/improving-render-parity/loop-rules.md#adoption-rule)) were settled from three adopted changes (#429, #431, #434), the `POLY_EDGES=1` variant #426 set aside for cost, three rejected changes rebuilt from their journals (two #255 depth gates, #407's late sprite pass) and one planted fault (actors removed).
  Two #430 variants were dropped: one rebuild missed #430's scores, and the other was not rebuilt.
  What each bound rests on:
  * **Film-mean bar, 0.002.**
    It rejects both #255 gates, each falling by more than 0.002 on four films; none of the three adopted changes falls by 0.002 on any film. #407's late sprite pass passes it.
  * **Per-frame bound, 0.025 in SSIM, target frames only.**
    It is the midpoint between the worst target frame of a change not rejected (-0.0164, `POLY_EDGES=1`) and the mildest fall of #407's late sprite pass on its three `CTRY` target frames (-0.0345; its worst, tick 871 at -0.0639, is the frame #407's rejection already rested on).
    That is a measured separation on the three `CTRY` target frames of one rejected change, the only rejected change with targets, and the bound alone rejects it.
    The planted fault falls by at least 0.045 on every target frame.
    Counts of falling frames over whole films do not separate the cases (#434 adopted with 18 frames down by more than 0.010 over seven films, while the planted fault, confined to 20 frames, had 20), so they are listed and not bounded.
  * **Target bar, +0.010 in index agreement.** #431's target mean rose by +0.0193 in index agreement while its SSIM fell by 0.0011 ([`metric-bench.md`](metric-bench.md) § 2.2).
    No case was heuristic, so the heuristic target branch, with its per-range and majority conditions, has judged no case it would run on; #431 would fail the majority condition (1 of its 3 target frames rose).
    The bar was not tuned at its margin, and its first heuristic round is its field test.
  * **Minimum, 3 scored target frames.** #431 sits on it, so a verdict at the minimum is thin evidence; #429's own two named ticks fall below it.
  * **Not tested.**
    Only the actors-removed fault was re-scored, and it lowers SSIM, so no SSIM-raising fault and no false adoption of that kind has been tested.

  _Source: [spike results for A1–A3](../../work/2026-11/440_target-frame-adoption/journal.md#2026-11-12-spike-results-for-a1a3), [R6 scored](../../work/2026-11/440_target-frame-adoption/journal.md#2026-11-12-r6-scored-a-rejected-case-with-targets), [third-round results](../../work/2026-11/440_target-frame-adoption/journal.md#2026-11-12-third-round-results-r4-and-r5-are-valid-rejected-cases), [a third review](../../work/2026-11/440_target-frame-adoption/journal.md#2026-11-12-a-third-review-the-majority-condition-and-claims-narrowed)._
* **Render start-up is the GPU instance (`[Bounded Observation]`, 2026-11-06, one Windows machine, RTX 4070).**
  An every-backend wgpu instance took about 1.9 s of a headless render.
  The offscreen path tries a Vulkan-only instance first (`OFFSCREEN_BACKENDS` in `renderer/adapter.rs`), going on to every backend when Vulkan finds no adapter or only a CPU one, which it keeps if no backend has hardware.
  A one-tick CTRY render then took a median 1.39 s against 3.15 s (six alternating runs each); a full CTRY render was byte-identical either way.
  A GL-only instance picked the integrated GPU.
  _Source: [2026-11-06](../../work/2026-11/distill-method/journal.md#2026-11-06-render-start-up-parallel-runs-and-the-references-archive)._
* **Parallel parity runs are GPU-bound (`[Bounded Observation]`, 2026-11-06, `48f5d49`, 16 threads, RTX 4070 Laptop GPU).**
  A render cost about 300 MiB of RAM and 200 MiB of VRAM whatever the film's length (`BOMB.FLM` and `LOCATION.FLM` as much as CTRY); LOCATION's world has grown about eightfold since, and its render's memory with it, from 258 to 1,004 MiB on lavapipe (next item).
  Render-and-score pairs per second rose from about 0.2 at one job to 0.8 at 8 and 1.0–1.16 at 16, noisy at 32 with the GPU saturated, so `mise run parity` and `mise run sweep` default `--jobs` to 8; `--jobs 1` and `--jobs 8` print identical scores.
  _Source: [2026-11-06](../../work/2026-11/distill-method/journal.md#2026-11-06-render-start-up-parallel-runs-and-the-references-archive)._
* **A LOCATION render's memory is mostly its world mesh (`[Bounded Observation]`, 2026-11-18 and 2026-11-20: Linux figures on `56a530d`, a cloud session's lavapipe, Ubuntu's Mesa 25.2.8 with LLVM 20.1.2; GPU figures on `4c43baa` and `2ecbad1`, an RTX 4070 Laptop).**
  CTRY's world is 20,044 vertices and its render peaks at 139 MiB; LOCATION's is 6,702,496 vertices, 7,488,138 indices and 12,861,990 outline indices in one chunk, and its render of ticks 12-120 peaked at 1,004 MiB.
  At `48f5d49` LOCATION's world was 795,172 vertices and 6,463 static props against 56,395 now, and the same render on the same lavapipe peaks at 258 MiB.
  On Windows (2026-11-16, [#645](https://github.com/neilsh/stunt-reel/issues/645)) LOCATION ticks 12-120 peaked at 982 MB working set and 1,078 MB private on mesa-dist-win 25.2.8, and 942 MB and 1,443 MB on the RTX 4070.
  Of LOCATION's peak, the built scene held 301 MiB, 253 MiB of it the world mesh's CPU copy; opening the device and uploading the shapes and sprites added 82 MiB, the outline list `plan_edges` builds 61 MiB, and the staging copies `write_buffer` makes of the world's vertex, index and outline buffers 257 MiB.
  Lavapipe fills the device buffers' pages when those copies run, at the first submit, so the first frames held the CPU mesh, the staging copies and the device buffers at once (`[Supported Inference]`: a submit and wait forced straight after the upload raised the high-water mark from 749 to 944 MiB, the upload's 687 MiB plus the buffers' 257).
  `run_headless` frees the CPU mesh after upload, before the first submit (`FilmScene::release_world_mesh`): LOCATION's peak falls to 749 MiB and its steady RSS from about 823 to 563 MiB, with the render stores byte-identical over LOCATION ticks 12-300 and CTRY's captured ticks.
  The world's three device buffers, 257 MiB, are then about half of LOCATION's steady RSS.
  With the mesh freed (`[Bounded Observation]`, `77a9a49`, 2026-11-19, `--report-memory` on Windows), the same render peaked at a 715 MiB working set on mesa-dist-win 25.2.8 and 603 MiB on the RTX 4070; the built scene held 289 MiB on both, and the working set after the last frame was 513 MiB on lavapipe and 233 MiB on the GPU ([`measure-a-renders-memory.md`](../../docs/howto/measure-a-renders-memory.md) § 3).
  At #706's own pair on that GPU, `4c43baa` (its parent) against `2ecbad1` (its merge, `crates` `71486d7` and `a00c4e7`), three runs each, LOCATION ticks 12-120 peaked at about 598 MiB working set and 1,297-1,303 MiB private before the change and about 598 MiB and 1,289-1,291 MiB after it; CTRY's captured ticks 14-1333 at 161 MiB and 343 MiB before and 160 MiB and 341 MiB after.
  Equal peaks at both commits put the peak before `release_world_mesh` runs: the peak working set does not move (about 598 MiB), while peak private falls about 10 MiB, from 1,297-1,303 to 1,289-1,291 MiB, about 0.7 GiB above the working set on both.
  After the upload LOCATION's working set is about 483 MiB before the change and about 227 MiB after it, a drop of about 256 MiB, about the CPU mesh's 253 MiB.
  The whole GPU's `nvidia-smi` used memory rose from idle to 520 MiB during LOCATION's render and 200 MiB during CTRY's, the same at both commits (200 ms sampling).
  In that pair the render stores are byte-identical: all seven films' `frames.zst`, `layers.zst` and `palettes.zst` (21 files) and their scores match, and every report named the RTX 4070 Laptop GPU.
  The 2026-11-16 pair (942 MB working set and 1,443 MB private) is not reproduced at `4c43baa`, where three runs read about 598 MiB and 1,297-1,303 MiB; the 603 MiB peak the flag read at `77a9a49` agrees with this pair's, and the gap to 942 MB is not attributed.
  Linux lavapipe's 749 and 556 MiB are `VmHWM` and `VmRSS` on another Mesa build (LLVM 20.1.2 against 21.1.7), so the gaps to them are not attributed.
  For CTRY, one run of a build with `VmRSS` and `VmHWM` probes at `9c9c6a5` (its captured ticks 14-1333) peaked at 144 MiB, against the 139-140 MiB of the unprobed runs at `342cc7a` (`56a530d` plus the freeing change), a gap not explained: RSS is 9 MiB once the scene is built, opening the device and uploading the shapes, sprites and world adds 97 MiB, and the frames that follow 38 MiB more.
  Splitting one film's ticks across processes, or across wgpu devices in one process, was set aside ([#645](https://github.com/neilsh/stunt-reel/issues/645)) on the assumption that one queue per device serializes in-process work and each process repeats the whole memory cost while parity already runs films in parallel (`--jobs`).
  Later `#918` measurements on `LOCATION` ticks `50..=649` (`[Bounded Observation]`, 2026-11-21) refine that note: two in-process `VkDevice`s parallelize partly (`2.21` cores on Windows `mesa-dist-win 25.2.8` and `2.07` cores on Ubuntu 24.04 `mesa-vulkan-drivers 25.2.8`), yet four in-process devices lose to four child processes (`6,727.8` ms shared / `5,451.2` ms separate instances vs `4,344.1` ms loop on Windows; regresses to `15,890.6` ms / `13,128.4` ms vs `7,650.1` ms on Ubuntu) while saving `257.5..299.7 MiB` polled RSS across 4 workers because each extra lavapipe device adds `751..796 MiB` RSS, so chunked child processes are preferred over in-process device pooling when sharding one long film ([`lavapipe-render-time.md`](lavapipe-render-time.md#5-multi-vkdevice-in-process-versus-child-processes)).
  Method: `stuntreel --headless … --report-memory` prints the resident set after each stage and the peak ([`measure-a-renders-memory.md`](../../docs/howto/measure-a-renders-memory.md)).
  _Source: [LOCATION's world at `48f5d49`](../../work/2026-11/645_world-mesh-memory/journal.md#2026-11-18-locations-world-at-48f5d49), [where a LOCATION render's memory goes on lavapipe](../../work/2026-11/645_world-mesh-memory/journal.md#2026-11-18-where-a-location-renders-memory-goes-on-lavapipe), [freeing the world mesh after upload](../../work/2026-11/645_world-mesh-memory/journal.md#2026-11-18-freeing-the-world-mesh-after-upload), [where a CTRY render's memory goes](../../work/2026-11/645_world-mesh-memory/journal.md#2026-11-18-where-a-ctry-renders-memory-goes-on-lavapipe), [`--report-memory` on Windows](../../work/2026-11/769_windows-render-memory/journal.md#2026-11-19---report-memory-on-windows-gpu-and-lavapipe), [the GPU's memory and byte-identity after freeing the world mesh](../../work/2026-11/707_gpu-free-world-mesh/journal.md#2026-11-20-the-gpus-memory-and-byte-identity-after-freeing-the-world-mesh), [multi-VkDevice in-process versus child processes](../../work/2026-11/918_lavapipe-render-time/journal.md#2026-11-21-multi-vkdevice-in-process-versus-child-processes-on-windows-and-linux-mesa)._
* **A reference pins its archive.**
  Each row pins `all_sha256`, and the render and `capture-ref` resolve the `.ALL` by it ([ADR 0037](../../docs/adr/0037-a-reference-pins-its-archive.md)).
  Before it, CTRY and INTRO rendered `.ALL` copies other than the ones their captures recorded and scored the same to four decimals, so no recorded score was affected (`[Bounded Observation]`, 2026-11-06, `48f5d49`).
  _Source: [2026-11-06](../../work/2026-11/distill-method/journal.md#2026-11-06-render-start-up-parallel-runs-and-the-references-archive)._
* **Lavapipe and GPU (`[Bounded Observation]`, 2026-11-07, `aa76d1e`).**
  The same commit scored CTRY and INTRO 0.23 lower on Mesa lavapipe than on the RTX 4070 machine, with identical IoU and scored counts: lavapipe wrote other palette indices inside the same silhouettes, from its software clipper interpolating the `linear` shade varying to NaN on near ground polygons (`[Supported Inference]`).
  With the guard in `fragment_index`, lavapipe scores less than the 0.002 adoption margin from those GPU figures.
  On `crates` `52d84e6` (2026-11-15, `[Bounded Observation]`) the guard leaves the RTX 4070's index planes byte-identical (20,621 ticks), and local lavapipe (mesa-dist-win 25.2.8) scores within the margin of the GPU on all seven reference films; the backends still differ by 23 to 147 index-plane pixels per tick on average, the largest region `lavapipe.md` section 5 names being 5,626 prop-layer pixels at LOCATION 2859, Gouraud polygons the clipper breaks drawn flat among them.
  By #265's criterion, mesa-dist-win 25.2.8 rows stand in for GPU rows on those films; CI's lavapipe is not yet compared ([`lavapipe.md`](lavapipe.md) sections 4 and 5, [#265](https://github.com/neilsh/stunt-reel/issues/265)).
  Mechanism, evidence and candidate fixes: [`lavapipe.md`](lavapipe.md).
  _Source: [2026-11-07](../../work/2026-11/distill-method/journal.md#2026-11-07-recapture-noise-the-build-floor-and-lavapipe); [2026-11-15](../../work/2026-11/265_lavapipe-parity/journal.md#2026-11-15-lavapipe-beside-the-gpu-on-one-crates-tree)._
* **One captured palette is not like the others (`[Bounded Observation]`).**
  In the `INTRO.FLM` set, ordinal 69 (tick 1516) carries a palette with 126 of 253 entries live: indices 0 to 135 black while 136 to 255 keep their normal colours, between two normal neighbours.
  The only other blacked-out palettes in either set are the end-fade tails (`CTRY` ordinals 122 to 140, `INTRO` 213), which the fade floor excludes.
  The frame agrees with the render on 0.642 of its palette indices yet scores SSIM 0.019, which only a palette difference explains, since the render's surface choice (sand, index 91) is the capture's.
  Whether `PLAYONE` blanks its palette for one retrace during a page switch, or the harness read a half-updated palette, is `[Unknown]`; the frame stays scored and the anomaly is recorded rather than repaired.

## 3.1 Captures from dosbox-automation

`[Bounded Observation]`, 2026-10-30.
`capture-ref` plans a run rather than stepping a halted guest ([`../playone-exe/capture-dosbox-automation.md`](../playone-exe/capture-dosbox-automation.md)).
Two consequences for reading a score:

* **Palette.**
  A page's palette is the working palette at `DS:0x2768` (6-bit, expanded as `round(v * 255 / 63)`), not a DAC read.
  `PLAYONE` writes the DAC in two retrace-gated halves, so the DAC shown with the page read at frame *f* is the working palette of *f* - 1 in its low half (indices below 128) and of *f* - 2 in its high half (one `CTRY.FLM` fade, five steps, exact; [`capture-dosbox-automation.md`](../playone-exe/capture-dosbox-automation.md) § 4.5).
  It equals the working palette of *f* unless the palette changed at *f* or *f* - 1, and `pick` skips those two frames ([`plan.usable`](../../python/stunt_reel/tac/plan.py)), so every kept page's working palette is its DAC.
  `meta.json` counts the palette steps (`palette_steps`).
* **Tears.**
  The page is read between emulated frames without waiting for retrace, so it can land inside `PLAYONE`'s copy of a composed page to `A000`.
  The game keeps two composed pages (segments at `DS:0x22CA` and `0x22CC`), and rows 0–191 of a finished page equal one of them; a page whose 8-row bands match only one in some places and only the other in others is torn.
  The trace tests every frame this way and `pick` passes over a torn frame, so the next changed frame (*f* + 1 in practice) takes its place, and a page whose own dump pass marks it unusable (replay jitter can move a tear onto it) is dropped.
  The earlier rule, matching a video frame in *f* - 2 to *f* + 4, needed an AVI per film and decoded ambiguously.
  `meta.json` counts torn frames (`torn_frames`).

The first plan-run capture of `CTRY.FLM` agreed with the DOSBox-X reference on 0.951 of the first 60,000 page indices over the 37 ticks the two share within one tick (8 exactly), with five frames under 0.90: at the low edge of the 0.95 to 0.99 index equality between that reference's own capture sets (section 3).
_Source: [2026-10-30: the first plan-run capture of CTRY.FLM](../../work/2026-11/distill-method/journal.md#2026-10-30-the-first-plan-run-capture-of-ctryflm)._

## Ruled out

* **glibc's malloc arenas, or the world `Vec`s' spare capacity, as a share of a render's memory.**
  `MALLOC_ARENA_MAX=2` left LOCATION's peak and steady RSS unchanged.
  The spare capacity, 8,388,608 entries against 6.7 and 7.5 million used, is grown into by reallocation and never written, so it should not be resident (`[Supported Inference]`: the 252.6 MiB that freeing the mesh released cannot tell the written arrays and nodes from the full capacity) ([journal](../../work/2026-11/645_world-mesh-memory/journal.md#2026-11-18-where-a-location-renders-memory-goes-on-lavapipe)).
* **A renderer change after `48f5d49` that moves the GPU score.**
  The RTX 4070 machine scores the logged figures at `aa76d1e`, the commit lavapipe scored 0.23 lower (section 3).

## Open questions

1. The remaining lavapipe questions: [`lavapipe.md`](lavapipe.md) Open questions ([#265](https://github.com/neilsh/stunt-reel/issues/265)).
2. What the ~0.7 GiB of private bytes above a GPU render's working set holds, and why the 2026-11-16 pair read 942 MB working set and 1,443 MB private where #706's pair reads about 598 MiB and 1,289-1,303 MiB ([#707](https://github.com/neilsh/stunt-reel/issues/707)).
   _Source: [the GPU's memory and byte-identity after freeing the world mesh](../../work/2026-11/707_gpu-free-world-mesh/journal.md#2026-11-20-the-gpus-memory-and-byte-identity-after-freeing-the-world-mesh)._
