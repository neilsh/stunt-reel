---
summary: "Procedures for diagnosing one parity discrepancy: `parity_probe.py` crop, shift, iou and retime, `DBG_` switch sweeps via `mise run sweep`, capture-side experiments, and environment pitfalls."
---
# Parity Probes: Diagnosing One Discrepancy

Procedures for finding out *what* is wrong once [`method.md`](method.md) says *where* the loss is. Terms are those of [`GLOSSARY.md`](../../GLOSSARY.md). Dated outcomes go in journal entries; earlier ones are rows of the [parity log](../../work/2026-10/parity-log/log.md) and the notes it links; the helpers are [`python/scripts/parity_probe.py`](../../python/scripts/parity_probe.py) and [`parity_sweep.py`](../../python/scripts/parity_sweep.py).

All probes read a capture directory (`<data root>/captures/<film>/<id>`, `tick_NNNN.idx` by ordinal) and a render store (index and layer planes by film tick, read through `RenderStore`). "Object pixels" are capture pixels outside the film's `background` bands and not index 0 or 255; `shift` and `iou` take the backdrop index bands from the `background` field of the `references.toml` row of the film the capture's `meta.json` names, and refuse a film whose row has none (every reference film's row records one; [section 3](#3-actor-window-iou-iou)).

## 1. Side-by-side crop (`crop`)

```bash
python python/scripts/parity_probe.py crop --ours build/parity/ours/ctry 9 97 60 20 260 160 --out build/scratch/crop.png
```

Capture on top, ours below, one frame region, nearest-neighbour scaled. Use it on any frame before trusting a score change: it is how the orientation sweep's best candidate was seen to be a plan view of the wrong aircraft.

## 2. Silhouette offset (`shift`)

Slides our actor silhouette (layer id 16 and up) over the capture's object pixels and prints, per scored frame, `film_tick`, silhouette size, best `dx`, `dy` and the hit fraction. A consistent `dy` across frames with a stable silhouette size means a placement error rather than a shape error. It showed the CTRY hero aircraft 10 to 14 rows low ([`hero-aircraft-placement.md`](hero-aircraft-placement.md)).

Each row also gives the world's own shift in the same frame: the whole-frame `dx`, `dy` (every even offset up to `--world-reach`, default 12, ties going to the smaller shift) that makes the most of our non-actor pixels equal the capture's index, with our actor left out and so is every capture object pixel within 8 px of our silhouette moved by the actor shift (the capture's aircraft, even where it is larger than ours, while scenery away from every actor stays in), and that fraction (`world_agree`). The closing line gives the medians of the actor shift, the world shift and actor minus world. Read the actor residual against that difference, not against a world baseline copied from an older note: the world's own shift moves whenever the camera or projection changes (it went from about -4 rows to 0 with the 256 px projection). `world_agree` compares raw palette indices, not colours, so it is low where the two pick different indices (terrain shading, dithering) and blind to a palette whose colours differ at the same index; the SSIM capture-shift scores in [`attribution.md`](attribution.md#ruled-out) remain the authority for the world's framing.

## 3. Actor-window IoU (`iou`)

IoU of our actor pixels against capture object pixels inside the actor's bounding box padded by 25 px, averaged over every second scored frame. Whole-film SSIM could not rank 48 model orientations (0.770 to 0.777); this can.

**Trap (`[Bounded Observation]`).** IoU rewards silhouette coverage. The best of 48 orientations scored 0.247 against 0.109 for the current one, yet its crop was a monoplane seen from above while the capture is a biplane seen from behind at about 45 degrees. Treat an IoU gain as a lead, and confirm it with a crop (section 1).

**Backdrop bands** (`background` in each `references.toml` row). `[Bounded Observation]`, 2026-11-14, #490 and the #501 review, on a render of `crates` tree `d2cd090` (the `expected.gpu` tables were measured on `adbde141`; every film's score matched them to 1e-6) on an RTX 4070. The rule, one for all six films: an index is backdrop when

* it has at least 0.05 % of the capture's rows 0..184 over capture frames 0, 4, 8, ... of the scored frames (`[0::4]`, 25 to 183 frames);
* at least 85 % of those capture pixels lie where our layer plane is none (0), ocean (1) or terrain (2); an index our render draws mostly on the props layer (3) is scenery and stays out, however large and however well our index agrees;
* **no actor pixel of ours carries it in any scored frame** (layer 16 and up, every scored frame, not the sample): a missing backdrop index only lowers IoU, one an actor paints hides the actor;
* where the layer is mostly ground or sea, our index equals the capture's on at least 90 % of those pixels; where it is mostly none (sky), it lies in 227-238, the sky of `CAPTURE_SKY_INDICES` (`crates/stunt-cli/src/parity/mask.rs`; 224 to 226 and 239 are `[Unknown]` in [`palette-and-shading.md`](../formats/concepts/palette-and-shading.md)).

Reproduce one film's bands after `mise run parity`, from the repo root:

```bash
mise exec -- uv run python - land < snippet.py   # the script below, saved as snippet.py
```

```python
import sys
from pathlib import Path
import numpy as np
from stunt_reel import dataroot
from stunt_reel.matched_frames import Reference
from stunt_reel.parity_artifacts import RenderStore, read_report

film, n = sys.argv[1], 320 * 185  # run from the repo root after `mise run parity`
store = RenderStore(Path(f"build/parity/ours/{film}_current"))
ref = Reference(dataroot.data_root() / "captures" / f"vault-{film}" / "frames", store)
frames = list(ref.from_report(read_report(Path(f"build/parity/report/{film}_current/report.json"))))
actor, count, agree = (np.zeros(256) for _ in range(3))
cap, sky = np.zeros(256), np.zeros(256)
for k, m in enumerate(frames):  # every scored frame: what our actors paint
    layers = np.array(m.page.layers[:n])
    ours = np.frombuffer(m.page.indices, np.uint8)[:n]
    actor += np.bincount(ours[layers >= 16], minlength=256)
    if k % 4:  # capture statistics on frames 0, 4, 8, ...
        continue
    c = np.frombuffer(m.capture_indices(), np.uint8)[:n]
    cap += np.bincount(c, minlength=256)
    sky += np.bincount(c[layers == 0], minlength=256)
    ground = (layers == 1) | (layers == 2)
    count += np.bincount(c[ground], minlength=256)
    agree += np.bincount(c[ground & (c == ours)], minlength=256)
keep = [
    i
    for i in range(1, 255)
    if cap[i] >= 0.0005 * cap.sum()
    and actor[i] == 0
    and (sky[i] + count[i]) >= 0.85 * cap[i]
    and (227 <= i <= 238 if sky[i] > 0.5 * cap[i] else agree[i] >= 0.9 * count[i])
]
bands = []
for i in keep:
    if bands and bands[-1][1] == i - 1:
        bands[-1][1] = i
    else:
        bands.append([i, i])
print(film, bands, f"{100 * cap[keep].sum() / cap.sum():.0f}% of capture pixels")
```

The `ctry` row is #485's and predates this rule (it keeps the ground ramp 192-199 and shade greens 161-165); it was not rederived. Zero tolerance is why the sets are small: the first round, which tolerated 0.1 % actor paint and took props-layer masses, put into bands the parachutist's visor on `balloon` (224), the train's 163 and 164 on `traintnl`, tarmac 13/14 on `land` and `bomb`, sky that cockpit canopies paint on `land` and `location`, and singletons that one shape paints (`location` 76 and 205, `intro` 208).

| Film | `background` | Capture pixels covered | `iou` (every 2nd scored frame) |
|---|---|---|---|
| `ctry` | `[192,199] [228,238] [161,165]` (#485) | not measured | 0.5405 (38) |
| `intro` | `[164,164] [195,195]` | 10 % | 0.1487 (89) |
| `land` | `[164,164] [195,195]` | 34 % | 0.1879 (47) |
| `balloon` | `[162,164] [194,195] [197,198] [208,208] [228,238]` | 57 % | 0.6796 (43) |
| `traintnl` | `[195,195] [228,228] [232,238]` | 62 % | 0.3397 (44) |
| `bomb` | `[163,164] [208,208] [227,235] [238,238]` | 34 % | 0.2709 (129) |
| `location` | `[164,164] [195,195] [208,208]` | 27 % | 0.1164 (86) |

"Covered" is the share of all rows 0..184 capture pixels, 0 and 255 included in the denominator, over the sampled frames. Four things lower the figures, and the IoU is a lead only (`[Bounded Observation]`, [trap above](#3-actor-window-iou-iou)):

* **A band limit, not a render gap.** The bands leave out every index our actors paint anywhere in the film, so those indices count as object pixels wherever they are backdrop. On `traintnl` the tunnel and track props inside the actor's box (visible in the crop of tick 628) are object pixels; `intro` has no sky band at all (our actors paint every index of 227-238 in some frame).
* **Props-layer scenery.** Tarmac, hills and buildings our render draws on layer 3 are object pixels in the capture, so `land`, `bomb` and `location` read low.
* **`location`'s omitted bands.** 161, 162, 236 and 237 (our actors paint each in some frame), the props-layer ground and the hillside stay in the object pixels.
* **A render fault.** `location` shows a black quadrilateral in the foreground that the capture lacks (crop of tick 848; our actor-pixel count is about 7,400 in each sampled frame from tick 805 to 892; [#504](https://github.com/neilsh/stunt-reel/issues/504)). The #501 review attributes it to camera-mount shapes `0x3E57` and `0x3A26`; that was not checked here.

Checks by eye: the first-round bands were cropped at `land` tick 540 (tarmac and canopy sky counted as backdrop), `balloon` 595, `traintnl` 628, `bomb` 1750, `intro` 2454 (hill masses in the object pixels) and `location` 4148 (platform and tower objects, sea and hill backdrop); the final bands were not re-cropped. Unsampled indices (a ramp neighbour a film shows in 0.05 % of pixels or less) count as object.

## 4. Candidate sweeps

For a hypothesis with a few dozen variants (axis permutations, Euler order and signs, camera or actor offsets):

1. Add a temporary `DBG_<NAME>` environment switch at the one place the variant applies (read with `std::env::var`). The switch itself never lands in the code; step 5 keeps it as a patch.
2. Run [`python/scripts/parity_sweep.py`](../../python/scripts/parity_sweep.py), as one command (in the background if the product is large):

   ```bash
   mise run sweep -- --var DBG_PITCH=0,-2 --var DBG_DY=0,-0.3 [--films ctry,intro] [--probe film|iou] [--keep-best] [--jobs N]
   ```

   It builds `stunt-cli` once, renders every combination of the `--var` values for each film with those variables in the environment (flags from [`method.md`](method.md) section 1; each film's capture and `.FLM` come from its [`references.toml`](references.toml) row and the corpus), scores each with `stuntreel parity`, and prints one line per variant sorted best first, then the winner. Every film `references.toml` pins is the default and the ranking is by mean SSIM over them, so a gain on one film that costs another shows up in the table. With `--track`, and the round's `--target` ranges, the sweep instead judges every variant against the first value's by the adoption rule ([`score-a-render-change.md`](../../docs/howto/score-a-render-change.md) § 8). `--jobs N` (default 8, capped by cores and pairs) runs N (variant, film) pairs at once, with the table in the same order as a sequential run ([`evidence-limits.md`](evidence-limits.md) section 3 has the cost per job). Render directories go under `build/scratch/sweep/` and are deleted after scoring.
3. `--probe iou` adds the actor-window IoU of section 3 per film, for a hypothesis about an actor (it reads each film's `background` bands from its `references.toml` row; a film whose row has none shows `-` in the actor column and keeps its SSIM). `--keep-best` keeps the winner's render directory and writes `crop_<film>.png` there: section 1's crop of the frame with the largest actor. Look at it before trusting a score change.
4. Re-run the winner against the other films if `--films` narrowed the sweep. Three CTRY-only gains (camera height, terrain base, hero lift) regressed `INTRO.FLM` and were not adopted.
5. For a winner you adopt, keep the switch until its PR pictures and scores are made ([Evidence for a rendering PR](../../.agents/skills/improving-render-parity/pr-evidence.md)), since `mise run frame -- --var` needs it. Before removing any switch, adopted or not, save it as a patch from Git Bash: `git diff HEAD -- <paths> > work/<YYYY-MM>/<folder>/switches/DBG_<NAME>.diff` (`git add -N` a new file first), and cite that file in the journal entry. A later rule change can then rescore the case: `git apply --check`, then `git apply`, on the commit the entry's **Method** names. Then `git restore <paths>` to remove it. Record the outcome, including a negative one, as a journal entry in the work item's folder and in the note that owns the residual.

`--data-root <dir>` points the tool at another copy of `corpus/` and the reference captures. A worktree normally needs neither: `capture-ref`, `parity` and `sweep` read the corpus and captures from the configured data root, with no link in the checkout ([ADR 0036](../../docs/adr/0036-worktrees-reach-shared-state-by-configuration.md)). The flag is for CI, for a machine that keeps its data elsewhere, and for scoring one checkout's captures from another. Smoke check: with an eye-height switch, `DBG_EYE_DY=0,-0.3` reproduces the eye-height sweep in [`framing-and-actors.md`](framing-and-actors.md) (CTRY 0.771 and 0.782, INTRO 0.676 and 0.669).

   `--no-build` scores with the existing release binary (useful when another session holds it); `--reuse DIR` scores an existing `DIR/<film>` tree and renders nothing; `--retime N` relabels that tree by N ticks before scoring (section 6). Two variants whose per-film SSIM and IoU agree to four decimals print `warning: variants ... scored identically; the switch may not be wired` — that is the `is_ok()` trap of section 5 firing. A winner within 0.002 of the runner-up is marked `noise floor +/-0.002; winner is ~within noise`. Both entry points preflight before building: a missing capture is named with `mise run capture-ref`, and a held release binary fails with `release binary is in use; rerun with --no-build or wait`.

## 5. Environment pitfalls

* Python on Windows opens text as cp1252: pass `encoding="utf-8"` or read bytes, or a `§` is written as byte `0xA7` and `ruff` rejects the file.
* wgpu's maximum buffer is 256 MiB. An 80-face sphere (700 MB on CTRY) and the 20-face INTRO world (312 MB) both exceeded it; spheres are 20-face and sub-pixel props are culled (see [`log.md`](../../work/2026-10/parity-log/log.md)).
* Capture indices are named by ordinal and renders by film tick; match them through `report.json`'s `per_frame` entries, not by number.
* **Depth effects in `mode13h.wgsl`.** Use the affine view depth `(view_proj * world_pos).w`, never `length(world_pos - camera_pos)`. Euclidean distance is not affine in world space, so perspective-correct interpolation across a kilometre-sized terrain triangle is invalid; the first depth cue built on it read about 4 km for every terrain fragment (`[Bounded Observation]`).
* **Render determinism.** Two separate processes rendering ticks 589 and 590 wrote byte-identical `.idx` planes, and in 2026-10 three separately built binaries scored 0.7706, 0.7708 and 0.7718 on `CTRY.FLM`; on 2026-11-07, three builds of `740c608` rendered byte-identically on an RTX 4070 ([`evidence-limits.md`](evidence-limits.md) section 3).
* **The release binary is shared.** Another session's build or benchmark holds `target/release/stuntreel.exe`, and `cargo build` then fails with "Access is denied". `--no-build` uses the binary as it stands; the preflight names the lock before any render starts.

## 6. Timing hypotheses (post-hoc retime)

The page timing is modelled in the renderer: `--headless` samples the scene at `tick - 1` because the page captured for film clock `t` is the state at `t - 1` ([`capture.md`](../playone-exe/capture.md)). Timing questions must therefore not need a rebuild. `retime` relabels an existing render by N ticks and writes it as a new render store; `--reuse` and `--retime` carry that into a score in one command:

```bash
python python/scripts/parity_probe.py retime \
    --ours build/parity/ours/ctry_current --reference <data root>/captures/ctry/<id> \
    --out build/scratch/retime/ctry --by -1 [--allow-missing] [--force]
mise run sweep -- --reuse build/scratch/retime --films ctry,intro --no-build
# or, scoring the existing _current renders in one command:
mise run parity -- --no-render --retime -1 --no-build
```

Target tick `t` gets the planes, palette and `render.json` entry of source `t + N`, relabelled to `t`, written into a new store. The sign follows the renderer: offset 0 compares capture `t` with the state at `t - 1` (the accepted timing), and `-1` lands on state `t - 2`. A non-empty `--out` is refused unless `--force`; a source outside the rendered range is reported, and since ±1 always drops one end tick, pass `--allow-missing` (the `parity_run` wrapper does). Moving the palette entry with the planes matters: the hand-made shift that discovered the page lag kept the original tick's palette entry and under-reported INTRO (0.6793 against 0.6799 with the entry relabelled).

Measured `mean_ssim_scored` (CTRY / INTRO, 2026-10-23, post-page-timing build):

| `--by` | CTRY | INTRO | scored frames |
|---|---|---|---|
| 0 | 0.7732 | 0.6799 | 114/140, 209/213 |
| -1 | 0.7723 | 0.6773 | 113/139, 208/212 |

Offset 0 is the peak on both films and fractional phases around it are worse (§ 13), so the page phase is a whole tick and the renderer's `tick - 1` stays hardcoded. Use this path for timing hypotheses only: it says nothing about geometry, and it changes no committed render. The first version of this test copied every render one tick back by hand while another process held `target/release/stuntreel.exe`; the fix was then confirmed by a fresh release render once the binary freed.

## 7. No-rebuild experiments on the capture

Two experiments change the capture instead of the render, so they need neither a rebuild nor a PNG edit, because the capture is scored from its index plane and palette (`[Bounded Observation]`, 2026-10-23, `213cb23`):

* **Shift** the captured scene's rows or columns by a few pixels and re-score. This equals shifting the render by the opposite amount and measures how much of the residual is framing.
* **Recolour** the capture's flat-ground pixels to our render's index to measure how much of the loss they own (results in [`attribution.md`](attribution.md)).

Neither has a subcommand; both were one-off scripts under `build/scratch/`. Prefer them to a render-side switch whenever the question is "how much would this be worth" rather than "what is the right value".

## 8. Tool coverage

Every repeated analysis has a home: baseline render and score is `mise run parity`; candidate products are `mise run sweep`; tick shifts are `parity_probe.py retime` or the `--reuse`/`--retime` flags (which move the palette entry with the planes to the shifted tick; the hand-made shift left it stale); the identical-variant warning catches `std::env::var(...).is_ok()` treating `"0"` as set, which once cost two sweeps. A decoder change across every stock shape is `stuntreel shape-views --archive X [--shapes IDS|FILE] [--views top,side,front] --out DIR`: orthographic views through the real renderer, back faces culled, and a `manifest.json` of each shape's geometry hash. `mise run shape-diff -- --var DBG_X=0,1 [--shapes IDS|FILE]` runs it once per value over `SUPERSET.ALL`, lists the shapes whose hash changed and draws a before|after sheet of only those. Before it, an export loop took over 10 minutes for the stock aircraft and PIL views drawn without culling misread a fix twice (issue #277). Still hand-rolled, with no subcommand yet: the 11x11 loss-window ranking (`windows`), the per-layer index histogram (`index-diff`) and the sand-coverage count (`coverage`).

## 9. Origin markers (proposed, not built)

Draw a small solid marker at each actor and prop origin in our render. A marker in the right place under a wrong shape is a decode error; a marker that is itself misplaced is a placement error. Alberto Marnetto used orange cubes above each scenery asset for this split ([*Vibe-exploring Stunt Island*](https://marnetto.net/2026/04/26/vibe-exploring-si)). Build it when `shift` and `iou` cannot tell the two apart.
