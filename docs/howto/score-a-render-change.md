# Score a render change against PLAYONE

The commands of the parity loop.
What each step measures, and how to read its output, is [`research/parity/method.md`](../../research/parity/method.md) § 1; the field tables of `report.json` and `compare.json` are [`report-fields.md`](../../research/parity/report-fields.md).

## 1. Baseline

`mise run parity` renders the reference films with the current release binary, scores each against the capture its `references.toml` row names, and prints, per film, its summary line (`ctry  ssim 0.7732  iou 0.9783  idx 0.505  scored 114/140`) and its expected line (method.md § 1).

* `--no-build` reuses the release binary (a parallel session may hold it); the drift check then assumes the binary came from the checkout.
* `--no-render` re-scores the existing `_current` trees.
  On a clean `crates/`, when the render records the tree that built it (a render `mise run parity` built and rendered on a clean `crates/` does) and `crates/` differs from that tree only under `crates/stunt-score/src/parity/` (the scorer), it records `crates` in the report, so `parity-repin` accepts it; any other change, or an older render, needs a render.
* `--retime N` scores the render relabelled by N ticks ([`probes.md`](../../research/parity/probes.md) section 6) and writes a `_retime<N>` report instead of overwriting the baseline report.
  On its own it renders first, which moves `_current` into `previous`; to retime the existing render, add `--no-render --no-build`.
* `--reuse build/parity/previous` scores the previous render without re-rendering.
  Without `--retime` its report replaces `build/parity/report/<film>_current`, so copy that report first or score the previous render by hand into another directory (section 5).

The latest render and report are `build/parity/ours/<film>_current` and `build/parity/report/<film>_current`.
A capture missing from `<data root>/captures/<slug>/frames` is named with the command that makes it.

## 2. Capture a reference

Once per `PLAYONE` build: `mise run capture-ref`; another film: `mise run capture-ref -- --film corpus/stisldem/VAULT/INTRO.FLM` ([`capture.md`](../../research/playone-exe/capture.md) § 4).
By default a successful capture replaces the film's stored capture, `<data root>/captures/<slug>/frames`, by swap, and until `research/parity/references.toml` is updated a replaced reference fails its pinned hash; `--out <dir>` writes a separate capture and replaces nothing.
A capture meant to become a reference is taken with the default parameters, so it lands in the store ([ADR 0028](../adr/0028-a-film-has-one-capture-of-each-kind.md)); promoting it is a reviewed commit to `references.toml`, which names it by film slug and content hash, and `mise run capture-digest -- <slug>` prints the entry that pins it.
The film-clock tags are read at the player's `DS`, which differs per build: the capture takes it from the layout matching `PLAYONE.EXE`'s SHA-256 ([`tac/playone.py`](../../python/stunt_reel/tac/playone.py); `0x0F46` for the unpatched demo under dosbox-automation).

## 3. Keep a baseline

* **The previous render.**
  Before a render replaces it, `mise run parity` renames the outgoing `build/parity/ours/<film>_current` to `build/parity/previous/<film>` (a rename, so the tree is never duplicated) and prints the re-score command.
  Only one prior tree per film is kept.
* **A pinned baseline.**
  Copy the render and report trees to names ending `_base` (`build/parity/ours/ctry_base`, `build/parity/report/ctry_base`).
  A report without its render directory cannot draw the before panels.
* **Another binary.**
  `mise run build-at -- <rev> <out>` builds a revision in a detached worktree with an isolated `target/build-at` and copies the binary to `<out>`; it never touches the current checkout.
* **Disk.**
  `mise run clean -- --parity --keep N --yes` reports the scratch trees in `build/parity/ours` and `build/scratch/sweep` (about 19.7 GB at one point) and removes all but the newest N per root, never `_current` or `_base`.
  It does not scan `build/parity/previous`.

## 4. Render by hand

```bash
stuntreel --headless <film>.FLM --all <film>.ALL --tick-range 0..=1342 --sidata <SIDATA> \
    --out-dir build/parity/ours/ctry --width 320 --height 200 --viewport-rows 185
```

`mise run parity` runs this command with the tick range of the capture's ticks, or `--at-ticks` for chosen ticks (`render_film` in [`parity_pipeline.py`](../../python/stunt_reel/parity_pipeline.py)), which resolves the `.ALL` by the row's pinned `all_sha256`.

* `--tick-range A..=B` is 0-based and inclusive; each tick is stored under its own tick (`458..=458` stores tick 458).
  Render the whole captured span (`159..=728` for the `COL3-2.FLM` capture): a tick outside the range counts as missing.
  The earlier `--frames A..B` is an error.
* `--width 320 --height 200`: the parity command rejects 320x240 input.
  `--viewport-rows 185` because the 3D view fills 185 rows.
* `--headless --out-dir` writes the render store ([ADR 0027](../adr/0027-renders-store-planes-in-per-second-zstd-chunks.md)): `frames.zst`, `layers.zst`, `palettes.zst` (the distinct palettes in one zstd frame; `frames.zst` and `layers.zst` hold one zstd frame per film second), `shapes.zst` (the shape plane the props-loss split reads, one zstd frame per film second; only the Rust store decodes it, and a render whose `render.json` does not list it scores without the split), `render.json` (written last: film identity, raster geometry, each tick's palette variables, palette index and camera, the chunk table, and each optional plane it holds with that file's SHA-256 and chunk spans) and one `preview/sec_NNNN.png` per film second.
  A directory without one, with a `render.json` older than schema 4, or with a listed plane whose file is missing or differs from its listing, is refused: re-render it.
* `--frame-step N` samples every N ticks, which keeps long films from filling the disk.
* `--sample-count` or `--video` samples off whole ticks, written as `sample_%04d.png` (1-based); these are not parity inputs.
* `--video <path>` (`.mp4`, `.webm`, `.mkv`, `.avi`) pipes frames to `ffmpeg` at `--fps` (default 30) from the 50 Hz timeline with 4:3 correction (320x240, `[I6]`), interpolating between slice keyframes, and trims the container to the authored span with `-t`.
  `--fps` then drives the loop and `--frame-step` is ignored.
  Without `ffmpeg` on `PATH` the command exits with a diagnostic.
  `CTRY.FLM` (1,342 ticks, 26.84 s) samples 806 frames at 30 fps; ffmpeg encodes 805 and reports 26.833 s (26.84 s exactly at `--fps 50`).

## 5. Score and compare by hand

```bash
stuntreel parity --reference <data root>/captures/<slug>/frames --test build/parity/ours/<film> \
    --output build/parity/report/<film> \
    --compare <previous report.json> --compare-test <previous render dir> \
    --noise-sigma <σ> --build-floor 0
```

* `parity` refuses a render whose film identity conflicts with the capture's: the `.FLM` name, size or hash, or the archive hash.
  `--waive-archive-conflict` lets an archive-only conflict through for a deliberate stand-in (a superset render against an own-archive capture) and marks the report `archive_conflict_waived`; `mise run parity` never passes it.
  When either side records no archive hash, `stuntreel parity` scores and prints `archive not checked`.
* Every run writes `report.json` and `contact_NNNN.png` sheets (`reference | rendered | |difference|`), which show only the first frame; `--compare` adds `compare.json`.
* `--compare` prints the means over the common frames, the 5 most improved and regressed frames and the count moved by more than 0.005, and writes `compare.json`.
* `--compare-test` adds the verdict on the windows the change touched, for example `[verdict] changed 27/121 frames: 15 closer, 12 further, 0 within noise; mean Δ +0.101 on changed windows`.
* `--noise-sigma` is the film's `noise_sigma` in `references.toml`; omit it for a film whose row has none, and the verdict then goes by the sign of Δ (only a Δ of exactly 0 is within noise).
  `--build-floor` labels frames with at most N changed pixels as build noise.
  Both need `--compare-test`, which needs `--compare`.

## 6. Look at the worst movers

Open `compare_regressed_tick_NNNNN.png` and `compare_improved_tick_NNNNN.png` (`reference | before | after | |ref-before| | |ref-after|`), one each for the single biggest mover each way by the verdict's Δ (when `--compare-test` is not a readable render store, the verdict and both sheets are skipped: re-render it), before trusting the mean; a mean can hide a regression or an improvement.
Diagnose one discrepancy with the probes in [`probes.md`](../../research/parity/probes.md) (crop, silhouette offset, actor-window IoU, where one palette index lies, candidate sweeps).

For a side-by-side of one tick, read the capture with `read_capture` in `stunt_reel.parity_artifacts` and take the frame whose `film_tick` is that tick: `tick_NNNN.idx` is numbered by capture order, not by tick, and `read_capture` supplies the capture-order file names when an older `meta.json` omits `frame_file` and `palette_file`.
Decode its frame (64000 bytes, 320x200) with its palette (`read_capture_palette`).
For ours, `RenderStore(...).frame(tick)` returns a `StoredFrame` whose picture is `palette[index]` at every pixel of `indices`.
A second's `preview/` PNG shows only that second's first tick, so use it only when that is the tick you want.

## 7. Record the result

Write a journal entry in the work item's `journal.md` ([`work/README.md`](../../work/README.md#journal-entries)): commit hash, matched frames, means, the reason for any movement, and the verdict, linking the sweep's figures file when a sweep gave it (§ 8).
`mise run parity-probe -- summary --report build/parity/report/ctry_current/report.json` prints the scores and worst frames the entry quotes, so nothing is retyped by hand.
A PR that adopts a change repins the expected tables of each reference film in `research/parity/expected/lavapipe.toml`, rendered on the canonical lavapipe (`ssim`, `iou`, `adapter`, the row's `sha256` and `all_sha256`, and `crates` from `git rev-parse <commit>:crates`, rendered with `crates/` clean; [method § 1](../../research/parity/method.md#1-the-loop) step 0): a cloud session, or local-windows through the WSL lavapipe ([`render-on-lavapipe.md` § 5](render-on-lavapipe.md#5-render-the-canonical-lavapipe-under-wsl)), whichever renderer class gave the verdict.
No PR repins `gpu`: the class agreement batch writes `expected/gpu.toml` ([`run-the-agreement-batch.md`](run-the-agreement-batch.md), [ADR 0055](../adr/0055-fidelity-pins-on-lavapipe-and-agreement-is-measured-apart.md)).
Commit `crates/`, run `mise run parity` without `--no-build`, `--reuse` or `--retime` (and without `--no-render`, unless `mise run parity` built and rendered it on a clean `crates/` and the commits since changed only `crates/stunt-score/src/parity/`), then `mise run parity-repin -- --class lavapipe`: it regenerates the class's file from every film's report, or writes nothing and says which film's report is missing, was rendered on another tree or another class, was scored against another capture or archive or without recorded pins, or that `crates/` is dirty.

## 8. Judge a candidate against a baseline

The adoption rule ([`loop-rules.md`](../../.agents/skills/improving-render-parity/loop-rules.md#adoption-rule)) is applied by the sweep, from each variant's per-frame scores held in memory once every variant has finished; the join and the rule live in [`parity_judge.py`](../../python/stunt_reel/parity_judge.py).

```bash
mise run sweep -- --var DBG_X=0,1 --track heuristic --record work/<YYYY-MM>/<folder> --topic <words> \
    --target intro:3279-3301 [--target ctry:859-881 ...]
```

* **The baseline** is the variant of each `--var`'s first value (`DBG_X=0` here).
  It is listed in the table and, with `--track`, never wins.
* `--track evidence|heuristic` names the round's track; with it the winner line gives the verdict, and it needs `--record`.
  Without `--track` the sweep ranks by mean SSIM, as it always has, and gives no verdict, but still prints each variant's change against the baseline and the stderr lines below.
* `--target <film>:<lo>-<hi>` names an inclusive range of film ticks on one reference film, repeatable, and needs `--track`.
  Quote the flags in the journal entry before the sweep runs; the sweep echoes them as its first stdout line (`targets: --target intro:3279-3301`).
* Both flags refuse a `--films` subset, `--reuse` and a single variant, since they judge every reference film against a baseline; `--retime` is allowed.
  Before rendering, the sweep stops on a `--target` range holding no tick of the film's reference capture.
  After rendering, a range holding no tick the baseline scores gives `winner: no verdict (...)`, naming it.
* `--record <work folder>` writes the figures file described under **Figures** below, named by `--topic <words>`, which it needs.
* `--images <dir>` draws the pictures described under **Pictures** below; it needs `--topic` and `--target`, and `--crop x0,y0,x1,y1` crops every picture to that box, enlarged 3 times.
* `--keep-best` with `--track` keeps the top-ranked variant other than the baseline, the winner when one adopts; without `--track` it keeps the top-ranked variant.

**The table** adds, per variant against the baseline: `target dSSIM` and `target dIdx`, the pooled target mean in SSIM and in index agreement; `worst target`, the worst target frame's change in SSIM, which the 0.025 guard reads; `worst frame`, the worst change in SSIM over every scored frame of every film; and `down>0.005`, the count of frames down by more than 0.005.
The baseline's row shows `-`.
Variants that adopt rank first, then by `target dIdx` (with `--target`) and mean SSIM.

**The winner line** names the branch the winner adopts on, or why the best variant other than the baseline does not:

```
winner: DBG_X=1 adopts (heuristic target idx +0.0213, 18/24 frames up; films ok; worst target frame -0.0041 intro:3302)
winner: DBG_X=1 adopts (evidence, film means; target idx +0.0071 attribution; worst target frame +0.0012 intro:3290; 3 frames down >0.005, listed)
winner: none adopts (best DBG_X=1: target-frame guard ctry:871 -0.0639)
winner: no verdict (baseline film ctry failed)
```

The failing reason is the first guard or test the variant fails: `film <film> failed`, `lost ticks`, `target-frame guard`, `film-mean guard`, `no film rises` (evidence-backed), or the film-mean branch falling short followed by the target branch's first failed condition (heuristic).
On an adopting winner line, `thin evidence: 3 target frames` marks a verdict at the 3-frame minimum and `target branch not run` a heuristic round with fewer; a heuristic rejection with fewer says `target branch needs 3 scored target frames`.
The note on a lead under 0.002 over the next variant stays.

**Stderr** describes the winner, or the best variant other than the baseline when none adopts: one line lists every frame down by more than 0.005 (`ctry:871 -0.0639, ...`), one counts per film the frames outside the target that moved by more than 0.005 (the side effects), and one more flags each edge frame, the baseline's nearest scored tick before or after a range, when it fell by more than 0.010 in SSIM.
An edge frame is a report and never changes the verdict.

**Pictures.**
`--images <dir> --topic <words>` (normally `work/<YYYY-MM>/<folder>/images` and a few words such as `conifer edge`) draw, once the verdict is in, one PNG per chosen tick of the winner, or of the best variant when none adopts: the capture, the baseline and the winner, left to right, with a magenta divider, named `<film>-<tick>-<topic>.png` as [`work/README.md`](../../work/README.md#images) asks.
Only those ticks are re-rendered, with `--at-ticks`, as `mise run frame --var` does; stdout is unchanged and the paths go to stderr.
Without `--crop` a picture is the whole 320x200 frame.

* **Which ticks.**
  For each targeted film, up to 5 target frames: the lowest change in whole-frame SSIM first, then the rest in descending change, each at least 50 ticks from every tick already chosen; if fewer than 5 are chosen, the spacing falls to 25 and the list is gone down again, so a film may get fewer than 5.
  Outside that cap, each film whose worst frame fell by more than 0.005 gets one picture of that frame, `<film>-<tick>-<topic>-guard.png` (not drawn twice when it is already a pick).
* **Refusals.**
  The sweep stops before rendering when `--images` lacks `--topic` or `--target`, when `--crop` lacks `--images` or is not a box on the 320x200 screen, when `--images` is not a directory, or when it already holds a picture of that topic (`<film>-<tick>-<topic>.png`, with or without `-guard`), since a picture is never replaced: name another `--topic`.
  A sweep that gives no verdict draws nothing and says so on stderr.
* **Citing.**
  Commit the pictures with the journal entry, which cites each one and names the commit each render panel came from; a round that is not adopted commits its pictures too.
  [`NOTICE.md`](../../NOTICE.md#illustrative-comparison-images) sets the limits.

**Figures.**
`--record <work folder> --topic <words>` writes, once the verdict is in, `<work folder>/sweeps/<topic>.toml`, the topic slugged as in a picture's name ([`parity_figures.py`](../../python/stunt_reel/parity_figures.py) has the layout).
It holds, per variant, each film's headline SSIM and IoU and, per frame, the `film_tick`, SSIM, index agreement and `scored` the judge reads from `report.json`; then the `--track` and `--target` flags, the baseline, the bounds the adoption rule applied, and the winner line as printed, without `--keep-best`'s `; kept` note.
Its path goes to stderr.

* **Who needs it.**
  `--track` refuses to run without `--record`: a verdict's figures are committed with its journal entry.
  An untracked, exploratory sweep may record too, and need not.
* **Refusals.**
  Before rendering, the sweep refuses `--record` without `--topic` or with `--reuse`, `--topic` with neither `--record` nor `--images`, a directory that is not a work folder, a work folder whose README has an `outcome` (it is frozen), and a figures file of that topic that exists, since a figures file is never replaced: name another `--topic`.
* **Citing.**
  Commit the file with the journal entry, which links it, beside the round's pictures.
  Scores are this project's own measurements ([`NOTICE.md`](../../NOTICE.md#scores-and-metrics)).

**Rechecking a verdict.**
`mise run judge -- --recheck <work folder>/sweeps/<topic>.toml` reads that file and nothing else.
It judges the variants again by the bounds the file records and prints what the sweep printed: the targets line, the table and the winner line on stdout, the listed frames on stderr.
It exits 1, naming the recorded line, when its winner line differs from the recorded one, and 2 on a file it cannot read.
When today's bounds in [`parity_judge.py`](../../python/stunt_reel/parity_judge.py) would give another verdict (another winner, or none), it adds a note on stderr naming each changed bound and today's winner line, and still exits 0, so a frozen record stays reproducible.
A reviewer recomputing a quoted sweep verdict ([`AGENTS.md`](../../AGENTS.md#committing) § 3, Committing, rule 5) runs it and compares its output with what the diff quotes.

**Two existing report trees.**
`mise run judge -- <baseline report dir> <candidate report dir> [--target ...] [--track ...]` prints the same table and winner line for two `stuntreel parity` runs, the rows labelled `run=baseline` and `run=candidate`.
A report dir holds each film's report as `<film>_report/report.json` (a sweep variant kept by `--keep-best`), `<film>_current/report.json` (`build/parity/report`) or `<film>/report.json`; a film without one counts as failed on that side.
On stderr it also prints, per film, both reports' `mean_index_agreement_scored` and the counts of frames where the candidate's `index_agreement` is better, equal or worse than the baseline's, pairing frames by `ordinal` over those scored in both reports (every frame when a report predates fade scoring).
These counts are information for a tie fix, whose SSIM may hide a few moved pixels; the verdict and `--recheck` ignore them.
It then prints one line per film with the candidate's change in each class's `mean_loss_by_class_scored` from the baseline's and, in parentheses, from the class losses pinned in `[<film>.loss]` of `research/parity/expected/<class>.toml` for the renderer class of the candidate's adapter.
A class moving less than 0.00005 on both comparisons is left out; a report or pin with no class losses, or one naming other classes than the rest, gets a line saying so.
This shows where an adoption moved the loss when the film mean nets out, and it is information too.
To judge two commits, copy `build/parity/report` aside after `mise run parity` on the first, then run it on the second.
