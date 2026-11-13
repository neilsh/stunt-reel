# Score a render change against PLAYONE

The commands of the parity loop. What each step measures, and how to read its output, is [`research/parity/method.md`](../../research/parity/method.md) § 1; the field tables of `report.json` and `compare.json` are [`report-fields.md`](../../research/parity/report-fields.md).

## 1. Baseline

`mise run parity` renders the reference films with the current release binary, scores each against the capture its `references.toml` row names, and prints, per film, its summary line (`ctry  ssim 0.7732  iou 0.9783  idx 0.505  scored 114/140`) and its expected line (method.md § 1).

* `--no-build` reuses the release binary (a parallel session may hold it); the drift check then assumes the binary came from the checkout.
* `--no-render` re-scores the existing `_current` trees.
* `--retime N` scores the render relabelled by N ticks ([`probes.md`](../../research/parity/probes.md) section 6) and writes a `_retime<N>` report instead of overwriting the baseline report. On its own it renders first, which moves `_current` into `previous`; to retime the existing render, add `--no-render --no-build`.
* `--reuse build/parity/previous` scores the previous render without re-rendering. Without `--retime` its report replaces `build/parity/report/<film>_current`, so copy that report first or score the previous render by hand into another directory (section 5).

The latest render and report are `build/parity/ours/<film>_current` and `build/parity/report/<film>_current`. A capture missing from `<data root>/captures/<slug>/frames` is named with the command that makes it.

## 2. Capture a reference

Once per `PLAYONE` build: `mise run capture-ref`; another film: `mise run capture-ref -- --film corpus/stisldem/VAULT/INTRO.FLM` ([`capture.md`](../../research/playone-exe/capture.md) § 4). By default a successful capture replaces the film's stored capture, `<data root>/captures/<slug>/frames`, by swap, and until `research/parity/references.toml` is updated a replaced reference fails its pinned hash; `--out <dir>` writes a separate capture and replaces nothing. A capture meant to become a reference is taken with the default parameters, so it lands in the store ([ADR 0028](../adr/0028-a-film-has-one-capture-of-each-kind.md)); promoting it is a reviewed commit to `references.toml`, which names it by film slug and content hash, and `mise run capture-digest -- <slug>` prints the entry that pins it. The film-clock tags are read at the player's `DS`, which differs per build: the capture takes it from the layout matching `PLAYONE.EXE`'s SHA-256 ([`tac/playone.py`](../../python/stunt_reel/tac/playone.py); `0x0F46` for the unpatched demo under dosbox-automation).

## 3. Keep a baseline

* **The previous render.** Before a render replaces it, `mise run parity` renames the outgoing `build/parity/ours/<film>_current` to `build/parity/previous/<film>` (a rename, so the tree is never duplicated) and prints the re-score command. Only one prior tree per film is kept.
* **A pinned baseline.** Copy the render and report trees to names ending `_base` (`build/parity/ours/ctry_base`, `build/parity/report/ctry_base`). A report without its render directory cannot draw the before panels.
* **Another binary.** `mise run build-at -- <rev> <out>` builds a revision in a detached worktree with an isolated `target/build-at` and copies the binary to `<out>`; it never touches the current checkout.
* **Disk.** `mise run clean -- --parity --keep N --yes` reports the scratch trees in `build/parity/ours` and `build/scratch/sweep` (about 19.7 GB at one point) and removes all but the newest N per root, never `_current` or `_base`. It does not scan `build/parity/previous`.

## 4. Render by hand

```bash
stuntreel --headless <film>.FLM --all <film>.ALL --tick-range 0..=1342 --sidata <SIDATA> \
    --out-dir build/parity/ours/ctry --width 320 --height 200 --viewport-rows 185
```

`mise run parity` runs this command with the tick range of the capture's ticks, or `--at-ticks` for chosen ticks (`render_film` in [`parity_pipeline.py`](../../python/stunt_reel/parity_pipeline.py)), which resolves the `.ALL` by the row's pinned `all_sha256`.

* `--tick-range A..=B` is 0-based and inclusive; each tick is stored under its own tick (`458..=458` stores tick 458). Render the whole captured span (`159..=728` for the `COL3-2.FLM` capture): a tick outside the range counts as missing. The earlier `--frames A..B` is an error.
* `--width 320 --height 200`: the parity command rejects 320x240 input. `--viewport-rows 185` because the 3D view fills 185 rows.
* `--headless --out-dir` writes the render store ([ADR 0027](../adr/0027-renders-store-planes-in-per-second-zstd-chunks.md)): `frames.zst`, `layers.zst`, `palettes.zst` (the distinct palettes in one zstd frame; `frames.zst` and `layers.zst` hold one zstd frame per film second), `render.json` (written last: film identity, raster geometry, each tick's palette variables, palette index and camera, and the chunk table) and one `preview/sec_NNNN.png` per film second. A directory without one, or with a `render.json` older than schema 3, is refused: re-render it.
* `--frame-step N` samples every N ticks, which keeps long films from filling the disk.
* `--sample-count` or `--video` samples off whole ticks, written as `sample_%04d.png` (1-based); these are not parity inputs.
* `--video <path>` (`.mp4`, `.webm`, `.mkv`, `.avi`) pipes frames to `ffmpeg` at `--fps` (default 30) from the 50 Hz timeline with 4:3 correction (320x240, `[I6]`), interpolating between slice keyframes, and trims the container to the authored span with `-t`. `--fps` then drives the loop and `--frame-step` is ignored. Without `ffmpeg` on `PATH` the command exits with a diagnostic. `CTRY.FLM` (1,342 ticks, 26.84 s) samples 806 frames at 30 fps; ffmpeg encodes 805 and reports 26.833 s (26.84 s exactly at `--fps 50`).

## 5. Score and compare by hand

```bash
stuntreel parity --reference <data root>/captures/<slug>/frames --test build/parity/ours/<film> \
    --output build/parity/report/<film> \
    --compare <previous report.json> --compare-test <previous render dir> \
    --noise-sigma <σ> --build-floor 0
```

* `parity` refuses a render whose film identity conflicts with the capture's: the `.FLM` name, size or hash, or the archive hash. `--waive-archive-conflict` lets an archive-only conflict through for a deliberate stand-in (a superset render against an own-archive capture) and marks the report `archive_conflict_waived`; `mise run parity` never passes it. When either side records no archive hash, `stuntreel parity` scores and prints `archive not checked`.
* Every run writes `report.json` and `contact_NNNN.png` sheets (`reference | rendered | |difference|`), which show only the first frame; `--compare` adds `compare.json`.
* `--compare` prints the means over the common frames, the 5 most improved and regressed frames and the count moved by more than 0.005, and writes `compare.json`.
* `--compare-test` adds the verdict on the windows the change touched, for example `[verdict] changed 27/121 frames: 15 closer, 12 further, 0 within noise; mean Δ +0.101 on changed windows`.
* `--noise-sigma` is the film's `noise_sigma` in `references.toml`; omit it for a film whose row has none, and the verdict then goes by the sign of Δ (only a Δ of exactly 0 is within noise). `--build-floor` labels frames with at most N changed pixels as build noise. Both need `--compare-test`, which needs `--compare`.

## 6. Look at the worst movers

Open `compare_regressed_tick_NNNNN.png` and `compare_improved_tick_NNNNN.png` (`reference | before | after | |ref-before| | |ref-after|`), one each for the single biggest mover each way by the verdict's Δ (when `--compare-test` is not a readable render store, the verdict and both sheets are skipped: re-render it), before trusting the mean; a mean can hide a regression or an improvement. Diagnose one discrepancy with the probes in [`probes.md`](../../research/parity/probes.md) (crop, silhouette offset, actor-window IoU, candidate sweeps).

For a side-by-side of one tick, read the capture with `read_capture` in `stunt_reel.parity_artifacts` and take the frame whose `film_tick` is that tick: `tick_NNNN.idx` is numbered by capture order, not by tick, and `read_capture` supplies the capture-order file names when an older `meta.json` omits `frame_file` and `palette_file`. Decode its frame (64000 bytes, 320x200) with its palette (`read_capture_palette`). For ours, `RenderStore(...).frame(tick)` returns a `StoredFrame` whose picture is `palette[index]` at every pixel of `indices`. A second's `preview/` PNG shows only that second's first tick, so use it only when that is the tick you want.

## 7. Record the result

Write a journal entry in the work item's `journal.md` ([`work/README.md`](../../work/README.md#journal-entries)): commit hash, matched frames, means, the reason for any movement, and the verdict. `mise run parity-probe -- summary --report build/parity/report/ctry_current/report.json` prints the scores and worst frames the entry quotes, so nothing is retyped by hand. A PR that adopts a change updates the expected table of each reference film for the renderer class it measured (`ssim`, `iou`, `adapter`, the row's `sha256` and `all_sha256`, and `crates` from `git rev-parse <commit>:crates`, rendered with `crates/` clean; [method § 1](../../research/parity/method.md#1-the-loop) step 0); the other class keeps its older entry until someone measures it. Commit `crates/`, run `mise run parity` without `--no-build`, `--no-render`, `--reuse` or `--retime`, then `mise run parity-repin -- [--class gpu|lavapipe]`: it writes every film's table from its report, or writes nothing and says which film's report is missing, was rendered on another tree or another class, or that `crates/` is dirty.
