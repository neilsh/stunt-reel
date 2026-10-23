# Parity Probes: Diagnosing One Discrepancy

Procedures for finding out *what* is wrong once [`method.md`](method.md) says *where* the loss is. Terms are those of [`GLOSSARY.md`](../../GLOSSARY.md). Dated outcomes are in [`../parity-findings.md`](../parity-findings.md); the helper is [`python/scripts/parity_probe.py`](../../python/scripts/parity_probe.py).

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

1. Add a temporary `DBG_<NAME>=k` environment switch at the one place the variant applies, never committed.
2. `cargo build --release -p stunt-cli`, then run `target/release/stuntreel.exe --headless ... --out-dir build/parity/ours/<name>_$k` once per `k`. Calling the binary directly is faster than `cargo run` per candidate; run the loop in the background.
3. Score each `k` with the probe that isolates the thing under test (section 3 for an actor), then delete its render directory.
4. Crop the winner (section 1), then re-score **both** films. Three CTRY-only gains (camera height, terrain base, hero lift) regressed `INTRO.FLM` and were not adopted.
5. `git checkout crates` to remove the switch, and record the outcome, including a negative one, in `parity-findings.md`.

## 5. Environment pitfalls

* Python on Windows opens text as cp1252: pass `encoding="utf-8"` or read bytes, or a `§` is written as byte `0xA7` and `ruff` rejects the file.
* wgpu's maximum buffer is 256 MiB. An 80-face sphere (700 MB on CTRY) and the 20-face INTRO world (312 MB) both exceeded it; spheres are 20-face and sub-pixel props are culled (`parity-findings.md` § 10).
* Capture indices are named by ordinal and renders by film tick; match them through `report.json`'s `per_frame` entries, not by number.
