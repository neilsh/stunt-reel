# Journal

## 2026-11-12: what thins the INTRO conifer field

- **Question**: Why does our render of `INTRO.FLM` ticks 3290 and 3301 show the conifer field past the `STUNT` letters sparser and fainter than the capture ([#426](https://github.com/neilsh/stunt-reel/issues/426))? Candidates from the issue: placement (`SP_1NODE` stand-ins, the sub-pixel cull, level of detail) or shading (the colour the trees take).
- **Method**: `mise run frame -- --film intro --ticks 3301` with crops at 4× and 8× on `main` `2a289b9b`; a scratch script counted palette indices per region in the capture and the render store, and printed one pine's pixels side by side. `stuntreel sod-trace` on `0x03A3` and `0x03A7` of the capture's `INTRO.ALL`. `mise run disasm -- 0x7571 0x75DB` on the unpatched load image (the Patch #3 image was not read).
- **Result**:
  - In the 60 × 60 pixels at `(20, 40)` of tick 3301, every tree the capture draws has one at the same place in ours; what differs is how many pixels each covers. Over the top-left 100 × 100 pixels the ground is a prop tile in index 174 in both. Tree indices 172, 173, 175 and 176 cover 442, 669, 133 and 227 pixels in the capture and 248, 403, 51 and 113 in ours.
  - Each pine is one `OP_IPG` type 8 quad and two `POLYZ` triangles. With the quad's corners `(±a, ±b, 0)` and `INTV` taking midpoints, the first triangle (`COLOR 0xAA` in `0x03A3`, `0xAC` in `0x03A7`) is the whole tree, apex `(0, −b)` over the base `(±a, b/2)`; the second (`0xAC`, `0xB0`) is a sliver outside its right edge, from the apex to `(a, b/4)` and `(a, b/2)`, at most `a/6` wide. The trunk is a `ZLINETO` in `0x44` or `0x49`.
  - At the pine near `(54, 87)`, about six pixels wide, the capture draws the sliver as a strip of 176 one to two pixels wide down 14 of the tree's rows (21 pixels); ours drew 2 pixels of it. The dark triangle is 55 pixels in the capture and 58 in ours.
  - `0x7571`, the flat filler `POLYZ` reaches ([`sod-vm.md`](../../../research/playone-exe/sod-vm.md) section 8.9), takes the bottom row minus the top row as its row count and loops while the decremented count is not negative (`dec word [0x10C6]; jns`), so it fills both the top and the bottom row; per row it fills `right − left + 1` pixels (`inc ax` at `0x75A5`) after clipping both ends. Both axes include both ends, so a polygon draws at least a pixel per row it spans however narrow it is. The edge builder's rounding of each row's ends (`0xC9D4`) was not read.
- **Verdict**: in this crop of tick 3301 the pines match the capture's in position (judged by eye at 8×; tick 3290 not compared), and part of the gap is the light sliver of each one, under a pixel wide (measured on one pine), which the GPU drops because it samples pixel centres where `PLAYONE` fills inclusive spans. `[Established]` for the filler's instructions (static), `[Bounded Observation]` for the pixel counts, `[Supported Inference]` that the inclusive spans are why the capture's slivers are a pixel or two wide. Placement outside this crop, and the issue's shading lead, were not examined further: the tree colours are the same indices in both images.
- **Lives in**: [`sod-vm.md`](../../../research/playone-exe/sod-vm.md) section 8.11; [`memory-map.md`](../../../research/playone-exe/memory-map.md) section 3.

## 2026-11-12: polygon outlines scored on the seven reference films

- **Question**: Does drawing each polygon's edges as one-pixel screen lines, so a polygon also covers the pixels on its outline, move the reference films toward the capture, and on which geometry should it apply?
- **Method**: Four temporary switches, each scored with `mise run sweep -- --no-build` on all seven films (RTX 4070 Laptop), then reverted. `DBG_POLY_EDGES=1`: in `tessellate.rs`, every filled polygon of every decoded shape also emitted its edges through `push_line`, interleaved with the polygon, so the world mesh's props carried them and terrain did not. `DBG_OUTLINE` in a new `stunt-render` step over the uploaded shape, which outlines every edge exactly one filled triangle of a mesh node uses: `1` on the per-frame shapes and the whole world mesh (terrain included), `2` on both but skipping terrain and ocean triangles, `3` on the per-frame shapes only. A scratch `eprintln!` reported the world mesh's size. `mise run frame -- --var` drew tick 3301 before and after. Track: evidence-backed (`0x7571`, previous entry).
- **Result**:

  | Film | Base | `POLY_EDGES=1` | `OUTLINE=1` | `OUTLINE=2` | `OUTLINE=3` |
  |---|---|---|---|---|---|
  | `CTRY` | 0.9015 | 0.9043 | 0.9035 | 0.9043 | 0.9022 |
  | `INTRO` | 0.8437 | 0.8455 | 0.8473 | 0.8462 | 0.8460 |
  | `LAND` | 0.8662 | 0.8662 | 0.8662 | 0.8672 | 0.8666 |
  | `BALLOON` | 0.8097 | 0.8133 | 0.8112 | 0.8143 | 0.8127 |
  | `TRAINTNL` | 0.8548 | 0.8574 | 0.8568 | 0.8576 | 0.8558 |
  | `BOMB` | 0.8129 | 0.8174 | 0.8182 | 0.8187 | 0.8134 |
  | `LOCATION` | 0.8098 | 0.8134 | 0.8139 | failed | 0.8089 |

  - `LOCATION`'s world mesh is 6,702,993 vertices and 7,486,710 indices; outlined it became 32,428,341 and 84,662,754. With `OUTLINE=2` its render failed with wgpu "Out of Memory" in the sweep and in two runs of `LOCATION` alone; `OUTLINE=1` rendered it in the sweep.
  - With `OUTLINE=3`, tick 3301's tree indices 172, 173, 175 and 176 cover 362, 545, 90 and 191 pixels of the 100 × 100 crop (capture 442, 669, 133, 227), and the pine near `(54, 87)` draws its sliver as 23 pixels of 176 (capture 21).
  - In `POLY_EDGES=1`, the per-tick worst movers include `INTRO` ticks 3235 to 3290, by 0.007 to 0.016, where our camera sits a few pixels off the capture's: the denser trees are drawn in the wrong place. At `LOCATION` 7679 a rotor blade's outline makes it draw longer than the capture's, and Gouraud body panels show their seams; at `LAND` 870 a ground marking's edge shows through a grass band.
- **Verdict**: `OUTLINE=3` adopted on the evidence-backed track: no film falls by more than 0.002 (`LOCATION` −0.0009) and `INTRO` rises by 0.0023. Outlining the world mesh scores higher on six films but multiplies its vertices about five times and ran a render out of memory, so it waits for a cheaper draw ([`sod-vm.md`](../../../research/playone-exe/sod-vm.md) section 10). The expected `gpu` tables in `references.toml` are updated from the committed change.
- **Lives in**: [`sod-vm.md`](../../../research/playone-exe/sod-vm.md) section 8.11.
