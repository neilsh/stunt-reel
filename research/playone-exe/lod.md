# `PLAYONE.EXE`: Level-of-Detail Distance Gate and the `GAME.VAR` Detail Word

* **Binary**: `PLAYONE.EXE` (LZEXE 0.91), unpacked with [`unlzexe.py`](../../python/scripts/unlzexe.py) to the load image `build/re/playone.img`
* **Method**: Capstone 16-bit disassembly of the load image, located from the patch signature in Alberto Marnetto's article [*Tweaking Stunt Island*](https://marnetto.net/2024/11/20/tweaking-stunt-island) (2024-11-20). The article analyses `STUNT.EXE` and states that `MAKEONE` and `PLAYONE` share the rendering code.
* **Scope**: where the detail setting enters the renderer, the distance comparison it scales, and what that means for parity captures
* **Evidence tier**: `[Established]` for the instruction sequences, the data flow and the walker being the `SP_1NODE` handler (section 1.1); `[Supported Inference]` for `0x229C` being the projection scale and for the distance in `CX` being view-space depth; `[Unknown]` for the walker's outer caller

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
| Per-shot scale | `0x120A..0x1223` | `mul [0x22B6]`, normalise, `mov [0x229C], ax` | Builds `0x229C` from a film variable (`[bx+si+0x7E]`) times `0x22B6`. It is also copied to `work:0x8108`, which the sun-disc drawer `0x908E` reads. |
| Detail word | `0x1242..0x124D` | `mov ax, [0x229C]; mul [0x0710]; shl ax,1; rcl dx,1; mov [0x22A4], dx` | `0x22A4 = (0x229C × detail × 2) >> 16` |
| Use | `0x212D` | `mul [0x22A4]` | The only reader |

`0x22A4` has exactly one writer (`0x124D`) and one reader (`0x212D`) in a whole-image decode. The threshold therefore scales with **both** the detail setting and the per-shot scale `0x229C`. A zoomed shot keeps fine detail further out than a wide one at the same distance. `[Established]` for the data flow; `[Supported Inference]` that `0x229C` is the projection (zoom) scale, from its copy at `work:0x8108`, which the sun-disc drawer uses as a size scale.

The detail scale matches the article: `0xFFFF` is 100%, and the in-game slider writes values such as `0xFD70` (99%) and `0x028F` (1%).

## 3. Capture Invariant: No `GAME.VAR`, So Full Detail

* The image initialises `DS:0x0710` to `0xFFFF`. When `game.var` cannot be opened, the word presumably keeps that value: the loader `0x4790` returns carry on failure (see its other caller at `0x0CD2`), and the only other code that names the buffer is a second `game.var` routine at `0x45B9` (`mov dx, 0x5B5; mov di, 0x710; mov cx, 0x1C; jmp 0x46EA`: 28 bytes, the size of `GAME.VAR`), most likely the save path. That part is `[Supported Inference]`; neither the loader's failure path nor `0x46EA` has been read.
* The parity stage built by [`capture_playone_reference.py`](../../python/scripts/capture_playone_reference.py) copies `ENGINE_FILES` from `corpus/stisldem`. That directory has no `GAME.VAR` and `ENGINE_FILES` doesn't list one, so **every capture runs at detail `0xFFFF` (100%)**. `[Established]` from the image bytes and the stage contents.
* The `GAME.VAR` in the local `target_bin/StuntIsl` starts with `60 3C` (`0x3C60`, about 24%). The archive copies under `corpus/si_archive/Films/*/GAME.VAR` start with `FF FF`. Staging either kind would change which level of detail the reference frames show, so a `GAME.VAR` must not be added to the stage without recording its first word next to the capture.

## 4. Consequences For The Renderer

* PLAYONE at 100% detail still switches to coarser nodes with distance. Its threshold is the node's size term scaled by `0x22A4`, not a fixed distance. A renderer that always draws the finest representation will over-draw distant objects compared with the captures.
* This gate is separate from the model bytecode's own `iftrue complex1..3` branches and from `OP_IFVIS` condition 1, whose `D^2 >= 1000 m^2` reading is still a `[Supported Inference]` ([`sod.md`](../formats/sod.md) section 4, Q-SOD-01 and Q-SOD-05).

* `world.rs` builds the world once per film, so it cannot switch level of detail per frame. It keeps an `SP_1NODE`'s subtree when the camera path ever comes within the threshold and draws the stand-in otherwise. It also uses Euclidean distance to the camera path for `CX` and a fixed scale of 0.5 for `[0x22A4] / 0x10000` (section 2's normalised range is `[0.5, 1)`). Scored in [`parity-findings.md` § 26](../parity-findings.md).

## 5. Open Items

* **The walker's outer caller.** The pending-node stack popped at `0x1B8C` and its feeder `0x1B75` (`xchg di, [bx+0x2346]`) are known; the routine that seeds the root hasn't been traced. It is also a static route to the code that hands ground objects to the display-list VM ([`parity/handoff-ground-shade.md`](../parity/handoff-ground-shade.md)).
* **The exponent `0x229E`.** `0x1200..0x1226` normalises `0x229C` with at most three shifts and stores the count at `0x229E`. The frustum test shifts `ext` by it (`0x20E2`), but the threshold at `0x2121` does not, so the units of `CX` against `splitdist` at other zoom levels are open.
* **The film variable** read at `0x1200` (`[bx+si+0x7E]`, see [`startup.md`](startup.md) section 5 for the variable addressing) that drives `0x229C`.
