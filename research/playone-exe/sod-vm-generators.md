---
summary: "The SOD VM raw-coordinate generators: `PERFDISK`, the model frames and two-vertex polygons; lines and polygon spans are in their own note."
sidebar_label: "SOD VM model frames"
---

# `PLAYONE.EXE`: SOD VM Model Frames and Two-Vertex Polygons

Part of the SOD VM notes: [`sod-vm.md`](sod-vm.md) lists the files and states the binary and method; section numbers run across the files.

### 8.8 Model Frame: the Other Generators

`[Established]` for the instruction sequences, static, read from the unpatched load image with `mise run re-tool -- vm-handler` and `mise run re-tool -- disasm` (2026-11-11, [#272](https://github.com/neilsh/stunt-reel/issues/272)); nothing observed live.
`OP_IPG` (`0x965F`) reads its type word and calls the word table at `work:0x1954` with `BX` = the type.
Each quad handler reads `a, b, reg`, computes two corners as `M · v` ([section 8.7](sod-vm-execution.md#87-model-frame-cube-corners-and-op_vectors)) and writes each one's negation as its opposite corner, as the cube does.
`vm.rs` stores every corner turned half a turn about z, `(−x, −y, z)`, the frame of [section 8.7](sod-vm-execution.md#87-model-frame-cube-corners-and-op_vectors).

| Generator | Handler (image) | Stream operands | Writes (raw, before the turn) | `vm.rs` |
|---|---|---|---|---|
| `OP_IPG` type 2, ground quad | `0xB41E` (VM `0x31DE`) | `a, b, reg` | `reg + 0..3` = `(+a, 0, −b)`, `(+a, 0, +b)`, `(−a, 0, +b)`, `(−a, 0, −b)`: the order of the cube's corners 0..3 | matches |
| `OP_IPG` type 8, vertical quad | `0xB4B5` (VM `0x3275`) | `a, b, reg` | `reg + 0..3` = `(+a, +b, 0)`, `(−a, +b, 0)`, `(−a, −b, 0)`, `(+a, −b, 0)` | fixed: corners 1 and 3 were swapped, the reverse winding |
| `OP_IPG` type 4, object bucket | `0xB54C` (VM `0x330C`) | `w` | No register. When the head `DGROUP:0x2346 + w` is nonzero it saves the 23-word block at `work:0x806E` (shift, translation, matrix), hands that pending-object list to `0x1B75`, which takes the head and sorts and draws its actors, and restores the block; the scenery walk's `SP_LEAF` fills the head with the actors whose probe recorded bucket `w` at that object ([`scene-walk-actors.md` § 3](scene-walk-actors.md#3-buckets)). | matches (one word, no effect) |
| `OP_IPG` type 6, streamer | `0xB58D` (VM `0x334D`) | none | Registers 4..10, whatever the stream says: point `i` (0..6) is `(M · (x_i, 0, 2(i + 1)) >> work:0x806F) + (BX, DX, BP)`, the CPU registers it was entered with, saved at `work:0x41B0..0x41B4`: `BX` = 6, the type word the dispatcher `0x965F` loads, and `DX`, `BP` as the previous opcode's handler left them, since `0x965F` sets no other register. `x_i = (sin(p + (i + 1) · 0x1000) / 2 − sin(p) / 2) / 2` from the table at `work:0x19AA`, phase `p = (DGROUP:0x22B8 & 0x3F) << 10`, one turn per 64 ticks. | fixed: it read two words; the registers are not written, and no model searched reaches type 6 (below) |
| `OP_SPHERE` | `0x9DB5` | `reg, radius` | No register. Unless the register's flag byte (`+0x0A`) is set, it passes the register's projected point and the screen radius `((radius · work:0x8070) >> 8) / (z + work:0x8088)` to `0xCF39`, then to the flat filler `0x8010`, or plots one pixel (`0x7FFB`) when the radius is 0. No facing test. That `0xCF39` builds a filled circle is `[Supported Inference]` from its inputs. | frame matches (centre from the register); faces fixed, below |
| `OP_BLOCK` (`0x02D9`) | `0xA405` | `reg, size` | No register. `OP_SPHERE`'s handler with a square: unless the register's flag byte (`+0x0A`) is set, it takes `h = ((size · work:0x8070) >> 8) / (z + work:0x8088)`, plots one pixel (`0x7FFB`) when `h` is 0, and otherwise passes the screen rectangle `(sx − h, sy − h)`..`(sx + h, sy + h)` about the register's projected point to `0xBECE`, which clips it to the viewport `0x41C0..0x41C6` and writes the same span `x0..x1` for every row `y0..y1`, then to the flat filler `0x8010`. No facing test. | fixed: a cube of half-side `size` about the register, in the current colour, which shows the square face on; it was read and dropped, so city-block stand-ins such as `BOMB`'s `0x066E` drew their trees and none of their houses ([#1032](https://github.com/neilsh/stunt-reel/issues/1032)) |
| `OP_PERFDISK` | `0xA040`, operands read by `0xA08E` | `centre_reg, radius, axis_reg` | No register. It skips while the shadow mode `work:0x806C` is set or the centre's depth `z + work:0x8088` is below `0x80` (signed), else builds, from the centre, `(radius · work:0x8070) >> 16` and the normal `regs[centre] − regs[axis]`, a quadratic form that it hands to the flat filler `0x8010`: the screen outline of a disc, `[Supported Inference]`. The normal enters the outline's quadratic form only through products of its components, and no branch tests its sign, so the disc draws from both sides (`[Supported Inference]`). | fixed: a 64-gon of `radius` about the centre, perpendicular to the raw normal, one face for each side ([#392](https://github.com/neilsh/stunt-reel/issues/392)), drawn without an outline and moved onto the pixels `0xD11D` fills (`snap_disc`, [#898](https://github.com/neilsh/stunt-reel/issues/898); [the renderer's disc pixels](#the-renderers-disc-pixels)), which the renderer squeezes along the view's depth by the lens zoom ([#754](https://github.com/neilsh/stunt-reel/issues/754)) and skips in shadow mode (`work:0x806C`, `0xA045`, [#690](https://github.com/neilsh/stunt-reel/issues/690)); radius scale checked on one `BOMB` disc at ticks 2058 and 2070, on lavapipe and the GPU on `LOCATION`'s ground disc, and on the GPU on `INTRO`'s triplane wheels at four ticks, below |
| `OP_VEC` (`0x004B`) | none | none | Not a dispatched opcode ([`sod-opcodes.md`](../formats/sod-opcodes.md) § 1): `CS:0x004B` is image `0x828B`, two bytes into slot `0x0048`'s patch store, where the bytes `FE F4` begin no defined instruction. | moot: three words, no effect |

Walking the 2,425 unique models in the data root's corpus reaches type 0 in 2,192 steps, type 2 in 320, type 4 in 152, type 8 in 57, `SPHERE` in 1,584 and `PERFDISK` in 2,531, and type 6 and `OP_VEC` in none (`[Bounded Observation]`, `trace_sod` over every `0x000C`-magic entry).
No model holds the words `0x0063 0x0006` at any even offset either, so none reaches type 6 on a path the walk does not follow (`[Bounded Observation]`, the same models and the seven reference films' archives, 2,428 in all; the 2,428 are the 2,425 of `corpus/` plus the models only the reference archives under `captures/` add, which the journal's Method scopes but does not itemise, so the three-model difference is likely, not checked, those).
The type-8 fix reverses the winding of any polygon that uses corners 1 or 3, so such a face that drew from the wrong side should now draw from the right one (`[Supported Inference]`: not checked against a capture).
_Source: [the #479 read](../../work/2026-11/479_perfdisk-sliced-streamer/journal.md#2026-11-17-sliced-discs-the-type-6-registers-and-the-disc-skips-read-statically)._
`OP_BLOCK`'s handler and `0xBECE` are `[Established]` for the instructions of the unpatched image; drawing the cube raised `BOMB` and `LAND` and moved no other reference film past the bounds, adopted on the evidence-backed track.
_Source: [the far town's stand-ins draw no `OP_BLOCK`](../../work/2026-11/1032_block-stand-ins/journal.md#2026-11-24-the-far-towns-stand-ins-draw-no-op_block), [`OP_BLOCK` drawn as a cube](../../work/2026-11/1032_block-stand-ins/journal.md#2026-11-24-op_block-drawn-as-a-cube)._

**`OP_PERFDISK` read** (2026-11-12, [#392](https://github.com/neilsh/stunt-reel/issues/392); `[Established]` for the instruction sequences, static, from the unpacked image with `mise run re-tool -- disasm`; nothing observed live).
The entry `0xA040` reads `centre_reg, radius, axis_reg` at `0xA08E`.
It skips in shadow mode and when the centre's view depth is below `0x80` (signed).
It scales the radius as `(radius · work:0x8070) >> 16`, the normal's depth difference by `work:0x8108` shifted by `work:0x810C + 1`, and normalises the radius and centre to one shift (`0x9FD9`) and the normal to another (`0x9FAB`).
It forms products of the normal's components in 32-bit arithmetic and calls `0x0D11D` with a screen centre, two extents and two offsets (`si`, `di`) that shear the mirrored half.
`0xD11D` clips against `work:0x41C4`/`0x41C6`, returns carry set off screen, and builds a table of row spans with a stepped 32-bit decision variable (`0xD440`, `0xD4AF`), not a closed form; the flat filler `0x8010` fills them.

**The pixels `0xD11D` fills** ([#898](https://github.com/neilsh/stunt-reel/issues/898); `[Established]` for the instruction sequences, static, from the unpatched image with `mise run re-tool -- disasm`; nothing observed live).
`0xA08E` calls it (`0xA2B7`) with the centre pixel `x` in `AX` and `y` in `BX`, the vertical half-extent `H` in `DX`, the centre row's half-width `A` in `CX`, and a 16.16 shear in `SI:DI`.
`x` and `y` are `idiv` quotients plus the projection centre `work:0x41C8`/`0x41CA` (160, 92; `0xA235..0xA25E`), so each is the offset truncated toward that centre; `H` (`0xA27B`) and `A` (`0xA2A6`) are `idiv` quotients made positive, so truncated.
The table's row bounds are `y − H` and `y + H − 1` (`0xD1D3..0xD1EF`).
`0xD440` writes the centre row and the `H − 1` rows below it, each from `x + shear − w` to `x + shear + w` with `w` starting at `A` and stepped down by the decision variable, and `0xD249..0xD274` copies them, from the centre row down, to the rows from `y − 1` up, mirrored through the centre.
So a disc fills `2H` rows, symmetric about the boundary above row `y`, and its centre row `2A + 1` pixels, symmetric about pixel `x`'s centre, as the sun disc `0xCF39` does in rows.
The captures fit it where unoccluded: `INTRO` `0x7F04`'s hub is 19 × 18 at tick 1101 and 9 × 8 at 1244 and its tyre 27 × 26 at 1101, `BOMB`'s wheel 61 × 60 at tick 2058 (`[Bounded Observation]`: those discs, read off their flat colours).
_Source: [the disc's rows read out of `0xD11D`](../../work/2026-11/898_perfdisk-row-height/journal.md#2026-11-22-the-discs-rows-read-out-of-0xd11d-and-three-candidates-read-at-the-wheel-rows)._
`0xA05C`, the entry of `OP_PERFDISCSL` (`0x264`), runs the same builder `0xA08E` but stores the span table's start at `work:0x423E + n` for its fourth operand `n` instead of filling ([section 9.1](sod-vm-frame.md#91-the-actor-shadow-draw)).
No branch tests the sign of a normal component.

**Perforation and the skips** (2026-11-17, [#479](https://github.com/neilsh/stunt-reel/issues/479); `[Established]` for the instruction sequences, static, the unpatched image read with `mise run re-tool -- disasm`; nothing observed live).

* **`OP_PERFDISK` never perforates.**
  `0xA040` calls `0xA08E` once and the flat gateway `0:8010` once, and reads or writes no span slot, so it fills one solid disc.
  A hole could only come from the sliced ops: a sliced builder such as `OP_PERFDISCSL` puts a span table in a slot, `0x291`, `0x29A`, `0x2A3` and `0x2AC` (`INTSL`, `SUBSL`, `ADDSL`, `DUPSL` by the opcode table; handlers `0xA4A6`, `0xA4C7`, `0xA4E0`, `0xA4FF`, which pass slots to `0xBCE0`, `0xBDC7`, `0xBDA5` and `0xBE7D`, not read) combine slots, and `0x288` (`0xA48F`) fills one through `0:8040`.
* **No model uses a sliced op** (`[Bounded Observation]`, 2,428 unique models: the data root's `corpus/` and the seven reference films' archives).
  No `trace_sod` walk steps on any of the 15 sliced opcodes (`0x240`..`0x2AC`, `0x345`, `0x3BA`, in [`sod-opcodes.md`](../formats/sod-opcodes.md)'s numbering).
  `sod-opcodes.md` numbers the patched build, and Patch #3 re-encoded no shape ([`patch3.md` § 4.1](patch3.md#41-the-patched-build-has-one-dispatch-slot-fewer), [#480](https://github.com/neilsh/stunt-reel/issues/480)), so the 15 are the sliced opcodes as the patched build numbers them.
  On the unpatched image `0x345` and `0x3BA` dispatch to `0xB13E` and `0xB0E9`, which fill flat (`call 0xB170; jb; call 0:8010`, and `call 0xCF39; call 0:8010`); the sliced handlers there, which store `[bx + 0x423E]`, are `0x34E` (`0xB14C`) and `0x3C3` (`0xB109`), nine above ([`patch3.md` § 4.1](patch3.md#41-the-patched-build-has-one-dispatch-slot-fewer)).
  Every `0x0264` word at an even offset lies inside an instruction a walk decodes.
  The 42 other sliced-opcode words that lie outside every decoded instruction all lie past the last word their shape's walk reaches.
  Only one of their 19 shapes has `BVGT`s (`PLANES.RES` `CESSNA 172`), and each of its three branches lands on an instruction the walk decodes.
  So no shape in this corpus draws a perforated disc.
  `vm.rs` has no handler for the sliced ops, and its census would list a shape that stopped on one.
* **The centre-depth skip.**
  `0xA08E` returns with carry, so nothing is filled, when the centre's view depth `z + work:0x8088` is below `0x80`, signed (`cmp bp,80h; jl` at `0xA09A`, so a negative depth is dropped too).
* **The eye-plane skip** (`0xA156`).
  With the radius `r`, the centre `(x, y, z)` and the normal `n` each shifted to a common scale, the builder forms `D = hi(z²) · hi(|n|²) − hi(nx² + ny²) · hi(r²)` (`0xA10A..0xA152`, `hi` the high word of a 32-bit product).
  It exits with carry through `0xA2BC` unless `D`'s high word is above 0, and that word is the divisor at `0xA235`, `0xA25A` and `0xA27B`.
  `[Supported Inference]` from the algebra: with exact products `D > 0` says the rim's least view depth, `z − r · √(nx² + ny²) / |n|`, is above 0, so a disc any part of which reaches the eye plane is dropped whole, where a clipper would draw the part in front.
  A zero normal (axis register equal to the centre register) gives `D = 0` and is dropped.
  `CTRY.ALL` shape `0x064A` has two such discs, and `vm.rs` drops them too, since `disc_polygons` returns nothing for a normal shorter than `1e-6`.
* **The second skip** (`0xA1AB`).
  It exits when the high word of a second 32-bit term (`work:0x4228`, built at `0xA185..0xA1A7` from the centre, `r²` and the normal) is 0.
  That word is the divisor at `0xA1FC` and `0xA2A6`, so the test at least guards those divisions; what the term measures was not worked out.

_Source: [sliced discs and the disc skips read](../../work/2026-11/479_perfdisk-sliced-streamer/journal.md#2026-11-17-sliced-discs-the-type-6-registers-and-the-disc-skips-read-statically)._

`vm.rs` draws the disc as a 64-gon (the radius is checked, below; the count, under [the renderer's disc pixels](#the-renderers-disc-pixels)) in the plane perpendicular to the raw register difference `regs[centre] − regs[axis]`, one face for each side, in the current colour, with `radius` in register units.
**Scale checked against a same-camera capture** ([#425](https://github.com/neilsh/stunt-reel/issues/425)).
`OP_SPHERE` shifts the radius product by 8 and divides by depth; this handler shifts by 16 (`0xA0A2..0xA0A6`: `imul [0x8070]`, high word) and leaves the perspective to the conic it builds, so the two shifts do not by themselves say the disc is 256 times smaller.
`BOMB` tick 2058 has a capture and a render from the same camera (the car body's left edge and the disc's centre column agree to 2 px), and the wheel disc's width agrees with `radius` in register units to about 2 px (one shape, ticks 2058 and 2070; a second shape is read below): at the rows 172 and 184 the capture is 77 and 91 px wide, the 16-gon 72 and 87 px, and a 64-gon 1 to 2 px under the capture; at tick 2070 the capture and the 64-gon differ by 1 to 2 px over four rows (`[Bounded Observation]`: two ticks, one shape, widths read off the palette index of the disc's flat colour).
The 16-gon is 4 to 6 % narrow and the 64-gon closes most of that gap; before [#898](https://github.com/neilsh/stunt-reel/issues/898) the remainder was unexplained, and [the renderer's disc pixels](#the-renderers-disc-pixels) now gives `BOMB`'s wheel the capture's size.
A 32-gon, with the outline the disc then had, moved no film by more than 0.00015 SSIM and BOMB, LOCATION, LAND and INTRO fell (BOMB -0.00014), so it was not adopted then.
The `work:0x8108` rescale of the normal's depth difference (`0xA0DB..0xA0E8`) is `dz · 0x8108 · 2^(0x810C+1) >> 16`; with the view matrix's two screen rows scaled by `0x8108` in Q15 and the depth row shifted right by `0x810C` ([`memory-map-vm.md`](memory-map-vm.md)), that makes the normal's three components share one scale, which `vm.rs` already has because it keeps the normal in the model frame, so no rescale is added (`[Supported Inference]`: read from the two sites, not verified live; a 2 px height gap at tick 2058 is unexplained).
The centre's depth is not rescaled: that is the lens squeeze below.
Of the skips, `vm.rs` reproduces the zero normal, and the renderer skips `FLAG_DISC` vertices (the disc triangles, and the `outline.rs` rim quads the disc had then) during actor shadow draws (`model.layer.y != 0`, reproducing `0xA045`), adopted evidence-backed on the seven reference films (RTX 4070: `intro`, `bomb` and `location` rose under +0.002, `land` and `traintnl` moved by −0.0000004, `ctry` and `balloon` unchanged; [#690](https://github.com/neilsh/stunt-reel/issues/690)).
The centre-depth (`0xA09A`) and eye-plane (`0xA156`) skips, tested for filled-disc triangles (`!FLAG_LINE && FLAG_DISC`, leaving `outline.rs` rim quads drawn) under temporary switches verified by positive controls, moved zero frames on the seven reference films and were not adopted (see Ruled out).
Scored against the seven reference films with `mise run parity` (RTX 4070).
_Source: [the handler read and the scores](../../work/2026-11/392_perfdisk/journal.md#2026-11-12-the-handler-read-to-its-end-and-drawn); [OP_PERFDISK shadow-mode skip](../../work/2026-11/690_perfdisk-skips/journal.md#2026-11-20-op_perfdisk-shadow-mode-skip-0xa045)._

**A ground disc, read on lavapipe and the GPU** ([#709](https://github.com/neilsh/stunt-reel/issues/709), [#689](https://github.com/neilsh/stunt-reel/issues/689); `[Bounded Observation]`, two ticks, one shape, widths read off index `0x4A`, the disc's flat colour, in both panels).
`LOCATION.ALL` shape `0x07C6` is one `OP_PERFDISK` of radius `0x2400` in colour `0x4A`, its normal along y: the stone circle's ground disc in `LOCATION.FLM`, lying flat and seen at a glancing angle across most of the screen, where `BOMB`'s wheel stands upright.
At ticks 6062 and 6161 (`mise run frame -- --film location --ticks 6062,6161 --software-only`, commit `9c9c6a5` (`crates/` tree `a00c4e7`)) the camera appears to match: the stones line up and the disc's far rim is row 76 in the capture, 77 in ours.
Stones stand on the rim, so only the ends a stone does not cover are read: at 6062 the right end of rows 106, 112 and 118 is at x 298, 300 and 299 in the capture and 299, 305 and 309 in ours; at 6161 the left end of rows 106, 112, 118 and 124 is at x 22, 19, 20 and 23 in the capture and 17, 14, 11 and 8 in ours.
The near rim is row 151 in the capture and 166 in ours.
So on this shape ours is the larger: it agrees at the far rim, reaches 1 to 15 px further at the sides and 15 rows nearer the camera, where on `BOMB` the 16-gon was 4 to 6 % narrow.
_Source: [the ground disc read on lavapipe](../../work/2026-11/425_perfdisk-radius/journal.md#2026-11-18-a-location-ground-disc-read-on-lavapipe)._
On the GPU (RTX 4070), at the same commit and ticks, every rim row and free end above reads the same as on lavapipe.
_Source: [the ground disc's widths re-read on the GPU](../../work/2026-11/689_perfdisk-depth-scale/journal.md#2026-11-20-the-ground-discs-widths-re-read-on-the-gpu)._

**The lens squeeze** ([#754](https://github.com/neilsh/stunt-reel/issues/754); `[Established]` for the instruction sequences, static, from the unpatched image with `mise run re-tool -- disasm`; `[Supported Inference]` that the outline is the projection of the circle its inputs describe; `[Bounded Observation]` for the fit, two `LOCATION` ticks on lavapipe).
The builder takes its inputs in two scales.
The centre (`0xA092..0xA0C6`) is the register plus the object origin: `x` and `y` in the screen rows' units (rows 0 and 1 of the view matrix, times `work:0x8108` in Q15) and `z` in the depth row's (shifted right by `work:0x810C`).
The radius, `(radius · work:0x8070) >> 16` with `0x8070 = 0x8108 >> work:0x806F` (`0x911A..0x9121`), is in the `x` and `y` units, and so is the normal once `0xA0D3..0xA0E8` rescales its depth difference.
So only the centre's depth is the true depth over the zoom (`0x8108 / 0x8000 · 2^0x810C`, [`lod.md` § 2.2](lod.md#22-how-the-lens-scales-the-projection)).
With the projector's `256 · x / z` (`0x9CF1`, [section 8.6](sod-vm-execution.md#86-facing-flags-op_rej-and-op_ifvis)), the outline is then the true disc's with every point's depth offset from the centre multiplied by the zoom: shallower than the true disc under a wide lens, deeper under a telephoto, and unchanged to 1 part in 32,768 at the default lens, whose zoom is `0x7FFF / 0x8000`.
At `LOCATION` ticks 6062 and 6161 the lens draws at 50.95° against the default 42.67°, a zoom of 0.820.
The renderer draws it so: a rim vertex carries the vector to its disc's centre (`VERTEX_FLAG_DISC`), and the vertex shader scales its clip-space depth offset from the centre (clip `z` and `w`, which alone hold depth on the symmetric projection) by `tan(42.67° / 2) / tan(fov / 2)`.
On lavapipe the near rim then reads row 153 at both ticks (capture 151, before 166), the far rim 75 and 76 (capture 76, before 77: still within 1 row of it, though 2 rows nearer the top at 6062), and the free ends of the rows quoted above 295, 299, 298 at 6062 and 21 on each row at 6161.
On the GPU (RTX 4070) the same rows and ends read identically.
_Source: [the GPU judge and rim re-read](../../work/2026-11/754_perfdisk-lens-squeeze/journal.md#2026-11-19-gpu-judge-and-rim-re-read)._
Adopted, evidence-backed: `LOCATION` rose by 0.0011 and the target frames' index agreement by 0.042; `CTRY`, `BALLOON` and `BOMB`, at the default lens, changed no frame, so `BOMB`'s wheel is as before; the other films moved by less than 0.00003.
The scores and pictures are in the journal.
_Source: [the disc squeezed along depth by the lens zoom](../../work/2026-11/754_perfdisk-lens-squeeze/journal.md#2026-11-18-the-disc-squeezed-along-depth-by-the-lens-zoom)._

**A third shape, at 17.76°** ([#841](https://github.com/neilsh/stunt-reel/issues/841); `[Bounded Observation]`, four ticks of one shape on the GPU, widths read off the discs' flat colours in both panels).
Of every captured tick of `CTRY`, `LAND`, `INTRO`, `LOCATION` and `TRAINTNL`, the frame with the most disc pixels at a lens other than 42.67° and 50.95° whose camera matches the capture's shows `INTRO`'s triplane wheel at 17.76° (lens zoom 2.50); `LAND`'s at 11.16° hold at most 101 px of disc in a frame (tick 540, jet wheels 5 to 10 px across), and at `TRAINTNL`'s 14.84° ticks 232, 243 and 254 our train is not where the capture's is.
`INTRO.ALL` shape `0x7F04`, on the `IFVIS` branches these frames draw, draws a wheel as a tyre `OP_PERFDISK` of radius `0x0580` (colour `0x06`) and a hub of radius `0x0400` over it (`0x15` or `0x17`); other branches draw a lone disc of radius `0x0580` in colour `0x03`.
The discs' normal runs along the axle, so the wheel stands upright as `BOMB`'s does.
At 17.76° (ticks 1244 and 2553, `origin/main` `111970f`) the tyre's widest row is 16 px in the capture and 17 in ours, the hub's 9 and 11; at 42.67° (ticks 1101 and 2399) the near tyre's is 27 and 27 to 28, the hub's 19 and 20 at 1101 and 21 in both at 2399.
So the radius holds on this shape at both lenses to 2 px at those rows, ours never the narrower there: at 17.76° ours is 2 px (22 %) wider on the 9 px hub and 1 px (about 6 %) on the 16 px tyre, at 42.67° at most 1 px (about 5 %).
Below its widest rows, tick 1101's tyre is 3 to 4 px wider at rows 136 to 140 (capture 21, 17 and 11 px, ours 24, 20 and 15), which is the [#898](https://github.com/neilsh/stunt-reel/issues/898) offset.
The top rims agree to a row, but ours reaches 1 to 2 rows lower at the bottom of each disc whose bottom rim was read and is 1 to 3 rows taller in every disc whose rim rows were read (the 17.76° hub 9 × 8 px in the capture, 11 × 10 in ours).
So at 17.76°, at tick 1101 and on tick 2399's tyre ours was wider at the widest rows as well as lower at the bottom rim; [the renderer's disc pixels](#the-renderers-disc-pixels) below gives the cause and the change ([#898](https://github.com/neilsh/stunt-reel/issues/898)).
These nearly face-on wheels barely feel the squeeze: forcing it to 1 changes 3 px of the frame at tick 1244 (17.76°), against 3,487 px at `LOCATION` tick 6062 at 50.95° (both measured for #841), so they test the radius at a telephoto lens but not the squeeze or the normal's depth rescale.
That control is at a different lens than the null results it supports: at the other lenses tested (`LAND` 11.16°, `TRAINTNL` 14.84°, `INTRO` 8.28°, `LOCATION` 22.10°) the switch moved 0 to 31 px of a frame on the ticks tested, and no large squeeze-sensitive disc was found there in the five films searched.
The seven films are bounded by [#754](https://github.com/neilsh/stunt-reel/issues/754)'s sweep, which scored their captured ticks with the squeeze off and on ([#899](https://github.com/neilsh/stunt-reel/issues/899); `[Bounded Observation]`, lavapipe, tree `191fa1a`, on a tree before #898, whose discs still drew a 16-gon fill with an unsqueezed one-pixel outline, so it bounds that renderer, not today's): it changed none of `CTRY`'s 121, `BALLOON`'s 108 or `BOMB`'s 339 ticks, which #754 puts at the default lens where the squeeze is 1, and outside `LOCATION`'s ticks 5953 to 6161 none moved by more than 0.00117 SSIM (`INTRO` 43 ticks, `TRAINTNL` 21, `LAND` 4, `LOCATION` 2).
_Source: [INTRO's triplane wheels](../../work/2026-11/841_perfdisk-third-shape/journal.md#2026-11-20-intros-triplane-wheels-at-the-default-lens-and-at-1776); [`BOMB`'s disc](../../work/2026-11/425_perfdisk-radius/journal.md#2026-11-12-the-discs-size-against-a-same-camera-bomb-capture); [the squeeze switch over seven films](../../work/2026-11/899_perfdisk-lens-closeout/journal.md#2026-11-22-the-squeeze-switch-over-seven-films-and-the-disc-outline)._

#### The renderer's disc pixels

([#898](https://github.com/neilsh/stunt-reel/issues/898); `[Supported Inference]` that the rule below is `0xD11D`'s, from the static read above; `[Bounded Observation]` for the rows: six `INTRO` discs at four ticks, `BOMB`'s wheel at two and `LOCATION`'s ground disc at two, on the GPU.)
Before #898 the disc was a 16-gon drawn with the one-pixel outline every filled polygon gets ([`sod-vm-lines-spans.md`](sod-vm-lines-spans.md) section 8.11), about its projected centre, which on our symmetric projection lies half a pixel below the top of row `92 + oy` for a centre `oy` pixels below the projection centre (`sky.rs`'s `to_pixel` takes the same centre).
Against `0xD11D` that adds a row from the outline, `2 · frac(r)` rows and columns from the untruncated radius `r`, and the centre's truncation, which is why `INTRO`'s wheels drew 1 to 3 rows taller, reached 1 to 2 rows lower and were up to 2 px wider, and `BOMB`'s wheel drew 62 × 62 against the capture's 61 × 60.
Now a disc's triangles take no outline (`outline.rs` `outlines`), and the vertex shader (`snap_disc`) moves the disc's centre to `PLAYONE`'s, `x` to the centre of pixel `160 + trunc(ox)` and `y` to the top of row `floor(rows / 2) + trunc(oy)`, and pulls each rim vertex's vertical offset in by half a pixel, scaled by its distance from the centre, which is the vertical half-extent at the top and bottom of the rim.
Sampled at pixel centres, a disc of radius `r` pixels then covers rows `y − trunc(r)` to `y + trunc(r) − 1` and, at its centre row, `x − trunc(r)` to `x + trunc(r)`: `0xD11D`'s bounds when its `H` and `A` equal `r`.
Without the outline the 16-gon's chords, up to about 2.5 px inside the circle on `LOCATION`'s ground disc, lost that disc's free ends beside the stones, so the disc is a 64-gon.
At the ticks read, every `INTRO` disc's rows are within a row of the capture's (the hubs at 1101, 2399 and 1244 and the 17.76° tyre exactly); `BOMB`'s wheel is 61 × 60 and 59 × 58 like the capture's, one row lower as before; `LOCATION`'s near rim is row 151 at both ticks as in the capture and its free ends lie within a pixel of the capture's on the rows no stone covers, while the two ends at 6161 that sit beside a stone lost their one-pixel sliver and the far rim gained a row above the capture's at both ticks (that row 9 px wide at 6062, 1 px at 6161).
Adopted, evidence-backed: on the GPU every reference film's SSIM rose or held (`location` +0.00038, `bomb` +0.00024, `traintnl` +0.00044, under the 0.002 noise floor) and one frame fell by more than 0.005 (`location` 6117, −0.0083), and lavapipe gave the same verdict on the same frame; the figures and pictures are in the journal.
_Source: [the disc's rows read out of `0xD11D`](../../work/2026-11/898_perfdisk-row-height/journal.md#2026-11-22-the-discs-rows-read-out-of-0xd11d-and-three-candidates-read-at-the-wheel-rows)._

**Sphere faces.**
`PLAYONE`'s sphere is a disc on screen, so it has no winding to match.
The icosahedron `vm.rs` draws for it wound every face with its right-hand normal outward, counter-clockwise seen from outside, and the pipeline keeps clockwise faces (`FrontFace::Cw`, [`pipeline.rs`](../../crates/stunt-render/src/pipeline.rs)).
So only the far half of each sphere drew, seen from inside (`[Supported Inference]` from the winding and the pipeline's cull mode; not scored against a capture).
The faces now wind clockwise from outside and the near half draws, with the same outline.
**Checked against the captures** ([#479](https://github.com/neilsh/stunt-reel/issues/479); `[Bounded Observation]`, lavapipe, seven reference films).
Restoring the old winding moved no film's mean by more than 0.0002 and dropped 10 frames by more than 0.005, all in `LOCATION`'s forest views (tick 1717 −0.036).
At tick 1717 the capture draws each tree crown as a filled disc, the current winding draws them filled, and the old one draws several near crowns hollow.
_Source: [the sphere winding scored](../../work/2026-11/479_perfdisk-sliced-streamer/journal.md#2026-11-17-the-sphere-winding-scored-and-seen-beside-the-capture)._

_Source: [the generators read](../../work/2026-11/272_generator-model-frame/journal.md#2026-11-11-the-raw-coordinate-generators-read-statically)._

**Type-8 shapes turn with the camera's heading** ([#399](https://github.com/neilsh/stunt-reel/issues/399)).
`[Established]` for the instruction sequences, static, read with `mise run re-tool -- disasm` from the unpatched load image (2026-11-11); `[Supported Inference]` for the header byte they test and for the census tie; nothing observed live.
The flat trees are single-sided in `PLAYONE` as in the renderer, but they are drawn through a matrix that keeps them facing the camera's heading:

* **One face, drawn from one side.**
  The pines `0x03A3` and `0x03A7` (`INTRO.ALL`) are an `OP_IPG` type 8 quad and two `POLYZ` triangles wound the same way; no second, reversed face exists.
  `POLYZ` (`0x9B78`) draws through the edge builder `0xC9D4`, which takes its left edge by walking backward from the topmost vertex, and the flat filler `0x7571` skips a row whose right end is left of its left (`sub ax,cx; jl` at `0x75A1`, section 8.9).
  So a `POLYZ` face fills only where its vertices run clockwise on screen, the side the renderer's `FrontFace::Cw` cull keeps, clipped or not; [section 8.12](sod-vm-lines-spans.md#812-back-faces-the-span-test) gives the rows a back face still draws.
* **Two view matrices.**
  The view setup builds the camera's rotation with `0824:04E5` from the view slot's words `+0x10`, `+0x12`, `+0x14` (roll, pitch, yaw, [`memory-map-main.md`](memory-map-main.md)) and transposes it into `0x80C0` (`0x12A7..0x12BD`).
  It then zeroes `SI`, the yaw (`xor si,si` at `0x12C2`), and builds `0x809C` the same way from roll and pitch alone (`0x12C4..0x12DA`; with the view selector `DS:0x2285` at 0, as in film playback, the words go in unchanged, and its other values swap or negate roll and pitch but still zero the yaw).
  With the builder's `Ry(−yaw) · Rx(pitch) · Rz(roll)`, a shape drawn through `0x809C` is turned in the world by `Ry(−yaw)`, the camera's yaw about the vertical, whatever the pitch and roll.
* **The header picks one.**
  The scenery draw copies `0x809C` into the draw matrix `0x808A` when `byte [es:9] & 1` is set, else `0x80C0` (`0x21A8..0x21D0`); its position still goes through `0x80C0` (`0x2195`).
  The actor entry copies `0x809C` and skips the slot's own rotation when entry byte `+0x0F` bit 0 is set (`0x1CFC..0x1D12`), a byte the queue fills from `[es:9]` (`0x1B6C`, `0x1AF0`).
  `ES` addresses the cached shape two bytes before its `.SOD` header: `0x9100`'s caller runs the stream from `SI = [es:2]` (`0x21E2`), the magic word `0x000C`, which puts the first opcode at file offset `0x0A`; `[es:4]` is read as the cull radius (`0x1B2C`) and `[es:8]` as the scale shift (`0x21D8`, `0x1AF7`), the header's `bounding_size` and `scale_index`.
  So `[es:9]` is the header byte `0x07`, `header_flags` ([`sod.md`](../formats/sod.md) section 2.1), and bit 0 means "face the view", not flat shading.
* **Who sets it** (`[Bounded Observation]`, the two reference archives).
  In `INTRO.ALL` 21 shapes set bit 0: the 18 that open with an `OP_IPG` type 8 quad and `0x0105`..`0x0107`, which stop at `OP_ANIMATE`.
  In `CTRY.ALL` 9 do: its 8 type-8 shapes and `0x0107`.
  No type-8 shape in either leaves it clear.

**Adopted** (evidence-backed): a shape with header bit 0 is drawn turned about `+Y` so that its `+Z` lies along the camera's look direction seen from above.
That heading is taken to equal the yaw of `Ry(−yaw)` (`[Supported Inference]`: the sign was checked only by the trees drawing rather than culling); past vertical pitch it is half a turn off, and a camera looking straight down gets heading 0 where `PLAYONE` keeps its yaw word.
A view-facing prop also skips the per-placement `OP_TAP` decode and the ground-decal snap; the type-8 trees of the reference archives run no `OP_TAP`.
Props with the bit leave the static world mesh and are drawn each frame as props, behind their `SP_1NODE` gates; actors with it drop the slot's rotation, while their shadow keeps it, since `0x1C0D` builds the shadow matrix from the slot's angles.
At `INTRO.FLM` tick 2080 the hill pines, missing before, stand facing the camera as in the capture; at tick 3301 the foreground pines still draw.
In `mean_ssim_scored` (RTX 4070 Laptop) `CTRY` and `INTRO` moved under the 0.002 floor; of the other reference films only `LOCATION` moved by more than 0.0001, 0.80682 → 0.80800.
_Source: [view-facing shapes adopted and scored](../../work/2026-11/distill-sod-vm/journal.md#2026-11-11-view-facing-shapes-adopted-and-scored)._

_Source: [type-8 shapes face the view](../../work/2026-11/399_view-facing-shapes/journal.md#2026-11-11-type-8-shapes-face-the-view)._

### 8.9 Polygons of Two Vertices

`[Supported Inference]`, static (the unpacked image read with `mise run re-tool -- disasm`; no live trace of a two-vertex polygon, and no capture).
The instruction sequences are `[Established]`; what they do for a count of 2 is read from them.
`POLYZ` (`0x9B78`) has no count test of its own.
It calls the routine at `[0x8080]` and, on no carry, the flat gateway `0:8010` (`0x8010`), which calls the driver slot `[0x2246]`.
`0x9100` (section 4.1 of [`terrain-shade.md`](terrain-shade.md)) sets `[0x8080]` to `0x4794` or `0x42CE`, VM-segment offsets, so image `0xC9D4` (chosen when `0x9100`'s bounding test passes; it rejects a vertex whose flag is set) or `0xC50E` (the clipping variant, read for its operand reads only, [section 8.5](sod-vm-execution.md#85-polygon-colour-at-shade-time)).
The slot `0x2246` is the fourth word of the vector table copied from `DS:0x10A4` ([`palette-fade.md` § 4](palette-fade.md#4-driver-vector-table)), `0x7571`.

* **The edge builder takes a count of two.**
  `0xC9D4` reads the count into `CX`, copies each vertex's two screen words into a table at `work:0x4250` (written twice, `4 * count` bytes apart, so a walk wraps), and runs its vertex loop with `dec cx` before `loop`.
  That loop is right for two or more vertices.
  For a count of 0 or 1 it wraps `CX` to `0xFFFF` and reads some 65,000 words past the stream, writing 4 bytes per vertex into the table at `work:0x4250` as it goes.
  No shipped shape does (the census finds none), so `vm.rs` still stops on a count below 2.
* **Two edges.**
  It finds the topmost vertex, then fills a left and a right edge table by one walk each from it.
  The `GVPOLY` entry (`[0x812D] = 0xFF`, the Gouraud route) walks its left edge from `0xCAE7`; its right edge uses the same arithmetic from `0xCBA9` only when its top row is clipped, and otherwise jumps to the `POLYZ` forward walk (`jmp 0xCDE6` at `0xCBA6`).
  So left equals right on every row only for a top-clipped `GVPOLY`; unclipped, its right end is that of the `POLYZ` walk below (read, not traced).
  The `POLYZ` entry (`[0x812D] = 0`, walks from `0xCC53` and `0xCDAE`) is symmetric only for steep edges (`|dx| <= dy`, the integer stepper at `0xCCF5` and `0xCE4E`).
  For shallower ones the left walk takes the leftmost pixel of each row's run and the right walk the rightmost, each half a step from the edge's line ([section 8.12](sod-vm-lines-spans.md#812-back-faces-the-span-test)), so a `POLYZ` of two vertices is a connected run about `|dx/dy|` pixels wide per row there, in either vertex order (read from the instructions, not traced).
  When both vertices share a row (`[0x41D0] == [0x41D2]`) `0xCAB4` writes a single row spanning the smaller to the larger column.
* **The flat filler draws it.**
  The driver routine `0x7571` skips the table's first two words, reads the top and bottom row (the count is their difference) and, per row, `right - left`, skips a negative span, and `inc ax` before `rep stosw`: spans are inclusive, so left equal to right is one pixel.
  Clipping against `[0x2294]` and `[0x2296]` is applied first.
* **`GVPOLY16`** (`0x9A24`) runs the same edge builder, as does `OP_GVPOLY`'s handler `0x995C`, which differs only in shifting the shade by 1 where `0x9A24` shifts by 2.
  With `[0x806C]` nonzero it takes the flat route (`call [0x8080]`, gateway, colour 0, shade words skipped).
  Otherwise `[0x806B]` clear means the flat route with a colour from the first vertex's shade, and set means Gouraud: `0xC9D4` is called directly.
  The Gouraud route stores one shade per vertex (its loop counts down `CL`, right for two), and calls the Gouraud filler `0x75DB`, which tests `right - left + 1 > 0` per row: a thin line of interpolated shade.
  A vertex with its clip flag set sends the Gouraud route back through the flat route (`0x99BB`, `0x9A8A`).

So the reading is that `PLAYONE` draws a two-vertex polygon as a thin line, with no facing test: its two walks follow the same edge, whatever the vertex order ([section 8.12](sod-vm-lines-spans.md#812-back-faces-the-span-test)).
The clipping variant `0xC50E` keeps the order and runs the same builder; the vertex-rejection exit `0xC9CB` (a clip flag set) draws nothing for `POLYZ`.
One pixel per row for steep lines and a top-clipped `GVPOLY` (a shaded one), a connected run for shallow `POLYZ` lines, one row wide when horizontal; whether an unclipped `GVPOLY`'s two steppers agree on a steep line's rows was not worked out.
It is neither skipped nor an error.
`vm.rs` emits it as a line, which the renderer draws one Mode 13h pixel wide at any distance, as it draws `ZLINETO` (section 8.10): one pixel per row when `|dy| > |dx|` and per column otherwise, both ends included.
For steep lines and a top-clipped `GVPOLY` that is the reading above; for a shallow `POLYZ` it is one pixel per column where the reading gives a run about `|dx/dy|` wide per row, which covers about the same pixels (not compared pixel for pixel).
Two coincident vertices draw nothing where `PLAYONE` draws a pixel, and a `GVPOLY` line takes the mean shade level, not a gradient.
No parity reference film is known to place a shape with a two-vertex polygon ([`sod-opcode-coverage.md` § 2.1](../formats/sod-opcode-coverage.md#21-the-side-view-census-shapes-that-do-not-decode-whole)), so the score changes in section 8.10 are taken to come from `ZLINETO` lines.

_Source: [two-vertex polygons read](../../work/2026-11/393_two-vertex-polygons/journal.md#2026-11-11-the-two-vertex-polygon-read-statically)._

_Source: [the polygon span builder read for a facing test](../../work/2026-11/850_playone-back-face-cull/journal.md#2026-11-20-the-polygon-span-builder-read-for-a-facing-test)._

Lines, polygon spans, the back-face span test and the polygon clipper (sections 8.10 to 8.13) are in [`sod-vm-lines-spans.md`](sod-vm-lines-spans.md).

## Ruled out

* **`0xD11D`'s stepped ellipse or the disc's placement as the cause of `LOCATION`'s 15-row near rim** (section 8.8): not needed, since at ticks 6062 and 6161 the lens squeeze alone brings the near rim within 2 rows of the capture, keeps the far rim within 1 row and the free ends within 3 px ([the disc squeezed along depth](../../work/2026-11/754_perfdisk-lens-squeeze/journal.md#2026-11-18-the-disc-squeezed-along-depth-by-the-lens-zoom)); [#898](https://github.com/neilsh/stunt-reel/issues/898) draws its rows and centre for the smaller residues.
* **Dropping the disc's outline alone, for `INTRO`'s tall wheels** (section 8.8, [#898](https://github.com/neilsh/stunt-reel/issues/898)): it takes a row off the top of each hub, not the bottom, so the hubs stay 1 to 2 rows taller than the capture's ([the disc's rows](../../work/2026-11/898_perfdisk-row-height/journal.md#2026-11-22-the-discs-rows-read-out-of-0xd11d-and-three-candidates-read-at-the-wheel-rows)).
* **Moving the disc up half a pixel, or onto `PLAYONE`'s centre pixel, without the truncated half-extent** (section 8.8, [#898](https://github.com/neilsh/stunt-reel/issues/898)): the hubs stay 1 to 2 rows tall, and as 16-gons both lose `LOCATION`'s ground-disc ends (the centre pixel alone dropped 7 `LOCATION` frames by more than 0.005) ([the disc's rows](../../work/2026-11/898_perfdisk-row-height/journal.md#2026-11-22-the-discs-rows-read-out-of-0xd11d-and-three-candidates-read-at-the-wheel-rows)).
* **`OP_SPHERE` faces wound counter-clockwise from outside** (section 8.8), the winding before #272.
  It draws only each sphere's far half; restoring it dropped 10 `LOCATION` frames by more than 0.005 and drew near tree crowns hollow where the capture fills them ([the sphere winding scored](../../work/2026-11/479_perfdisk-sliced-streamer/journal.md#2026-11-17-the-sphere-winding-scored-and-seen-beside-the-capture)).
* **`OP_PERFDISK` centre-depth skip (`< 0x80` signed, `0xA09A`) for filled-disc triangles on the seven reference films** (section 8.8, [#690](https://github.com/neilsh/stunt-reel/issues/690)): under a temporary switch (`DBG_PERFDISK_ZMIN`) collapsing `!FLAG_LINE && FLAG_DISC` vertices (leaving `outline.rs` `FLAG_LINE` rim quads drawn) with `0x31CF`'s shift `s` mapped from `hi = floor(max |coord|)` in metres via 16.16 fixed point (`1 m = 1` in the high word, [`coordinates-and-units.md` § 2.1](../formats/concepts/coordinates-and-units.md#21-fixed-point-integer-bitfields), matching the magnitude up to 1 for negative fractional coordinates) and `work:0x810C`, the seven reference films scored identically to seven decimals and 0 frames moved; a one-frame positive control forcing `min_depth` 100,000x higher changed 4,178 px at `bomb` tick 2058 and 7,742 px at `location` tick 6062 ([the centre-depth sweep](../../work/2026-11/690_perfdisk-skips/journal.md#2026-11-20-op_perfdisk-centre-depth-skip-below-0x80-signed-0xa09a)).
* **`OP_PERFDISK` eye-plane skip (`0xA156`) for filled-disc triangles on the seven reference films** (section 8.8, [#690](https://github.com/neilsh/stunt-reel/issues/690)): under a temporary switch (`DBG_PERFDISK_EYEPLANE`) collapsing `!FLAG_LINE && FLAG_DISC` vertices (leaving `outline.rs` `FLAG_LINE` rim quads drawn) when the disc's minimum squeezed rim depth reaches the eye plane, the seven reference films scored identically to seven decimals and 0 frames moved; a one-frame positive control moving the eye plane 500 m forward changed 4,178 px at `bomb` tick 2058 and 7,739 px at `location` tick 6062 ([the eye-plane sweep](../../work/2026-11/690_perfdisk-skips/journal.md#2026-11-20-op_perfdisk-eye-plane-skip-0xa156)).
* **An actor disc's one-pixel outline left outside the lens squeeze** (section 8.8, [#899](https://github.com/neilsh/stunt-reel/issues/899)): the gap a static read of the vertex shader suggested needs outline corners that carry the disc flag, and a disc has had none since [#898](https://github.com/neilsh/stunt-reel/issues/898) (`outline.rs` `outlines`, test `a_disc_is_not_outlined`; [the outline read](../../work/2026-11/899_perfdisk-lens-closeout/journal.md#2026-11-22-the-squeeze-switch-over-seven-films-and-the-disc-outline)).

## 10. Open questions

* **The other generators** (section 8.8, [#272](https://github.com/neilsh/stunt-reel/issues/272)).
  Closed: `OP_IPG` types 0, 2, 4 and 8 and `OP_SPHERE` read against their handlers, and type 6's operand width; `OP_VEC` has no handler.
  Closed by [#479](https://github.com/neilsh/stunt-reel/issues/479): type 6's registers (`BX` = 6, `DX` and `BP` as the previous handler left them; no model searched reaches it), the sphere faces against the captures, and `OP_PERFDISCSL` (no model searched uses a sliced op, so no disc is perforated).
  Closed by [#754](https://github.com/neilsh/stunt-reel/issues/754): the lens squeeze, the cause of `LOCATION`'s near rim.
  Closed by [#690](https://github.com/neilsh/stunt-reel/issues/690): the shadow-mode skip is applied (`0xA045`); under temporary switches verified by positive controls for filled-disc triangles, the centre-depth (`0xA09A`) and eye-plane (`0xA156`) skips moved zero frames on the seven reference films and remain unimplemented.
  Checked by [#841](https://github.com/neilsh/stunt-reel/issues/841): the radius on a third shape, `INTRO`'s triplane wheels, at 42.67° and 17.76° (four ticks, on the GPU; widest rows within 2 px).
  Closed by [#898](https://github.com/neilsh/stunt-reel/issues/898): the wheels' 1 to 3 extra rows, `0xD11D`'s rows and centre read and reproduced; open, whether `0xD11D`'s stepped spans below the centre row match the 64-gon's, which the rows read so far do not separate from the radius.
  Bounded by [#899](https://github.com/neilsh/stunt-reel/issues/899): the squeeze at the lenses the seven reference films' captured ticks use (`[Bounded Observation]`, lavapipe, tree `191fa1a`, scored SSIM and index agreement with the squeeze off and on, on a tree before #898, whose discs still drew a 16-gon fill with an unsqueezed one-pixel outline, so it bounds that renderer, not today's): `CTRY`, `BALLOON` and `BOMB` (default lens per #754, squeeze 1) changed no tick, and no tick outside `LOCATION`'s 5953 to 6161 (50.95°) moved by more than 0.00117 SSIM.
  The normal's depth rescale and the squeeze stay read but not verified live at any lens but 50.95°: the discs the captured ticks hold at other lenses are small (at most 356 px of a frame in the five films #841 searched), and the old-renderer sweep's changes there are at most 0.00117 SSIM, which may understate the effect on today's discs.
  _Source: [the squeeze switch over seven films](../../work/2026-11/899_perfdisk-lens-closeout/journal.md#2026-11-22-the-squeeze-switch-over-seven-films-and-the-disc-outline)._
  Closed by [#899](https://github.com/neilsh/stunt-reel/issues/899): a disc takes no outline since [#898](https://github.com/neilsh/stunt-reel/issues/898) (`outline.rs` `outlines`), so none escapes the squeeze.
  Open: whether actor `0x31CF` rounding changes any frame under `0xA09A` or `0xA156`; what `0xA1AB`'s term measures; and whether the archives outside this data root (the full `siarchive`) hold a sliced op or type 6.
  The type-8 trees are checked against `INTRO.FLM` ticks 2080 and 3301 and turn with the camera's heading (section 8.8, [#399](https://github.com/neilsh/stunt-reel/issues/399)).
