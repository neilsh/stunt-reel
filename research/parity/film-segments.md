---
summary: "Covers COL3-2.FLM and INTRO.FLM segments where PLAYONE shows a scene we do not: the unresolved COL3-2 studio, INTRO sand shots as SCENERY tiles, the montage clock, and black title cards."
---
# Film Segments Where the Original Shows a Scene We Do Not

`[Bounded Observation]` unless a claim says otherwise. This note covers the segments of `COL3-2.FLM` and `INTRO.FLM` where `PLAYONE.EXE` draws a scene (a news studio, held sand-field shots, a montage) that `stuntreel` does not. The scoring procedure is in [`method.md`](method.md); dated results are in [`log.md`](../../work/2026-10/parity-log/log.md). The static frame composition (UI bar, credits text) is in [`../playone-exe/sod-vm.md`](../playone-exe/sod-vm.md).

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

## 2. `INTRO.FLM`: segments that do not match

### 2.1 Held sand shots at ticks 2690-2850

**Superseded 2026-11-06 (below); kept as first recorded, 2026-10-22, on the capture of that date.** The capture was dominated by sand index 91 (33,902 to 57,582 of the 59,200 viewport pixels), with a hill (193) in some frames, while our camera moved to a 500 m view looking west (eye `(3000, 500, 0)`, target `(2000, 500, 0)`, level, at tick 2790) and drew sea, sky and hills. Two samples 10 ticks apart were nearly identical (57,582 and 57,572 sand pixels) although the film clock advanced, so it was a held shot. The capture's horizon at about row 5 put its camera about 22 degrees down. No `MAP.BIN` patch covers `(3000, 0)` to `(1000, 0)`, so our world is sea there. The open question was whether view selection, aim or a surface we do not build explained it.

**Answered: `PLAYONE` draws these ticks from the view slot, eye and angles we use, and the sand is drawn.** `[Bounded Observation]`, 2026-11-06, on `48f5d49`, [#70](https://github.com/neilsh/stunt-reel/issues/70). `mise run debug-x -- --plan tools/dosbox-x/plans/view-slot.toml --film corpus/stisldem/VAULT/INTRO.FLM` (unpatched) breaks in the view setup at `0x1251`, where `SI` is the view slot's record (`[0x4888 + 2 × view_obj + 0x2E]`, kept at `DS:0x22DE`), and reads the record, the snapshot `view_obj` and the eye `DS:0x2A68` ([`memory-map.md`](../playone-exe/memory-map.md) § 1). 23 hits, ticks 2678 to 2801. Eyes are in `PLAYONE`'s axes (x and y negated against ours); angles are the record's three words, which `0x1266..0x12A7` hand to the rotation builder.

| tick | `view_obj`, record | `PLAYONE` eye | `PLAYONE` roll, pitch, yaw | our tick | our eye | our roll, pitch, yaw |
|---|---|---|---|---|---|---|
| 2687 | 1, `0x3994` | (-3448.03, -16.53, 2406.57) | 355.1, -10.8, 3.4 | 2687 | (3448.03, 16.63, 2406.20) | 355.1, -10.8, 3.5 |
| 2740-2745 | 1, `0x3994` | (-3448.8, -12.9 to -12.6, 2426.2 to 2428.2) | 4.5 to 5.9, -10.9 to -11.0, 1.1 to 0.7 | 2742 | (3448.81, 12.81, 2426.60) | 4.7, -10.9, 1.0 |
| 2766 | 1, `0x3994` | (-3449.50, -11.36, 2435.79) | 8.6, -11.3, -1.1 | 2775 | (3449.73, 10.93, 2438.64) | 8.7, -11.4, -2.0 |
| 2801 | 4, `0x3AA2` | (-3003.79, -500.52, -0.35) | 1.0, 0.0, 270.0 | 2797 | (2993.34, 500.45, -0.44) | 11.9, 0.0, -90.0 |

The view changes are the film's own (`0x91` at 2630, `0x94` at 2786, `mise run flm-events`) and our player follows them. Under slot 1 the eye and angles agree to 0.4 m and 0.2 degrees at the same tick, so the camera is not the cause: from 2687 to 2786 the view is slot 1, 11 to 17 m over the montage's sand flat at z 2400 to 2440, pitched 11 degrees down, and from 2797 it is slot 4 at 500 m over the sea. The current reference (`vault-intro`, `ac93c3ba`, pinned 2026-10-31) shows exactly that, and so does our render (`mise run frame -- --film intro --ticks 2687,2742,2775,2797,2852`).

The sand was a surface we built but hid: `PLAYONE` draws it as `SCENERY` tiles over the Ground, which our depth test hid under coplanar terrain until the ground-decal change ([#69](https://github.com/neilsh/stunt-reel/issues/69), [`world-scene.md`](../playone-exe/world-scene.md) § 6). Not a Ground patch (§ 2.1-2.3 there) and not the view. On `48f5d49` (CTRY 0.8725, INTRO 0.8273) the 11 frames the issue named lose 0.000 to terrain (ticks 1306-1372, 1506, 2687-2775) or at most 0.025 (1086, 1097); the largest terrain loss on any `INTRO` frame is 0.135 (tick 2147). What these frames still lose is in the props class, whose layer now holds the sand: at 1506 (0.382), 2731 (0.328) and 2742 (0.280) the capture draws a large fireball over the sand and we draw nothing. `[Hypothesis]`: it is an `OP_ANIMATE` image ([#222](https://github.com/neilsh/stunt-reel/issues/222)) of the slots created with flags `0x23` from tick 2710 (slots 10 and 16), like the hit flash of § 2.3. At 1350 (0.246) the hero biplane is drawn smaller and at another attitude than the capture's.

The 2026-10-22 held shot does not recur in this reference: its frame at 2797 is slot 4's 500 m view. Under the debugger only one view setup ran between ticks 2766 and 2870 (at 2801), and its slot-4 pose is the one our timeline gives at about tick 2788. `[Hypothesis]`: the first 500 m frame, which sees most of the island, is slow to draw at the debugger's 8,000 cycles, and the old capture held slot 1's last sand frame on screen while it drew; its "22 degrees down" assumed the default lens, but camera 1's lens is 44236 (an 8.3 degree field of view, [`lod.md`](../playone-exe/lod.md) § 2.1), so at 11 degrees of pitch no horizon is in frame and the edge read as one was the grass-sand boundary.

### 2.2 Studio-like held shots

Twenty-eight of the 209 scored INTRO frames are more than 55% one non-sky colour, all sand index 91, in two runs (about ticks 1330-1484 and 2690-2850): a flat sand field with the aircraft small and centred. CTRY's 68 such frames are ordinary airfield green (194) and score 0.75-0.84, so flatness alone is not the problem; the missing backdrop is. Since the ground-decal change the sand is drawn and these frames lose nothing to terrain (§ 2.1).

### 2.3 Montage frames

The montage cuts `view_obj` almost every slice; the 2026-10-22 reading that its scene clock runs slower than the film clock (a lag growing about 0.9 ticks per tick) is refuted by the offset search below; see [`timeline-and-ticks.md`](../formats/concepts/timeline-and-ticks.md). Scoring the 19 frames at ticks 1290-1500 against our renders at several offsets gives 0.5769 at 0, 0.5895 at -1, 0.5786 at -2, 0.5826 at -3 and 0.5904 at -8, while the whole-film optimum stays at -1, so it is not a simple one-tick page lag.

The capture shows four large aircraft resting on a sand flat (one red biplane, grey and dark-airframe models in the foreground). Our scene at tick 1352 holds twelve actors of 8-97 triangles placed 16-90 m away, and the render covers only 58 actor pixels, so the large parked aircraft are not where our slot data puts them. `[Unknown]`: whether the montage places those actors through a path we do not model (the captured page is not an earlier scene: its best-matching render tick lies within 7 ticks, below).

_Found 2026-10-22; see the [parity log](../../work/2026-10/parity-log/log.md)._

**The parked aircraft now draw where the capture does; re-creating an absent slot does not explain the position miss.** `[Bounded Observation]`, 2026-11-04, on `3ee5e34`. At captured ticks 1350 and 1383 (`mise run frame -- --film intro --ticks 1350,1361,1383`) the parked aircraft (slots 7, 10 and 12-14, about 70 m out at z 2488-2490) and the hero biplane (slot 0, shape `0x7F19`, 16 m from the eye) land within a few pixels of the capture's; the 2026-10-22 miss predates the actor fixes in [`framing-and-actors.md`](framing-and-actors.md) § 1. The 19 scored frames at ticks 1290-1500 now average SSIM 0.7662 (0.5769 when this section was written), and the worst three, 1350, 1361 and 1372 (0.561, 0.574, 0.584), lose to the ground: the capture's sand flat is green airfield in ours, the missing backdrop of section 2.2. (Drawn since the ground-decal change: on `48f5d49` these frames lose 0.000 to terrain, § 2.1.)

The montage does re-create slots every slice. From tick 1307 slots 8, 9, 11 and 19-24 (shape `0x101`, create flags `0x1F`) run as a pool: each is created at slot 0's position, moves about 1.8 m per tick down to the parked line at z 2488, is created again there, and is destroyed; slot 15 (shape `0x105`, flags `0x23`, a fixed position by the red biplane) is created again in slices 1383, 1388 and 1392. `[Hypothesis]` by their look: a stream of bullets and a hit flash. The worry was that the lerp, which pairs actors by `actor_id` across two trajectory records, would sweep a re-created slot from its old instance's pose to its new one. It never does in this film. Each slice is followed by a zero-duration slice at the same tick, and a slot leaves the line by a destroy in one of them and comes back by a create in a later one, so some record between the two holds no instance of the slot and nothing pairs across the jump. Over all 538 `INTRO.FLM` slices, 283 interpolated spans hold a slot that was created or destroyed in the span's later slice and is present at both ends; the largest move among them is 18.5 m over a 10-tick span (1408 to 1418), the pool's ordinary speed, against about 55 m for an end-to-start jump. `CTRY.FLM` has 2 such spans. The rule that a record without the slot separates a destroy from its create does not cover a create on a live slot (the pool's create at the parked line, slot 15 at 1383, 1388 and 1392): those spans do lerp the old instance to the new one, and are safe only because the two positions coincide, which the 18.5 m maximum move bounds. `FilmTimeline::sample` at ticks 1350-1360 confirms it: every `0x101` slot steps evenly, and a slot appears only at the start of the line.

Still `[Unknown]`: whether `PLAYONE` restarts an animated shape's frame on such a re-create (slot 15, `SIF_ANIMATES`); at tick 1383 the capture draws a pink burst by the red biplane and the render draws nothing there.

**The montage shows no growing lag: the best-matching render tick follows the capture tick at slope 0.99.** `[Bounded Observation]`, 2026-11-05, on `70a9f70` with the reference `captures/vault-intro` (`ac93c3ba...`, [#73](https://github.com/neilsh/stunt-reel/issues/73)). One render of every tick 1085-1510, then for each offset `by` from -200 to +10 in steps of 1 the render relabelled so capture tick `t` shows render tick `t + by` (`parity_probe.py retime`'s rule) and scored with `stuntreel parity`; per capture frame the matched tick is `t + by` at the highest per-frame SSIM. Over the 19 scored frames at ticks 1295-1495:

| capture ticks | matched `by` | matched render ticks | best SSIM (at `by` 0) |
|---|---|---|---|
| 1295-1350 | +2, +1, +1, 0, +2, +1 | 1297, 1307, 1318, 1328, 1341, 1351 | 0.785 (0.767) to 0.727 (0.713) |
| 1361-1394 | +5, +5, +7, +4 | 1366, 1377, 1390, 1398 | 0.767 (0.737) to 0.895 (0.874) |
| 1405 | -5 | 1400 | 0.900 (0.888) |
| 1416-1483 | 0, 0, +1, +2, +1, +1, 0 | 1416, 1427, 1439, 1451, 1461, 1472, 1483 | 0.910 to 0.968; each within 0.012 of its `by` 0 score |
| 1495 | flat: every `by` from -9 to +10 within 0.002 | not determined | 0.826 |

A fit over the 18 determined frames gives matched = 0.992 x capture + 12.8: slope 0.992 (1 to within the fit), a mean offset of +1.6 ticks and a largest deviation of 7. A growing lag of 0.9 per tick would have put 1495 about 180 ticks behind 1295, at the search's old -180 limit; no frame's best offset lies below -5, and for every frame the best score inside -10..+10 beats the best below -10 by 0.02 to 0.25 (the curve is peaked, not saturated: e.g. tick 1383 scores 0.877 at +7, a median of 0.639 over the range and 0.477 at -180). So the old near-constant matched ticks (1225, 1268, 1283, 1272, 1282) were a search saturating at its -180 limit over a changing scene, as the re-scoping of #73 suspected, and the film clock does follow the global counter ([`memory.md`](../playone-exe/memory.md) section 3.2). What remains is a bump of +4 to +7 ticks on captures 1361-1394, at or below the noise: the per-frame margin that counts as significant is about 0.03 ([`method.md`](method.md) section 4.4) and repeat captures of one tick agree only to SSIM 0.939-0.997, and only 1361, 1372 and 1383 gain about that much over `by` 0 (the rest under 0.02; 1383 scores 0.8738 at +3 and 0.8769 at +7, 1394 ties +4 and +5, 1405 prefers -5 over +3 by 0.007). The exact offsets in 1361-1405 are therefore not resolved, and the slope verdict does not depend on them. Where the pool of bullet-like slots of this section moves 1.8 m per tick: `[Hypothesis]` that this is our actors' pool positions lagging the capture's, a renderer or trajectory question and not a clock rate. The frame at 1405 prefers -5 by only 0.012. Results are per-frame optima over page-aligned captures 11 ticks apart, so a rule that skips single ticks (the per-slice catch-up of the film reader at `0x3A88`) is not excluded, only unneeded to explain these scores.

Issue #73's done criteria are met in part: the lag premise is answered and a per-frame matched tick is tabulated, but no rule is read at an image offset and the prediction is the measured one, not derived. The static read of `0x3A88` is not triggered by this result.

### 2.4 Title cards: credits on black

`[Bounded Observation]`, 2026-11-01. View slot 3 is a static rig (eye 3.2 m, rotation only) that frames nothing: it points about 89 degrees away from every drawn slot. It is the view for three shots, ticks 0–760, 1519–2055 and 3641–3822, which hold 134 of the 346 frames in the `vault-intro` reference. Over the first two, `credits_set` (`0x99`) counts down `DISNEY INTRO REEL` / `15` to `1` every 50 ticks, and `credits_clear` (`0x98`) ends each run at ticks 759 and 1519 (`mise run flm-events`). The capture is a black screen with that two-line text centred (tick 103: `DISNEY INTRO REEL` over `13`); until 2026-11-01 `stuntreel` drew this view without the text, because nothing in the renderer drew the credits string that `PLAYONE.EXE` draws after the 3D scene (`0x58BD`, [`../playone-exe/sod-vm.md`](../playone-exe/sod-vm.md)), and over sky rather than black (below). Per-shot mean SSIM over those 134 frames is 0.485 on `fix/gvpoly-colour`, the film's lowest-scoring group by far, and it does not move with the camera height (§ Ruled out in [`framing-and-actors.md`](framing-and-actors.md#ruled-out)).

**The text is drawn; the background is what scores.** `[Bounded Observation]`, 2026-11-01. The renderer now draws the credits by `PLAYONE`'s rule ([`pfont.md` § 3.2](../formats/auxiliary/pfont.md#32-drawing-the-credits)), and at tick 103 every rendered ink and shadow pixel lands on the capture's. The scores do not move. In the first shot (69 frames before tick 760) the capture's view is index 193, black, everywhere but the text, while the render's is sky (238 over 233), so those frames score SSIM 0.000 with or without the text. The other two shots (65 frames) are unscored: the film's authored brightness is 0 there, and the render already matches their black page (SSIM 1.000). The black is the film's Fade: `INTRO.FLM` first keys brightness (var 14) at tick 760, and `PLAYONE` starts every film variable at 0, so the scene palette is black until then; the renderer started brightness at full ([`palette-fade.md` § 6](../playone-exe/palette-fade.md#6-open-points)). With brightness starting at 0 the 69 frames render black with the text and score SSIM 1.000, and fall below the fade floor like the other title cards. Under the black, `PLAYONE` still writes index 193 where the render writes sky indices, so index agreement on those frames stays 0.003.

## Ruled out

- Near-clip plane 0.5 m to 0.05 m on `COL3-2.FLM`: frame unchanged.
- Terrain occlusion: rendering without `--sidata` still shows no studio.
- Back-face culling: the pipeline had none when this was measured; the 2026-10-24 change is recorded in [attribution.md](attribution.md#6-back-faces). Mirrored model: the model-to-world matrices are proper rotations.
- Visibility gates: every near mesh passes, and all 70 vertices of `15135` are in front of the camera.
- Pulling the camera back 3 m or 10 m draws some dark furniture-scale blocks, so the near actors render, but not the walls, window or anchorman.
- Dropped geometry in the display-list decode (section 1.4).
- A single global tick offset for the INTRO montage (section 2.3).
- A view-slot selection, aim or Euler-composition difference at INTRO ticks 2687-2801: `PLAYONE`'s live `view_obj`, eye and angle words match our camera to 0.4 m and 0.2 degrees (section 2.1).
- A Ground patch coloured wrong under the INTRO sand flat: the sand is `SCENERY` tiles, and terrain loss there is 0.000 since the ground-decal change (section 2.1).
- Re-creation of an absent slot interpolated across in the INTRO montage: no span pairs a slot's pose from before its destroy with its pose after the re-create, because a record without the slot separates them (section 2.3). A create on a live slot does pair; only its position is bounded (18.5 m), not its rotation, shape or state (section 2.3).

## Open questions

1. Read `PLAYONE`'s own slot and shape tables at runtime around tick 458 (the `0x4778` / `0x48B6` arrays and the shape each active slot resolves to) with the capture harness's debugger, and compare with our 18 actors. This separates "the evaluator drops or misplaces slots" from "the engine draws something the film does not list". ([#67](https://github.com/neilsh/stunt-reel/issues/67))
2. Inspect `COL3-2.FLM` pixels with `--sidata` to split the 0.127 index agreement into studio gap versus night palette.
3. Find the INTRO ticks 2690-2850 view: slot selection, aim-at target or Euler composition (section 2.1). ([#70](https://github.com/neilsh/stunt-reel/issues/70)) Answered 2026-11-06: `PLAYONE`'s live view slot, eye and angles match ours; the sand is `SCENERY` tiles, drawn since the ground-decal change. Still open there: the fireball at ticks 1506 and 2731-2742 ([#222](https://github.com/neilsh/stunt-reel/issues/222)), and why the old capture held a sand frame through 2850.
4. Find which path places the parked aircraft in the INTRO montage (section 2.3). ([#72](https://github.com/neilsh/stunt-reel/issues/72)) Answered 2026-11-04: the ordinary slot path; they draw where the capture does at ticks 1350 and 1383. Still open there: the sand ground (section 2.2) and the hit flash of slot 15, shape `0x105`.
5. Draw the credits overlay (`0x99` lines, cleared by `0x98`) for the INTRO title cards (section 2.4). Answered 2026-11-01: drawn from `PFONT.BIN` by the rule at `0x0F7B`, pixel-exact on the capture ([`pfont.md`](../formats/auxiliary/pfont.md)). ([#75](https://github.com/neilsh/stunt-reel/issues/75))
6. Why does `PLAYONE` fill INTRO's first title-card view (slot 3, ticks 0–759) with black where the render drew sky (section 2.4)? Answered 2026-11-01: brightness (var 14) starts at 0 and the film first keys it at 760. Still open: why the view's indices are 193 rather than sky indices.
7. Does the UI-overlay mask hide the credits ink, which is palette index 255 like the cursor (section 2.4)? Answered 2026-11-01: it did. The mask now drops index 255 only on ticks where the film shows no credits, by the render record's per-tick `credits` flag (2026-11-02; it first keyed on the render's `LAYER_OVERLAY` pixels, which let a render that lost its credits mask the captured ink), so credits ink is scored and misplaced or missing ink counts against the render. Scores did not move (CTRY 0.7843, INTRO 0.6902) because every title-card frame is below the fade floor and unscored.
