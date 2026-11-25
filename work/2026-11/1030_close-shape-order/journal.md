# Journal

## 2026-11-24: list order explains the BOMB trees, not the canyon rock

- **Question**: does painting a shape's polygons in `PLAYONE`'s display-list order, with no depth test inside the shape, explain the cover order the capture shows on `location` tick 7019 (canyon rock 1145) and `bomb` ticks 2080 and 2300 (autumn trees 542 and 545)?
- **Method**: on `main` at `19869b40` (`crates/` tree `d897adcc`), GPU render (RTX 4070), the issue's steps 1 and 2:
  1. `stuntreel sod-trace` of shapes 1145 (`LOCATION.ALL`) and 542 (`BOMB.ALL`), and `mise run re-tool -- disasm 0x9183 0x91B0` for the `SORTON` handler.
  2. A temporary switch, saved as [`switches/DBG_INSHAPE.diff`](switches/DBG_INSHAPE.diff).
     It records each `POLYZ`, `SPHERE`, queued `SORT` and `RETURN` of a shape's walk.
     During a headless render it then paints every placement of shape `DBG_INSHAPE` on the CPU into the same 320 × 185 view, in two ways:
     - *painter*: placements far to near by their origin, each shape in list order, each `SORT`'s two branches swapped when its facing flag is clear (the handler's rule, below), with each `SPHERE` drawn as a screen disc;
     - *CPU z-buffer*: the same primitives, the nearest fragment winning.
     `IFVIS` gates are applied in both, and polygons are clipped at `w = 0.05`.
     The control is the CPU z-buffer, which must reproduce our GPU render inside the shape.
  3. `DBG_INSHAPE=<shape> DBG_INSHAPE_ALL=<film>.ALL mise run frame -- --film <film> --ticks … --no-build`, then [`inshape.py`](inshape.py).
     The script takes the pixels our render's `shapes.zst` gives to the shape and the painter covers, and counts how many carry the capture's index in our render, the CPU z-buffer and the painter ([`inshape.txt`](inshape.txt)).
     Its sheets run capture, ours, ours with the painter's pixels inside the shape, and ours with the CPU z-buffer's.
- **Result**:
  - **The `SORTON` rule** (handler image `0x9183`): it pushes the stream's continuation, `operand + first`, then reads the flag byte `[w3 + 0x7C68]`.
    When the flag is set (`js`: the face points at the eye), it runs the branch after the three operands first, then the one at `operand + second`.
    When the flag is clear (`xchg cx, si`), it runs the same two branches in the other order.
    Each branch ends in a `RETURN` that resumes the next.
    Our VM runs the inline branch first whatever the flag.
  - **Shape 1145** (`stuntreel sod-trace` on `LOCATION.ALL`) is 51 flat `POLYZ` polygons (`COLOR`), each behind an `IFVIS` gate: 41 triangles, 6 quads, 2 pentagons, a hexagon and a heptagon.
    50 lie inside 12 `SORT` nodes; one quad (`0x0A16`) follows the outermost `SORT`'s continuation (`0x0A0C`).
    **Shape 542** (`sod-trace` on `BOMB.ALL`; 545 the same) is one `SPHERE` (`0x0322`), 10 trunk polygons behind `IFVIS` gates (`0x0328..0x03F7`), then 41 `SPHERE`s (`0x03FC..0x058C`), 42 in all, with no `SORT`.
  - **`location` 7019, shape 1145** ([sheet](images/location-7019-inshape.png)): it covers 49,095 of the view's pixels.
    The CPU z-buffer gives the same index as our render on 0.990 of them, and the painter shows another polygon than the z-buffer on 20.
    Capture agreement: ours 0.368, CPU z-buffer 0.373, painter 0.373.
    The painter draws the same near face across the lower left that our render draws and the capture does not.
  - **`bomb` trees** ([2080, 542](images/bomb-2080-542-inshape.png), [2300, 545](images/bomb-2300-545-inshape.png)):

    | Tick | Shape | Pixels | Ours | CPU z-buffer | Painter | CPU z-buffer = ours | Painter ≠ z-buffer polygon |
    |---|---|---|---|---|---|---|---|
    | 2080 | 542 | 3,237 | 0.669 | 0.664 | 0.875 | 0.902 | 865 px |
    | 2300 | 542 | 1,439 | 0.589 | 0.594 | 0.906 | 0.885 | 780 px |
    | 2080 | 545 | 465 | 0.613 | 0.634 | 0.849 | 0.923 | 122 px |
    | 2300 | 545 | 5,667 | 0.686 | 0.699 | 0.885 | 0.889 | 1,671 px |

    The CPU z-buffer draws the spheres as the same discs and stays within 0.022 of ours (10 of 465 pixels at 2080, shape 545), so the gain is the order, not the disc outline.
    In the sheets the painter's leaf clusters cover each other and the trunk as the capture's do.
- **Verdict**: control (diagnosis), no renderer change.
  For the trees, list order is the explanation: each later `SPHERE` covers the earlier ones and the trunk, whatever its depth.
  For the canyon rock it is a negative: in-shape order, `SORTON` swaps included, changes 20 of 49,095 pixels.
  Our near face is drawn whichever order is used, so 7019 needs another cause.
  `[Hypothesis]`, not tested here: the rock's own placement or geometry, the camera, or `PLAYONE` dropping a polygon that crosses the eye plane, since it has no near-plane clipper.
  The issue's step 3, a renderer that draws a shape's spheres in list order, scored on all seven films, is [#1066](https://github.com/neilsh/stunt-reel/issues/1066).
- **Lives in**: [`prop-shape-loss.md`](../../../research/parity/prop-shape-loss.md) § 2.3, [`render-model.md`](../../../research/parity/render-model.md) § 2, [`sod-vm-execution.md`](../../../research/playone-exe/sod-vm-execution.md) § 8.6.
