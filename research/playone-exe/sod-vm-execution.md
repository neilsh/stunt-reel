---
summary: "The SOD VM execution model: the vertex and vector banks, the transform stack, control flow, `SHADE` colour, the facing and depth gates, and the model frame of cube corners and `OP_VECTORS`."
---

# `PLAYONE.EXE`: SOD VM Execution Model

Part of the SOD VM notes: [`sod-vm.md`](sod-vm.md) lists the files and states the binary and method; section numbers run across the files.

## 8. Execution Model

The VM is a stack-based, register-oriented geometry engine.
Opcode semantics and operand widths are in [`formats/sod-opcodes.md`](../formats/sod-opcodes.md); this section holds the state the opcodes act on.
Dispatch is [section 1](sod-vm.md#1-dispatch).
Each claim carries its tier.

### 8.1 Vertex Register Bank

`[Established]` for the 12-byte stride, the 1024-entry arena at `DS:0x4450` and the `x/y/z` words ([section 4](sod-vm.md#4-register-side-effects) step 4).
`[Supported Inference]` for the index mask.

- The VM keeps 1024 vertex registers (`regs[0..1023]`).
  In `PLAYONE.EXE` each is 12 bytes: three signed 16-bit coordinate words plus projection and flag words at `+6`, `+8` and `+0xA` ([section 3](sod-vm.md#3-anchor-record-layout)).
- Bytecode operands address a register by **byte offset** (a multiple of 12).
  The reconstruction decodes `reg_index = (reg_off / 12) & 1023`; the mask keeps a bad operand inside the bank.
- The reconstruction stores each register as three floating-point metres `[x, y, z]`, scaled by the header scale table ([`sod.md`](../formats/sod.md) section 2); the original holds raw 16-bit units.
- Whether `PLAYONE.EXE` paged the bank or kept it in the work segment is Q-SOD-06 in [`sod.md`](../formats/sod.md).
  The captured session holds it in the work segment `0x1DF8`.

### 8.2 Vector Accumulator

`[Supported Inference]` — operand semantics from `SOD.H`, FreeFlight and the assembler macros; handlers other than `TAP` are not traced.

The VM keeps one 3D accumulator, `cur_vert = [x, y, z]`, which the vector opcodes read and write:

- `OP_CLRV` zeroes it; `OP_GETV reg` loads `regs[reg]`; `OP_PUTV reg` stores it into `regs[reg]`.
- `OP_ADDV reg` and `OP_SUBV reg` add or subtract `regs[reg]`; `OP_NEGV` negates; `OP_INTV reg` sets it to the midpoint `(cur_vert + regs[reg]) * 0.5`.
- `OP_SHLV n` and `OP_SHRV n` multiply or divide by `2^n`.
- `OP_BLOKADD` and `OP_BLOKNEG` apply the accumulator or a negation across a register range.

The CTRY hill example in [section 5](sod-vm.md#5-hill-fins) uses this pattern: `GETV 511; SHLV 1; PUTV 510`.

### 8.3 Transform Stack and Subobject Articulation

`[Supported Inference]` — from the assembler macro sources (`SABRE.SOD`, `CURTISS.SOD`) and FreeFlight's `siobj.cpp`; the handlers are not disassembled.

Moving parts (propellers, landing gear, rudders) are subobjects drawn under a hierarchical stack, so they stay attached to the body:

1. `OP_PUSHCENTRE` (`0x007E`) pushes the current rotation origin onto the centre stack.
2. `OP_PUSHRELMAT` (`0x01E6`) pushes the current 3x3 local orientation matrix.
3. `OP_MOVECENTRE reg` (`0x0090`) translates the origin to `regs[reg]`, for example a landing-gear hinge.
4. `OP_ROTX` (`0x02E2`), `OP_ROTY` (`0x01DD`) and `OP_ROTZ` (`0x02EB`) rotate about one axis by a 16-bit BAM angle driven by an animation variable (`undercarriage1`, `rudder`).
   The si-tools reading of the operand differs ([`sod-opcodes.md`](../formats/sod-opcodes.md) section 3).
5. `OP_GOSUB target` (`0x01A7`) evaluates the articulated subobject geometry (for example `sabre_uc`).
6. `OP_POPRELMAT` (`0x01EF`) restores the parent matrix.
7. `OP_POPCENTRE` (`0x0087`) restores the parent rotation centre.

### 8.4 Control Flow

`[Supported Inference]`

`OP_GOTO` jumps and `OP_GOSUB` calls by a relative word offset; `OP_RETURN` (`OP_END`) ends the list or returns from a subroutine.
`OP_SORTON` and the conditional branches `OP_IFVIS`/`OP_BVIS`, `OP_BVLT`, `OP_BVGT` and `OP_BZLT` choose which subtree runs; the visibility and BSP behaviour is in [`sod-opcodes.md`](../formats/sod-opcodes.md) section 2.5.
The branch targets are relative, so a walk that mis-sizes one operand desynchronises (see [`sod-opcode-coverage.md`](../formats/sod-opcode-coverage.md) section 4).

### 8.5 Polygon Colour at `SHADE` Time

`[Hypothesis]` for the `SHADE*` level law, static and read once; `[Supported Inference]` for the light, measured below.
Polygon colour is a running word at `[0x41E8]` that `OP_COLOR` and the four shade opcodes all write.
`SHADE1` (`0x0144`), `SHADE2` (`0x014D`), `SHADE16` (`0x02B5`) and `SHADE216` (`0x02C7`) take `norm, base` (handlers at image `0xA526`, `0xA519`, `0xA550`, `0xA55D`, shared tail `0xA52F`): they load `s = word[0x7468 + norm]`, the per-normal shade that `SHADES` (`0x9481`) wrote as `-clamp(N.L >> 16)`, halve it (twice for the 16-level forms; the `2` forms negate it first), and store `base + max(0, (s >> 8) + adj)`, with `adj = -2` when `base == 0x10`.
`base` is a ramp start: in the `INTRO.FLM` palette `0x10` is red 16..29, `0x30` grey 48..53, `0x40` brown 64..79, the ramps the capture's triplane uses.
FreeFlight discards the operands and paints with the last `OP_COLOR`.
The light vector `L` is passed in registers to the display-list entry `0x9100` by its caller: scenery gets the world light `DS:0x49EC..0x49F0` unchanged, a rotated object that light turned by its rotation and the view and doubled (caller `0x1CFB`; [`terrain-shade.md`](terrain-shade.md) section 4.2).
`GVPOLY`/`GVPOLY16` give each vertex its own index, which the filler interpolates (below).
Their word after the register list is `(ramp_base << 8) | count` (`0x3004` in `CTRY.FLM`'s `0x7F37`, `0x1004` on the triplane), not a normal register, and `count` shade offsets into the `SHADES` words follow, one per vertex.
`[Established]`, static, for the Gouraud route: `0x9A24` calls the edge builder `0xC9D4` (`0x9A7E`), which reads `count` and then `count` register offsets, and only then reads this word (`es lodsw; mov cx, ax` at `0x9A98`: `CH` is the ramp base, `CL` the loop count) and the shade offsets (`0x9AB0`); `0x995C` does the same at `0x99AF`/`0x99C9`.
The flat routes take their base as `es:[si+1]` after `call [0x8080]`, which is `0xC9D4` or the clipping variant `0xC50E`; `0xC50E` also leaves `SI` on that word (`[Established]`, static): it reads `count` into `work:0x41AC` (`0xC523`), and each register `es lodsw` (`0xC556`, `0xC589`) is paired with one `dec word [0x41AC]` (`0xC561`, `0xC57F`, `0xC59C`), so it reads exactly `count` register offsets; `0xC60C`/`0xC656` push and pop `SI` around their own use of it, `0xC6AF` and `0xC88E` push and pop it, `0xC65A` does not touch it, and the shared tail `0xCA5E` leaves it alone on its reject exits (`0xCAB3`, `0xCACF`) and on the accept path pushes it at `0xCAD7` (and `0xCADA`) and pops both before each `ret` (`0xCB95`/`0xCC4F`, `0xCDAD`/`0xCF1F`).
The Gouraud loop counts its shade offsets with `dec cl` over the ramp word's whole low byte (`0x99FF`, `0x9ACF`); only the skip tail masks it with `and ax, 0Fh` (`0x9970`, `0x9A38`).
_Source: [the clipping edge builder and the Gouraud loop count](../../work/2026-11/472_research-contradictions/journal.md#2026-11-14-the-clipping-edge-builder-and-the-gouraud-loop-count)._ The live probe `ground-objects` broke at the handlers' entry, where `ES:SI` is on `count`, so the base `0x00` it logged ([`world-scene.md` § 4.1](world-scene.md#41-the-gouraud-records-ops-0x0168-0x02be)) is `count`'s high byte, not the ramp. _Source: [GVPOLY16 reads its ramp after the registers](../../work/2026-11/472_research-contradictions/journal.md#2026-11-14-gvpoly16-shifts-its-shade-by-two-and-reads-its-ramp-after-the-registers)._ A flat paint of each such polygon at `base` plus the mean of its vertices' levels moved grey-ramp pixels toward the capture's without raising SSIM. _Source: [GVPOLY polygons painted flat, and the triplane before the ramp word](../../work/2026-11/distill-sod-vm/journal.md#2026-11-01-gvpoly-polygons-painted-flat-and-the-triplane-before-the-ramp-word)._

**The light** (2026-11-05, [#221](https://github.com/neilsh/stunt-reel/issues/221)).
`SHADES` dots `L` with the shape's raw normal words, and an unrotated object is handed the world light as stored, so `L` is in the raw model frame and needs no game-to-`[I1]` axis mapping: the decoder keeps the normals in that frame too.
The mapping is derived, not chosen by score.
The decoded model frame is +Y up ([`coordinates-and-units.md` § 1.2](../formats/concepts/coordinates-and-units.md#12-right-handed-metric-basis-i1)), so `(99, 32766, -17)` points up, and `s = -(N . L)` leaves an upward face at its ramp base and lifts a downward one.
The old stand-in `SHADE_LIGHT = (0, -32767, 0)` had the opposite sign.
Both films set film variable 13 to `0x2D` at tick 0 (`mise run flm-events`), so both get `(99, 32766, -17)`; [`ShadeLight::world`](../../crates/stunt-core/src/sod/light.rs) computes the light from any value as `0x196C` does ([`terrain-shade.md`](terrain-shade.md) section 4.2).
Measured with `DBG_SHADE_LIGHT`, every shape under one light: the world light scored 0.8641 / 0.8128 (`CTRY` / `INTRO`) against the stand-in's 0.8646 / 0.7986, and its negation `(-99, -32766, 17)` and the 180-degree-about-Z form `(-99, -32766, -17)` both scored as the stand-in, so the 99 and 17 move no shade across a ramp step and only the sign of y matters.
The world light for scenery with the stand-in for actors scored as the stand-in exactly, so no scenery shade that reaches the screen moves and the whole gain is on the aircraft.
_Source: [the SHADE light swept with DBG_SHADE_LIGHT](../../work/2026-11/distill-sod-vm/journal.md#2026-11-05-the-shade-light-swept-with-dbg_shade_light)._ Actors are therefore decoded under the world light unrotated, the light `PLAYONE` would hand a level, unrotated object. Their own light turns with their rotation and the view every frame, and shapes are decoded once, so it is not modelled.

**Interpolation.**
The `GVPOLY` handlers write `(index << 8) | fraction` per vertex and the filler `0x75DB` interpolates it linearly in screen space ([`terrain-shade.md`](terrain-shade.md) sections 5-6).
The renderer now gives each vertex its own index (`base` plus that vertex's level, the fraction dropped) and interpolates it in screen space (`@interpolate(linear)`), rounding to a whole index per fragment (`[I3]`): CTRY 0.8641 -> 0.8642, INTRO 0.8128 -> 0.8166 (`DBG_GVPOLY_INTERP`).
Rounding stands in for the dropped fraction: `PLAYONE` floors the interpolated 8.8 value, and an average fraction of one half makes that a rounding of the whole indices.

Before the ramp word was read, `INTRO.FLM` tick 1009 drew the triplane in the wrong colours where the capture has a red fuselage and dark red wings (capture above, ours below): [`intro-1009-gvpoly-running-colour.png`](../../work/2026-11/aircraft-render/images/intro-1009-gvpoly-running-colour.png).

_Found 2026-11-01 by the aircraft render round 2; see the [parity log](../../work/2026-10/parity-log/log.md)._

---

### 8.6 Facing Flags: `OP_REJ` and `OP_IFVIS`

`[Established]` for the instruction sequences, static, read from `build/re/playone.img` with iced-x86 (2026-11-05, [#74](https://github.com/neilsh/stunt-reel/issues/74)); nothing observed live.
`OP_IFVIS` is not a level-of-detail gate.
Its first operand is the byte offset of a facing flag in `work:0x7C68`, one byte per face, which three earlier opcodes write from the vertex registers.
The section runs while its face points at the eye.

| Opcode | Handler | Reads | Does |
|---|---|---|---|
| `0x017A` `OP_IFVIS` | `0x9BCC` | `flag, size` | `cmp byte [flag + 0x7C68], 0`: nonzero runs the section, zero skips `size` bytes from the size word. |
| `0x0183` `OP_BVIS` | `0x9BB3` | `flag, size` | The inverse: zero runs the section. |
| `0x01B9` `REJ` | `0x9567` | `first, count, count × (a, b, c)` | Normal `n = (a - b) × (c - b)` (`0xB621`, registers at `work:0x4450 + reg`), then `n · (b + o)`, `o` the words at `work:0x8084..0x8088` (read as the object's origin relative to the eye, `[Supported Inference]`: the sign measurement below fits it); flag `first + i` = `0xFF` when negative (`shl dx, 1; sbb al, al`), else 0. |
| `0x01B0` `REJVEC` | `0x94D8` | `first, count, count × (p, b, e)` | The same flag from `(e - b) · (p + o)`, the normal given as two registers; the z term is scaled by `work:0x810A` and the x, y terms shifted by `work:0x810C`. |
| `0x01C2` `REJ2D` | `0x95C0` | `first, count, count × (a, b, c)` | The flag from the sign of the 2D cross product of the projected points (`+6`, `+8` of each register): the screen winding. |
| `0x0318` `BZLT` | `0x9BE5` | `reg, val, size` | `cmp [reg + 0x4454], (val >> work:0x806F) - work:0x8088` (signed, `jg`): a register depth `z` with `z + work:0x8088` above `val >> work:0x806F` runs the section, otherwise it skips `size` bytes from the size word. |

`SORTON` (`0x9183`) reads the same table (`js` on the flag byte) to order its two branches.
The renderer keeps each `REJ` face as `VisibilityCondition::FacesEye { point: b, normal: n }` in model space and draws the section while `n · (b - eye) < 0`, with the eye taken into each actor's space, and into the world's for scenery props, every frame.
Measured 2026-11-05 ([parity log](../../work/2026-10/parity-log/log.md)): CTRY 0.8645 -> 0.8646, INTRO 0.7973 -> 0.7986; the opposite sign gives 0.8061 / 0.7366, which fixes the sign.
The old reading (condition 1 as `D^2 <= 1000 m^2`, everything else drawn) had no binary basis.

The in-shape depth gate is `BZLT` (`0x0318`, handler `0x9BE5`), not `IFVIS`: it reads `reg, val, size` and skips `size` bytes when the register's view depth `z + work:0x8088` is at most `val >> work:0x806F`, so its section is drawn only when far.
The census once stepped over it by 2 words, one short.

**The rest of the gates in `vm.rs`** (2026-11-12, [#235](https://github.com/neilsh/stunt-reel/issues/235)).
`[Established]` for the instruction sequences above, static, read from `build/re/playone.img` with `mise run re-tool -- disasm`; the five gate handlers (`BVIS`, `IFVIS`, `BZLT`, `REJVEC`, `REJ2D`) occur byte for byte in the Patch #3 image the references ran (at `0x8DBE`, `0x8DD7`, `0x8DF0`, `0x87CF`, `0x88B7`).
How each becomes a gate:

* **Sections end `size` bytes from the size word.**
  All three skip with `add si, [es:si]` while `SI` points at the size word (`0x9BBE`, `0x9BD7`, `0x9BFB`).
  `vm.rs` counted from the word after it, one word late, so the opcode at the true end was still gated.
  A section that starts inside another pushes the outer gate, which comes back when the inner section ends; a polygon in the inner section takes the inner gate only, since a mesh node carries one condition.
* **`BVIS`** is the `IFVIS` gate with the face's normal negated: the section draws while the face points away.
  A flag the shape never set leaves the section ungated, as for `IFVIS`.
* **`REJ2D`** is the `REJ` gate of the same triple.
  The handler computes `P2 − P1` with `P1 = (a.x − b.x)(b.y − c.y)` and `P2 = (a.y − b.y)(b.x − c.x)` on the projected points, flag set when negative, so when `cross2(a − b, c − b) < 0` on screen.
  The projector (`0x9CF1`) stores `(x + o.x) · 256 / (z + o.z)` and the same for y, with no sign change.
  For points in front of the eye, that screen sign equals the sign of `((a − b) × (c − b)) · b` in view space, the `REJ` test.
  `[Supported Inference]`: the equality is algebra on the handlers.
  For a triple with a point behind the eye the two can differ, and the renderer keeps the `REJ` form.
* **`REJVEC`** sets `FacesEye { point: p, normal: e − b }`.
  Registers carry the lens zoom: x and y scaled by `m = work:0x8108 / 0x8000`, z shifted right by `c = work:0x810C`.
  The handler shifts the x and y products right by `2c` (`shl cx, 1` at `0x9524`) and multiplies the z product's point term by `work:0x810A = m² · 0x8000` (`0x953F`).
  Each term is then the unzoomed product times `m² / 2^(2c)`, so the sign is that of the model-space `(e − b) · (p − eye)`.
  `[Supported Inference]` for the unit reading.
* **`BZLT`** sets `VisibilityCondition::BeyondDepth { point: reg, depth: val × scale }`, with `scale` the shape's metres per raw unit.
  The vertex loaders store each register as the high word of the Q15 matrix product, shifted right by `work:0x806F` (section 8.7).
  That is half the rotated raw coordinate, and the zoomed depth row also shifts it right by `c`.
  `0x806F` is `CH − CL` from the object entry (`0x9111..0x9113`): the header's scale shift less the view-position shift.
  The origin word `0x8088` is in the same register units.
  So the compare is, to rounding, `true depth / 2^(1 + c) ≤ val × scale` in metres, the same halving and lens shift as the `SP_1NODE` gate ([`lod.md`](lod.md) section 2.2).
  The renderer tests it per frame with [`CameraTransform::view_depth_exceeds`](../../crates/stunt-core/src/contracts/trajectory.rs), from the view taken into the model's space for actors and view-facing props and the world's for gated scenery props.
  `[Supported Inference]` for the units: they are read from the loaders and the entry, and no `BZLT` was traced live.

**`REJ` in the shadow draw** (`[Supported Inference]`, 2026-11-22, [#840](https://github.com/neilsh/stunt-reel/issues/840)).
`REJ` reads the vertex registers, which hold the points the draw matrix produced, so in the shadow draw (`0x1C0D`, [`sod-vm-frame.md` § 9.1](sod-vm-frame.md#91-the-actor-shadow-draw)) it tests each face as flattened onto the ground plane, with `o` the shadow's ground point.
Flattened along `y` onto a plane of normal `p`, a face's normal is `(n_y / p_y) p`: with the eye above the plane a face passes when its world normal points up, whatever the eye's side of the unflattened face.
That a handler reads the registers is `[Established]` (static, `0x9567`); that the shadow's registers are the flattened ones follows from `0x1C0D`'s matrix and is not observed in a register dump.
The renderer's shadow draw tests its `FacesEye` gates this way (`faces_flattened` in `stunt-render`'s `mesh.rs`); the view slot of `BRETT.FLM`, whose eye is inside its car, then draws 4,809 of the capture's 4,856 index-0 pixels in rows 150 to 184 on each of its 20 view-slot frames, from 22 (`[Bounded Observation]`, one film), and the seven reference films' `mean_ssim_scored` does not fall (ctry 0.9377 to 0.9385).
`REJVEC` and `REJ2D` are not covered: no census walk reaches them.
_Source: [the shadow draw's facing gates](../../work/2026-11/840_brett-view-slot-shadow/journal.md#2026-11-22-the-shadow-draws-facing-gates-test-the-flattened-face)._

**No census walk reaches any of them.**
On the `sod-census` walk of the corpus's 3,703 unique models, which follows `SORTON`, `GOTO`, `GOSUB` and, with a temporary switch, both arms of every `BVGT`, no walk reaches `BZLT`, `BVIS`, `REJVEC` or `REJ2D`.
With the corrected end, no section starts inside another.
No drawing opcode stands at any section's true end.
The words there are 102,536 `IFVIS`, 13,845 `RETURN`, 3,070 `SORTON`, 713 `LINECOL`, 79 `COLOR`, 37 `PUSHCENTRE`, 36 `BVGT`, 31 `IPG`, 24 `MOVETO`, 3 `GOSUB` and one `0x0333`.
No opcode at a true end draws by itself, though the targets of the 3 `GOSUB` and 36 `BVGT` there were not checked, and `0x0333` is not decoded.
A sweep of the old end against the corrected one scored the seven reference films identically to four decimals.
`[Bounded Observation]` for this walk: `BVLT`'s branch is not followed, and code no branch reaches is not walked.
A raw byte scan for `0x0318` finds hundreds of matches in the `.RES` files, but they are register offsets, since `0x0318` is register 66, not opcodes.
So, on the paths the census walks, the props loss the seven reference films measure ([`attribution.md`](../parity/attribution.md) section 2) does not come from `BZLT`, `BVIS`, `REJVEC` or `REJ2D`.
A gate behind a `BVLT` branch or in code no branch reaches is not covered.

_Source: [the gate handlers](../../work/2026-11/235_sod-gates/journal.md#2026-11-12-the-gate-handlers), [which stock shapes reach the gates](../../work/2026-11/235_sod-gates/journal.md#2026-11-12-which-stock-shapes-reach-the-gates), [scoring the section end](../../work/2026-11/235_sod-gates/journal.md#2026-11-12-scoring-the-section-end-and-the-gates)._

_Found 2026-11-05 for [#74](https://github.com/neilsh/stunt-reel/issues/74); see the [parity log](../../work/2026-10/parity-log/log.md)._

### 8.7 Model Frame: Cube Corners and `OP_VECTORS`

`[Established]` for the instruction sequences, static, read from `build/re/playone.img` with Capstone (2026-11-06); nothing observed live.
`[Supported Inference]` that this is why stock shapes decoded upside down, from the shape census and the sweep below.

Both vertex loaders store `M · v` into a register, with `M` the 3×3 matrix at `work:0x808A` (three words a row) and the sum shifted right by `work:0x806F`:

| Handler | Image offset | Stores |
|---|---|---|
| `OP_VECTORS` (`0x0075`) | `0x9C51` | `count` stream vectors into consecutive registers, each `M · (x, y, z)` with the stream's own signs. |
| `OP_IPG` type 0, cube (`dx, dy, dz, reg`) | `0x965F` calls the word table at `work:0x1954` (type 0: VM `0x3035`, image `0xB275`) | Corners `reg + 0..7` = `M ·` `(+dx, +dy, −dz)`, `(+dx, +dy, +dz)`, `(−dx, +dy, +dz)`, `(−dx, +dy, −dz)`, `(+dx, −dy, −dz)`, `(+dx, −dy, +dz)`, `(−dx, −dy, +dz)`, `(−dx, −dy, −dz)`. It computes four and writes each one's negation as its antipode. |

`vm.rs` writes the cube as PLAYONE's turned half a turn about z (every corner with x and y negated), and its `TAP` writes `(−x, −y, z)`.
So the reconstruction's model frame is the raw frame turned 180 degrees about z, which puts the shapes' raw −y, up in their authoring, at `[I1]` +y.
`OP_VECTORS` was the exception: it stored `(x, y, z)` unturned.
A shape that adds `OP_VECTORS` deltas to cube corners then decodes with those parts turned over, and one built from `OP_VECTORS` alone decodes wholly upside down.
That is the "construction delta" correlate in [`hero-aircraft-orientation.md`](../parity/hero-aircraft-orientation.md) section 1.

**Adopted: `OP_VECTORS` turned the same way** (store `(−x, −y, z)`; measured first with the temporary switch `DBG_VECNEG`).
All 14 inverted stock `0x7Fxx` aircraft stand upright, as do the two unclear ones (`0x7F18`, `0x7F21`); the 9 that were upright, and the `OP_IPG`-led aircraft, are unchanged.
Of the 397 stock shapes holding the word `0x0075`, 229 export different geometry; the rest are unchanged, and 19 export nothing either way (terrain patches without anchors, empty shapes).
In side views none turns over and many are righted: the masts of the sailing ships `0x4114`..`0x4117`, `0x414D`, `0x414E` and `0x4153` (below the hull before), the conning tower of `0x3E19`, the antennas of `0x3D47`/`0x3D48`, the wheels of trucks and tanks, and the sign `0x063D`, which now reads "STUNT / ISLAND" top to bottom.
`CTRY.FLM` and `INTRO.FLM` SSIM rose with IoU unchanged, and at `CTRY` tick 499 the biplane matches the capture, wing stripes included, which the hand-picked mirror culled.
_Source: [OP_VECTORS turned, swept and adopted](../../work/2026-11/distill-sod-vm/journal.md#2026-11-06-op_vectors-turned-swept-and-adopted)._

Section 8.5's light needs no change: `SHADES` dots the raw-frame light with the raw normal words, which this turn does not touch.
`REJ` takes its points from registers, so it follows them.

**Ruled out: a per-shape term in the draw path.**
The actor entry (`0x1C00` → `0x1CFB`) builds its matrix from the slot's three angles at `+0x10/+0x12/+0x14` (`0x04E5`) and the view (`0x060A`) alone.
`0x1D5F` hands the VM only slot `+0x16` (stored at `work:0x8124`) and the shape fetched by `0x4C41`, a cache lookup with no transform.

**The `ROT*` angle bank.**
`ROTZ` (`0xA807`), `ROTX` (`0xA8F3`) and `ROTY` (`0xA906`) take their angle from the word at `work:0x810E + operand` and skip a zero.
The draw path fills that bank: operand `0x16` is slot `+0x16` (`0x1D5F`), and `0x1D96` writes the rest once per frame for the whole film, never per actor: `0x10` the film clock `<< 12`, `0x12` var 10's change since the previous frame saturated at 255 `<< 8`, `0x14` the previous frame's `(var 10 & 0xFF) << 8`, and `0x18`/`0x1A` `±var 12` ([`angle-bank.md`](angle-bank.md), `[Established]`, static and by breakpoint).
The stock aircraft use `0x14` with `ROTZ` on propellers, and `0x18`/`0x1A` with `ROTX` and `ROTZ`.
`PUSHRELMAT` (`0xA99A`) pushes the nine words at `0x808A` and the light at `0x8072..0x8076` ([`memory-map-vm.md`](memory-map-vm.md)); `POPRELMAT` (`0xA9B8`) restores them.

**How each `ROT*` turns.**
`[Established]`, static, read with `mise run re-tool -- disasm` of `0xA807..0xA9D0` (2026-11-17); nothing observed live.
Each post-multiplies the draw matrix, `M ← M · R`, so a vertex loaded after it is `M · R · v`: the part turns about the shape's origin, the current centre (`MOVECENTRE`) moving it into place.
`ROTX` and `ROTY` call the builder `0x8725` ([`coordinates-and-units.md`](../formats/concepts/coordinates-and-units.md) § 3.4) with the angle as its pitch (`BP`, `0xA8F7`) and as its yaw (`SI`, `0xA90B`), the other two angles 0, so `R = Rx(a)` and `R = Ry(−a)`, and multiply through `0x884A` into `0x808A`.
`ROTZ` turns the matrix's first two columns in place, `(c₀ cos a + c₁ sin a, c₁ cos a − c₀ sin a)` for each row (`0xA823..0xA8B8`), which is `R = Rz(a)`, and then turns the light's x and y words the same way (`0xA8BC..0xA8EB`), `L ← Rz(a)ᵀ · L`; `ROTX` and `ROTY` leave the light alone.
All three look the angle up as `angle >> 4` in the 4,096-entry sine table, so a bank word is a 16-bit angle, 65,536 to a turn.
`vm.rs` follows this: a decode takes an angle bank ([`AngleBank`](../../crates/stunt-core/src/sod/bank.rs)), and the renderer decodes an actor's shape again in the pose its bank words give at each tick, from film variables 10 and 12 as [`angle-bank.md`](angle-bank.md) § 2 describes.
Scenery and view-facing shapes draw at rest.
In a `sod-census --rot` audit of the 31 retail, demo and FreeFlight archives (`2,473` unique `.SOD` models, `0` stops, `[Bounded Observation]`), `54` shapes execute `ROT*` (`52` in `PLANES.RES`, `0x3E57` and `0x3E39` in `MILITARY.RES`; `46` placed as film actors, `8` unplaced across the 22 corpus films), `0` are `SCENERY.scn` props or `HEADER_FACES_VIEW` shapes, and only operands `0x14`, `0x18` and `0x1A` appear (`0` uses of `0x10`, `0x12` or `0x16`).
`OP_BVLT` (`CENSUS_SKIPS`) and unwalked branches are excluded by the walk, though a raw byte scan finds `0` aligned `ROT*` words across all `1,504` models in `SCENERY1`..`SCENERY6.RES`, `0` in all `64` `HEADER_FACES_VIEW` `.RES` shapes and `0` `ROT*` patterns paired with `0x10`, `0x12` or `0x16` across `.RES` or the four `.ALL` archives, so leaving scenery and view-facing draws at rest leaves no stock `ROT*` unposed in those archives ([`angle-bank.md`](angle-bank.md) § 5).
_Source: [the `ROT*` handlers read and the bank driven](../../work/2026-11/271_rot-angles/journal.md#2026-11-17-the-rot-handlers-read-and-the-bank-driven), [corpus `ROT*` census finds no scenery or view-facing reader and no `0x12` rotation](../../work/2026-11/681_sod-rot-census/journal.md#2026-11-19-corpus-rot-census-finds-no-scenery-or-view-facing-reader-and-no-0x12-rotation)._

_Found 2026-11-06; see the [parity log](../../work/2026-10/parity-log/log.md)._

## 10. Open questions

* **Facing flags and depth sections** (section 8.6, [#74](https://github.com/neilsh/stunt-reel/issues/74), [#235](https://github.com/neilsh/stunt-reel/issues/235)).
  Ruled out: `OP_IFVIS` as a distance gate; on the paths the census walks, any of `BZLT`, `BVIS`, `REJVEC`, `REJ2D` or a nested section as a parity lever, since no census walk of the stock shapes reaches one (`[Bounded Observation]`; `BVLT`'s branch and code no walked branch reaches are unchecked).
  Open: a polygon in a nested section takes only the inner gate, and a `GOSUB` or `SORTON` resume restores the current gate but not the outer ones; at `n · (b − eye) = 0` `BVIS` draws in PLAYONE and in neither form here; an `IFVIS` or `BVIS` on a flag its shape never set is drawn, where PLAYONE reads a stale byte; `REJ2D` for a triple with a point behind the eye; no `BZLT` has been traced live.
  The `INTRO.FLM` "conifers drawn as round bushes" grader note (tick 3295, not in the current capture) no longer shows at ticks 3290 and 3301, where ours draws conifers since [#399](https://github.com/neilsh/stunt-reel/issues/399); the capture's conifer field there is denser than ours ([#426](https://github.com/neilsh/stunt-reel/issues/426)).

* **The `SHADE` light vector and the `GVPOLY16` colour path** (section 8.5).
  Closed: the callers that hand `0x9100` its light are the three call sites of [`terrain-shade.md`](terrain-shade.md) section 4.2, and the renderer shades with the world light ([#221](https://github.com/neilsh/stunt-reel/issues/221)); `GVPOLY16` reads its ramp from the word after its registers (section 8.5).
  Open: an actor's own light (the world light turned by its rotation and the view, `0x1CFB`), which changes every frame while shapes are decoded once; the vertex fraction the interpolation drops; the light for a film-variable-13 value other than `0x2D`; and `vm.rs`'s `shade_level`, which subtracts 2 from a `GVPOLY`/`GVPOLY16` level when the base is `0x10` (the triplane's red ramp), where the handlers' Gouraud routes add `G` (`[0x812E]`, `0x99EB`, `0x9ABB`) and `GVPOLY16`'s flat route `0x9A58..0x9A65` adds neither `G` nor an adjustment (section 8.5, [`terrain-shade.md`](terrain-shade.md) section 5).
  They decide the colour of the aircraft parts a full `SORTON` walk would reach ([`hero-aircraft-placement.md`](../parity/hero-aircraft-placement.md) section 1).
