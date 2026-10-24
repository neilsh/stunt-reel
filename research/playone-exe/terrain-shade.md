# `PLAYONE.EXE`: Terrain Shading (Gouraud in Palette-Index Space)

* **Binary**: `PLAYONE.EXE` (LZEXE 0.91), unpacked with [`unlzexe.py`](../../python/scripts/unlzexe.py) to the 200,524-byte load image (`build/re/playone.img`)
* **Method**: Capstone 16-bit disassembly of the unpacked image, cross-checked against the notebook addresses in [`sod-vm.md`](sod-vm.md) (`image_offset = notebook_address + 0x6F30`)
* **Scope**: the ground/terrain polygon path: where the base colour comes from, how a per-vertex shade is computed, and how the filler writes the framebuffer
* **Anchors**: none new; the parity consequences are recorded in [`parity-findings.md`](../parity-findings.md) sections 15-17
* **Evidence tier**: `[Established]` for the instruction sequences, addresses and formulas below; `[Supported Inference]` for the light vector being the sun; `[Unknown]` for the caller that sets the light vector per shot

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

Polygon filler `0x75DB` (reached by `lcall 0,0x75DB` from `0x9A15`), per span:

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

* Inside one polygon the written index is `base + floor(k)` for a continuously varying `k`, so pixels fall into two to four adjacent ramp entries with **hard boundaries along straight lines**: the level sets of a linear function of screen position. For ground seen by a pitched camera a constant-screen-`y` iso-line is approximately a constant-world-`z` line (the "18-20 m boundary" measured from the captures), but it is not a plane in world `(x, z)` - which is why a world-space plane fit and a per-patch lookup both fail ([`parity-findings.md`](../parity-findings.md) sections 15-17).
* Per-shot movement can only come from `L` or from a different ground polygon with different vertex normals. The scale is `idx = base + (s >> 9)`, so **one ramp step is 512 units of `s`** - a small change of `N . L`; a faithful reconstruction needs `L` exactly, not merely "a sun".
* A flat polygon whose vertex normals are all equal produces no ramp. The three shades seen inside `MAP.BIN` patch 4 therefore mean PLAYONE's ground geometry is not `MAP.BIN`'s 179 records: it is the demo build's own display list, whose polygons and per-vertex normals are still to be located and decoded.

## 8. Next probes

1. **The per-shot light.** Breakpoint `0x9106` at the post-retrace trap in DOSBox-X, dump `AX/BX/DX` and the return address across two shots with different ground shade (e.g. film ticks 10 and 448 of `CTRY.FLM`), and compare with `DS:0x49EC` and the var-13 value.
2. **The ground display list.** Locate the embedded ground geometry (colour byte, vertex registers, `SHADES` normal blocks) in the image, or in the memory dumps taken at the LOAD FILM dialog, and decode it into polygons + per-vertex normals.
3. Only then is an exact renderer implementation possible: per-vertex `s`, `idx = base + (s >> 9)`, 8.8 interpolation with `@interpolate(linear)` on the shade varying, quantise per fragment.

## 9. Measured inputs, and why the base colour is baked

The light vector was measured live with [`probe_playone_light.py`](../../python/scripts/probe_playone_light.py) (DOSBox-X TAC harness, film `CTRY.FLM`). At the post-retrace trap the display-list work segment is `0x1DF8` (far pointer at `DS:0x0542`); `work:0x8072` holds `L`, `work:0x8078` holds `-L`, and `DS:0x49EC` holds `L` in its first three words. `L` is a unit vector at 1.0 = 32767:

| Film clock | `L` at `work:0x8072` |
|---|---|
| 14, 65, 448, 702, 900, 1100, 1251 | `(99, 32766, -17)` (straight up) |
| 155 | `(-19344, 26134, -4016)` |
| 276 | `(-15780, 25000, -14120)` |
| 345 | `(-9156, 28402, -13524)` |
| 564 | `(-570, 31498, -8998)` |

Magnitudes are 32761-32766, i.e. 1.0 = `0x7FFF`, and `N` is scaled the same way: `(N . L) >> 16` then peaks at `0x4000`, which is exactly the clamp constant. The shade array (`work:0x7468`) changes with the tilt (negative entries at clock 564), so the harness observes a real per-frame lighting state.

Because the index composition adds a non-negative offset to a per-polygon base byte, a polygon can never be drawn darker than its own base colour. The captures draw the airfield at 193, 194, 195 and 196 (193 on about 90% of flat pixels late in the film): values both above and below 195, which one base cannot produce. **So the player's ground display list bakes its own per-polygon colours**, and `MAP.BIN`'s 195 is not the byte it uses (see `0x9988` reading `es:[si+1]`). The apparent "per-shot shade level" is that baked colour, and the light only brightens it.

## 10. Next probes (superseding section 8)

1. **Decode the ground display list** from the dumped work/DGROUP segments (or a fresh LOAD FILM-dialog dump): polygon records with their colour byte, vertex registers and `SHADES` normal blocks. Compare its per-polygon colours with `MAP.BIN`'s patch colours; that decides between re-baking our terrain colours and rendering the player's display list directly.
2. **The per-shot light source.** `L` is mostly straight up and tilts on some shots; the caller of `0x9100` is still unknown, but with the harness above we can now sample `L` per frame and correlate it with `DS:0x49EC` and the film vars instead of guessing.
