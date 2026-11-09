# Score a render change against PLAYONE

The commands of the parity loop. What each step measures, and how to read its output, is [`research/parity/method.md`](../../research/parity/method.md) § 1; the field tables of `report.json` and `compare.json` are its § 1.3.

## 1. Baseline

`mise run parity` renders the reference films with the current release binary, scores each against the capture its `references.toml` row names, and prints, per film, its summary line (`ctry  ssim 0.7732  iou 0.9783  idx 0.505  scored 114/140`) and its expected line (method.md § 1).

* `--no-build` reuses the release binary (a parallel session may hold it); the drift check then assumes the binary came from the checkout.
* `--no-render` re-scores the existing `_current` trees.
* `--retime N` scores the render relabelled by N ticks ([`probes.md`](../../research/parity/probes.md) section 6) and writes a `_retime<N>` report instead of overwriting the baseline report. On its own it renders first, which moves `_current` into `previous`; to retime the existing render, add `--no-render --no-build`.
* `--reuse build/parity/previous` scores the previous render without re-rendering. Without `--retime` its report replaces `build/parity/report/<film>_current`, so copy that report first or score the previous render by hand into another directory (section 5).

The latest render and report are `build/parity/ours/<film>_current` and `build/parity/report/<film>_current`. A capture missing from `<data root>/captures/<slug>/frames` is named with the command that makes it.

## 2. Capture a reference

Once per `PLAYONE` build: `mise run capture-ref`; another film: `mise run capture-ref -- --film corpus/stisldem/VAULT/INTRO.FLM` ([`capture.md`](../../research/playone-exe/capture.md) § 4). By default a successful capture replaces the film's stored capture, `<data root>/captures/<slug>/frames`, by swap, and until `research/parity/references.toml` is updated a replaced reference fails its pinned hash; `--out <dir>` writes a separate capture and replaces nothing. Promoting a capture is a reviewed commit to `references.toml`, which names it by film slug and content hash. The film-clock tags are read at the player's `DS`, which differs per build, so `DS` (`0x1575` for the demo) is a capture parameter.

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
* `--headless --out-dir` writes the render store ([ADR 0027](../adr/0027-renders-store-planes-in-per-second-zstd-chunks.md)): `frames.zst`, `layers.zst`, `palettes.zst`, `render.json` and one `preview/sec_NNNN.png` per film second. A directory without one, or with a `render.json` older than schema 3, is refused: re-render it.
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

* Every run writes `report.json` and `contact_NNNN.png` sheets (`reference | rendered | |difference|`), which show only the first frame; `--compare` adds `compare.json`.
* `--compare` prints the means over the common frames, the 5 most improved and regressed frames and the count moved by more than 0.005, and writes `compare.json`.
* `--compare-test` adds the verdict on the windows the change touched, for example `[verdict] changed 27/121 frames: 15 closer, 12 further, 0 within noise; mean Δ +0.101 on changed windows`.
* `--noise-sigma` is the film's `noise_sigma` in `references.toml`; omit it for a film whose row has none, and the verdict then goes by the sign of Δ (only a Δ of exactly 0 is within noise). `--build-floor` labels frames with at most N changed pixels as build noise.

## 6. Look at the worst movers

Open `compare_regressed_*.png` and `compare_improved_*.png` (`reference | before | after | |ref-before| | |ref-after|`) before trusting the mean; a mean can hide a regression or an improvement. Diagnose one discrepancy with the probes in [`probes.md`](../../research/parity/probes.md) (crop, silhouette offset, actor-window IoU, candidate sweeps).

For a side-by-side of one tick, decode a reference `.idx` page (64000 bytes, 320x200) with its `palettes_NNNN.json` and paste it beside ours, `RenderStore(...).frame(tick)` in `stunt_reel.parity_artifacts`. A second's `preview/` PNG shows only that second's first tick, so use it only when that is the tick you want.

## 7. Record the result

Write a journal entry in the work item's `journal.md` ([`work/README.md`](../../work/README.md#journal-entries)): commit hash, matched frames, means, the reason for any movement, and the verdict. `mise run parity-probe -- summary --report build/parity/report/ctry_current/report.json` prints the scores and worst frames the entry quotes, so nothing is retyped by hand. A PR that adopts a change updates the expected table of each reference film for the renderer class it measured (`ssim`, `iou`, `adapter` and the `commit` measured); the other class keeps its older entry until someone measures it.
