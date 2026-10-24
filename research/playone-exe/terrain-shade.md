# `PLAYONE.EXE`: Terrain Shading (Gouraud in Palette-Index Space)

* **Binary**: `PLAYONE.EXE` (LZEXE 0.91), unpacked with [`unlzexe.py`](../../python/scripts/unlzexe.py) to the 200,524-byte load image (`build/re/playone.img`)
* **Method**: Capstone 16-bit disassembly of the unpacked image, cross-checked against the notebook addresses in [`sod-vm.md`](sod-vm.md) (`image_offset = notebook_address + 0x6F30`)
* **Scope**: the ground/terrain polygon path: where the base colour comes from, how a per-vertex shade is computed, and how the filler writes the framebuffer
* **Anchors**: none new; where the ground records come from is in [`world-scene.md`](world-scene.md)
* **Evidence tier**: `[Established]` for the instruction sequences, addresses and formulas below; `[Supported Inference]` for the light vector being the sun; `[Unknown]` for the caller that sets the light vector per shot (see [`world-scene.md`](world-scene.md))

---

## 1. The terrain is not flat-filled at its data colour

PLAYONE draws each ground polygon as a **Gouraud ramp on the palette index itself**: 8.8 fixed point, 1/256-index resolution, high byte written per pixel. There is no per-pixel depth term and no depth buffer.

For the parity loop this is the missing law behind "the airfield's flat colour is drawn one or two ramp entries away, per shot, split by a straight boundary": the boundary is an iso-index line of a linear function of *screen* position, not a world-space plane or a depth threshold.

## 2. The colour is a display-list byte, not `MAP.BIN + 0x0C`

* No file-name literal `MAP.BIN` exists in the image (the only file literals are `game.cfg`, `game.var`, `pfont.bin`, `pilots`, `res\*.res`, `res\*.xmp|.xma|.xmm|.ess|.smp|.zcr`, `driver1..3.bin`, `vdata.bin`, `VAULT\*.FLM`, `VAULT\*.TKE`, `VAULT\*.*`, `VAULT\SPOOL.$$$`).
* The immediate `0x1E` (30, the `MAP_AREA` stride) occurs **zero** times in the code region `0x0000..0xD510`, so this binary never walks 30-byte patch records. The demo build streams/embeds its ground geometry instead (see [`sod-vm.md`](sod-vm.md)).
* The airfield's `195` is one operand byte of the ground display list, read at `0x9988: mov ch, byte ptr es:[si+1]`.

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
| Light vector `L` | `work:0x8072/0x8074/0x8076` | only writer `0x9106` inside the per-frame setup entry `0x9100` (which also sets the model shift `0x806E` and projection scale `0x8070`); `L` arrives in `AX/BX/DX` |
| Sun-billboard direction | `work:0x8078/0x807A/0x807C` | written by the film-variable-13 handler at `0x196C` (angle = var13 - 0x4000, trig at `0x824:0x05D2`, also stored at `DS:0x49EC`), read by the sun-disc drawer `0x908E` |

`L` is three words in the same layout as the negated sun vector six bytes later, and only the shading opcode reads it, so it is the scene light direction. **Its caller is unknown**: there is no direct `call`/`jmp`, no `lcall 0,0x9100` and no `mov ax,0x9100`; the entry is reached indirectly.

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
* A flat polygon whose vertex normals are all equal produces no ramp. The three shades seen inside `MAP.BIN` patch 4 therefore mean PLAYONE's ground polygons are not `MAP.BIN`'s 179 records: the player draws a different set, with its own per-vertex normals and colour bytes (where that set comes from: [`world-scene.md`](world-scene.md)).
* An exact implementation needs per-vertex `s`, `idx = base + (s >> 9)`, 8.8 interpolation with `@interpolate(linear)` on the shade varying, quantised per fragment.

## 8. Measured inputs: the light and the additive-only rule

*[Bounded Observation] for the samples, [Supported Inference] for the consequence.* The light vector was measured live with [`probe_playone_light.py`](../../python/scripts/probe_playone_light.py) (DOSBox-X TAC harness, film `CTRY.FLM`). At the post-retrace trap the display-list work segment is `0x1DF8` (far pointer at `DS:0x0542`); `work:0x8072` holds `L`, `work:0x8078` holds `-L`, and `DS:0x49EC` holds `L` in its first three words. `L` is a unit vector at 1.0 = 32767 (magnitudes 32761-32766):

| Film clock | `L` at `work:0x8072` |
|---|---|
| 14, 65, 448, 702, 900, 1100, 1251 | `(99, 32766, -17)` (straight up) |
| 155 | `(-19344, 26134, -4016)` |
| 276 | `(-15780, 25000, -14120)` |
| 345 | `(-9156, 28402, -13524)` |
| 564 | `(-570, 31498, -8998)` |

`N` is scaled the same way, so `(N . L) >> 16` peaks at `0x4000`, exactly the clamp constant. The shade array (`work:0x7468`) changes with the tilt (negative entries at clock 564), so the harness observes a real per-frame lighting state.

The index composition adds a non-negative offset (`G = 0`) to a per-polygon base byte, so **a polygon can never be drawn darker than its own base colour**. The captures draw the airfield at 193, 194, 195 and 196, values on both sides of `MAP.BIN`'s 195, which one base cannot produce. So the player's ground polygons carry their own base colours (read from `es:[si+1]` at `0x9988`), and the apparent per-shot shade level is mostly that base, with the light adding a small brightening on top. This is why no per-frame light fit ever worked. That the colour is stored per polygon is confirmed in [`world-scene.md`](world-scene.md) section 3.

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
* **Coplanar draw order** (`DBG_DEPTH_LE`, `LessEqual` instead of `Less`): both films identical to four decimals, so no tie at equal depth.
* **Geometry:** all 12 colour-195 patches are flat and convex; fan triangulation area equals polygon area for all 166 active patches.
* **"The ground shade is world-fixed, not Gouraud."** An earlier reading was wrong: the player interpolates the index per vertex in screen space (sections 3-6).

## Open questions

1. Recover the per-shot light's caller: breakpoint `0x9106` at the post-retrace trap in DOSBox-X, dump `AX/BX/DX` and the return address across film ticks 10 and 448 of `CTRY.FLM`, compare with `DS:0x49EC` and the variable-13 value. With the harness, `L` can already be sampled per frame.
2. Decode the ground polygons (colour byte, vertex registers, `SHADES` normal blocks) and compare their colours with `MAP.BIN`'s: [`world-scene.md`](world-scene.md) section 6 holds the route.
3. Only then a renderer round (re-bake terrain colours or build terrain from the player's records), under the [parity skill](../../.agents/skills/improving-render-parity/SKILL.md)'s adoption rule.
