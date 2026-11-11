---
summary: "Reads the ten retail vault films through the batch survey: the vision-model error readout, their render-store scores and capture rates, and the suspects rescored on the stride plan."
---

# Batch Parity Survey: Retail Vault Films

`[Bounded Observation]`. The retail game's ten vault films, read after the corpus survey of [`batch.md`](batch.md) stopped; the survey's method, results and cost (sections 1 to 3) are there. Method: [`method.md`](method.md).

## 4. Error readout of the retail vault films

`[Bounded Observation]`, 2026-11-01, render at `ea99618`. The ten films in the retail game's `VAULT` folder went through the survey (`--only`, slugs by content: `HIGHWAY.FLM` is `vault-highways`, `PLANES.FLM` is `vault-splanes`), then through the error readout ([`metric-bench.md`](metric-bench.md#23-error-categories-graded-by-a-vision-model)): each kept render, `mise run parity-bench -- errors-make --film <slug> --batch`, one Haiku grader per two films, `errors-score --batch`, and the table from `errors-table --films <slugs>`. Twelve frames per film over its whole length; the table lists the categories graded 2 or more on at least 3 of the 12 (the readout's noise is up to 3 frames per category, so 3 is a lead and 4 or more a finding).

| Film | Ticks | Graded | Categories graded 2+ (frames) | `other` notes | SSIM (scored frames) |
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

## 6. The suspects on the stride plan

`[Bounded Observation]`, 2026-11-01, uncommitted work on `eb62a1f`. `egalloc-egallo10` was rescored on its existing capture; `collage4-elbarto`, `flmonly-act5`, `flmonly-act1`, `flmonly-cllction` and `collage3-col3-2` were captured afresh on the current harness (`--only <five> --retry-errors --jobs 3`). Three things stood in the way before any of them scored:

* **A low-integrity virtualenv.** The checkout root carries a Windows `Mandatory Label\Low` that `.venv` inherits, so its Python could not write `build\`, the data root or the temp directory, and each stage failed with `PermissionError`. Running with `UV_PROJECT_ENVIRONMENT` pointed at a venv under the unlabelled `.cache\` works around it ([`docs/harness.md`](../../docs/harness.md)); the label is the machine owner's to remove. Since [ADR 0036](../../docs/adr/0036-worktrees-reach-shared-state-by-configuration.md) `.cache\` holds no environment and `.venv` is the checkout's own again, so removing the label is the fix ([`docs/harness.md` § A low-integrity virtualenv](../../docs/harness.md#a-low-integrity-virtualenv)).
* **A stale binary.** The batch renders and scores with `target\release\stuntreel.exe` and never rebuilds it, so an old binary rejected the current render schema (`frame_file must be a basename`, `render schema 1`). Rebuilt with `cargo build --release -p stunt-cli`.
* **The instruction budget.** Four of the five are longer than the roughly 7,800 ticks one dense trace script can follow (a length census put 40% of the corpus past it). Capture now samples the clock in one pass and reads short windows in later passes ([`capture-dosbox-automation.md`](../playone-exe/capture-dosbox-automation.md) § 4.8).

| Film | Frames | Scored | `film_tick` | SSIM | IoU | Index agreement | Capture s |
|---|---|---|---|---|---|---|---|
| `egalloc-egallo10` | 368 | 343 | 3–4149 | 0.807 | 0.893 | 0.715 | 321 |
| `flmonly-act1` | 1334 | 1256 | 12–14994 | 0.774 | 0.851 | 0.414 | 1271 |
| `collage3-col3-2` | 1639 | 1586 | 26–20793 | 0.727 | 0.874 | 0.512 | 2102 |
| `flmonly-cllction` | 1577 | 1556 | 37–17656 | 0.707 | 0.805 | 0.554 | 1623 |
| `flmonly-act5` | 1090 | 1089 | 13–12016 | 0.671 | 0.803 | 0.480 | 928 |
| `collage4-elbarto` | 950 | 871 | 12–11056 | 0.535 | 0.783 | 0.328 | 821 |

* **The near-zero scores were noise frames.** The four films below 0.05 in [`batch.md` section 2](batch.md#2-results) now score 0.535 to 0.807 over hundreds of frames, inside section 2's band; their single scored frame was not a film frame.
* **Capture time follows film length**, about 0.1 s per tick at three films at once: the stride plan keeps one frame per 10 to 12 ticks but plays the film once per pass.
* **`vault-location` captures.** Off the known-stalls list, it captured 746 frames over ticks 12 to 8262 in 557 s and scores 0.684 (IoU 0.957, index agreement 0.651, 733 scored), so eight of the ten `VAULT` films now score.
* **`collage4-elbarto`** is the lowest of the six on every measure and the only one under 0.6; it is a lead for the error readout, not yet a finding.

## Ruled out

None recorded here. Rejected survey approaches are in [`batch.md`](batch.md#ruled-out).

## Open questions

1. ~~Why does a scored single-frame film show IoU 0.83 and index agreement 0.001?~~ Answered: the one frame was not a film frame, and recaptured whole the films score normally (section 6).
2. Why do `vault-intro`, `vault-location` and `vault-tod` stop with `instruction limit exceeded` about 40 s into Mode 13h, on every attempt (section 4)? Answered: the trace script has a fixed budget of one million Lua instructions and ends only once the film clock holds above 0. `TOD.FLM` and `INTRO.FLM` come from `siarchive/Films/NewPLAY/`, whose folder ships Patch #3's `PLAYONE.EXE`; that build stalls on those two retail archives (TOD's clock falls back to 0, INTRO holds a title card), while the unpatched build or a `make-all` archive plays both, and `--game-root builds/unpatched` captured them (`vault-tod/frames/001`, `vault-intro/frames/006`). The batch first captured those two on that build with a hand-kept list; the capture lifecycle's fallback is expected to find it by itself (a stall exception on patch3, then the unpatched build, and a suggested `references.toml` row), pending a capture run that shows patch3 raising one for these films. It has run only against a mock emulator; a patch3 attempt that completes normally is published and is not retried, and `TOD.FLM` is not an example of a stall the fallback sees, because the trace script ends only once the film clock holds above 0. `LOCATION.FLM` plays but, at 8,266 ticks, was too long for one trace script; on the clock and window passes it captures (section 6). Open: what in those archives stalls the patched build ([`../playone-exe/capture-dosbox-automation.md`](../playone-exe/capture-dosbox-automation.md#47-the-instruction-budget-and-three-retail-archives) § 4.7).
3. ~~Why does a capture's end tick differ by 100 to 400 ticks between runs?~~ Answered: it does not; section 4's column was the readout's picked span, not the capture's ([`../playone-exe/capture-speed.md`](../playone-exe/capture-speed.md) § 3).
4. Section 4's error readout graded renders from `ea99618` of older captures; should the Haiku readout be rerun on the render-store renders and the fresh captures? Not done here.
