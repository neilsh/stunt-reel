# Batch Parity Survey: Every Distinct Corpus Film

`[Bounded Observation]`, 2026-10-30. The survey was stopped on purpose after **79 of 529** distinct films were scored (about 15%): enough to characterise the failure modes and the score spread, and the remaining films would cost tens of hours at 200 s per capture. The numbers below are the ledger at that point (`--summary` regenerates them); resuming is just `mise run batch-parity`. The plan is [`docs/process/plans/batch-parity-2026-10-30.md`](../../docs/process/plans/batch-parity-2026-10-30.md).

## 1. How to Run

```
mise run batch-parity                       # resumable: finished stages are skipped
mise run batch-parity -- --only SLUG,...    # named films
mise run batch-parity -- --limit N          # the first N films by slug
mise run batch-parity -- --retry-errors     # rerun stages whose latest record is an error
mise run batch-parity -- --jobs N            # N films at once (default 1)
mise run batch-parity -- --summary          # counts, failing films, lowest and highest SSIM
```

Each distinct film (579 `.FLM` files, 529 after de-duplication by sha256, [`batch_films.py`](../../python/stunt_reel/batch_films.py)) goes through four stages ([`batch_parity.py`](../../python/scripts/batch_parity.py), [`batch_stages.py`](../../python/stunt_reel/batch_stages.py)): `archive` (`MAKEONE` through `make_all`; skipped when a sibling `.ALL` exists, 260 films), `capture` (`capture_playone_reference`), `render` (`stuntreel --headless`) and `score` (`stuntreel parity`). The stages stop at a film's first error. A capture whose `meta.json` shows a stuck film clock (first and last `film_tick` equal) or fewer than 2 frames is recorded as `capture invalid: ...`, not ok. The append-only ledger is `build/parity/batch/ledger.jsonl` ([`batch_ledger.py`](../../python/stunt_reel/batch_ledger.py)), one record per stage run (`slug`, `stage`, `status`, `message`, `seconds`, `ssim`, `iou`); the latest record per slug and stage wins. Per film, `build/parity/batch/<slug>/report/` holds `report.json` and the contact sheets, copied to `frames/`, and the render is kept: since the render store ([ADR 0027](../../docs/adr/0027-renders-store-planes-in-per-second-zstd-chunks.md)) one is a few megabytes, where per-tick files ran to 2 to 5 GB per film and were deleted after scoring. With `--jobs N` each worker runs one film's stages in order; ledger appends and progress lines share one lock, `--max-renders M` (default 2) caps simultaneous renders, and a render waits, polling every 30 s, while less than `--min-free-gb` (default 8) is free under the batch root. Nothing here touches `references.toml`: the survey scores whatever capture it makes and pins nothing.

## 2. Results

By latest record per film and stage: archive 47 ok and 40 skipped (sibling `.ALL`), no errors; capture 80 ok and 5 errors; render and score 79 ok. 79 films scored.

* **Scores** (`[Bounded Observation]`, 79 films): median 0.68, 10th percentile 0.53, 90th percentile 0.79, range 0.004 to 0.924. 35 films score 0.70 or more; one reaches 0.88 (`vault-balloon`, 0.9236). 4 are below 0.1 and 7 below 0.5. For scale, the two pinned films score about 0.78 (CTRY) and 0.68 (INTRO) with the render tuned for them, so the untuned corpus lands in the same band; no film outside those two is near the 0.90 sign-off.
* **By family** (median, count): `flmonly` 0.73 (36), `desperat` 0.69 (3), `boz` 0.66 (3), `collage4` 0.63 (7), `collage5` 0.60 (9), `egalloc` 0.56 (11); `flmonly` is the best-behaved and `egalloc` the worst, but small families and noisy captures limit what that says.
* **Degenerate scores.** (`vault-balloon` was rescored in section 5: 0.678 over 108 frames.) `vault-balloon` scored 0.9236 with IoU 0.0 and index agreement 0.0 over 3 frames, and its survey capture `frames/002` holds 3 frames at `film_tick` 0, the stuck-clock signature ([`../playone-exe/capture-speed.md`](../playone-exe/capture-speed.md) § 1). Films below 0.05 (`collage4-elbarto` 0.0042, `flmonly-act5` 0.0071, `egalloc-egallo10` 0.0114, `flmonly-act1` 0.0196) had one scored frame with IoU about 0.83 and index agreement near 0. Neither group is parity evidence; the capture-validity check (§ 1) now rejects the stuck-clock case at capture time, but these scores predate it.
* **Capture stalls are intermittent.** `no new frame after 2001 trap hits (0 frame(s) captured, 6 to 9 indices on the page)` after the dialog settled. Five films still end in a capture error: `collage4-exit`, `collage4-exit2`, `flmonly-bigman`, `flmonly-count` (stalls) and `flmonly-colprt2` (`capture invalid: only 1 frame(s)`). But `amcrisis-ac`, `egalloc-egalloc0` and `egalloc-egalloc5` stalled on the first pass and captured fine on a retry (305 s, 146 s, 311 s), so a stall is not a property of the film. Each stall costs about 207 s. These were DOSBox-X debugger stalls (no trap hit). Re-run on dosbox-automation with both `PLAYONE` builds ([`../playone-exe/patch3.md`](../playone-exe/patch3.md) § 3), `collage4-exit`, `collage4-exit2` and `flmonly-count` capture whole (`COUNT` is only 92 ticks long). The driver's default skip list is now `flmonly-bigman` alone, which replays a tick apart from boot to boot so a dump pass disagrees with its trace (`--skip` adds slugs, `--only` or `--retry-errors` runs it).
* **Archive timeouts** (`exit 124`, 900 s) hit films of 323 KB or more under the original `cycles = 8000` conf; `MAKEONE` plays in real time, so these were long films, not hangs. Under `core = dynamic` and `cycles = max` they were retried and none remains an error ([`../makeone-exe/driving.md`](../makeone-exe/driving.md) § 8).
* **Orphaned emulators.** A timeout killed only the direct Python child on Windows, so each left a `dosbox-x.exe` and a 12 MB stage directory. The runner now kills the process tree and `make_all` gets a 90 s head start on its own timeout.
* **Disk full.** The first full run died after 12 films (`WinError 112`): nothing deleted the render output. Fixed; see § 1.
* **Frame sampling did not work.** An experimental `--sample-frames K` (a stride in trap hits between dumps, removed again) announced a stride of 2 on `vault-balloon` yet captured 112 frames either way, 10 to 11 ticks apart: guest time follows the host clock, so skipped dumps do not widen the spacing ([`../playone-exe/capture-speed.md`](../playone-exe/capture-speed.md) § 1).

## 3. Cost

Median stage times, from the ledger: archive 68 s (mixed settings; 7 to 27 s at `cycles = max`), capture 200 s (mean 229, 90th percentile 460, max 722), render 16 s, score 1.2 s. At the original settings archive generation was 44% of wall time and capture 52%; timeouts and failed captures were 37.5% of it. Capture is wall-paced (about 0.25 s per frame, 4 s of boot), and no DOSBox-X setting, `turbo` or frame sampling cut it, so serial capture over all 529 films would take about 36 hours. Eight captures at once on an idle machine finished in 64 s with the tick spread unchanged at 0 to 2 ticks ([`../playone-exe/capture-speed.md`](../playone-exe/capture-speed.md) § 1); `--jobs 8` is therefore the lever, with simultaneous renders capped by `--max-renders`.

## 4. Error readout of the retail vault films

`[Bounded Observation]`, 2026-11-01, render at `ea99618`. The ten films in the retail game's `VAULT` folder went through the survey (`--only`, slugs by content: `HIGHWAY.FLM` is `vault-highways`, `PLANES.FLM` is `vault-splanes`), then through the error readout ([`method.md`](method.md) § 2.3): each kept render, `mise run parity-bench -- errors-make --film <slug> --batch`, one Haiku grader per two films, `errors-score --batch`. Twelve frames per film over its whole length; the table lists the categories graded 2 or more on at least 3 of the 12 (the readout's noise is up to 3 frames per category, so 3 is a lead and 4 or more a finding).

| Film | Ticks | Graded | Categories graded 2+ (frames of 12) | `other` notes | SSIM (scored frames) |
|---|---|---|---|---|---|
| `vault-balloon` | 4–1185 | 12 | `aircraft-absent` 6, `actors-missing` 5, `scenery-missing` 4, `aircraft-shape-broken` 4, `aircraft-parts-missing` 4 | 8 | 0.678 (108) |
| `vault-bomb` | 3–3475 | 12 | `aircraft-too-small` 7, `aircraft-parts-missing` 7, `aircraft-misplaced` 5, `scenery-missing` 4 | 2 | 0.655 (310) |
| `vault-ctry` | 4–1001 | 12 | `aircraft-shape-broken` 8, `aircraft-parts-missing` 8, `shadow-missing` 5, `scenery-missing` 3 | 4 | 0.776 (113) |
| `vault-highways` | 52–1070 | 12 | `scenery-missing` 6, `aircraft-parts-missing` 6 | 2 | 0.745 (91) |
| `vault-land` | 3–898 | 12 | `aircraft-absent` 11, `shadow-shape-wrong` 8 | 0 | 0.750 (95) |
| `vault-splanes` | 3–961 | 12 | `sea-band-wrong` 12, `scenery-missing` 11, `aircraft-absent` 8, `shadow-shape-wrong` 4, `aircraft-shape-broken` 3, `aircraft-parts-missing` 3 | 0 | 0.631 (106) |
| `vault-traintnl` | 4–1229 | 12 | `sea-band-wrong` 5, `aircraft-absent` 5, `shadow-shape-wrong` 4, `actors-missing` 4 | 3 | 0.712 (107) |

* **The aircraft is the common error.** It is absent, broken or missing parts on 4 or more frames in all seven films; in `vault-highways` missing aircraft parts tie with missing scenery at 6 frames. `vault-land` draws no aircraft on 11 of 12 frames, the same failure `INTRO.FLM` shows.
* **`other` notes name kinds no category covers.** `vault-balloon`: the sun disc and sky colour, a missing parachute, two frames drawn flat grey with no ground; `vault-ctry`: tents and hangars drawn as pink cones; `vault-bomb`: black blocks over a wall and sign; `vault-highways`: a missing banner and marker; `vault-traintnl`: train livery drawn dark, a train the capture lacks. Three recur on more than one frame and are now categories: `sun-missing` (the balloon's sun), `frame-blank` (its flat grey frames) and `black-block` (black shapes over the bomb film's wall and sign and the balloon's parachute).
* **Three films have no capture.** `vault-intro`, `vault-location` and `vault-tod` failed twice, the second time one at a time: the capture script stops with `instruction limit exceeded` about 40 s after the game enters Mode 13h, far short of the long-film limit in [`capture-dosbox-automation.md`](../playone-exe/capture-dosbox-automation.md). `vault-highways` failed the same way under `--jobs 3` and passed alone.

The survey then deleted each render after scoring it; the readout needs the render's planes, so the seven were rendered again with the survey's own render stage and kept (about 260 MB each, before the render store).

## 5. Retail vault films on the render store

`[Bounded Observation]`, 2026-11-01, commit `f0e4300` (PR #44, render store, [ADR 0027](../../docs/adr/0027-renders-store-planes-in-per-second-zstd-chunks.md)). The ten `VAULT` films went through all four stages in a fresh worktree whose ledger was empty (`mise run batch-parity -- --only <ten> --stages archive,capture,render,score --retry-errors --jobs 4`, default `--max-renders`). The ledger skips stages whose latest record is ok and `batch_parity.py` has no force flag, so a rerun in a worktree with old records would reuse them; this run needed none of that. Scoring only: no error readout. Every capture below is a new directory from this run.

| Film | Capture | Frames | `film_tick` | Scored / total | SSIM | IoU | Index agreement | Render | Capture / render / score s |
|---|---|---|---|---|---|---|---|---|---|
| `vault-balloon` | ok | 108 | 4–1185 | 108 / 108 | 0.678 | 0.598 | 0.418 | 1.6 MB, 28 files | 93 / 1.9 / 0.4 |
| `vault-bomb` | ok | 328 | 3–3725 | 305 / 328 | 0.660 | 0.817 | 0.549 | 9.5 MB, 79 | 295 / 4.0 / 1.0 |
| `vault-ctry` | ok | 120 | 4–1335 | 113 / 120 | 0.776 | 0.977 | 0.526 | 3.9 MB, 31 | 97 / 2.1 / 0.5 |
| `vault-highways` | ok | 92 | 52–1068 | 92 / 92 | 0.744 | 0.941 | 0.676 | 1.4 MB, 25 | 89 / 2.0 / 0.3 |
| `vault-land` | ok | 99 | 3–1126 | 94 / 99 | 0.748 | 0.970 | 0.656 | 2.1 MB, 27 | 88 / 2.3 / 0.4 |
| `vault-splanes` | ok | 112 | 3–1240 | 106 / 112 | 0.632 | 0.878 | 0.452 | 1.0 MB, 29 | 92 / 1.9 / 0.4 |
| `vault-traintnl` | ok | 108 | 4–1239 | 108 / 108 | 0.712 | 0.908 | 0.716 | 3.4 MB, 29 | 93 / 2.5 / 0.4 |
| `vault-intro` | capture error | | | | | | | | 177 |
| `vault-location` | capture error | | | | | | | | 133 |
| `vault-tod` | capture error | | | | | | | | 44 |

Seven of ten films are scored; none is a stuck clock or under 2 frames. SSIM, IoU and index agreement are the scored-frame means from `report.json`; archive was skipped for all ten (sibling `.ALL`).

* **Against section 4.** SSIM agrees with the earlier readout to within 0.005 for all seven scored films (balloon 0.678, bomb 0.655 to 0.660, the largest change, ctry 0.776, highways 0.745 to 0.744, land 0.750 to 0.748, splanes 0.631 to 0.632, traintnl 0.712), and scored-frame counts to within 5 (bomb 310 to 305, highways 91 to 92, land 95 to 94, traintnl 107 to 108; the rest equal). The two `film_tick` columns measure different things: section 4's is the span of the 12 frames the readout picked (`pick_ticks` in [`errors.py`](../../python/stunt_reel/bench/errors.py) takes scored frames with fade level 0.95 or more), this section's is the capture's own first and last tick, fade tail included. Captures run to within 10 ticks of the film's end (`vault-ctry`'s listed runs end at 1332 to 1342 of 1,342) and the closing fade frames are excluded both times, so the two surveys score the same fade-excluded span, give or take capture jitter ([`../playone-exe/capture-speed.md`](../playone-exe/capture-speed.md) § 3).
* **`vault-balloon` is no longer degenerate.** Section 2's 0.9236 (IoU 0.0, 3 frames at tick 0) is superseded: the current capture has 108 frames over ticks 4 to 1185 and scores 0.678, IoU 0.598. That section's remark that the old score predates the validity check is confirmed. Balloon also has the lowest IoU of the seven.
* **Render store size.** 1.0 to 9.5 MB and 25 to 79 files per film (`frames.zst`, `layers.zst`, `palettes.zst`, `preview/`, `render.json`), against about 260 MB per film in section 4 and 2 to 5 GB before the store; `vault-bomb` is the largest because it has 328 frames. Render time is 2 to 4 s, score under 1 s; capture (88 to 97 s with 4 films at once, 295 s for bomb) is the whole cost.
* **The three failures are unchanged** (cause: open question 6). `vault-intro`, `vault-location` and `vault-tod` ended `instruction limit exceeded` (from the capture script, `[string "unnamed"]:32` or `:38`) in the 4-job run and again on the single retry run one at a time, after 177, 133 and 44 s. With section 4's two, each of the three films has now failed four attempts the same way (12 in all).

## Ruled out

- **De-duplicating by name.** The same film appears under several folders (`NewPLAY`, `OldPLAY`, `Morganroth`); only the content hash identifies it.
- **Keeping the rendered frames.** Gigabytes per film; the report and contact sheets are kept.

## Open questions

1. Rescore after rejecting stuck-clock and single-frame captures: how many of the 79 scored films survive the validity check? Rerun the suspects (`vault-balloon`, the four below 0.05) with the current harness.
2. Why do captures stall intermittently at the dialog (6 to 9 indices, the film never starts)? A stall that clears on retry points at timing in the dialog selection, not the film.
3. A scored single-frame film with IoU 0.83 and index agreement 0.001 suggests a palette or index-plane mismatch; look at one report's index planes.
4. A full `--jobs 8` survey has not run: the idle-machine test passed, but the heavy-load behaviour (the earlier -28 tick dips) is untested.
5. Resume to cover the remaining 450 films, or sample the families (`egalloc`, `collage4`, `collage5`) where scores are lowest.
6. Why do `vault-intro`, `vault-location` and `vault-tod` stop with `instruction limit exceeded` about 40 s into Mode 13h, on every attempt (section 4)? Partly answered: the trace script has a fixed budget of one million Lua instructions and stops only once the film clock holds above 0, which never happens with the retail `siarchive` `.ALL` the survey picks (TOD's clock falls back to 0 onto a one-colour page; INTRO holds a title card), so the trace runs until the budget is spent. The earlier `vault-intro` captures used the demo's `INTRO.ALL`. Open: why the retail archives play this way, and which archive the survey should pick ([`../playone-exe/capture-dosbox-automation.md`](../playone-exe/capture-dosbox-automation.md#47-the-instruction-budget-and-three-retail-archives) § 4.7).
7. ~~Why does a capture's end tick differ by 100 to 400 ticks between runs?~~ Answered: it does not; section 4's column was the readout's picked span, not the capture's ([`../playone-exe/capture-speed.md`](../playone-exe/capture-speed.md) § 3).
8. Section 4's error readout graded renders from `ea99618` of older captures; should the Haiku readout be rerun on the render-store renders and the fresh captures? Not done here.
