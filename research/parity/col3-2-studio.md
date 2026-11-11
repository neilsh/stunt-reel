---
summary: "Records the COL3-2.FLM studio interior (anchorman, desk, window) that PLAYONE draws from tick 458 and we do not: evaluator state, actor clusters, shape census, and why the gap is unresolved."
---

# Film Segments: the `COL3-2.FLM` Studio Interior

`[Bounded Observation]` unless a claim says otherwise. This note covers the segment of `COL3-2.FLM` where `PLAYONE.EXE` draws a news studio that `stuntreel` does not. The `INTRO.FLM` segments are in [`film-segments.md`](film-segments.md). The scoring procedure is in [`method.md`](method.md); dated results go in journal entries; earlier ones are rows of the parity log. The static frame composition (UI bar, credits text) is in [`../playone-exe/sod-vm.md`](../playone-exe/sod-vm.md).

## 1. `COL3-2.FLM`: the studio interior

Scored against the 30 night frames of [`palette-fade.md` § 5.1](../playone-exe/palette-fade.md#51-night-capture-col3-2flm), where the modelled palette is already exact: mean SSIM 0.666, minimum 0.479, mean IoU 0.651. The four black frames (ticks 168-201) score 0.925-0.931. Every frame from tick 458 scores 0.62-0.66 with a constant IoU of 0.751. This is far below the `[I6]` gate, and the cause is not colour.

_Found 2026-10-22; see the [parity log](../../work/2026-10/parity-log/log.md)._

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

_Found 2026-10-23; see the [parity log](../../work/2026-10/parity-log/log.md)._

## Ruled out

- Near-clip plane 0.5 m to 0.05 m on `COL3-2.FLM`: frame unchanged.
- Terrain occlusion: rendering without `--sidata` still shows no studio.
- Back-face culling: the pipeline had none when this was measured; the 2026-10-24 change is recorded in [attribution.md](attribution.md#6-back-faces). Mirrored model: the model-to-world matrices are proper rotations.
- Visibility gates: every near mesh passes, and all 70 vertices of `15135` are in front of the camera.
- Pulling the camera back 3 m or 10 m draws some dark furniture-scale blocks, so the near actors render, but not the walls, window or anchorman.
- Dropped geometry in the display-list decode (section 1.4).

## Open questions

1. Read `PLAYONE`'s own slot and shape tables at runtime around tick 458 (the `0x4778` / `0x48B6` arrays and the shape each active slot resolves to) with the capture harness's debugger, and compare with our 18 actors. This separates "the evaluator drops or misplaces slots" from "the engine draws something the film does not list". ([#67](https://github.com/neilsh/stunt-reel/issues/67))
2. Inspect `COL3-2.FLM` pixels with `--sidata` to split the 0.127 index agreement into studio gap versus night palette.
