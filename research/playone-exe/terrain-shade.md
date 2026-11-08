---
summary: "`GVPOLY`/`GVPOLY16` shade as a Gouraud ramp on the palette index (`SHADES` term, `idx = base + (s >> 9)`, screen-space fill), lit by the world light the var-13 handler writes; the ground does not."
---
# `PLAYONE.EXE`: Terrain Shading (Gouraud in Palette-Index Space)

* **Binary**: `PLAYONE.EXE` (LZEXE 0.91), unpacked with [`unlzexe.py`](../../python/scripts/unlzexe.py) to the 200,524-byte load image (`build/re/playone.img`)
* **Method**: Capstone 16-bit disassembly of the unpacked image, cross-checked against the notebook addresses in [`sod-vm.md`](sod-vm.md) (`image_offset = notebook_address + 0x6F30`)
* **Scope**: the Gouraud polygon path of the display-list VM (`GVPOLY`, `GVPOLY16`): where the base colour comes from, how a per-vertex shade is computed, how the filler writes the framebuffer, and the light it uses
* **Anchors**: none new; how the ground itself is drawn is in [`world-scene.md`](world-scene.md)
* **Evidence tier**: `[Established]` for the instruction sequences, addresses and formulas below; `[Bounded Observation]` for the light's callers (section 4.2)

**Correction, 2026-11-04.** The ground is not drawn by this path. `PLAYONE` draws each ground polygon flat at its `MAP.BIN` colour from a leaf of the scenery tree in its own image, and paints the airfield's scenery tiles (`SCENERY2.RES`, `SCENERY3.RES`) over it ([`world-scene.md`](world-scene.md) sections 2, 3). Sections 3 to 6 stand as the rule for `GVPOLY` objects; in the airfield shot only the hero aircraft uses it. The readings in sections 1, 2, 7 and 9 that a ground polygon is a Gouraud ramp, or that `MAP.BIN`'s colour is not the player's, are superseded. The 193/194/196 on patch 4, and their straight screen-space boundaries, are the edges and colours of the tiles drawn over it.

---

## 1. A `GVPOLY` polygon is a ramp on the palette index

PLAYONE draws each `GVPOLY` polygon as a **Gouraud ramp on the palette index itself**: 8.8 fixed point, 1/256-index resolution, high byte written per pixel. There is no per-pixel depth term and no depth buffer.

## 2. No `MAP.BIN` in the image (superseded reading of the colour)

* No file-name literal `MAP.BIN` exists in the image (the only file literals are `game.cfg`, `game.var`, `pfont.bin`, `pilots`, `res\*.res`, `res\*.xmp|.xma|.xmm|.ess|.smp|.zcr`, `driver1..3.bin`, `vdata.bin`, `VAULT\*.FLM`, `VAULT\*.TKE`, `VAULT\*.*`, `VAULT\SPOOL.$$$`).
* The immediate `0x1E` (30, the `MAP_AREA` stride) occurs **zero** times in the code region `0x0000..0xD510`, so this binary never walks 30-byte patch records. The demo build streams/embeds its ground geometry instead (see [`sod-vm.md`](sod-vm.md)).
* Superseded: `0x9988: mov ch, byte ptr es:[si+1]` reads a `GVPOLY` base, not the ground's colour. The ground's `195` is the colour word of a leaf in the image's scenery tree, equal to `MAP.BIN`'s byte ([`world-scene.md`](world-scene.md) section 2).

## 3. Per-vertex shade: `SHADES` (opcode `0x0156`)

Dispatch `0x839C` -> handler `0x9481`. Operand stream: `di_off, count, (nx, ny, nz)*count`.

```asm
9481  bf 68 74        mov  di, 0x7468      ; shade array in the work segment
9484  26 ad           lodsw es:[si]        ; offset into the shade array
9486  03 f8           add  di, ax
9488  26 ad           lodsw                ; count
948a  8b c8           mov  cx, ax
948c  26 ad           lodsw                ; nx
948e  f7 2e 72 80     imul word [0x8072]   ; Lx
9498  ...             ; ny * [0x8074], nz * [0x8076], accumulate into BP:BX
94ac  81 fd 00 40     cmp  bp, 0x4000
94b0  7c 03 bd ff 3f  jl / mov bp, 0x3fff ; clamp |dot| <= 0x3FFF
94b5  f7 dd           neg  bp
94b7  89 2f           mov  [di], bp        ; s = -clamp((N.L) >> 16)
```

`s = -clamp((N . L) >> 16, +/-0x3FFF)` per vertex normal, one word per emitted normal at `work:0x7468 + off`.

## 4. The light vector and the sun

| Item | Address | Notes |
|---|---|---|
| Light vector `L` | `work:0x8072/0x8074/0x8076` | set by `0x9106` inside the per-object setup entry `0x9100` (which also sets the model shift `0x806E` and projection scale `0x8070`) from `AX/BX/DX`; rotated in place by the display-list rotation op at `0xA8BC` and restored by `0xA9B8` (section 4.2) |
| Sun-billboard direction | `work:0x8078/0x807A/0x807C` | written by the film-variable-13 handler at `0x196C` (angle = var13 - 0x4000, trig at `0x824:0x05D2`, also stored at `DS:0x49EC`), read by the sun-disc drawer `0x908E` |

`L` is three words in the same layout as the negated sun vector six bytes later, and only the shading opcode reads it, so it is the scene light direction. A static search finds no `lcall 0,0x9100` because the three callers address it as `lcall 0824:0EC0`, in the VM segment (section 4.2).

### 4.1 The entry decodes, but it is handed its light

`[Established]` for the instruction sequence. Disassembled at image `0x9100`, the routine is a per-object setup that fills a 0x2E-byte state block at `work:0x806E` and then runs the display list:

```asm
9100  push ds / mov di,0x15d4 / mov ds,di   ; work segment: 0x15D4 here, 0x1DF8 at runtime (+0x824)
9106  mov [0x8072],ax ; mov [0x8074],bx ; mov [0x8076],dx   ; L, straight from the caller's AX/BX/DX
9111  sub ch,cl
9113  mov [0x806e],cx                     ; shift word: low byte is the exponent
911d  shr [0x8108],cl ; mov [0x8070],ax    ; projection scale
9124  cmp bp,0x200 / test against [0x8084] → one of two clip sets
914f  [0x807e]=0x3994 [0x8080]=0x4794 [0x8082]=0x1ab1
9167  [0x807e]=0x3943 [0x8080]=0x42ce [0x8082]=0x1afa
9161  lodsw ax,es:[si] / call ax           ; the first word of the stream is a code offset
```

So the light is not computed here: it arrives in registers from the caller (section 4.2). What the routine does own is the block layout and the fact that `0x806E` is a **shift count, not a model origin**: its low byte is the exponent used at `0xADAC`, where a model coordinate pair `([si+0x0A],[si+0x0C])` becomes `((hi >> (0x10 - cl)) + (lo << cl)) - [0x8084]`. The 0x17 words at `0x806E` are copied to the stack, passed through `0x1B75` and copied back at `0xB568`-`0xB585`, so that block is the walker's per-frame input.

### 4.2 Who hands it the light

*[Bounded Observation]* for the calls (DOSBox-X breakpoint plans `light-caller`, `light-callers-tilt`, `light-source`, `light-work` and `light-writers` in `tools/dosbox-x/plans/`, [`debugger-plans.md`](debugger-plans.md); `CTRY.FLM` and `INTRO.FLM`, both builds, 2026-11-04); *[Established]* for the instruction sequences. `0x9100` is called once per drawn object, each with its own object segment in `ES` (the stream at `ES:0x000C`, `es:[2]` to `SI`, `es:[4]` to `BP`, `es:[8]` to `CH`, `[0x22EC]` pushed), from three sites:

| Call site (return) | Patch #3 return | Passes | Share of 40 calls, ticks 169-173 |
|---|---|---|---|
| `0x21F9` (`0x21FE`) in function `0x1DD5` | `0x2311` | `DS:0x49EC..0x49F0` unchanged | 24 |
| `0x234B` (`0x2350`) in function `0x1DD5` | `0x2463` | `DS:0x49EC..0x49F0` unchanged | 14 |
| `0x1D8D` (`0x1D92`) in function `0x1D5F` | `0x1EA5` | the world light rotated into the object's frame | 2 (one object, `ES = 0x608A`) |

The third caller is reached through `0x1CFB`. Unless the object's flag `[si+0x0F] & 1` selects a stored matrix, it builds the object's rotation matrix from its three angles `[bx+0x10]`, `[bx+0x12]`, `[bx+0x14]` (`0824:04E5`, into `work:0x80D2`), multiplies it with the view matrix `0x80C0` into `0x808A` (`0824:060A`), transforms `DS:0x49EC` by it (`0824:071D`) and doubles the result into `AX/BX/DX`. Inside the display list, the rotation op at `0xA8BC..0xA8EB` rotates `L` (and the vector at `0x8096`) by the op's cosine and sine for a sub-model, and the ops at `0xA99A` and `0xA9B8` save and restore the matrix and `L` around it.

`DS:0x49EC..0x49F0` is the world light. The variable-13 handler `0x196C` is the one writer found (`[Bounded Observation]`: four direct references per word, [`memory-map.md`](memory-map.md), which a static count cannot extend to indirect stores, and the memory watch `light-writers`, described next). The handler (Patch #3 `0x1A7F`) computes `angle = var 13 - 0x4000`, a fixed second angle `0x71C` (about 10 degrees), trig at `0824:05D2`, stored at `DS:0x49EC` and negated at `work:0x8078` for the sun disc. Its caller `0x0F50`, in the frame step `0x0EE9`, passes `[0x4888 + 0x98]`, variable 13's copy in the film-state snapshot. It is entered with `var 13 = 0x002D` on `CTRY.FLM` on both builds (first at tick 74 unpatched in the earlier plans, which armed late; 51 in the series below, and 53 patched) and on `INTRO.FLM` unpatched (ticks 48, 159 and 204; no patched `INTRO` run), and the world light it stores is `(99, 32766, -17)`. `DS:0x49EC` held that value at every sample: ticks 59, 160-587 (`light-work`), 204 and 462. The memory watch `light-writers` saw no changing write, but both of its runs ended on the 120 s timeout soon after tick 75, so it does not cover the film; `light-world-series` below does.

So every object set up through `0x9100` without a rotation is lit by the world light, a function of variable 13 alone, and a rotated object by that light in its own frame. The ground takes no light: its leaves are drawn flat and never pass through `0x9100` ([`world-scene.md`](world-scene.md) section 2). The per-shot tilts of section 8 are the light of rotated objects and sub-models, sampled at `work:0x8072` after the last object of the frame was set up. At every sampled tick of both films the world light was `(99, 32766, -17) / 32767` with variable 13 at `0x002D`. Whether a renderer computes `L` from variable 13 or tabulates it is still open (Open questions).

*[Bounded Observation]* for the series over the whole of `CTRY.FLM` (plan `light-world-series`: a break on `0x196C`, Patch #3 `0x1A7F`, to `stop_tick = 1342`, logging the registers (`AX` is variable 13) and `DS:0x49EC..0x49F0` on every entry; one film, DOSBox-X 2026.10.01, 2026-11-05, both runs on the committed plan). The handler was entered 161 times unpatched (film clock 51 to 1340) and 156 times on Patch #3 (53 to 1340), and every entry carried the same values:

| Build | Entries | Clock range | `AX` (variable 13) | `DS:0x49EC..0x49F0` on entry | Caller |
|---|---|---|---|---|---|
| unpatched | 161 | 51-1340 | `0x002D` on all | `6300 fe7f efff` = `(99, 32766, -17)` on all | return `0x0F53` |
| Patch #3 | 156 | 53-1340 | `0x002D` on all | `(99, 32766, -17)` on all | return `0x1066` |

Variable 13 never leaves `0x002D` at any entry, and the light on entry (what the previous entry stored) never leaves `(99, 32766, -17)`. The entries are not evenly spaced (usually 3 to 6 ticks apart; the largest gaps are 224 ticks unpatched (51 to 275) and 243 patched (53 to 296)). The data does not distinguish whether the handler was not entered during a gap or the breakpoint missed an entry. That does not matter if `0x196C` is the only writer: it stores a function of `AX` unconditionally, so the light is `f(0x2D)` from the first entry to the end of the film. That conclusion holds only under the premise that `0x196C` is the only writer, which has the tier of the premise (`[Bounded Observation]`, above); the residual risk is another writer whose change is undone before the next entry. Within `CTRY.FLM` the only per-frame differences in `work:0x8072` (section 8) would then be the rotated copies of rotated objects.

_Found 2026-11-04; the whole-film series added 2026-11-05; see the [parity log](../parity/log.md)._

## 5. Index composition

Opcodes `0x0168` (handler `0x995C`, per-vertex path) and `0x02BE` (handler `0x9A24`) both do:

```asm
9988  8b 6c 01 00     mov  ch, es:[si+1]   ; base palette index (195 for the airfield)
99e5  8b 87 68 74     mov  ax, [bx+0x7468] ; s
99e9  d1 f8           sar  ax, 1           ; s / 2, fraction kept in AL
99eb  02 26 2e 81     add  ah, [0x812E]    ; + global one-step offset G
99f1  33 c0           xor  ax, ax          ; clamp index part >= 0
99f3  02 e5           add  ah, ch          ; INDEX = base + light
99f5  89 45 02        mov  [di+2], ax      ; store (index << 8) | fraction
```

```
s      = -clamp((N . L) >> 16, +/-0x3FFF)
idx    = max(0, highbyte(s >> 1) + G) + base
vertex = (idx << 8) | lowbyte(s >> 1)
```

The flat variant at `0x9A58` (used when `work:[0x806B] == 0`) replaces `s >> 1` with `s >> 3`, so `idx = base + (s >> 11)`.

**The global offset `G` is 0 in the shipped build.** At `0x0E1C` startup computes `G` from `DGROUP:0x713`, which is `0xFF` in the image (`neg al; mov es:[0x812E], ah`). So there is no constant global darkening anywhere: every visible offset has to come from the light term.

## 6. The filler writes an index ramp

Polygon filler `0x75DB` (reached by `lcall 0,0x75DB` from `0x9A15`; the 16-bit accumulate is at `0x7671`), per span:

```asm
760c  ad              lodsw                ; span x1
760f  ad              lodsw                ; span x2
761a  8b 47 02        mov  ax, [bx+2]      ; right end value (8.8)
761d  2b 07           sub  ax, [bx]        ; - left end value
7620  f7 f9           idiv cx              ; per-pixel delta = (right - left) / width
7671  aa              stosb es:[di], al    ; write palette index (high byte)
7672  02 e2           add  ah, dl
7674  12 c6           adc  al, dh          ; accumulate the full 16-bit index:fraction
76c7  81 c5 40 01     add  bp, 0x140       ; next scanline
```

Edge entries are prepared at `0xC65A` and clipped by the Cohen-Sutherland clipper at `0xBF82`/`0xC073` as 4-byte `(screen_x, idx<<8 | fraction)` pairs. The interpolation is **linear in screen space** and happens in index space.

## 7. Consequences for parity

* Inside one polygon the written index is `base + floor(k)` for a continuously varying `k`, so pixels fall into two to four adjacent ramp entries with **hard boundaries along straight lines**: the level sets of a linear function of screen position. For ground seen by a pitched camera a constant-screen-`y` iso-line is approximately a constant-world-`z` line (the 18-20 m boundary measured from the captures), but it is not a plane in world `(x, z)`, which is why a world-space plane fit and a per-patch lookup both fail (section 9, [Ruled out](#ruled-out)).
* Per-shot movement can only come from `L` or from a different ground polygon with different vertex normals. The scale is `idx = base + (s >> 9)`, so **one ramp step is 512 units of `s`**: a small change of `N . L`. A faithful reconstruction needs `L` exactly, not merely "a sun".
* A flat polygon whose vertex normals are all equal produces no ramp. The three shades inside `MAP.BIN` patch 4 are scenery tiles drawn over it, not a ramp (see the correction above).
* An exact implementation needs per-vertex `s`, `idx = base + (s >> 9)`, 8.8 interpolation with `@interpolate(linear)` on the shade varying, quantised per fragment.

## 8. Measured inputs: the light and the additive-only rule

*[Bounded Observation] for the samples, [Supported Inference] for the consequence.* These samples read `work:0x8072` once per frame, so they show the light of the last object set up in that frame: the world light after scenery, a rotated copy after a rotated object (section 4.2). The light vector was measured live with [`probe_playone_light.py`](../../python/scripts/probe_playone_light.py) (DOSBox-X TAC harness, film `CTRY.FLM`). At the post-retrace trap the display-list work segment is `0x1DF8` (far pointer at `DS:0x0542`); `work:0x8072` holds the light of the last object set up (the world light for an unrotated one, a rotated copy otherwise), `DS:0x49EC` holds the world light in its first three words, and `work:0x8078` holds the world light negated. `L` is a unit vector at 1.0 = 32767 (magnitudes 32761-32766):

| Film clock | `L` at `work:0x8072` |
|---|---|
| 14, 65, 448, 702, 900, 1100, 1251 | `(99, 32766, -17)` (straight up) |
| 155 | `(-19344, 26134, -4016)` |
| 276 | `(-15780, 25000, -14120)` |
| 345 | `(-9156, 28402, -13524)` |
| 564 | `(-570, 31498, -8998)` |

`N` is scaled the same way, so `(N . L) >> 16` peaks at `0x4000`, exactly the clamp constant. The shade array (`work:0x7468`) changes with the tilt (negative entries at clock 564), so the harness observes a real per-frame lighting state.

The index composition adds a non-negative offset (`G = 0`) to a per-polygon base byte, so **a polygon can never be drawn darker than its own base colour**. The captures draw the airfield at 193, 194, 195 and 196, values on both sides of `MAP.BIN`'s 195, which one base cannot produce. The answer is not a base per ground polygon: the airfield is patch 4 at 195 with tiles of 193, 194 and 196 on top ([`world-scene.md`](world-scene.md) section 3). This is why no per-frame light fit ever worked.

_Found 2026-10-23 at `b44c6bc`; see the [parity log](../parity/log.md)._

## 9. What the captures show on the flat airfield

*[Bounded Observation], `CTRY.FLM`, 114 scored frames.* Our render's index and layer planes were joined to the capture at the same `film_tick`; view depth `w` and screen position were reconstructed for the colour-195 flat patches by intersecting each pixel ray (authored camera from `palette_controls.json`, 45 degree FOV, 4:3, the 200/185 vertical squeeze, roll about the view axis) with the plane `y = 0`. That is exact because all 12 colour-195 patches carry raw y 0.

* **The data colour is almost never drawn.** The capture draws 195 on under 1% of those pixels. The whole patch sits at one neighbouring ramp entry for long stretches and switches between them:

  | `film_tick` | eye height (m) | pitch (deg) | capture index on our flat terrain | share |
  |---|---|---|---|---|
  | 10 | 14.00 | -13.8 | 194 | 90% |
  | 97 | 13.40 | -13.7 | 195 | 45% |
  | 185 | 10.29 | -13.6 | 193 | 41% |
  | 273 | 7.02 | -13.2 | 196 | 50% |
  | 360 | 4.32 | -13.2 | 194 | 44% |
  | 404 | 3.59 | -13.2 | 196 | 92% |
  | 448 | 3.26 | -13.1 | 196 | 92% |
  | 667 | 3.14 | -12.2 | 196 | 93% |
  | 1063 | 2.89 | -0.7 | 193 | 79% |
  | 1194 | 2.89 | -0.5 | 193 | 92% |

* **Not the palette, the map or the fade.** Palette entries 192-199 are byte-identical at ticks 10, 273, 448 and 667 (`[36,69,20]` to `[101,162,69]`), so 194 and 196 are genuinely different framebuffer values. Only the fade (from about tick 990) dims them, and the shifts happen before it.
* **One polygon, up to three shades.** 61,205 flat-terrain samples (every second frame, every fourth pixel; pixel ray to `y = 0`, first `MAP.BIN` patch in loader order containing the point) land on record 4, the airfield, where the capture draws 196 on 50%, 194 on 27% and 193 on 13% (rest edge and prop pixels). A pixel-ID render over all 114 frames (`DBG_TERRAIN_ID`, every patch at its own index) agrees: record 4 holds 2,438,973 of 3.35 million terrain pixels and is drawn 196 on 58.3%, 194 on 24.3%, 193 on 15.4%, 195 on 0.3%. All five of its anchors carry `f[10] = 31`, so no per-patch or per-anchor field is the driver.
* **The split follows screen position.** At tick 273 the capture splits 194 (far) from 196 (near) inside the patch, with no data-colour edge within 3 px of the boundary (328 boundary nodes). The boundary slope is about 0.23 rows per pixel against 0.30 for a constant-`w` line and 0 for a scanline, at reconstructed `w` of 18-20 m with camera roll 340 degrees. That matches the straight screen-space iso-index line of section 1, not a world plane.
* **The level changes per shot, not with the camera.** Ticks 273 (eye 7.0 m) and 448 (eye 3.3 m) share pitch -13.2 degrees and view direction yet differ (far ground 194 against a uniform 196). The sky moves on the same timescale (top-of-sky mode 234 at tick 10 to 228 at tick 1194) but not monotonically with the ground.
* **Pooled by depth** (all frames): below 10 m the capture draws 196 on 89% of flat pixels, 20-30 m 194 on 81%, 30-40 m 194 on 77%, 60-400 m mostly 196 (61-73%). No fixed depth law reconciles near and far bins across frames.
* **Size of the lever.** One ramp step shifts about 40% of terrain pixels by one palette index, and terrain carries about 45% of the loss on both films.

_Found 2026-10-23 at `42cb36f`; see the [parity log](../parity/log.md)._

## Ruled out

The data-side and renderer-side explanations for the ground shade, all negative (scores are `mean_ssim_scored`, CTRY / INTRO; baseline 0.7708 / 0.6762 at the time):

* **Per-patch or per-anchor shade from `MAP.BIN`.** `f[10]` is 31 on patches 1, 4, 7, 25, 28 and the airfield; it is 0 on 826 of 1,024 anchors and 27-29 or 2-13 on far and coastal patches (10, 17, 18, 22, 29, 33, 39). An interpolated `f[10]` would be uniform on patch 4. The `num`/`bounds` words and `f[8]` (the only field that varies on patch 4: 1, 8, 102, 115, 116; meaning `[Unknown]`) do not explain it either. The community reimplementation (`FreeFlight/src/sisland.cpp`) draws each `MAP_AREA` as one flat colour and reads no `f[]` scalar.
* **Uniform terrain offset** (`DBG_TERRAIN_SHADE`): -1 gives 0.7643 / 0.6725, +1 gives 0.7683 / 0.6675, +2 gives 0.7548 / 0.6506. Worse than 0 on both films.
* **Fixed-distance depth cue** (`DBG_TERRAIN_CUE`, +1 inside / -1 outside a threshold): 15 m 0.7574 / 0.6667, 25 m 0.7572 / 0.6677, 40 m 0.7586 / 0.6689, 80 m 0.7625 / 0.6689; restricted to ramp 192-199 at 15 m 0.7601 / 0.6727. The single-frame fit (tick 273: +1 at 10-19 m, -1 beyond 40 m) averaged +0.36 in the 0-19 m bin over 114 frames. There is no per-pixel depth term in the player.
* **Coplanar draw order** (`DBG_DEPTH_LE`, `LessEqual` instead of `Less`): both films identical to four decimals. The tiles do tie the terrain, but not exactly: their quads and the terrain's fan triangles are different triangulations of one plane and round to different depths ([`world-scene.md`](world-scene.md) section 6.1).
* **Geometry:** all 12 colour-195 patches are flat and convex; fan triangulation area equals polygon area for all 166 active patches.
* **A per-shot terrain light.** The ground is drawn flat and takes no light ([`world-scene.md`](world-scene.md) section 2); the world light `DS:0x49EC` held one value at every sample (section 4.2), and the tilted values in section 8 belong to rotated objects.
* **"The ground shade is world-fixed, not Gouraud."** An earlier reading was wrong: the player interpolates the index per vertex in screen space (sections 3-6).

## Open questions

1. The trig at `0824:05D2`: `(99, 32766, -17)` has a horizontal part of about 100, where `32767 cos(var 13 - 0x4000)` would give about 141. Whether the table, a scale or the second angle accounts for it decides whether a renderer computes `L` from variable 13 or tabulates it; a film with another variable-13 value would test the formula.
2. The renderer round for the ground is the terrain-under-props change of [`world-scene.md`](world-scene.md) section 6. ([#69](https://github.com/neilsh/stunt-reel/issues/69))
