# Journal: LOCATION's stadium infield against the ground

## 2026-11-18: the infield, the plaza under it and the order PLAYONE paints them

- **Question**: Is `LOCATION`'s stadium infield (index 169) coplanar with the index-14 ground our render draws over it at ticks 2586 to 2872 ([#651](https://github.com/neilsh/stunt-reel/issues/651)), and how does `PLAYONE` come to paint the infield on top?
- **Method**: static reads only, no render.
  `stuntreel sod-trace` over every shape of the `vault-location` capture's `LOCATION.ALL` (`all_sha256` `4a427bdd…`), kept those that run `COLOR 0x00A9`, and read the headers of `0x0265` and `0x064A` from the archive.
  `stuntreel export-gltf --shape 0x0265` and `--shape 0x064A` for the vertex heights our VM gives (header lift included).
  `scene_tree.placements` and a scratch walk of the unpatched image's tree (`build/re/playone.img`, `scene_tree.tree_segment`) that records each leaf's path from the root; `scene_tree.parse_map_bin` with the image's anchor table and `covers` for the `MAP.BIN` polygon under the stadium.
  iced-x86 over image `0x2205..0x2245` (the `SP_LEAF` lift) and `0x2150..0x2178` (the `SP_1NODE` stand-in's).
  The film's scene at tick 2586 (`export-gltf --film`) for the eye.
- **Result**:
  - **The infield is `0x0265`'s first polygon**, an 8-gon (`0x06E4 COLOR 0x00A9`, `0x06E8 POLYZ 0008 …`), placed by the tree's `SP_LEAF` at `0x6F54` at tree `(-7128, 0, 2560)`, our `(7128, 0, 2560)`, with stand-ins `0x026B` (`SP_1NODE` `0x6E94`) and `0x026A` (`0x6E9E`) at the same point.
    Within 400 m no other placed shape runs `COLOR 0x00A9` but the football field `0x037C` (stand-ins `0x037D`, `0x0386`), 206.5 m away.
    At tick 2586 the eye is at our `(7195.7, 30.0, 2507.2)`, 86 m from the stadium's centre in plan and 30 m up.
  - **The index 14 is a prop, not a `MAP.BIN` leaf.**
    `MAP.BIN` record 1 (colour 195, all six anchors at height 0, tree leaf `0x036C`) is the ground polygon under the stadium; no colour-14 record covers it (records 0, 98, 101 and 131 are elsewhere).
    The 14 is `0x064A`, a flat 10-gon about 384 m across (`IPG` cube `dx = dz = 0x17FB`, `dy = 0x009F`; `0x0362 COLOR 0x000E`, `0x0366 POLYZ 000A …`), placed at tree `(-7040, 0, 2624)`, which covers the stadium.
  - **Heights, exact.**
    `0x0265`: `ground_y_offset` 2993, `scale_index` 8 (2^-8 m per unit), `IPG 0000 1FF3 0BB3 1FF3 1800`: every infield vertex is a midpoint of the cube's bottom corners, raw `y = +2995` down, so `-2995/256 + 2993/256 = -2/256 = -0.0078125` m in our axes.
    `0x064A`: `ground_y_offset` 158, `scale_index` 5 (2^-5 m), cube `dy` 159: `(-159 + 158)/32 = -0.03125` m.
    Both shapes' placements have `y = 0` on their path.
    `export-gltf` gives the same: every 169 vertex of `0x0265` at `y = -0.0078125`, `0x064A` at `-0.03125` (at some vertices 1 mm higher, the exporter's decal lift `EPSILON_DISPLACEMENT`, which the IR does not carry); `0x0265` reaches up to `9.497` m, so it is no flat prop.
  - **`PLAYONE`'s lift is exact.**
    `0x2219 mov bx,[es:6]; neg bx; mov cl,[es:8]; mov dx,bx; sar dx,cl; sub cl,0x10; neg cl; shl bx,cl; add bx,[0x49F6]; adc dx,[0x49F8]`: `DX:BX` is `-ground_y_offset << (16 - scale_index)` as one 32-bit 16.16 value (`DX` its high word, `BX` its low), so the lift is `-ground_y_offset / 2^scale_index` m with no truncation for `scale_index <= 16`.
    `0x2160` (`SP_1NODE`) computes the same into `BP:BX`.
    So the source heights are the ones above: the infield lies 7.8125 mm below the ground plane and 23.4375 mm above the plaza.
  - **Our world IR.**
    `0x064A` is flat (one height in the IR) and lies within 0.1 m of record 1, so `ground_decal_vertices` snaps it to `y = 0`, and `push_prop_mesh` puts it in the `WORLD_GROUND` pass (`Always`, depth write).
    `0x0265` is not flat, so it is not snapped; its infield, 7.8125 mm off `y = 0` (the ground pass takes only triangles within 1e-4 m), stays in the base pass and must pass `Less` against the plaza drawn 7.8125 mm above it.
    The snap that lets the plaza beat record 1 thus moves the plaza above the infield, which in the source lies 23.4375 mm above it.
    An exact depth test draws the plaza; #595's depth gaps (3.2e-6 and 2.9e-6, opposite signs, near 0.994) are about six times the at most `0.5 / 85² × 0.0078125 = 5.4e-7` this offset gives at 85 m (near plane 0.5 m), so the f32 vertex-stage error #636 removed flipped the tie, not depth precision (inferred); after #636 both backends draw the plaza at the ticks it measured, as the IR says.
  - **The paint order.**
    The two leaves' paths from the root share every node down to `SP_2NODE` `0x6BFC` (under the `SP_1NODE` `0x6BF2`, `obj` 0, `ext` 303, `splitdist` 2500): its `ptr` is the `SP_LEAF` `0x6C02` of `0x064A`, and `0x0265`, with both stand-ins, is in its `next` chain (through `XPLANE` `0x6C06`, `0x6D36`, `0x6E7C` and the stand-in nodes).
    `SP_2NODE` (`0x1EC0`) visits `ptr`, then `next`, with no eye test, so `PLAYONE` paints the plaza, then whichever of `0x0265`, `0x026A` and `0x026B` it draws, wherever the eye is.
    Record 1's leaf `0x036C` is in the root `SP_2NODE` `0x0000`'s `ptr` subtree (through the `SP_GROUND` chain `0x008C` … `0x01A4`), and both props in its `next` subtree (`0x0622`), so the ground is painted before both.
    Within `0x0265` the infield is the first polygon after `IFVIS 0200`.
- **Verdict**: control (no render change).
  Not coplanar: 7.8125 mm below the ground in the source and in our IR, 23.4375 mm above the plaza in the source, 7.8125 mm below it in our IR.
  `PLAYONE` paints it on top by walk order, ground then plaza then stadium, fixed by two `SP_2NODE`s.
  The fix this points to for #651 is the ground pass: a face of a non-flat prop lying within the snap tolerance of the ground plane drawn in the `WORLD_GROUND` walk-order pass after the plaza; a depth rule draws the plaza (it is above the infield in our IR), and the decal pass takes a face coplanar with an earlier face of its own shape, while the infield is `0x0265`'s first face.
- **Lives in**: [`world-scene.md`](../../../research/playone-exe/world-scene.md) section 3.1 and Ruled out, [`world-scene-residuals.md`](../../../research/playone-exe/world-scene-residuals.md) section 6.8, Ruled out and Open questions, [`lavapipe.md`](../../../research/parity/lavapipe.md) section 5, [`memory-map-main.md`](../../../research/playone-exe/memory-map-main.md).
