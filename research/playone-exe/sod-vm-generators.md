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

**How the renderer draws the disc** ([#392](https://github.com/neilsh/stunt-reel/issues/392), [#425](https://github.com/neilsh/stunt-reel/issues/425), [#690](https://github.com/neilsh/stunt-reel/issues/690)).
`vm.rs` draws it as a 64-gon of `radius` in register units, in the plane perpendicular to the raw register difference `regs[centre] − regs[axis]`, one face for each side, in the current colour; [the renderer's disc pixels](#the-renderers-disc-pixels) gives its outline (none) and its pixels.
`OP_SPHERE` shifts the radius product by 8 and divides by depth, while this handler shifts by 16 (`0xA0A2..0xA0A6`: `imul [0x8070]`, high word) and leaves the perspective to the conic it builds, so the two shifts do not by themselves say the disc is 256 times smaller; the width checks below show register units are right.
On `BOMB`'s wheel, from a render whose camera matches the capture's to 2 px, a 16-gon of that radius was 4 to 6 % narrow at tick 2058 (rows 172 and 184), and a 64-gon 1 to 2 px under the capture there and at tick 2070 (`[Bounded Observation]`: two ticks, one shape, widths read off the disc's flat colour).
_Source: [the disc's scale against `BOMB`](../../work/2026-11/distill-sod-vm-generators/journal.md#2026-11-12-the-discs-scale-against-a-same-camera-bomb-capture)._
On a second upright shape, `INTRO.ALL` `0x7F04`'s triplane wheels (a tyre `OP_PERFDISK` of radius `0x0580` in colour `0x06` under a hub of radius `0x0400` in `0x15` or `0x17` on the `IFVIS` branches those frames draw, a lone disc of radius `0x0580` in `0x03` on the others; the normal along the axle), the widest rows were within 2 px of the capture's at 17.76° (ticks 1244, 2553) and 42.67° (1101, 2399), ours never the narrower (`[Bounded Observation]`, four ticks on the GPU, before [#898](https://github.com/neilsh/stunt-reel/issues/898)).
_Source: [`INTRO`'s triplane wheels](../../work/2026-11/distill-sod-vm-generators/journal.md#2026-11-20-intros-triplane-wheels-at-a-third-lens-and-the-squeezes-bound)._
The `work:0x8108` rescale of the normal's depth difference (`0xA0DB..0xA0E8`) is `dz · 0x8108 · 2^(0x810C+1) >> 16`; with the view matrix's two screen rows scaled by `0x8108` in Q15 and the depth row shifted right by `0x810C` ([`memory-map-vm.md`](memory-map-vm.md)), that makes the normal's three components share one scale, which `vm.rs` already has because it keeps the normal in the model frame, so no rescale is added (`[Supported Inference]`: read from the two sites, not verified live).
The centre's depth is not rescaled: that is the lens squeeze below.
Of the skips, `vm.rs` reproduces the zero normal, and the renderer skips `FLAG_DISC` vertices during actor shadow draws (`model.layer.y != 0`, reproducing `0xA045`), adopted evidence-backed on the seven reference films.
The centre-depth (`0xA09A`) and eye-plane (`0xA156`) skips, tested on a renderer before [#898](https://github.com/neilsh/stunt-reel/issues/898) by collapsing filled-disc triangles only (`!FLAG_LINE && FLAG_DISC`, the `outline.rs` rim quads left drawn) under switches verified by positive controls, moved zero frames on the seven reference films, and are not reproduced (see Ruled out).
The centre-depth switch mapped actor `0x31CF`'s shift `s` from `hi = floor(max |coord|)` in metres via 16.16 fixed point, matching the magnitude up to 1 for negative fractional coordinates.
_Source: [the skips scored](../../work/2026-11/distill-sod-vm-generators/journal.md#2026-11-20-the-shadow-mode-skip-adopted-and-the-other-skips-scored); [OP_PERFDISK shadow-mode skip](../../work/2026-11/690_perfdisk-skips/journal.md#2026-11-20-op_perfdisk-shadow-mode-skip-0xa045)._

**The lens squeeze** ([#754](https://github.com/neilsh/stunt-reel/issues/754); `[Established]` for the instruction sequences, static, from the unpatched image with `mise run re-tool -- disasm`; `[Supported Inference]` that the outline is the projection of the circle its inputs describe; `[Bounded Observation]` for the fit, two `LOCATION` ticks on lavapipe).
The builder takes its inputs in two scales.
The centre (`0xA092..0xA0C6`) is the register plus the object origin: `x` and `y` in the screen rows' units (rows 0 and 1 of the view matrix, times `work:0x8108` in Q15) and `z` in the depth row's (shifted right by `work:0x810C`).
The radius, `(radius · work:0x8070) >> 16` with `0x8070 = 0x8108 >> work:0x806F` (`0x911A..0x9121`), is in the `x` and `y` units, and so is the normal once `0xA0D3..0xA0E8` rescales its depth difference.
So only the centre's depth is the true depth over the zoom (`0x8108 / 0x8000 · 2^0x810C`, [`lod.md` § 2.2](lod.md#22-how-the-lens-scales-the-projection)).
With the projector's `256 · x / z` (`0x9CF1`, [section 8.6](sod-vm-execution.md#86-facing-flags-op_rej-and-op_ifvis)), the outline is then the true disc's with every point's depth offset from the centre multiplied by the zoom: shallower than the true disc under a wide lens, deeper under a telephoto, and unchanged to 1 part in 32,768 at the default lens, whose zoom is `0x7FFF / 0x8000`.
The renderer draws it so: a rim vertex carries the vector to its disc's centre (`VERTEX_FLAG_DISC`), and the vertex shader scales its clip-space depth offset from the centre (clip `z` and `w`, which alone hold depth on the symmetric projection) by `tan(42.67° / 2) / tan(fov / 2)`.
At `LOCATION` ticks 6062 and 6161, where the lens draws at 50.95° against the default 42.67° (a zoom of 0.820), the unsqueezed ground disc (`LOCATION.ALL` shape `0x07C6`, one `OP_PERFDISK` of radius `0x2400` in colour `0x4A`, its normal along y, lying flat at a glancing angle) agreed at the far rim but reached 1 to 15 px further at the sides and 15 rows nearer the camera; squeezed, on that renderer before [#898](https://github.com/neilsh/stunt-reel/issues/898), its near rim came within 2 rows of the capture's, its far rim within 1 and its free ends within 3 px, on lavapipe and the GPU alike (`[Bounded Observation]`, two ticks, one shape); [the renderer's disc pixels](#the-renderers-disc-pixels) gives today's rows.
Adopted, evidence-backed: `LOCATION` rose, the films at the default lens (`CTRY`, `BALLOON`, `BOMB`) changed no frame, and the others moved by less than 0.00003.
_Source: [the ground disc read](../../work/2026-11/distill-sod-vm-generators/journal.md#2026-11-18-a-location-ground-disc-read-on-lavapipe-and-the-gpu); [the disc squeezed along depth](../../work/2026-11/distill-sod-vm-generators/journal.md#2026-11-18-the-disc-squeezed-along-depth-by-the-lens-zoom)._
The squeeze and the normal's depth rescale are verified live only at 50.95°.
`INTRO`'s nearly face-on wheels barely feel the squeeze, so they test neither it nor the rescale: forcing the squeeze to 1 changes 3 px of tick 1244 at 17.76°, against 3,487 px at `LOCATION` tick 6062.
At the other lenses tested (`LAND` 11.16°, `TRAINTNL` 14.84°, `INTRO` 8.28°, `LOCATION` 22.10°) the switch moved 0 to 31 px of a frame on the ticks tested, and in the five films searched (`CTRY`, `LAND`, `INTRO`, `LOCATION`, `TRAINTNL`) no large squeeze-sensitive disc was found at a lens other than 42.67° and 50.95° (at most 356 px of disc in a frame; `LAND`'s 11.16° ticks at most 101 px, tick 540's jet wheels 5 to 10 px across; at `TRAINTNL`'s 14.84° ticks 232, 243 and 254 our train is not where the capture's is).
Scoring the seven reference films' captured ticks with the squeeze off and on ([#899](https://github.com/neilsh/stunt-reel/issues/899); `[Bounded Observation]`, lavapipe, tree `191fa1a`, before [#898](https://github.com/neilsh/stunt-reel/issues/898), so it bounds that renderer, not today's) changed none of `CTRY`'s 121, `BALLOON`'s 108 or `BOMB`'s 339 ticks, and outside `LOCATION`'s ticks 5953 to 6161 none moved by more than 0.00117 SSIM.
_Source: [`INTRO`'s triplane wheels and the squeeze's bound](../../work/2026-11/distill-sod-vm-generators/journal.md#2026-11-20-intros-triplane-wheels-at-a-third-lens-and-the-squeezes-bound); [the squeeze switch over seven films](../../work/2026-11/899_perfdisk-lens-closeout/journal.md#2026-11-22-the-squeeze-switch-over-seven-films-and-the-disc-outline)._

#### The renderer's disc pixels

([#898](https://github.com/neilsh/stunt-reel/issues/898); `[Supported Inference]` that the rule below is `0xD11D`'s, from the static read above; `[Bounded Observation]` for the rows: six `INTRO` discs at four ticks, `BOMB`'s wheel at two and `LOCATION`'s ground disc at two, on the GPU.)
On our symmetric projection a disc's projected centre lies half a pixel below the top of row `92 + oy` for a centre `oy` pixels below the projection centre.
Against `0xD11D`, the 16-gon drawn there before [#898](https://github.com/neilsh/stunt-reel/issues/898), with the one-pixel outline every filled polygon gets ([`sod-vm-lines-spans.md`](sod-vm-lines-spans.md) section 8.11), added a row from the outline, `2 · frac(r)` rows and columns from the untruncated radius `r`, and the centre's truncation: `INTRO`'s wheels drew 1 to 3 rows taller, and `BOMB`'s wheel 62 × 62 against the capture's 61 × 60.
_Source: [the disc's pixels before and after #898](../../work/2026-11/distill-sod-vm-generators/journal.md#2026-11-22-the-discs-pixels-before-and-after-898)._
Now a disc's triangles take no outline (`outline.rs` `outlines`), and the vertex shader (`snap_disc`) moves the disc's centre to `PLAYONE`'s (the pixel `sky.rs`'s `to_pixel` puts a point on), `x` to the centre of pixel `160 + trunc(ox)` and `y` to the top of row `floor(rows / 2) + trunc(oy)`, and pulls each rim vertex's vertical offset in by half a pixel, scaled by its distance from the centre, which is the vertical half-extent at the top and bottom of the rim.
Sampled at pixel centres, a disc of radius `r` pixels then covers rows `y − trunc(r)` to `y + trunc(r) − 1` and, at its centre row, `x − trunc(r)` to `x + trunc(r)`: `0xD11D`'s bounds when its `H` and `A` equal `r`.
Without the outline the 16-gon's chords, up to about 2.5 px inside the circle on `LOCATION`'s ground disc, lost that disc's free ends beside the stones, so the disc is a 64-gon.
At the ticks read, every `INTRO` disc's rows are within a row of the capture's (the hubs at 1101, 2399 and 1244 and the 17.76° tyre exactly); `BOMB`'s wheel is 61 × 60 and 59 × 58 like the capture's, one row lower as before; `LOCATION`'s near rim is row 151 at both ticks as in the capture and its free ends lie within a pixel of the capture's on the rows no stone covers, while the two ends at 6161 that sit beside a stone lost their one-pixel sliver and the far rim gained a row above the capture's at both ticks (that row 9 px wide at 6062, 1 px at 6161).
Adopted, evidence-backed: on the GPU every reference film's SSIM rose or held and one frame fell by more than 0.005 (`location` 6117, −0.0083), and lavapipe gave the same verdict on the same frame.
_Source: [the scores](../../work/2026-11/distill-sod-vm-generators/journal.md#2026-11-22-the-discs-pixels-before-and-after-898)._
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
_Source: [scores](../../work/2026-11/distill-sod-vm-generators/journal.md#2026-11-11-view-facing-shapes-scored); [view-facing shapes adopted and scored](../../work/2026-11/distill-sod-vm/journal.md#2026-11-11-view-facing-shapes-adopted-and-scored)._

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

The entries' full text, switches and positive controls included, is in [the journal](../../work/2026-11/distill-sod-vm-generators/journal.md#2026-11-22-the-ruled-out-entries-in-full).

* **`0xD11D`'s stepped ellipse or the disc's placement as the cause of `LOCATION`'s 15-row near rim** (section 8.8): the lens squeeze alone brings it within 2 rows of the capture's ([the disc squeezed](../../work/2026-11/754_perfdisk-lens-squeeze/journal.md#2026-11-18-the-disc-squeezed-along-depth-by-the-lens-zoom)).
* **Dropping the disc's outline alone, for `INTRO`'s tall wheels** (section 8.8, [#898](https://github.com/neilsh/stunt-reel/issues/898)): it takes a row off the top of each hub, not the bottom, so the hubs stay 1 to 2 rows taller than the capture's ([the disc's rows](../../work/2026-11/898_perfdisk-row-height/journal.md#2026-11-22-the-discs-rows-read-out-of-0xd11d-and-three-candidates-read-at-the-wheel-rows)).
* **Moving the disc up half a pixel, or onto `PLAYONE`'s centre pixel, without the truncated half-extent** (section 8.8, [#898](https://github.com/neilsh/stunt-reel/issues/898)): the hubs stay 1 to 2 rows tall, and as 16-gons both lose `LOCATION`'s ground-disc ends; the centre pixel alone dropped 7 `LOCATION` frames by more than 0.005 ([the disc's rows](../../work/2026-11/898_perfdisk-row-height/journal.md#2026-11-22-the-discs-rows-read-out-of-0xd11d-and-three-candidates-read-at-the-wheel-rows)).
* **`OP_SPHERE` faces wound counter-clockwise from outside**, the winding before #272 (section 8.8): only each sphere's far half draws, and near tree crowns draw hollow ([the sphere winding scored](../../work/2026-11/479_perfdisk-sliced-streamer/journal.md#2026-11-17-the-sphere-winding-scored-and-seen-beside-the-capture)).
* **`OP_PERFDISK`'s centre-depth skip (`< 0x80` signed, `0xA09A`) for filled-disc triangles** (section 8.8, [#690](https://github.com/neilsh/stunt-reel/issues/690)): on a renderer before #898, with the `outline.rs` rim quads left drawn, 0 frames of the seven reference films moved ([the centre-depth sweep](../../work/2026-11/690_perfdisk-skips/journal.md#2026-11-20-op_perfdisk-centre-depth-skip-below-0x80-signed-0xa09a)).
* **`OP_PERFDISK`'s eye-plane skip (`0xA156`) for filled-disc triangles** (section 8.8, [#690](https://github.com/neilsh/stunt-reel/issues/690)): on a renderer before #898, with the `outline.rs` rim quads left drawn, 0 frames of the seven reference films moved ([the eye-plane sweep](../../work/2026-11/690_perfdisk-skips/journal.md#2026-11-20-op_perfdisk-eye-plane-skip-0xa156)).
* **An actor disc's one-pixel outline left outside the lens squeeze** (section 8.8, [#899](https://github.com/neilsh/stunt-reel/issues/899)): a disc has had no outline since [#898](https://github.com/neilsh/stunt-reel/issues/898) (`outline.rs` `outlines`, test `a_disc_is_not_outlined`; [the outline read](../../work/2026-11/899_perfdisk-lens-closeout/journal.md#2026-11-22-the-squeeze-switch-over-seven-films-and-the-disc-outline)).

## 10. Open questions

* **The other generators** (section 8.8, [#272](https://github.com/neilsh/stunt-reel/issues/272)).
  Every generator but `OP_VEC`, which has none, is read against its handler (the slot combiners `0xBCE0`, `0xBDC7`, `0xBDA5`, `0xBE7D` not read), the disc's radius, rows and lens squeeze are checked against captures, and the type-8 trees against `INTRO.FLM`.
  _Source: [the questions closed](../../work/2026-11/distill-sod-vm-generators/journal.md#2026-11-22-the-open-questions-as-they-stood)._
  Open: whether `0xD11D`'s stepped spans below the centre row match the 64-gon's, which the rows read so far do not separate from the radius; whether the squeeze and the normal's depth rescale hold at a lens other than 50.95°, on today's renderer; whether actor `0x31CF` rounding changes any frame under `0xA09A` or `0xA156`, and whether either skip moves a frame of today's outline-free discs; what `0xA1AB`'s term measures; and whether the archives outside this data root (the full `siarchive`) hold a sliced op or type 6.
