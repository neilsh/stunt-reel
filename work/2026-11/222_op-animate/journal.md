# Journal: OP_ANIMATE

## 2026-11-11: what picks the OP_ANIMATE frame

- **Question**: Which value selects `OP_ANIMATE`'s frame, how does the `.FLM` `animate` word reach it, and what exactly does the handler draw?
- **Method**: Static, `mise run disasm` and `mise run xref` over the unpatched load image (`build/re/playone.img` in the data root), at `1308da0`: the handler `0xA9DC`, the cache lookup `0x4C41`, the draw entry `0x8073` and its blitter `0x7DE6`, the actor draw `0x1D5F`, the bank writer `0x1D96`, the frame step `0x0F4A`, and the slot interpolator `0x3E6C`. Corpus cross-check with a scratch scan of every `.ALL` under the data root's `corpus/`, and the slot keys of `CTRY.FLM` and `INTRO.FLM` read with `flm_walk.py`'s walk.
- **Result**:
  - The selector is an offset into the same word bank `ROTX`/`ROTY`/`ROTZ` read: `[selector − 0x7EF2]` is `work:0x810E + selector`. The frame is `ids[(count × word) >> 16]` (`mul` at `0xAA13`, high word to `BP`).
  - Selector `0x16` is `work:0x8124`, which `0x1D66` fills from the slot record's `+0x16` on every actor draw. The slot record is 24 bytes (`0x39AE` copies 12 words): flags at `+1`, position `+4..+0xF`, angles `+0x10..+0x14`, animate `+0x16`. `0x3EF8..0x3F13` interpolates `+0x16` while the slot's flag `0x20` (`SIF_ANIMATES`) is set: `start + ((end − start) × frac) >> 16` taken unsigned, so it falls straight down when `end < start` and never wraps; `frac` is `0x22E0`.
  - Selector `0x10` is `work:0x811E`, which `0x1DCA` writes as `[bx + 0x0E] << 12`; the frame step reaches it with `BX = 0x4888` (`0x4A2F`, `lod.md`), whose `+0x0E` is the film clock `DS:0x4896`. So a selector-`0x10` table cycles once every 16 ticks.
  - Corpus selectors: every multi-frame table uses `0x16` (shapes `0x0105`–`0x010C`, 12 frames) or `0x10` (`0x3A80` and `0x7E49`, 4 and 8 frames); the rest have one frame (selector `0x10` or `0`).
  - The draw: size `(param × work:0x8070) >> 8 / (z + work:0x8088)` pixels (the 32-bit product shifted right 8 by the byte moves at `0xA9FC`), skipped when 0 or when the register's flag byte `+0x0A` is set. `0x8073` centres it: left `x − size/2`, top `y − size/2`. `0x7DE6` stretches the image to `size × size` with 16.16 steps `width/size` and `height/size`, clips to `[0x2294..0x229A]`, and stores every non-zero byte. The cache loads a chunk at segment offset 2 (`0x4CE0`), and the blitter reads width at `es:2`, height at `es:4` and pixels from `es:8`: chunk byte 6.
  - `OP_SPHERE`'s screen radius is the same expression with its radius, so a sprite of size `p` is as wide on screen as a sphere of radius `p` is in radius.
  - All 2,815 image chunks the corpus's `ANIMATE` tables name and its archives hold are `width × height + 6` bytes with a zero word at 4 and at the end; 144 named frames are absent from their archive.
  - `CTRY.FLM` keys the explosion slot (11, shape `0x0107`) at 0, 24576, 47104 and 4096 over ticks 851–885; `CTRY.ALL` holds only frames `0x1F02`, `0x1F06` and `0x1F07` (indices 1, 5 and 6), which fall inside the interpolated sweep.
- **Verdict**: control (static reading). `[Established]` for the instruction sequences; `[Supported Inference]` that `CTRY.ALL`'s frame subset reflects the interpolated value, from one film.
- **Lives in**: [`sod-animate.md`](../../../research/playone-exe/sod-animate.md) §§ 1–3, [`memory-map.md`](../../../research/playone-exe/memory-map.md).

## 2026-11-11: drawing the OP_ANIMATE sprite

- **Question**: Does drawing `OP_ANIMATE` as `PLAYONE` selects and sizes it raise `CTRY` and `INTRO`?
- **Method**: Evidence-backed track (image `0xA9DC`, `0x7DE6`, `0x3EFE`, `0x1D66`, `0x1DCA`). The VM records each `OP_ANIMATE` as a shape sprite; the scene picks its frame from the bank word and places it at the actor; the renderer draws the image as a camera-facing square of the sprite's size, depth-tested in the actor's layer. `mise run sweep -- --var DBG_SPRITES=0,1 --films ctry,intro` (a temporary switch that dropped the sprite draws), RTX 4070, on branch `feat/222-op-animate` from `1308da0`.
- **Result**: `CTRY` 0.8973 → 0.8974, `INTRO` 0.8344 → 0.8357; IoU unchanged (0.9897, 0.9856). The explosions land where the capture draws them (`CTRY` ticks 859–881, `INTRO` 1387–1409 and 2707–2729); where an object stands within the explosion's square, the capture draws the whole image over it and our depth test cuts it.
- **Verdict**: adopted (no film falls, both rise).
- **Lives in**: [`sod-animate.md`](../../../research/playone-exe/sod-animate.md) § 4; the `expected.gpu` scores of `vault-ctry` and `vault-intro` in [`references.toml`](../../../research/parity/references.toml) (the parity log is retired for these entries).

## 2026-11-11: pushing the sprite toward the eye

- **Question**: Does moving the sprite's square toward the eye by a fraction of its size, scaled to keep its screen size, recover `PLAYONE`'s draw-over-neighbours order?
- **Method**: Heuristic track. `mise run sweep -- --var DBG_SPRITE_PUSH=0,0.25,0.5,1 --films ctry,intro` on top of the adopted sprite draw, same commit and GPU.
- **Result**: `CTRY` 0.8974 / 0.8974 / 0.8975 / 0.8971, `INTRO` 0.8357 / 0.8360 / 0.8361 / 0.8362. The best mean (0.5) gains 0.0001 and 0.0004.
- **Verdict**: rejected: no film gains 0.004, and not every film gains 0.002.
- **Lives in**: [`sod-animate.md`](../../../research/playone-exe/sod-animate.md) § Ruled out.
