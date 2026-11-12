# Journal: `INTRO` camera 1 under the per-frame `SP_1NODE` gate

## 2026-11-11: what camera 1 loses

- **Question**: Why does each of `INTRO` camera 1's 17 scored ticks (lens 44236, ticks 1216–1290 and 2511–2624) lose 0.0012 to 0.0023 SSIM with the per-frame gate of [#402](https://github.com/neilsh/stunt-reel/pull/402)?
- **Method**: `INTRO` rendered at `0dc7c77` (main) and with `mise run build-at -- 78a4e203` (the commit before #402), both scored against `vault-intro` with `stuntreel parity`. Changed pixels between the two renders at ticks 1266 and 2531, from the render stores. A temporary `DBG_LOD_TRACE` print in `world/mod.rs` listed every gated placement with its gate chain on a render of tick 1266; a script projected each into the frame from the camera in `render.json` and evaluated `CameraTransform::lod_keeps_subtree`'s rule on its chain. `stuntreel sod-trace` and `shape-views` on the shapes found. A temporary `DBG_LINE_W` set the width of `line_polygons`' ribbons, for named shapes only (`DBG_LINE_SHAPES`), and `INTRO` was rendered and scored with it. No switch is committed.
- **Result**:
  - Main scores `INTRO` 0.8404 and the commit before #402 0.8344; on camera 1's 17 ticks main loses 0.0012 to 0.0023 each, as #402 measured.
  - Only 106 pixels change at tick 1266 and 92 at 2531, all in one band across the frame at rows 143–159: power lines about 430–440 m away. The capture draws them as two continuous one-pixel cables from edge to edge.
  - The line is pylons `0x05B6`–`0x05B8` (at raw x −3386, −3482, −3578, z 2056) and spans `0x058C`, with coarser stand-ins `0x0590`, `0x05AD`, `0x05AF`, `0x05B1` above them. At depth about 437 m, `>> (0x229E + 1)` gives 27; the gate keeps every level down to the span `0x058C` (gate `ext` 48, `splitdist` 80, threshold 61) and the pylon stand-in `0x05B7` (gate `ext` 13, `splitdist` 32, threshold 23).
  - `0x058C` and `0x0590` are drawn with `MOVETO`/`ZLINETO` only: `0x058C` has two cables of four segments each (`LINECOL` 0x24 and 0x25), `0x0590` two straight lines (`LINECOL` 0x25). Our `line_polygons` draws each line as two 0.03 m ribbons. Our render draws tick 1266 at a 17.76° field of view over 185 rows (`render.json`), a focal length of about 592 px, so at 437 m that is about 0.04 px, so main draws the cables as scattered dots. The static rule had drawn coarser stand-ins on this line, and some of their colour-37 lines reached pixels; which shapes those were was not traced.
  - With the ribbons 0.75 m wide (about one pixel at that depth) on those eight shapes only, every one of camera 1's 17 ticks scores above the commit before #402, by 0.0023 to 0.0050, and `INTRO` scores 0.8414. The picture then shows both cables across the frame as the capture does. The same width on every shape scores 0.8075: close lines, such as the biplane's rigging, swell.
- **Verdict**: The loss is lines drawn sub-pixel, not a wrong gate threshold (`[Supported Inference]`). The gate keeps the finer power-line spans, which are drawn with lines, and our lines are a fixed world width rather than a pixel, so far away they vanish. The fix is [#415](https://github.com/neilsh/stunt-reel/issues/415), screen-space lines in `stunt-render`; no rendering change here. Whether the gate picks `0x058C` rather than `0x0590` where `PLAYONE` does cannot be told from these frames: both draw two lines.
- **Lives in**: [`lod.md`](../../../research/playone-exe/lod.md) section 4.4.

## 2026-11-11: do the CTRY hill fins show through the hills

- **Question**: In `CTRY`'s airfield shot, do the `OP_TAP` fins `0x0402`–`0x0408` show through the hill patches in front of them, in the capture or in ours?
- **Method**: `mise run frame -- --film ctry --ticks 287,298,309 --var DBG_TAP_ANY=0,1`, where 1 (temporary) restored the old rule that dropped every fin for anchor 81. Changed pixels between the two, and the capture beside both. The fins' placements and gates from the `DBG_LOD_TRACE` print, projected from the camera at tick 287.
- **Result**: With the current rule all seven fins are placed, each kept by its gate. At ticks 287, 298 and 309 drawing them changes no pixel of our render. At tick 287 the fins project to the right edge of the frame and past it, into the hills' region at the top right (`0x0408` near x 305, y 72). There, and in the same crop at tick 309, the capture shows the same hill faces and ridge lines as ours, with no extra edge or face. Tick 298 was compared only as whole frames. A fin shares the hill patches' colour range, so one drawn over a patch of its own shade would not show in either picture.
- **Verdict**: No fin shows through the hills in ours at these three ticks, nor in the capture at 287 and 309. `[Bounded Observation]`, captured ticks of one shot.
- **Lives in**: [`world-scene.md`](../../../research/playone-exe/world-scene.md) section 6.2; [`lod.md`](../../../research/playone-exe/lod.md) section 4.2.

## 2026-11-11: the gate in the Patch #3 image

- **Question**: The captures ran Patch #3 (`playone_sha256` `fc532c94…` in `vault-intro`'s `meta.json`, the same file as `corpus/siarchive/Films/NewPLAY/PLAYONE.EXE`). Does its gate match the unpatched one #402 traced?
- **Method**: `mise run unlzexe -- <NewPLAY/PLAYONE.EXE> build/re/playone_p3.img` (192,028 bytes, PR #409), then `mise run disasm` over both images and a byte search for the unpatched routines.
- **Result**:
  - The gate at P3 `0x2231..0x2270` is instruction for instruction the unpatched `0x211E..0x215D`: `mov cx, di` (`0x2231`), the threshold with `mul word [0x1C2A]` (`0x2240`), the near dispatch `jmp [bx+0x05E8]` (`0x2250`), the stand-in store `mov [0x1C72], ax` (`0x226D`). Only the `DS` offsets and branch targets differ.
  - The lens normalisation at P3 `0x1313..0x1360` matches `0x1200..0x124D`, with `0x1C3C`, `0x1C22`, `0x1C24`, the detail word `0x078C` and the store to `0x1C2A`; the work-segment fields `0x8108`, `0x810A`, `0x810C` are unchanged. The matrix rescale at P3 `0x13EF..0x1418` matches `0x12DC..0x1305` with the segment word at `0x05BE`. The matrix-vector routine `0x88FB..0x895D` occurs byte for byte once in the P3 image, at `0x7BF2`.
  - `lod.md` section 1.2 listed `DS:0x22A4`, `[bx+0x056C]` and `DS:0x22EC` for the P3 site; those are the unpatched offsets.
- **Verdict**: The captures ran the same gate. `[Established]` for the instructions of both images.
- **Lives in**: [`lod.md`](../../../research/playone-exe/lod.md) sections 1.2 and 2.2; [`memory-map.md`](../../../research/playone-exe/memory-map.md) section 1.1.
