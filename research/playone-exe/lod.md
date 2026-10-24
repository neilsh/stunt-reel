# `PLAYONE.EXE`: Level-of-Detail Distance Gate and the `GAME.VAR` Detail Word

* **Binary**: `PLAYONE.EXE` (LZEXE 0.91), unpacked with [`unlzexe.py`](../../python/scripts/unlzexe.py) to the load image `build/re/playone.img`
* **Method**: Capstone 16-bit disassembly of the load image, located from the patch signature in Alberto Marnetto's article [*Tweaking Stunt Island*](https://marnetto.net/2024/11/20/tweaking-stunt-island) (2024-11-20). The article analyses `STUNT.EXE` and states that `MAKEONE` and `PLAYONE` share the rendering code.
* **Scope**: where the detail setting enters the renderer, the distance comparison it scales, and what that means for parity captures
* **Evidence tier**: `[Established]` for the instruction sequences and the data flow below; `[Supported Inference]` for the node-tree reading of the walker and for `0x229C` being the projection scale; `[Unknown]` for the caller and node layout of the walker

Offsets are load-image offsets, and `DS:` offsets are DGROUP-relative (image `0xD510 + off`; see [`static-tooling.md`](static-tooling.md) section 3).

---

## 1. The Article's Patch Site Exists In PLAYONE

The article finds the detail check in `STUNT.EXE` by the sequence `03 D3 3B CA 7F 1B` (`add dx, bx; cmp cx, dx; jg`), preceded by `F7 26 xx xx`, a `mul` by the detail word. Its 8x patch replaces those six bytes, `F7 26 xx xx 03 D3`, with `89 C2 C1 E2 03 90` (`mov dx, ax; shl dx, 3; nop`), so the threshold becomes eight times the unscaled value.

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

`[Established]` for the instructions. `[Supported Inference]` that this walks the scenery node tree described in [`map.md`](../formats/auxiliary/map.md) (`SP_1NODE` carries `splitdist` and `next`): `[bp+8]` is a child link and `[bx+0x56C]` a jump table indexed by node type.

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

## 5. Open Items

* **The walker's entry and caller.** The routine's start (before `0x20F0`), its callers and the targets of the `[bx+0x56C]` table haven't been traced. If it is the world-scenery walker, it is also a static route to the code that hands ground objects to the display-list VM ([`parity/handoff-ground-shade.md`](../parity/handoff-ground-shade.md)).
* **The node layout** at `[bp+2]`, `[bp+4]`, `[bp+6]` and `[bp+8]`, and whether it matches `map.md`'s `SP_1NODE`.
* **The film variable** read at `0x1200` (`[bx+si+0x7E]`, see [`startup.md`](startup.md) section 5 for the variable addressing) that drives `0x229C`.
