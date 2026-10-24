# `PLAYONE.EXE`: Level-of-Detail Distance Gate and the `GAME.VAR` Detail Word

* **Binary**: `PLAYONE.EXE` (LZEXE 0.91), unpacked with [`unlzexe.py`](../../python/scripts/unlzexe.py) to the load image `build/re/playone.img`
* **Method**: Capstone 16-bit disassembly of the load image, located from the patch signature in Alberto Marnetto's article [*Tweaking Stunt Island*](https://marnetto.net/2024/11/20/tweaking-stunt-island) (2024-11-20). The article analyses `STUNT.EXE` and states that `MAKEONE` and `PLAYONE` share the rendering code.
* **Scope**: where the detail setting enters the renderer, the distance comparison it scales, and what that means for parity captures
* **Evidence tier**: `[Established]` for the instruction sequences, the data flow and the walker being the `SP_1NODE` handler (section 1.1); `[Established]` for `0x229C` coming from film variable `view_obj` (section 2.1) and for how `0x229C`/`0x229E` zoom the view matrix (section 2.2); `[Supported Inference]` for that variable being the camera's zoom and for the distance in `CX` being view-space depth; `[Unknown]` for the walker's outer caller

Offsets are load-image offsets, and `DS:` offsets are DGROUP-relative (image `0xD510 + off`; see [`static-tooling.md`](static-tooling.md) section 3).

---

## 1. The Article's Patch Site Exists In PLAYONE

The article finds the detail check in `STUNT.EXE` by the sequence `03 D3 3B CA 7F 1B` (`add dx, bx; cmp cx, dx; jg`), preceded by `F7 26 xx xx`, a `mul` by the detail word. Its 8x patch replaces those six bytes, `F7 26 xx xx 03 D3`, with `89 C2 C1 E2 03 90` (`mov dx, ax; shl dx, 3; nop`), so the threshold becomes eight times the unscaled value.

The released `si-8x` (version 1.1, 2026-03-17, in the local `si-tools` checkout) applies the patch as whole-file byte diffs of `STUNT.EXE`, `MAKEONE.EXE` and `PLAYONE.EXE` for two releases. Its README tells them apart by the size of `STUNT.EXE`: 137,240 bytes for the GOG release, 134,784 bytes after the "P3 - Final Patch Set".

In `PLAYONE.EXE` that sequence occurs exactly once, at image `0x2131`, and the `mul` before it reads `DS:0x22A4`:

```asm
2121  8b 5e 04        mov  bx, [bp+4]
2124  d1 eb           shr  bx, 1
2126  8b 46 06        mov  ax, [bp+6]
2129  2b c3           sub  ax, bx
212b  78 14           js   0x2141
212d  f7 26 a4 22     mul  word [0x22A4]     ; scale by the detail-and-zoom word
2131  03 d3           add  dx, bx
2133  3b ca           cmp  cx, dx            ; node distance vs threshold
2135  7f 1b           jg   0x2152            ; too far: draw this node
2137  8b 6e 08        mov  bp, [bp+8]        ; near enough: descend to the finer child
213a  8b 5e 00        mov  bx, [bp]
213d  ff a7 6c 05     jmp  [bx+0x056C]       ; dispatch on the child's type word
```

The far branch (`0x2152`) takes the node's object word `[bp+2]`, stores it at `DS:0x22EC` and calls `0x4C41`. Before this, `0x20F2..0x211C` tests the node's extent against three more scale words, `0x229C`, `0x22A0` and `0x22A2`. If the test fails, it branches to `0x2149`, which returns or continues at `0x1B8C`.

`[Established]` for the instructions.

### 1.1 It Is The `SP_1NODE` Handler, And `obj` Is A Far Stand-In

The scene walker dispatches on a node's type word through two jump tables in DGROUP, `DS:0x0554` (image `0xDA64`) and `DS:0x056C` (image `0xDA7C`). Both are indexed by the even type word of [`map.md`](../formats/auxiliary/map.md) section 3.2:

| Type | Node | `0x0554` entry | `0x056C` entry |
|---|---|---|---|
| 0 | `SP_POS` | `0x1E89` | `0x1E89` |
| 2 | `SP_1NODE` | `0x20A7` | `0x2121` |
| 4 / 6 / 8 | `SP_2NODE` / `SP_XPLANE` / `SP_ZPLANE` | `0x1EC0` / `0x1EF2` / `0x1EF6` | same |
| 10 | `SP_LEAF` | `0x220B` | `0x220B` |
| 12 / 14 | `SP_GROUND` / `SP_GLEAF` | `0x2360` / `0x23BF` | same |
| 16 / 18 / 20 / 22 | `SP_HSLOPE` / `SP_VSLOPE` / `SP_LIST` / `SP_POSXZ` | `0x200B` / `0x2059` / `0x1FD0` / `0x1EA8` | same |

The two tables differ only for type 2. `SP_POS` (`0x1E89`) and `SP_POSXZ` (`0x1EA8`) add their offsets to the accumulated position `DS:0x49F4/0x49F8/0x49FC` and continue through `0x0554`. So an `SP_1NODE` reached after a position change enters at `0x20A7`. That path rotates the position into view space (`lcall 0x0824:0x06B0` with the matrix at `0x80C0`), culls the node's `ext` against the frustum (`0x20BF..0x211C`, scaled by `0x229C`, `0x22A0`, `0x22A2`; outside goes to `0x2149`, which skips the node), puts the view-space depth in `CX` and falls into `0x2121`. When a near `SP_1NODE` descends, it dispatches its `next` through `0x056C`. A chained `SP_1NODE` at the same position then enters at `0x2121` directly and reuses `CX`.

At `0x2121` the node is `type, obj, ext, splitdist, next` at `[bp+0..8]`, matching `map.md`'s `SP_1NODE`. With `half = ext >> 1`:

* the threshold is `half + ((splitdist - half) × [0x22A4] >> 16)`, or `splitdist` itself when `splitdist < half` (`0x2141`);
* **near** (`CX <= threshold`, `0x2137`): descend to `next` (`[bp+8]`); `obj` is not drawn;
* **far** (`CX > threshold`, `0x2152`): if `obj` (`[bp+2]`) is non-zero, store it at `DS:0x22EC` and draw it at the accumulated position through the same sequence as `SP_LEAF` (`0x220B`: `call 0x4C41`, the projection at `0x31CF`, `lcall 0x0824:0x0EC0`). Either way the walker then pops its pending-node stack (`0x2202`/`0x214A` → `0x1B8C`). `next` is never walked.

So `obj` is a coarse stand-in drawn **instead of** the subtree beyond the threshold, never in addition to it. A far node with `obj = 0` draws nothing. `[Established]` for the control flow; `[Supported Inference]` that `CX` is view-space depth (it is the first rotated coordinate after the frustum test, which compares the other two against it).

Alberto Marnetto's MIT-licensed `si-free-flight-2` (`scenegraph_loader.cpp`, [`si-tools`](https://github.com/AlbertoMarnetto/si-tools), consulted 2026-10-23) has no level-of-detail gate. It places `obj` at the accumulated position **and** walks `next`, so a viewer built that way draws both representations at once. `world.rs` follows the PLAYONE control flow above.

## 2. Where `DS:0x22A4` Comes From

| Step | Address | Instruction | Meaning |
|---|---|---|---|
| Load `game.var` | `0x0DB8` | `mov dx, 0x5B5; mov cx, 0x710; call 0x4790` | Reads the file named at `DS:0x05B5` (`"game.var"`) into `DS:0x0710`. The first word is the detail setting. |
| Per-shot scale | `0x11FC..0x1223` | `mov ax, [bx+si+0x7E]`, `mul [0x22B6]`, normalise, `mov [0x229C], ax` | Builds `0x229C` from film variable `view_obj` (section 2.1) times `0x22B6`. It is also copied to `work:0x8108`, which the sun-disc drawer `0x908E` reads. |
| Detail word | `0x1242..0x124D` | `mov ax, [0x229C]; mul [0x0710]; shl ax,1; rcl dx,1; mov [0x22A4], dx` | `0x22A4 = (0x229C × detail × 2) >> 16` |
| Use | `0x212D` | `mul [0x22A4]` | The only reader |

`0x22A4` has exactly one writer (`0x124D`) and one reader (`0x212D`) in a whole-image decode. The threshold therefore scales with **both** the detail setting and the per-shot scale `0x229C`. A zoomed shot keeps fine detail further out than a wide one at the same distance. `[Established]` for the data flow; `[Supported Inference]` that `0x229C` is the projection (zoom) scale, from its copy at `work:0x8108`, which the sun-disc drawer uses as a size scale.

The detail scale matches the article: `0xFFFF` is 100%, and the in-game slider writes values such as `0xFD70` (99%) and `0x028F` (1%).

### 2.1 The Film Variable Is The View Camera's Lens

* **Index.** The frame step's caller (`0x4A2F`) loads `BX = 0x4888` and `AX = [0x4888 + 0x1A]`, then calls `0x0EE9`. That routine pushes `AX` (`0x0F4A`) and passes it to `0x11FC`, where `SI = 2 × AX` and the variable is `[BX + SI + 0x7E]`. The only film-opcode writer of `+0x1A` is the `view_obj` handler: `0x3D0D` subtracts `0x98` from opcodes `0x90..0x97` and `0x3D7B` adds 8 back before `mov [bx+0x1A], ax` (`0x3D7F`). So `+0x1A` is `view_obj`, 0 to 7, and the variable is **film variable `n` while camera `n` is the view**. `[BX + SI + 0x2E]` in the same routine is that camera's object pointer, from the object table the create and interp handlers index (`0x3CE7`, `0x3CF8`). `[Established]` for the data flow; `[Supported Inference]` that the variable is the camera's zoom.
* **Multiplier.** `0x22B6` is written only by `0x11F8`. Its caller at `0x4A29` passes `0x7FFF`.
* **Normalisation.** `0x120E..0x121F` shifts `DX:AX = var × 0x7FFF` left until bit 14 of `DX` is set, at most three times. `0x229C` is then `DX` and `0x229E` the unused shift count. With the full detail word, `[0x22A4] / 0x10000` is therefore a mantissa in about `[0.5, 1)` for any lens of 4096 or more.
* **Film values.** Both parity films set variables 0 to 3 to 8192 at tick 0. That gives three shifts, `0x229C = 0x7FFF` and `[0x22A4] = 0xFFFD`, a scale of 0.99995. `INTRO.FLM` also uses 20480 (scale 0.625, camera 4), 44236 (0.675, camera 1 from tick 1216) and 10649 (0.65, camera 7), listed with [`flm_events.py`](../../python/scripts/flm_events.py). Variables 0 to 7 have no fixed-offset reader ([`palette-fade.md`](palette-fade.md) section 3.2) because this index-driven read is their reader.
* **Renderer.** The film evaluator carries the lens per frame and narrows `fov_degrees` by it (section 2.2, [`parity-findings.md` § 29](../parity-findings.md)). A per-frame level-of-detail patch carried `var[view_obj]` and reproduced `0x120A..0x124D`, but it was not adopted ([`parity-findings.md` § 28](../parity-findings.md)).

### 2.2 How The Lens Scales The Projection

* **The view matrix is zoomed.** After `0x11FC` normalises the lens, `0x1260..0x12D2` builds the camera rotation at `work:0x80D2` (`lcall 0x0824:0x04E5`) and copies it to `0x80AE` and `0x809C` (`lcall 0x0824:0x0681`). `0x12DC` then rescales the copy in the work segment: the first six words (`0x12E3..0x12F3`) are multiplied by `work:0x8108 = 0x229C` as a Q15 factor (`imul bx; shl ax,1; rcl ax,1`, so `w × m / 0x8000`), and the last three (`0x12F5..0x1303`) are shifted right arithmetically by `work:0x810C = 0x229E` (`sar ax, cl`). The first call writes `0x80C0` from `0x80AE`; the second rescales `0x809C` in place. `[Established]`.
* **Rows 0 and 1 are the screen axes, row 2 is depth.** The matrix-vector routine `lcall 0x0824:0x06B0` (image `0x88FB`) is row-major: row 0 gives `DX:AX`, row 1 `BP:BX`, row 2 `DI:CX`. The frustum test at `0x20BF` treats `DI` as depth (in front when `ext + DI ≥ 0`) and `DX`, `BX` as the two screen axes. `[Established]`.
* **Focal length.** Screen position is `x / depth` times a fixed pixel scale, so with screen rows scaled by `m / 0x8000` and depth by `2^-c` the focal length is multiplied by `zoom = (0x229C / 0x8000) × 2^0x229E`. The normalisation always does `s` shifts with `s + c = 3`, so `0x229C ≈ lens × 0x7FFF × 2^s / 0x10000` and **`zoom ≈ lens / 8192`** to Q15 rounding. The default lens 8192 gives `0x7FFF / 0x8000`, i.e. 1.0. INTRO's 20480 gives 2.50, 10649 gives 1.30 and 44236 gives 5.40, so camera 1's shots from tick 1216 are a 5.4× telephoto. `[Established]` for the arithmetic; `[Supported Inference]` that the fixed pixel scale is the same for every lens, since no other reader of the lens was found.
* **Field of view.** The renderer's 45° vertical field of view stands for the default lens, so a lens `L` draws at `2 × atan(tan(22.5°) / zoom(L))`: 8.8° at 44236, 18.8° at 20480, 35.3° at 10649. [`CameraTransform::lens_fov_degrees`](../../crates/stunt-core/src/contracts/trajectory.rs) computes it.
* **Other readers.** `0x810A = 0x229C² × 2 >> 16` (`0x1232..0x1238`) is written for the work segment. The sun-disc drawer `0x908E` multiplies by `0x8108` (`0x90DE`, `0x911A`), as do `0x9E94` and `0xA0DB`. The frustum tests at `0x1B23..0x1B67` and `0x20E2..0x211C` scale the bounding extent the same way the matrix scales a point: by `0x229C` against the two screen slopes `0x22A0`/`0x22A2` (the larger half-width and half-height of the viewport around `0x41C8/0x41CA`, times 256, written at `0x11A4` and `0x11B9`), and by `>> (0x229E + 1)` along depth.
* **Consequence for the distance gate.** `CX` at `0x211E` is the depth from the zoomed matrix, so it is in units of `2^-0x229E` of true depth, while the threshold at `0x212D` scales by `0x22A4` (mantissa only). In true depth the threshold is therefore about the size term times `zoom(L)`: about 1.0 for the default lens, about 5.4 for 44236. The per-frame patch scored in [`parity-findings.md` § 28](../parity-findings.md) used the mantissa alone, which is right for CTRY's lens but under-counts INTRO's zoomed shots. `[Supported Inference]`.

## 3. Capture Invariant: No `GAME.VAR`, So Full Detail

* The image initialises `DS:0x0710` to `0xFFFF`. When `game.var` cannot be opened, the word presumably keeps that value: the loader `0x4790` returns carry on failure (see its other caller at `0x0CD2`), and the only other code that names the buffer is a second `game.var` routine at `0x45B9` (`mov dx, 0x5B5; mov di, 0x710; mov cx, 0x1C; jmp 0x46EA`: 28 bytes, the size of `GAME.VAR`), most likely the save path. That part is `[Supported Inference]`; neither the loader's failure path nor `0x46EA` has been read.
* The parity stage built by [`capture_playone_reference.py`](../../python/scripts/capture_playone_reference.py) copies `ENGINE_FILES` from `corpus/stisldem`. That directory has no `GAME.VAR` and `ENGINE_FILES` doesn't list one, so **every capture runs at detail `0xFFFF` (100%)**. `[Established]` from the image bytes and the stage contents.
* The `GAME.VAR` in the local `target_bin/StuntIsl` starts with `60 3C` (`0x3C60`, about 24%). The archive copies under `corpus/si_archive/Films/*/GAME.VAR` start with `FF FF`. Staging either kind would change which level of detail the reference frames show, so a `GAME.VAR` must not be added to the stage without recording its first word next to the capture.

## 4. Consequences For The Renderer

* PLAYONE at 100% detail still switches to coarser nodes with distance. Its threshold is the node's size term scaled by `0x22A4`, not a fixed distance. A renderer that always draws the finest representation will over-draw distant objects compared with the captures.
* This gate is separate from the model bytecode's own `iftrue complex1..3` branches and from `OP_IFVIS` condition 1, whose `D^2 >= 1000 m^2` reading is still a `[Supported Inference]` ([`sod.md`](../formats/sod.md) section 4, Q-SOD-01 and Q-SOD-05).

* `world.rs` builds the world once per film, so it cannot switch level of detail per frame. It keeps an `SP_1NODE`'s subtree when the camera path ever comes within the threshold and draws the stand-in otherwise. It also uses Euclidean distance to the camera path for `CX` and a fixed scale of 0.5 for `[0x22A4] / 0x10000` (section 2's normalised range is `[0.5, 1)`). Scored in [`parity-findings.md` § 26](../parity-findings.md).
* Selecting the branch per frame, from view-space depth and the lens scale of section 2.1 (about 1.0 for the parity films' default lens), scored within noise of the static rule and was not adopted ([`parity-findings.md` § 28](../parity-findings.md)).

## 5. Open Items

* **The walker's outer caller.** The pending-node stack popped at `0x1B8C` and its feeder `0x1B75` (`xchg di, [bx+0x2346]`) are known; the routine that seeds the root hasn't been traced. It is also a static route to the code that hands ground objects to the display-list VM ([`parity/handoff-ground-shade.md`](../parity/handoff-ground-shade.md)).
* **The fixed pixel scale.** Section 2.2 gives the zoom relative to the default lens. The pixel scale it multiplies, and so the absolute field of view at lens 8192, hasn't been traced to the divide; the renderer's 45° is an assumption.
