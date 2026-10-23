# Parity Probes: Diagnosing One Discrepancy

Procedures for finding out *what* is wrong once [`method.md`](method.md) says *where* the loss is. Terms are those of [`GLOSSARY.md`](../../GLOSSARY.md). Dated outcomes are in [`../parity-findings.md`](../parity-findings.md); the helpers are [`python/scripts/parity_probe.py`](../../python/scripts/parity_probe.py) and [`parity_sweep.py`](../../python/scripts/parity_sweep.py).

All probes read a capture directory (`build/parity/reference/<film>`, `tick_NNNN.idx` by ordinal) and a render directory (`tick_NNNNN.idx` and `.layer` by film tick). "Object pixels" are capture pixels that are not sky, ground ramp, button bar or cursor; the index ranges in the script are `CTRY.FLM`'s and must be changed per film.

## 1. Side-by-side crop (`crop`)

```bash
python python/scripts/parity_probe.py crop --ours build/parity/ours/ctry 9 97 60 20 260 160 --out build/scratch/crop.png
```

Capture on top, ours below, one frame region, nearest-neighbour scaled. Use it on any frame before trusting a score change: it is how the orientation sweep's best candidate was seen to be a plan view of the wrong aircraft.

## 2. Silhouette offset (`shift`)

Slides our actor silhouette (layer id 16 and up) over the capture's object pixels and prints, per scored frame, `film_tick`, silhouette size, best `dx`, `dy` and the hit fraction. A consistent `dy` across frames with a stable silhouette size means a placement error rather than a shape error. It showed the CTRY hero aircraft 10 to 14 rows low ([`parity-findings.md` § 11](../parity-findings.md)).

## 3. Actor-window IoU (`iou`)

IoU of our actor pixels against capture object pixels inside the actor's bounding box padded by 25 px, averaged over every second scored frame. Whole-film SSIM could not rank 48 model orientations (0.770 to 0.777); this can.

**Trap (`[Bounded Observation]`).** IoU rewards silhouette coverage. The best of 48 orientations scored 0.247 against 0.109 for the current one, yet its crop was a monoplane seen from above while the capture is a biplane seen from behind at about 45 degrees. Treat an IoU gain as a lead, and confirm it with a crop (section 1).

## 4. Candidate sweeps

For a hypothesis with a few dozen variants (axis permutations, Euler order and signs, camera or actor offsets):

1. Add a temporary `DBG_<NAME>` environment switch at the one place the variant applies (read with `std::env::var`), never committed.
2. Run [`python/scripts/parity_sweep.py`](../../python/scripts/parity_sweep.py), as one command (in the background if the product is large):

   ```bash
   mise run sweep -- --var DBG_PITCH=0,-2 --var DBG_DY=0,-0.3 [--films ctry,intro] [--probe film|iou] [--keep-best]
   ```

   It builds `stunt-cli` once, renders every combination of the `--var` values for each film with those variables in the environment (flags and clear index from [`method.md`](method.md) section 1; the per-film inputs are one table at the top of the script), scores each with `stuntreel parity`, and prints one line per variant sorted best first, then the winner. Both films are the default and the ranking is by mean SSIM over them, so a CTRY-only gain that costs INTRO shows up in the table. A render takes about 7 s for CTRY and 8 s for INTRO. Render directories go under `build/scratch/sweep/` and are deleted after scoring.
3. `--probe iou` adds the actor-window IoU of section 3 per film, for a hypothesis about an actor (it uses CTRY's background index ranges for every film, so read INTRO's figure with care). `--keep-best` keeps the winner's render directory and writes `crop_<film>.png` there: section 1's crop of the frame with the largest actor. Look at it before trusting a score change.
4. Re-run the winner against the other film if `--films` narrowed the sweep. Three CTRY-only gains (camera height, terrain base, hero lift) regressed `INTRO.FLM` and were not adopted.
5. `git checkout crates` to remove the switch, and record the outcome, including a negative one, in `parity-findings.md`.

`--data-root <dir>` points the tool at another checkout's `corpus/` and `build/parity/reference/` (a worktree has neither). Smoke check: with an eye-height switch, `DBG_EYE_DY=0,-0.3` reproduces [`parity-findings.md` § 11](../parity-findings.md) (CTRY 0.771 and 0.782, INTRO 0.676 and 0.669).

## 5. Environment pitfalls

* Python on Windows opens text as cp1252: pass `encoding="utf-8"` or read bytes, or a `§` is written as byte `0xA7` and `ruff` rejects the file.
* wgpu's maximum buffer is 256 MiB. An 80-face sphere (700 MB on CTRY) and the 20-face INTRO world (312 MB) both exceeded it; spheres are 20-face and sub-pixel props are culled (`parity-findings.md` § 10).
* Capture indices are named by ordinal and renders by film tick; match them through `report.json`'s `per_frame` entries, not by number.
