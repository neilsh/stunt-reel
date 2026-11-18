---
summary: "The SOD VM raw-coordinate generators: `PERFDISK`, the model frames, two-vertex polygons, `MOVETO`/`ZLINETO`/`LINECOL` lines, and polygon spans that include both ends."
sidebar_label: "SOD VM frames, lines & spans"
---

# `PLAYONE.EXE`: SOD VM Model Frames, Lines and Spans

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
| `OP_PERFDISK` | `0xA040`, operands read by `0xA08E` | `centre_reg, radius, axis_reg` | No register. It skips while the shadow mode `work:0x806C` is set or the centre's depth `z + work:0x8088` is below `0x80` (signed), else builds, from the centre, `(radius · work:0x8070) >> 16` and the normal `regs[centre] − regs[axis]`, a quadratic form that it hands to the flat filler `0x8010`: the screen outline of a disc, `[Supported Inference]`. The normal enters the outline's quadratic form only through products of its components, and no branch tests its sign, so the disc draws from both sides (`[Supported Inference]`). | fixed: a 16-gon of `radius` about the centre, perpendicular to the raw normal, one face for each side ([#392](https://github.com/neilsh/stunt-reel/issues/392)); radius scale checked on one `BOMB` disc at ticks 2058 and 2070 and, on lavapipe, on `LOCATION`'s ground disc, below |
| `OP_VEC` (`0x004B`) | none | none | Not a dispatched opcode ([`sod-opcodes.md`](../formats/sod-opcodes.md) § 1): `CS:0x004B` is image `0x828B`, two bytes into slot `0x0048`'s patch store, where the bytes `FE F4` begin no defined instruction. | moot: three words, no effect |

Walking the 2,425 unique models in the data root's corpus reaches type 0 in 2,192 steps, type 2 in 320, type 4 in 152, type 8 in 57, `SPHERE` in 1,584 and `PERFDISK` in 2,531, and type 6 and `OP_VEC` in none (`[Bounded Observation]`, `trace_sod` over every `0x000C`-magic entry).
No model holds the words `0x0063 0x0006` at any even offset either, so none reaches type 6 on a path the walk does not follow (`[Bounded Observation]`, the same models and the seven reference films' archives, 2,428 in all; the 2,428 are the 2,425 of `corpus/` plus the models only the reference archives under `captures/` add, which the journal's Method scopes but does not itemise, so the three-model difference is likely, not checked, those).
The type-8 fix reverses the winding of any polygon that uses corners 1 or 3, so such a face that drew from the wrong side should now draw from the right one (`[Supported Inference]`: not checked against a capture).
_Source: [the #479 read](../../work/2026-11/479_perfdisk-sliced-streamer/journal.md#2026-11-17-sliced-discs-the-type-6-registers-and-the-disc-skips-read-statically)._

**`OP_PERFDISK` read** (2026-11-12, [#392](https://github.com/neilsh/stunt-reel/issues/392); `[Established]` for the instruction sequences, static, from the unpacked image with `mise run re-tool -- disasm`; nothing observed live).
The entry `0xA040` reads `centre_reg, radius, axis_reg` at `0xA08E`.
It skips in shadow mode and when the centre's view depth is below `0x80` (signed).
It scales the radius as `(radius · work:0x8070) >> 16`, the normal's depth difference by `work:0x8108` shifted by `work:0x810C + 1`, and normalises the radius and centre to one shift (`0x9FD9`) and the normal to another (`0x9FAB`).
It forms products of the normal's components in 32-bit arithmetic and calls `0x0D11D` with a screen centre, two extents and two offsets (`si`, `di`) that shear the mirrored half.
`0xD11D` clips against `work:0x41C4`/`0x41C6`, returns carry set off screen, and builds a table of row spans with a stepped 32-bit decision variable (`0xD440`, `0xD4AF`), not a closed form; the flat filler `0x8010` fills them.
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

`vm.rs` draws the disc as a 16-gon (16 is a guess at roundness; the radius is checked, below) in the plane perpendicular to the raw register difference `regs[centre] − regs[axis]`, one face for each side, in the current colour, with `radius` in register units.
**Scale checked against a same-camera capture** ([#425](https://github.com/neilsh/stunt-reel/issues/425)).
`OP_SPHERE` shifts the radius product by 8 and divides by depth; this handler shifts by 16 (`0xA0A2..0xA0A6`: `imul [0x8070]`, high word) and leaves the perspective to the conic it builds, so the two shifts do not by themselves say the disc is 256 times smaller.
`BOMB` tick 2058 has a capture and a render from the same camera (the car body's left edge and the disc's centre column agree to 2 px), and the wheel disc's width agrees with `radius` in register units to about 2 px (one shape, ticks 2058 and 2070; a second shape is read below): at the rows 172 and 184 the capture is 77 and 91 px wide, the 16-gon 72 and 87 px, and a 64-gon 1 to 2 px under the capture; at tick 2070 the capture and the 64-gon differ by 1 to 2 px over four rows (`[Bounded Observation]`: two ticks, one shape, widths read off the palette index of the disc's flat colour).
The 16-gon is 4 to 6 % narrow and the 64-gon closes most of that gap; the remainder is unexplained, perhaps the stepped ellipse of `0xD11D`.
A 32-gon moved no film by more than 0.00015 SSIM and BOMB, LOCATION, LAND and INTRO fell (BOMB -0.00014), so it is not adopted and 16 stays.
The `work:0x8108` rescale of the normal's depth difference (`0xA0DB..0xA0E8`) is `dz · 0x8108 · 2^(0x810C+1) >> 16`; with the view matrix's two screen rows scaled by `0x8108` in Q15 and the depth row shifted right by `0x810C` ([`memory-map-vm.md`](memory-map-vm.md)), that makes the normal's three components share one scale, which `vm.rs` already has because it keeps the normal in the model frame, so no rescale is added (`[Supported Inference]`: read from the two sites, not verified live; the tilt looks similar, and a 2 px height gap at tick 2058 is unexplained).
Of the skips, `vm.rs` reproduces only the zero normal.
The centre-depth and eye-plane skips depend on the camera, which a decode does not have, and the shadow draw reuses the actor's whole mesh, discs included, where `0xA040` skips in shadow mode ([#690](https://github.com/neilsh/stunt-reel/issues/690)).
Scored against the seven reference films with `mise run parity` (RTX 4070).
_Source: [the handler read and the scores](../../work/2026-11/392_perfdisk/journal.md#2026-11-12-the-handler-read-to-its-end-and-drawn)._

**A ground disc, read on lavapipe** ([#709](https://github.com/neilsh/stunt-reel/issues/709); `[Bounded Observation]`, two ticks, one shape, lavapipe, widths read off index `0x4A`, the disc's flat colour, in both panels; the GPU re-read is [#689](https://github.com/neilsh/stunt-reel/issues/689)).
`LOCATION.ALL` shape `0x07C6` is one `OP_PERFDISK` of radius `0x2400` in colour `0x4A`, its normal along y: the stone circle's ground disc in `LOCATION.FLM`, lying flat and seen at a glancing angle across most of the screen, where `BOMB`'s wheel stands upright.
At ticks 6062 and 6161 (`mise run frame -- --film location --ticks 6062,6161 --software-only`, commit `9c9c6a5` (`crates/` tree `a00c4e7`)) the camera appears to match: the stones line up and the disc's far rim is row 76 in the capture, 77 in ours.
Stones stand on the rim, so only the ends a stone does not cover are read: at 6062 the right end of rows 106, 112 and 118 is at x 298, 300 and 299 in the capture and 299, 305 and 309 in ours; at 6161 the left end of rows 106, 112, 118 and 124 is at x 22, 19, 20 and 23 in the capture and 17, 14, 11 and 8 in ours.
The near rim is row 151 in the capture and 166 in ours.
So on this shape ours is the larger: it agrees at the far rim, reaches 1 to 15 px further at the sides and 15 rows nearer the camera, where on `BOMB` the 16-gon was 4 to 6 % narrow.
Why is open: candidates are the view tilt of the normal with the `work:0x8108` rescale, the stepped ellipse of `0xD11D`, or the placement (none tested).
_Source: [the ground disc read on lavapipe](../../work/2026-11/425_perfdisk-radius/journal.md#2026-11-18-a-location-ground-disc-read-on-lavapipe)._

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
  So a `POLYZ` face draws only where its vertices run clockwise on screen, the side the renderer's `FrontFace::Cw` cull keeps (`[Supported Inference]`: the clipping variant `0xC50E` was not read).
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
  The `GVPOLY` entry (`[0x812D] = 0xFF`, `sub si,4` from `0xCAE7`, `add si,4` from `0xCBA9`) measures the same `dx` and `dy` in both walks with the same arithmetic, so left equals right on every row.
  The `POLYZ` entry (`[0x812D] = 0`, walks from `0xCC53` and `0xCDAE`) is symmetric only for steep edges (`|dx| <= dy`, the integer stepper at `0xCCF5` and `0xCE4E`).
  For shallower ones the left and right walks start or end half a step off the vertex on opposite sides, so a `POLYZ` of two vertices is a connected run about `|dx/dy|` pixels wide per row there (read from the instructions, not traced).
  When both vertices share a row (`[0x41D0] == [0x41D2]`) `0xCAB4` writes a single row spanning the smaller to the larger column.
* **The flat filler draws it.**
  The driver routine `0x7571` skips the table's first two words, reads the top and bottom row (the count is their difference) and, per row, `right - left`, skips a negative span, and `inc ax` before `rep stosw`: spans are inclusive, so left equal to right is one pixel.
  Clipping against `[0x2294]` and `[0x2296]` is applied first.
* **`GVPOLY16`** (`0x9A24`; `OP_GVPOLY`'s handler `0x995C` was not traced for two vertices) runs the same edge builder.
  With `[0x806C]` nonzero it takes the flat route (`call [0x8080]`, gateway, colour 0, shade words skipped).
  Otherwise `[0x806B]` clear means the flat route with a colour from the first vertex's shade, and set means Gouraud: `0xC9D4` is called directly.
  The Gouraud route stores one shade per vertex (its loop counts down `CL`, right for two), and calls the Gouraud filler `0x75DB`, which tests `right - left + 1 > 0` per row: a thin line of interpolated shade.

So the reading is that `PLAYONE` draws a two-vertex polygon as a thin line on the paths read (`POLYZ` through `0xC9D4` and `GVPOLY16`'s Gouraud route); the vertex-rejection path, the clipping variant `0xC50E` and `OP_GVPOLY`'s handler were not traced for this case, so whether a rejected or clipped one draws stays open.
On the paths read: one pixel per row for steep lines and `GVPOLY` (a shaded one), a connected run for shallow `POLYZ` lines, one row wide when horizontal.
It is neither skipped nor an error.
`vm.rs` emits it as a line, which the renderer draws one Mode 13h pixel wide at any distance, as it draws `ZLINETO` (section 8.10): one pixel per row when `|dy| > |dx|` and per column otherwise, both ends included.
For steep lines and `GVPOLY` that is the reading above; for a shallow `POLYZ` it is one pixel per column where the reading gives a run about `|dx/dy|` wide per row, which covers about the same pixels (not compared pixel for pixel).
Two coincident vertices draw nothing where `PLAYONE` draws a pixel, and a `GVPOLY` line takes the mean shade level, not a gradient.
No parity reference film is known to place a shape with a two-vertex polygon ([`sod-opcode-coverage.md` § 2.1](../formats/sod-opcode-coverage.md#21-the-side-view-census-shapes-that-do-not-decode-whole)), so the score changes in section 8.10 are taken to come from `ZLINETO` lines.

_Source: [two-vertex polygons read](../../work/2026-11/393_two-vertex-polygons/journal.md#2026-11-11-the-two-vertex-polygon-read-statically)._

### 8.10 Lines: `MOVETO`, `ZLINETO` and `LINECOL`

`[Established]` for the instructions, static, in the unpatched image (not run; the Patch #3 image not read).
The dispatch slots ([section 1](sod-vm.md#1-dispatch)) send `MOVETO` (`0x00A2`) to `0x968D`, `ZLINETO` (`0x00BD`) to `0x9696` and `LINECOL` (`0x00B4`) to `0x9BAA`.

| Image offset | Role |
|---|---|
| `0x968D` | `MOVETO`: stores its operand, a register's byte offset, at `work:0x41EC` (the pen). |
| `0x9696` | `ZLINETO`: `BX` = the pen, the pen = its operand, then `call [0x807E]`. |
| `0x9BAA` | `LINECOL`: stores its word at `work:0x41EA`, the line colour. |
| `0xBBD4`, `0xBB83` | Line routines that `0x9100` puts in `work:0x807E` (at `0x914F` and `0x9167`, beside `work:0x8080`'s polygon routines). `0xBBD4` reads both registers' screen words (`+6`, `+8`), clips the segment to the rectangle at `work:0x41C0..0x41C6` and calls `0:7FD2`. `0xBB83`, the clipping variant, was not read line by line. |
| `0x7FD2` | Line gateway: `DI` = `work:0x41EA`, or 0 when `work:0x806C` is set (the shadow draw, [section 9.1](sod-vm-frame.md#91-the-actor-shadow-draw)), then the driver slot `DS:[0x2244]`. |
| `0x7511` | The driver's line (third word of the table at `DS:0x10A4`): a Bresenham line over the 320-byte page rows, endpoints ordered by column. When `\|dx\| >= \|dy\|` it stores `\|dx\| + 1` pixels, one per column; otherwise `\|dy\| + 1`, one per row. Both ends are drawn, in the low byte of `DI`, with no depth test. |

So a `ZLINETO` line is one pixel wide at any distance, from the pen register's screen point to the operand's, in the `LINECOL` colour.
The pen is a register, so the line uses that register's value when `ZLINETO` runs.
`0x7511` draws one pixel for coincident endpoints; whether the clipper `0xBBF3` passes such a segment was not read.

The renderer follows it.
`vm.rs` emits each line, and each two-vertex polygon (section 8.9), as one polygon of its two endpoints.
Tessellation turns it into a quad of zero world width whose corners are flagged as line vertices (`SodVertex::flags` bits 3 to 5) and carry the vector to the other endpoint, and the vertex shader moves each corner half a pixel across the line's minor screen axis and half a pixel past its endpoint along the major one.
The quad is meant to cover one pixel per column when `|dx| >= |dy|` and one per row otherwise, both ends included (a GPU test checks this for a steep and a shallow line at 200 m and 1000 m; it is not compared with `0x7511` pixel for pixel), at the endpoints' depth, so lines are depth-tested like every other polygon here.
A shadow draw puts lines in index 0, as `0x7FD2` does.
`vm.rs` still takes the pen's point at `MOVETO` time, draws nothing for a zero-length line, and leaves the colour at `OP_COLOR`'s until a `LINECOL` (whether `PLAYONE` resets `work:0x41EA` is not read).

The change was adopted, every reference film's score rising, measured against main's ribbons restored by a temporary switch on the same commit; the journal entry cited below has each film's scores.
Each of `INTRO` camera 1's scored ticks gains 0.0034 to 0.0060: its power line about 437 m away, drawn by `ZLINETO` spans, is two continuous one-pixel cables, as the capture shows, where the 0.03 m ribbons came to scattered dots.

_Source: [the ZLINETO draw path read statically](../../work/2026-11/415_screen-space-lines/journal.md#2026-11-11-the-zlineto-draw-path-read-statically)._ _Source: [one-pixel screen lines scored](../../work/2026-11/415_screen-space-lines/journal.md#2026-11-11-one-pixel-screen-lines-scored-on-the-seven-reference-films)._

### 8.11 Polygon Spans Include Both Ends

`[Established]` for the instructions, static, in the unpatched image (`mise run re-tool -- disasm 0x7571 0x75DB`; the Patch #3 image not read).
The flat filler `0x7571`, which `POLYZ` reaches through the gateway (section 8.9), fills both ends of a polygon on both axes:

* **Rows.**
  It takes the bottom row minus the top row as a count, stores it at `DS:0x10C6`, and after each row runs `dec word [0x10C6]; jns` (`0x75BE`), so it fills the top row, the bottom row and every row between.
* **Spans.**
  Per row it reads the left and right ends, clips them to `[0x2294]` and `[0x2296]`, skips a row whose right end is left of its left (`sub ax,cx; jl` at `0x75A1`), and fills `right − left + 1` pixels (`inc ax` at `0x75A5`).

So every row from top to bottom whose right end is not left of its left is drawn, a row with left equal to right as one pixel, however narrow the polygon.
How the edge builder `0xC9D4` rounds each row's ends was not read, so the pixel-for-pixel extent of a wide polygon is not known.

**What it does to thin polygons** (`[Bounded Observation]`, `INTRO.FLM` tick 3301, [#426](https://github.com/neilsh/stunt-reel/issues/426)).
The pines `0x03A3` and `0x03A7` are a type-8 quad (section 8.8) whose `INTV` midpoints make two `POLYZ` triangles: the whole tree, and a sliver outside its right edge at most a sixth of its half-width across.
The capture draws a six-pixel-wide pine's sliver as a strip of light green one to two pixels wide down 14 rows (21 pixels); our renderer, whose rasteriser fills only pixels whose centres a triangle covers, drew 2 pixels of it.
Across the top-left 100 × 100 pixels the four tree colours covered 1,471 pixels in the capture and 815 in ours, with every tree checked in a 60 × 60 part of the crop at the same place in both.
`[Supported Inference]` that the inclusive spans are why the sliver measured is drawn.

The renderer follows it in part.
`stunt-render` draws every edge that exactly one filled triangle of a mesh node uses as a one-pixel screen line (section 8.10), in its end vertices' colours, after the node's triangles, or in a decal node after each fan's triangles ([`outline.rs`](../../crates/stunt-render/src/outline.rs)), so a polygon also covers the pixels its outline crosses.
It does this as line quads for the shapes drawn per frame (actors and view-facing props such as these pines), and as a line list for the world mesh's props (below).
With it the pine's sliver draws 23 pixels and the crop's tree colours 1,188.
The outline lines are wound both ways, like every line here, so a back-facing polygon's outline still draws where nothing hides it, which `PLAYONE` does not do.

**The world mesh.**
Line quads cost four vertices and twelve indices an edge, and outlining `LOCATION`'s world that way grew it from 6.7 million vertices and 7.5 million indices to 32.4 million and 84.7 million and made its render, with terrain excluded, fail with a wgpu out-of-memory error.
The world instead draws the same edges, those exactly one filled triangle of a mesh slice uses, as a `LineList` index buffer over its own vertices, two indices an edge, after the world draw's triangles (a decal slice's outline right after that slice's triangles, [ADR 0046](../../docs/adr/0046-coplanar-decals-are-drawn-in-an-ordered-pass.md)) and with their depth test (a decal slice's outline compares `LessEqual` without the `[I5]` bias, which wgpu allows only on triangles; [`mesh.rs`](../../crates/stunt-render/src/mesh.rs) `GpuModel::from_ir_outlined`).
Terrain and ocean triangles are not outlined.
The line list is drawn one pixel wide by the backend's line rules, which need not draw the end pixels a line quad does (not measured).
A slice split over chunks (a world over `max_buffer_size`; `LOCATION`'s is one chunk) gets the outline of the unsplit slice, its edges counted over all its runs, each run drawing its share ([#475](https://github.com/neilsh/stunt-reel/issues/475)).
On `LOCATION` the outline is 6.4 million edges, 51.5 MB of indices, and a whole-film render took about 16 % longer (two runs each).
With line quads on the per-frame shapes every reference film's score rose but `LOCATION`'s, which fell; with the world's line list added every film's rose, and at `LOCATION` tick 4170 the derrick's legs draw a pixel wider, as in the capture (judged by eye).
_Source: [thin polygons measured and outlines drawn](../../work/2026-11/distill-sod-vm/journal.md#2026-11-12-thin-polygons-measured-and-outlines-drawn)._

_Source: [what thins the INTRO conifer field](../../work/2026-11/426_intro-conifers/journal.md#2026-11-12-what-thins-the-intro-conifer-field)._ _Source: [polygon outlines scored](../../work/2026-11/426_intro-conifers/journal.md#2026-11-12-polygon-outlines-scored-on-the-seven-reference-films)._ _Source: [world-mesh slivers](../../work/2026-11/430_world-mesh-slivers/journal.md#2026-11-12-world-mesh-slivers-by-conservative-rasterization-and-by-a-line-list-outline)._

## Ruled out

* **`OP_SPHERE` faces wound counter-clockwise from outside** (section 8.8), the winding before #272.
  It draws only each sphere's far half; restoring it dropped 10 `LOCATION` frames by more than 0.005 and drew near tree crowns hollow where the capture fills them ([the sphere winding scored](../../work/2026-11/479_perfdisk-sliced-streamer/journal.md#2026-11-17-the-sphere-winding-scored-and-seen-beside-the-capture)).

* **Conservative rasterization for the world mesh's slivers** (section 8.11).
  It likely over-covers, taking every pixel a triangle touches (inferred): with the world drawn that way `CTRY` fell 0.006 and `LOCATION` 0.0023 (`INTRO` and `BOMB` rose), and every film fell with the per-frame shapes drawn that way too ([world-mesh slivers](../../work/2026-11/430_world-mesh-slivers/journal.md#2026-11-12-world-mesh-slivers-by-conservative-rasterization-and-by-a-line-list-outline)).

* **Outlining the world's terrain and ocean** (section 8.11).
  With the line-list outline, adding them moved `LAND` and `BALLOON` below the base without world outlines (−0.0008 and −0.0013), where props alone raised both; `LOCATION` and `INTRO` still rose ([world-mesh slivers](../../work/2026-11/430_world-mesh-slivers/journal.md#2026-11-12-world-mesh-slivers-by-conservative-rasterization-and-by-a-line-list-outline)).

* **SOD lines as 0.03 m world ribbons** (section 8.10).
  They vanish far away and swell up close; one-pixel screen lines score higher on all seven reference films ([one-pixel screen lines scored](../../work/2026-11/415_screen-space-lines/journal.md#2026-11-11-one-pixel-screen-lines-scored-on-the-seven-reference-films)).

* **Missing placements as the cause of `INTRO`'s faint conifer field at tick 3301** (section 8.11).
  In a 60 × 60 crop of that tick the pines match the capture's in position, judged by eye at 8×; the slivers explain part of the gap (the crop's tree pixels go from 815 to 1,188 of the capture's 1,471).
  Tick 3290, whose camera sits a few pixels off the capture's, was not compared ([what thins the INTRO conifer field](../../work/2026-11/426_intro-conifers/journal.md#2026-11-12-what-thins-the-intro-conifer-field)).

## 10. Open questions

* **The other generators** (section 8.8, [#272](https://github.com/neilsh/stunt-reel/issues/272)).
  Closed: `OP_IPG` types 0, 2, 4 and 8 and `OP_SPHERE` read against their handlers, and type 6's operand width; `OP_VEC` has no handler.
  Closed by [#479](https://github.com/neilsh/stunt-reel/issues/479): type 6's registers (`BX` = 6, `DX` and `BP` as the previous handler left them; no model searched reaches it), the sphere faces against the captures, and `OP_PERFDISCSL` (no model searched uses a sliced op, so no disc is perforated).
  Open: the normal's depth scale (read, not verified live; [#425](https://github.com/neilsh/stunt-reel/issues/425)) and the radius on shapes other than `BOMB`'s wheel ([#689](https://github.com/neilsh/stunt-reel/issues/689)); the centre-depth, eye-plane and shadow-mode skips, which our renderer does not apply ([#690](https://github.com/neilsh/stunt-reel/issues/690)); what `0xA1AB`'s term measures; and whether the archives outside this data root (the full `siarchive`) hold a sliced op or type 6.
  The type-8 trees are checked against `INTRO.FLM` ticks 2080 and 3301 and turn with the camera's heading (section 8.8, [#399](https://github.com/neilsh/stunt-reel/issues/399)).

* **Polygon outlines** (section 8.11).
  Open: how `0xC9D4` rounds a row's ends, so whether the outline matches the inclusive spans pixel for pixel; whether `PLAYONE` fills terrain through `0x7571` as well, since outlining terrain scored below the base on `LAND` and `BALLOON`; and whether the world's line-list outline drops end pixels a line quad draws.

* **Lines** (section 8.10).
  Open: a zero-length `ZLINETO` or two-vertex polygon, one pixel in `PLAYONE`, draws nothing here; `vm.rs` keeps the pen's point at `MOVETO` rather than reading the register at `ZLINETO`; whether anything resets `work:0x41EA`; whether the pen persists across `RETURN` and subobjects (`work:0x41EC` is global, `vm.rs` keeps one pen per decode); the clipping variant `0xBB83` and the Patch #3 image's line path.
