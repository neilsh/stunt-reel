# Film Segments Where the Original Shows a Scene We Do Not

`[Bounded Observation]` unless a claim says otherwise. This note covers the segments of `COL3-2.FLM` and `INTRO.FLM` where `PLAYONE.EXE` draws a scene (a news studio, held sand-field shots, a montage) that `stuntreel` does not. The scoring procedure is in [`method.md`](method.md); dated results are in [`log.md`](log.md). The static frame composition (UI bar, credits text) is in [`../playone-exe/sod-vm.md`](../playone-exe/sod-vm.md).

## 1. `COL3-2.FLM`: the studio interior

Scored against the 30 night frames of [`palette-fade.md` § 5.1](../playone-exe/palette-fade.md#51-night-capture-col3-2flm), where the modelled palette is already exact: mean SSIM 0.666, minimum 0.479, mean IoU 0.651. The four black frames (ticks 168-201) score 0.925-0.931. Every frame from tick 458 scores 0.62-0.66 with a constant IoU of 0.751. This is far below the `[I6]` gate, and the cause is not colour.

_Found 2026-10-22; see the [parity log](log.md)._

### 1.1 What the reference shows

From tick 458 the original draws a studio interior: an anchorman at a desk, a window with an outdoor scene in it, caption text from the `0x99` credits opcode, and the UI bar. `stuntreel` draws only the empty outdoor view toward the horizon. The film's `CNN Headline News` credits at tick 198 and its 26 created slots fit a news-studio set.

### 1.2 Evaluator state at tick 458

- Active camera: slot 7 (`0x97` at tick 448) at `(6239.6, 0.30, -3247.3)` m, look target `eye + (17, -87, 996)` m, so it points almost straight along `+Z`.
- The evaluator places 18 actors, exactly the slots 8-25 created with `0x13`/`0x17`/`0x1b` at tick 198.
- Near actors: `15135` (0.5 x 0.1 x 0.2 m, 0.55 m away), `16495` (4.4 x 2.0 x 5.9 m, 1.14 m), `16393` and `16423` (3-5 m blocks, 34 m), `16421` (91 m, 372 m). Eleven more are 15.6 m-tall models 4.9 km away; these are the figures on our horizon. None is person-sized or room-sized.
- Slots 2-4 are created with `0x19` at tick 194 and destroyed at tick 198 by `0x12` (exists bit clear).
- Five other shapes (`261`, `262`, `266`, `268`, `14976`) stop early at opcode `504` (`UnknownOpcode`); none is among the placed actors.

### 1.3 Where the 18 actors sit

Three clusters, stable from tick 200 to 458:

| Cluster | Position (m) | Shapes |
|---|---|---|
| Studio (camera is here) | `(6240, 0, -3247)` | `15135`, `16495`, `16423`, `16393`, one copy of `16421` |
| Row of nine, 12 m apart, 15.6 m tall | near `(1900, 8, -879)` | `15486`-`15530` |
| Three | near `(-3681, 1, 342)` | `15111`, `15134`, `16421` |

The largest near shape, `16495`, has 52 vertices and 20 + 2 + 4 triangles in three meshes.

### 1.4 The display-list decode is not lossy for the studio shapes

`16495`, `15135`, `16423`, `16393`, `16421`, `15111` and `15486` use only `POLYZ`, `COLOR`, `IFVIS`, `IPG` type 0 (a cube generator), vertex arithmetic and a single `PERS`. None uses `SPHERE`, `BLOCK`, `PERFDISK` or `IPG` type 4 (subobject), the opcodes whose geometry `vm.rs` reads and discards. `16495` has 13 `POLYZ` ops and decodes to 26 triangles, so the missing studio is not dropped geometry.

### 1.5 Shape census

Up to tick 470 the film's `create` opcodes bind only shape ids in `0x3B07`-`0x4027`, `0x3C7E`-`0x3CAA`, `0x3E57` and `0x406F`. There is no person or character id; slots 0-7 are rigs without the draw bit. The anchorman is therefore not a shape this film binds to a slot, yet the original draws one.

### 1.6 Conclusion

The studio is not among the shapes the evaluator places near the camera, and `PLAYONE` has no extra layer to supply it, so the original places or builds something we do not. Candidates, none tested:

- the anchorman and walls are slots whose shapes decode to less geometry than the original draws (for example a model composed of references the display-list VM does not follow);
- `PLAYONE` places or scales slots differently from the evaluator;
- the set is drawn from data absent from the `.ALL` and the staging mount. `COL3-2.ALL` holds no `0x8100`-`0xBFFF` scenery chunk, only 750 models, one palette and sounds.

Vars 2-7, 10 and 11 change at tick 198 (see [`palette-fade.md` § 3.2](../playone-exe/palette-fade.md#32-other-readers-of-the-live-variables)); none has a reader that explains the studio.

### 1.7 With `--sidata` the studio gap is unresolved

The 2026-10-22 figures above come from a render without `--sidata`. The `--sidata` world (43,199 props, 18,001,215 vertices, 504 MB) first panicked on wgpu's 256 MB buffer limit. `GpuModel` now splits an oversized model into several vertex/index buffer pairs (`plan_upload` in `crates/stunt-render/src/mesh.rs`), cutting each mesh slice into runs of whole triangles in draw order; a model that fits is uploaded unchanged. The `COL3-2.FLM` world splits on vertices (about 9.59 million per 256 MiB buffer). `CTRY.FLM` and `INTRO.FLM` re-rendered on this build score exactly as before (0.771 / 0.475 / 0.978 and 0.676 / 0.481 / 0.919).

| `COL3-2.FLM` render | Scored / matched | `mean_ssim_scored` | `mean_index_agreement_scored` | `mean_iou_scored` | `mean_iou` |
|---|---|---|---|---|---|
| without `--sidata` | 26 / 30 | 0.636 | 0.061 | 0.021 | 0.018 |
| with `--sidata` | 26 / 30 | **0.692** | 0.127 | **0.828** | 0.809 |

Both rows use the render's sidecar for the authored fade, so 26 frames are scored, not the single one counted in section 1; they are not comparable with section 1's figures. The silhouette now largely agrees (IoU 0.83), but index agreement stays at 0.127 against 0.475 and 0.481 for the day films, so most pixels still differ in colour. `[Unknown]`: whether that is the studio gap, the night palette, or both; pixels have not been inspected. The `INTRO.FLM` sub-pixel cull is not enough to explain it.

_Found 2026-10-23; see the [parity log](log.md)._

## 2. `INTRO.FLM`: segments that do not match

### 2.1 Held sand shots at ticks 2690-2850

`[Unknown]` cause. The capture is dominated by sand index 91 (33,902 to 57,582 of the 59,200 viewport pixels), with a hill (193) in some frames. Our camera moves from the airfield to a 500 m altitude view looking west (eye `(3000, 500, 0)` at tick 2790) and renders sea, sky and hills. Two samples 10 ticks apart are nearly identical (57,582 and 57,572 sand pixels), so this is a held shot, not a boundary effect. The film clock advances normally (captures at 2790 and 2800 have distinct `film_tick`), so it is not a paused clock.

Camera aim: the capture's horizon sits at about row 5 of the viewport, so the authored camera is pitched down about 22 degrees. Our `SceneFrame` camera at tick 2790 has eye `(3000, 500, 0)` and target `(2000, 500, 0)`, exactly level, five metres from actor `0x7F09` at `(2984, 500, 0)`. No `MAP.BIN` patch covers `(3000, 0)`, `(2500, 0)`, `(2000, 0)`, `(1500, 0)` or `(1000, 0)`, so our world is sea where the capture shows sand.

Open: whether the aim comes from the slot rotation we use, from an aim-at target we do not model, or from an Euler composition that only diverges at large yaw (this segment looks west, yaw about 90 degrees; CTRY's residuals are sub-degree). `[Hypothesis]`: a per-slice view-slot selection difference, since our camera is a plausible slot, just not the one the capture shows.

### 2.2 Studio-like held shots

Twenty-eight of the 209 scored INTRO frames are more than 55% one non-sky colour, all sand index 91, in two runs (about ticks 1330-1484 and 2690-2850): a flat sand field with the aircraft small and centred. CTRY's 68 such frames are ordinary airfield green (194) and score 0.75-0.84, so flatness alone is not the problem; the missing backdrop is.

### 2.3 Montage frames

The montage cuts `view_obj` almost every slice, and its scene clock runs slower than the film clock; see [`timeline-and-ticks.md`](../formats/concepts/timeline-and-ticks.md). Scoring the 19 frames at ticks 1290-1500 against our renders at several offsets gives 0.5769 at 0, 0.5895 at -1, 0.5786 at -2, 0.5826 at -3 and 0.5904 at -8, while the whole-film optimum stays at -1, so it is not a simple one-tick page lag.

The capture shows four large aircraft resting on a sand flat (one red biplane, grey and dark-airframe models in the foreground). Our scene at tick 1352 holds twelve actors of 8-97 triangles placed 16-90 m away, and the render covers only 58 actor pixels, so the large parked aircraft are not where our slot data puts them. `[Unknown]`: whether the montage places those actors through a path we do not model, or the captured page belongs to an earlier scene.

_Found 2026-10-22; see the [parity log](log.md)._

### 2.4 Title cards: the credits text we do not draw

`[Bounded Observation]`, 2026-11-01. View slot 3 is a static rig (eye 3.2 m, rotation only) that frames nothing: it points about 89 degrees away from every drawn slot. It is the view for three shots, ticks 0–760, 1519–2055 and 3641–3822, which hold 134 of the 346 frames in the `vault-intro` reference. Over the first two, `credits_set` (`0x99`) counts down `DISNEY INTRO REEL` / `15` to `1` every 50 ticks, and `credits_clear` (`0x98`) ends each run at ticks 759 and 1519 (`mise run flm-events`). The capture is a black screen with that two-line text centred (tick 103: `DISNEY INTRO REEL` over `13`); `stuntreel` draws the black screen without the text, because nothing in the renderer draws the credits string that `PLAYONE.EXE` draws after the 3D scene (`0x58BD`, [`../playone-exe/sod-vm.md`](../playone-exe/sod-vm.md)). Per-shot mean SSIM over those 134 frames is 0.485 on `fix/gvpoly-colour`, the film's lowest-scoring group by far, and it does not move with the camera height (§ Ruled out in [`framing-and-actors.md`](framing-and-actors.md#ruled-out)).

## Ruled out

- Near-clip plane 0.5 m to 0.05 m on `COL3-2.FLM`: frame unchanged.
- Terrain occlusion: rendering without `--sidata` still shows no studio.
- Back-face culling: the pipeline had none when this was measured; the 2026-10-24 change is recorded in [attribution.md](attribution.md#6-back-faces). Mirrored model: the model-to-world matrices are proper rotations.
- Visibility gates: every near mesh passes, and all 70 vertices of `15135` are in front of the camera.
- Pulling the camera back 3 m or 10 m draws some dark furniture-scale blocks, so the near actors render, but not the walls, window or anchorman.
- Dropped geometry in the display-list decode (section 1.4).
- A single global tick offset for the INTRO montage (section 2.3).

## Open questions

1. Read `PLAYONE`'s own slot and shape tables at runtime around tick 458 (the `0x4778` / `0x48B6` arrays and the shape each active slot resolves to) with the capture harness's debugger, and compare with our 18 actors. This separates "the evaluator drops or misplaces slots" from "the engine draws something the film does not list". ([#67](https://github.com/neilsh/stunt-reel/issues/67))
2. Inspect `COL3-2.FLM` pixels with `--sidata` to split the 0.127 index agreement into studio gap versus night palette.
3. Find the INTRO ticks 2690-2850 view: slot selection, aim-at target or Euler composition (section 2.1). ([#70](https://github.com/neilsh/stunt-reel/issues/70))
4. Find which path places the parked aircraft in the INTRO montage (section 2.3). ([#72](https://github.com/neilsh/stunt-reel/issues/72))
5. Draw the credits overlay (`0x99` lines, cleared by `0x98`) for the INTRO title cards (section 2.4): font, position and colour from `PLAYONE.EXE`'s `0x58BD` routine or the capture pixels. 134 of 346 reference frames depend on it. ([#75](https://github.com/neilsh/stunt-reel/issues/75))
