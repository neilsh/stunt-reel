# Journal: full-rate video captures

## 2026-11-27: LOCATION with the slot words in the per-frame row

**Question.** Does `capture-video` still finish `LOCATION.FLM` (previous row: `end` `hold` at 11,616 frames) when the row also reads `slot_clock` and `slot_ticks`, against the emulator's one-million-instruction Lua budget (`capture-dosbox-automation.md` § 4.7)?

**Method.** `main` at `d21e5cd` plus the change in #1198, Patch 3 build, the reference `.ALL` pinned in `references.toml`, stubbed samples, `capture` profile (`core = dynamic`, `cpu_cycles = 45000`), dosbox-automation 0.85.1 in a cloud session.
The row read `film_tick`, `global_tick`, `slot_clock` and `slot_ticks` (`DS:0x421C`, `0x1C3E`, `0x4220`, `0x1C62`; the last two inferred, ADR 0057) every frame.
Two runs of `mise run capture-video -- --film corpus/stuntisl/VAULT/LOCATION.FLM --out <dir>`: the first with `meta.json` carrying the slot columns only, the second with the whole-film fields too.

**Result.**

| Run | `end` | Frames | Palette changes | `capture.avi` | `meta.json` | Whole task |
|---|---|---|---|---|---|---|
| 1 | hold | 11,616 | 118 | 19,996,314 B | 2,622,322 B | 334 s (its first build) |
| 2 | hold | 11,616 | 118 | 19,996,314 B | 2,622,941 B | 185 s |

* Both runs finished before the budget ran out, so the row costs under about 86 instructions per frame, the million divided by 11,616 frames, boot and tail included.
  The count itself is not exposed, so the 0.6 to 0.7M estimate ([#1194 budget check](https://github.com/neilsh/stunt-reel/issues/1194#issuecomment-7227024791)) stands unmeasured.
* The two runs' `capture.avi` share one SHA-256 (`16f37fb3980c1b98a0fa2cf3d28bfb22c4a6fcacb250a568ab23a63f0df656ad`), and their `log` and `palettes` objects (`frame`, `film_tick`, `global_tick`, `slot_clock`, `slot_ticks`) are equal.
* `slot_ticks` runs 0 to 2 in the log; `slot_clock` runs 3 to 8,266 with 7,897 distinct values.
* The previous row's `capture.avi` was 19,996,314 bytes (issue #1194, 2026-11-27 comment), the same length as both runs here.
* `meta.json` pretty-printed at indent 2 grew from 2.38 MB to 2.62 MB with the two columns.
* Run 2's `meta.json` validates against the regenerated `video.schema.json` (`jsonschema`), loads in `load_video_capture` (Python) and reads and validates as `VideoCapture` in `stunt-parity`.

**Verdict.** Adopted: the per-frame slot columns stay, and the change-only `slot` log the issue held in reserve is not needed for LOCATION.

**Lives in.** [`capture-dosbox-automation.md` § 4.6 and § 4.7](../../../research/playone-exe/capture-dosbox-automation.md).

## 2026-11-27: Reference check, replay and the pairing rule on seven full-rate recordings

**Question.** (1) Does a recording replay identically? (2) How do the pinned frame captures' pages compare with the video? (3) Does ADR 0057's pairing rule hold on full-rate video frames, which the plan validated only on kept pages?

**Method.** `main` at `9efc5dd` plus #1200's change, a cloud session, Patch 3, the reference `.ALL`s (each recording's `film.all_sha256` equals its `references.toml` row's), stubbed samples, `capture` profile, dosbox-automation 0.85.1.
One `mise run capture-video -- --film <flm> --out <dir>` per film, nothing uploaded, a second recording of `CTRY` and of `LOCATION`.
`mise run video-derive -- reference-check <film> --dir <dir>` against the film's pinned `captures/<slug>/frames` (the `references.toml` digest).
Each page's indices go through its own palette to RGB, rows 0..184 are compared with the video frame at `emu_frame - capture_start_frame - 1 + offset`, offsets -8..+8, the best frame taking the page, ties to the offset nearest zero.
A page that no frame equals is a `split` when each of its rows equals that row of some video frame in `-2..+4` of the paired frame (the journal's rule of 2026-10-30), else a `band`.
`mise run video-derive -- pairing --dir <dir> --render <store>` against a store of the film's ticks `1..last` rendered on lavapipe (`render_film`, `--at-ticks`, software adapter) at this tree's `crates/`, SSIM of the luma over rows 0..184 with `bench/ssim.py`'s 11x11 windows at stride 8, no overlay mask.
Frames are the last frame of each run of one `slot_clock` value (a run end), minus those in the two frames after a palette write, which the DAC may show in a lagged palette (`capture-dosbox-automation.md` § 4.5).
That a run end is a whole picture was not established (a video frame can be torn between two buffers), so the figures describe run ends, not finished frames.
Control: the same render store scores the pinned pages' own `render_tick` against their tag (CTRY 0.9509 against 0.9493, LOCATION 0.9205 against 0.9016), the ADR's gain.

**Replay.**

| Film | Recordings | `capture.avi` | `meta.json` |
|---|---|---|---|
| CTRY | 2 in one session | identical, 2,532,660 B, sha256 `e1e8cd339069ee1f53afc17822a2e291e6c7d3e80239016c2efbad79d717827a` | identical, 1,291,880 B |
| LOCATION | 2 in one session | identical, 19,996,314 B, sha256 `16f37fb3980c1b98a0fa2cf3d28bfb22c4a6fcacb250a568ab23a63f0df656ad` | identical |

The LOCATION hash equals the one of the 2026-11-27 slot-word entry above, made in another container.

**Alignment.** Log row *i* is AVI frame *i*: over CTRY, a `slot_clock` change at row *i* coincides with a changed picture at AVI frame *i* + *s* in 1,197 of 1,200 changes at *s* = 0, and 1,106 to 1,148 at the other six shifts from -3 to +3 (`slot_clock` change rows 1,200; picture changes 1,750 to 1,756).
The row of `emu_frame` is `emu_frame - capture_start_frame - 1` (the first row is frame `capture_start_frame + 1`), so `VideoCapture.video_index` runs one above the AVI index of the same frame.

**Reference check.** Counts of pages by their best offset:

| Film | Pages | -5 or less | -2..-1 | 0 | +1 | +2 or more | Median pixel-equal | Min | Exact | Split | Band |
|---|---|---|---|---|---|---|---|---|---|---|---|
| CTRY | 121 | 1 | 0 | 57 | 63 | 0 | 99.9747% | 95.98% | 31 | 28 | 62 |
| INTRO | 347 | 0 | 0 | 272 | 75 | 0 | 100% | 97.14% | 235 | 62 | 50 |
| LAND | 103 | 0 | 0 | 37 | 66 | 0 | 99.9949% | 93.55% | 46 | 39 | 18 |
| BALLOON | 108 | 0 | 0 | 64 | 44 | 0 | 100% | 97.08% | 65 | 29 | 14 |
| TRAINTNL | 112 | 0 | 0 | 63 | 49 | 0 | 99.9992% | 87.99% | 56 | 44 | 12 |
| BOMB | 339 | 0 | 0 | 204 | 132 | 3 | 100% | 96.53% | 230 | 94 | 15 |
| LOCATION | 745 | 2 | 5 | 425 | 302 | 11 | 99.9983% | 90.86% | 369 | 207 | 169 |

Exact, split and band sum to the pages in every row.
`CTRY`'s offsets are the plan's baseline (0 on 63, -1 on 57) in the plan's base, which is one higher than this one; its median, minimum and 31 exact pages repeat.
Every page's video frame lies inside the `-8..+8` window (0 skipped).
Of the mismatched pages, no page is explained by a palette alone: for each of the 90 mismatched CTRY pages and 376 LOCATION pages some palette index shows two video colours on one page, which a palette (DAC lag) difference alone would not give (the comment of 2026-11-27 on #1194 reached the same for CTRY with the working palette log).

**Pairing rule on run ends.** Frames compared, then the best offset of the `render_tick` pairing, mean SSIM with the `render_tick` pairing and with the tag, and the frames where the two ticks differ and the rule scores higher:

| Film | Compared | Best offset 0 | -1 | SSIM `render_tick` | SSIM tag | Rule higher where ticks differ |
|---|---|---|---|---|---|---|
| CTRY | 1,099 | 544 | 437 | 0.9427 | 0.9441 | 161 of 441 |
| INTRO | 3,563 | 2,665 | 359 | 0.9528 | 0.9443 | 668 of 2,156 |
| LAND | 914 | 418 | 358 | 0.9318 | 0.9323 | 151 of 386 |
| BALLOON | 1,161 | 542 | 287 | 0.9060 | 0.9074 | 261 of 522 |
| TRAINTNL | 1,194 | 579 | 229 | 0.9186 | 0.9132 | 352 of 496 |
| BOMB | 3,603 | 2,314 | 639 | 0.9248 | 0.9166 | 1,079 of 1,916 |
| LOCATION | 7,774 | 5,148 | 2,219 | 0.9050 | 0.8923 | 2,309 of 3,923 |

* `render_tick` scores above the tag on four films (+0.0054 to +0.0127) and below it on three (-0.0005 to -0.0014).
* A key naming two pictures: on CTRY the pairs of consecutive run ends that share one `render_tick` all differ in picture (296 of 296 shared keys, 592 of 1,100 frames), against 180 of 180 shared tags (360 frames).
  The other films' shared `render_tick` keys that name more than one picture, in frames of the compared run ends: INTRO 1,016, LAND 320, BALLOON 570, TRAINTNL 558, BOMB 1,222, LOCATION 3,292.
* `slot_ticks` is not constant in a run: of the runs of two or more frames, it varies in 393 of 578 (CTRY), 315 of 527 (LAND), 424 of 497 (BALLOON), 315 of 471 (TRAINTNL), 991 of 1,506 (BOMB), 1,058 of 1,601 (INTRO) and 2,455 of 3,533 (LOCATION).
  The commonest CTRY pattern in a two-frame run is 1 then 0 (386 runs).
* Taking the words from the first row of each run instead of its last scored below the last row on six films (CTRY above by 0.0009).

**Verdict.** Adopted for the code: `derived.json` keeps `render_tick` per row by the ADR's rule, `finished` is left out, and `palette_step` marks the write frame.
The rule's gain over the tag holds on run ends for four of seven films and is below it by at most 0.0014 on three, so it is not refuted; whether run ends are whole pictures is the open part.

**Lives in.** [`capture-dosbox-automation.md` § 4.6](../../../research/playone-exe/capture-dosbox-automation.md#46-whole-film-video-capture).
