# Journal

## 2026-11-23: a frame's off-model tick changes with the capture's settings

- **Question**: is a captured frame whose best render offset is not 0 a property of the film, shown by every capture, or of that capture's timing?
- **Method**: `main` at `e2981f3d`, all seven films rendered once on the canonical lavapipe under WSL (`llvmpipe (LLVM 20.1.2, 256 bits)`), then `mise run parity -- --no-render --no-build --software-only --retime N` for N in -2, -1, +1, +2 ([`retime-<film>.csv`](retime-location.csv), per-frame SSIM of the reference capture; the film means below are the CSVs' column means).
  The runs compared, with their settings: the reference (`captures/`, Patch 3, sound samples stubbed); each film's two older capture sets in the data root's `backup/`, `pre-305` (Patch 3, sound kept) and `pre-300` (unpatched, sound kept); and two LOCATION captures taken for this question with `capture-ref --out <data root>/scratch/1033/…`, a stubbed Patch 3 recapture (the control) and a stubbed unpatched one, `s300` (`--game-root <data root>/builds/unpatched --archive` the reference's `LOCATION.ALL`, under a scratch `--name` because the `[location]` row pins Patch 3).
  Every capture but the reference was scored against the same render and its retimed copies with `parity_probe.py retime --reference` and `stuntreel parity --reference … --waive-archive-conflict` (the waiver because some `pre-300` sets were made from another archive build, `all_sha256` differing on five films though not LOCATION or LAND; used for every such score alike).
  Captured frames sit 10 to 12 ticks apart, so a frame in one run has one counterpart in another, at its own tag or a tick away: each run is given its own best offset through the render instead.
  [`cross_run.py`](cross_run.py) takes each frame's best offset in -2..+2 by palette-index agreement (SSIM breaking ties), with `d_ia` its gain over offset 0 (decidable at `d_ia` ≥ 0.01), and compares pages directly over rows 0..184 ([`offsets-<film>.csv`](offsets-location.csv); printed tables in [`cross-run.txt`](cross-run.txt) for the backups of all films and [`cross-run-stubbed.txt`](cross-run-stubbed.txt) for LOCATION with `s300`).
  A gainer is a reference-capture frame whose best-SSIM offset gains 0.02 or more.
- **Result** (LOCATION, 732 scored frames, unless named):
  - Offset 0 is the film-mean peak over -2..+2 on all seven films: LOCATION 0.8172, 0.8522, **0.8728**, 0.8379, 0.8134 for -2 to +2; BOMB 0.8641, 0.8852, **0.8949**, 0.8790, 0.8575; INTRO 0.8559, 0.8774, **0.8833**, 0.8622, 0.8411; CTRY 0.9096, 0.9241, **0.9385**, 0.9310, 0.9169; LAND 0.8871, 0.9042, **0.9245**, 0.9192, 0.9014; BALLOON 0.8640, 0.8850, **0.9059**, 0.8891, 0.8694; TRAINTNL 0.8922, 0.9065, **0.9107**, 0.8958, 0.8829.
    Giving every scored frame its best-SSIM offset instead raises the mean by 0.0195 (LOCATION), 0.0191 (INTRO), 0.0107 (BOMB), 0.0086 (TRAINTNL), 0.0077 (LAND), 0.0027 (CTRY) and 0.0021 (BALLOON), from the CSVs.
  - The control: the stubbed Patch 3 recapture is index-identical to the reference on 745 of 745 frames, every `emu_frame` equal.
  - 157 frames are gainers; the reference has a decidable non-zero offset on 143 of them (97 negative, 46 positive) and on 25 of the other 575.
  - Split by how far another run's page at the same tag differs (rows 0..184), the reference's decidable offset on a gainer recurs in that run:

    | Other run | Identical | 1 to 100 pixels | Over 100 pixels: same / undecided / other |
    |---|---|---|---|
    | `pre-305` (Patch 3, sound) | 72 of 72 | 9 of 9 | 5 / 26 / 2 of 33 |
    | `pre-300` (unpatched, sound) | 33 of 33 | 9 of 9 | 6 / 56 / 2 of 64 |
    | `s300` (unpatched, stubbed) | 36 of 36 | 9 of 9 | 8 / 48 / 2 of 58 |

    An identical page must pick the same offset (no identical pair picked different ones), so only the last column tests anything: there the other run nearly always prefers offset 0.
    Outside the canyon run that column's recurrences are 4 of 32, 4 of 61 and 4 of 53; over all ticks, the reference's decided gainer offsets recur on 86 of 114, 48 of 106 and 53 of 103, mostly through identical pages.
  - The canyon run, ticks 6700 to 7400, differs: no pair decides a different offset there (reference against `pre-305` 9 tags both decided the same, 0 different, 1 decided in one only; against `pre-300` 11, 0, 2; against `s300` 11, 0, 2), and on gainers whose page differs by over 100 pixels the offset recurs on 1 of 1, 2 of 3 and 4 of 5.
  - Pairwise, both decided the same / both decided differently / decided in one run only: reference and `pre-305` 106 / 3 / 64; reference and `pre-300` 62 / 2 / 116; reference and `s300` 65 / 3 / 107; `pre-300` and `s300` 98 / 3 / 67.
  - Page identity at shared tags: the reference and `pre-305` 406 of 645; the reference and `pre-300` 277 of 625; the reference and `s300` 281 of 629; `pre-300` and `s300` 428 of 647.
    Of 98 reference frames whose tag `pre-305` lacks but whose tag ± 1 it has, 15 are index-identical to that neighbour (27 of 119 against `pre-300`, 21 of 115 against `s300`).
  - Off-model frames are as common with sound as without: a decidable-by-over-0.01 non-zero offset on 168 of 732 frames (reference) and 172 of 733 (`pre-305`), 161 of 732 (`s300`) and 162 of 732 (`pre-300`).
  - The other six films (backups only) have these gainers (BOMB 49 of 316, INTRO 50 of 209, TRAINTNL 16 of 112, LAND 8 of 97, CTRY 5 of 114, BALLOON 1 of 107); `pre-300` shares only 7 CTRY and 10 INTRO tags with the reference, so those pairs say little.
- **Verdict**: control (diagnosis).
  Repeat captures of one configuration replay a frame's off-model tick; where other settings (sound playback or the build) change a frame's page, outside the canyon run its off-model tick mostly goes with it, so for those frames the tick follows the capture's timing.
  Where the page does not change this test cannot tell timing from the film.
  The canyon run's offsets recur where the page changes too (7 of 9), so they belong to the film or our model (#1029).
- **Lives in**: [`capture.md` § 4](../../../research/playone-exe/capture.md#4-observed-results), [`evidence-limits.md` § 3](../../../research/parity/evidence-limits.md#3-what-is-not-yet-evidence), [`capture-dosbox-automation.md`](../../../research/playone-exe/capture-dosbox-automation.md#open-questions) open questions 15 and 17.

## 2026-11-23: the offset's sign follows the frame's phase within its tick

- **Question**: does a frame's best offset follow its place in time, as the capture records it?
- **Method**: [`emu_time.py`](emu_time.py) fits `film_tick` against `emu_frame` over the ten frames either side of each frame (the frame left out), takes φ, the fitted tick minus the tag, and bins LOCATION's decidable offsets (`d_ia` ≥ 0.01) by φ; it then relabels every frame of every film to the whole tick nearest its emulator time ([`emu-time.txt`](emu-time.txt)).
  The `film_tick` gap to the previous captured frame is the capture's 10-to-12-tick window spacing, not PLAYONE's drawing, and was not used.
- **Result**:
  - The fit gives 0.713 ticks per emulated frame; φ has a standard deviation of 0.23 to 0.25 ticks on every film's reference capture and up to 0.32 on the backups (INTRO `pre-305`).
  - LOCATION reference run: φ < -0.3 (the tag ahead of the fit: the frame early in its tick), 19 negative and 3 positive offsets of 69 frames; φ > 0.3 (late in its tick), 2 negative and 12 positive of 83; -0.3 to 0, 61 and 25 of 301; 0 to 0.3, 17 and 29 of 279.
    `pre-305`: 28/2 of 79, 3/16 of 87; `pre-300`: 24/6 of 89, 1/17 of 85.
  - Relabelling to the nearest emulator-time tick moves 0 to 38 frames per film and run and changes film means by -0.0013 (TRAINTNL `pre-305`) to +0.0018 (INTRO `pre-305`); LOCATION's reference run goes from 0.8728 to 0.8722.
- **Verdict**: control.
  The sign follows φ in the same direction in all three runs, but most frames at any φ keep offset 0, so φ does not decide a frame's offset.
- **Lives in**: [`capture.md` § 4](../../../research/playone-exe/capture.md#4-observed-results).

## 2026-11-23: rendering each frame at its emulator-time phase

- **Question**: does the page show the film at a fractional time that follows the emulator, `t - 1 + φ`?
- **Method**: [`DBG_PHASE.diff`](switches/DBG_PHASE.diff) adds φ × `DBG_PHASE_SCALE` to each sampled tick from the reference capture's φ (`emu_time.py`'s phase files), on `e2981f3d` under WSL; `mise run sweep -- --var DBG_PHASE_SCALE=0,0.5,1,-1 --track evidence --topic per-frame-phase --record <this folder>` over all seven films ([`sweeps/per-frame-phase.toml`](sweeps/per-frame-phase.toml)).
- **Result**:

  | Scale | LOCATION | BOMB | INTRO | CTRY | LAND | BALLOON | TRAINTNL | Mean | Frames down > 0.005 |
  |---|---|---|---|---|---|---|---|---|---|
  | 0 | 0.8728 | 0.8949 | 0.8833 | 0.9385 | 0.9245 | 0.9059 | 0.9107 | 0.9044 | |
  | 0.5 | 0.8691 | 0.8965 | 0.8791 | 0.9386 | 0.9242 | 0.9052 | 0.9108 | 0.9034 | 182 |
  | 1 | 0.8656 | 0.8964 | 0.8789 | 0.9384 | 0.9237 | 0.9040 | 0.9101 | 0.9024 | 319 |
  | -1 | 0.8628 | 0.8901 | 0.8815 | 0.9370 | 0.9221 | 0.9019 | 0.9083 | 0.9005 | 437 |

  The worst losses at 0.5 are INTRO 2234 (-0.304), INTRO 881 (-0.243), LOCATION 7415, 6931 and 7195 (-0.20 to -0.23, in and just past the canyon run) and INTRO 871 (-0.202).
- **Verdict**: rejected by the adoption rule (no variant adopts; the best, 0.5, fails the film-mean guard on INTRO, -0.0042).
  The seven-film mean falls (0.9044 to 0.9034 at 0.5) though BOMB rises 0.0016; the page shows a whole tick, as the film-wide fractional sweep found ([`capture.md` § 4](../../../research/playone-exe/capture.md#4-observed-results)), and not the frame's emulator-time phase.
- **Lives in**: [`probes.md` § 6](../../../research/parity/probes.md#6-timing-hypotheses-post-hoc-retime).
