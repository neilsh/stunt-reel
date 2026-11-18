# Journal: CTRY tick 871 replay

## 2026-11-18: the CTRY tick 871 explosion replayed through the image's tree

- **Question**: Which `SP_LEAF` does the `CTRY` tick 871 explosion's pending-list entry reach in the image's scenery tree, which planes separate it from the tower and the foreground hill, and does that order (over the tower, under the hill) follow?
- **Method**: static, film data plus the unpatched load image (`mise run unlzexe`; `mise run re-tool -- disasm` over `0x1E89..0x20A7` and `0x1AD8..0x1B88`).
  The slot and eye positions came from `FilmTimeline::sample(871.0)` on `corpus/stisldem/VAULT/CTRY.FLM` (a scratch example, not committed): slot 11, shape `0x0107`, at DOS `(−3192.69, −1.88, 2489.42)` m; eye at `(−3170.51, −2.89, 2493.34)`, looking at `(−4154.64, 41.88, 2322.00)`.
  A scratch walker (not committed) followed the draw walk from `SS:0` with `scene_tree.tree_segment`, splitting the one-entry list as the handlers do: `SP_XPLANE`/`SP_ZPLANE` (`0x1EF2`) compare the plane's world coordinate (`[0x2A6A+bx] + [0x49F4+bx] + [bp+6]`) with the slot's high word, child `+2` taking the greater side and `+4` the lesser, the eye's side walked last; a cut slot with no bucket goes to the eye's side (`0x1F46`).
  `SP_HSLOPE`/`SP_VSLOPE` (`0x200B`, `0x2059`) put a point on `+2` when `(a × slope × 2 >> 16) + coord ≥ b`.
  The `SP_1NODE` gate was taken as near when the view depth is under `2 × splitdist` (default lens, [`lod.md` § 2.2](../../../research/playone-exe/lod.md#22-how-the-lens-scales-the-projection)); the five on the list's path were each at most 13% of that gate (2 × splitdist), by absolute depth.
  The entry's extent is `([es:4] >> [es:8]) + 1` (`0x1AF3..0x1AFE`); the loaded segment is the `.SOD` file two bytes on, so for `MODEL_0107.SOD` (`bounding_size` `0x4000`, `scale_index` `0x0A`) it is 17.
  The shapes' headers came from `CTRY.ALL` and `SUPERSET.ALL`; the picture is [#407's `ctry_871.png`](../407_sprite-draw-order/images/ctry_871.png).
  Nothing was run in DOSBox.
- **Result**:
  - The list reaches leaf `0x7BE0` (shape `0x0262` at `(−3180, 0, 2488)`, view depth 10.4 m, left of centre), where the explosion (view depth 22.5 m) is the larger depth and is drawn just before the object.
  - The two placements of leaf `0x7C14` (shape `0x03DD`, at `(−3191, 0, 2485)` and `(−3191, 0, 2491)`, view depths 21.7 and 20.7 m, 4.7 and 2.3 m from the explosion) lie on the far side (`+4`, `x < −3188`) of the `SP_XPLANE` at node `0x7BBE` (`x = −3188`).
    The explosion's centre is 5 m on that far side too, but its extent 17 crosses the plane, so with no bucket it goes to the eye's side (`+2`), which is walked after the far side: both `0x03DD` placements are drawn before it.
  - Planes on the list's path within 17 m of the slot, all of which the extent crosses: `x = −3200` (`0x7A5C`), `z = 2496` (`0x7A64`), `z = 2480` (`0x7BB6`), `x = −3188` (`0x7BBE`), `z = 2484` (`0x7BC6`); each sends the entry to the eye's side.
  - With extent 1 (a centre-only split), the list would instead reach leaf `0x7C14`, the `0x03DD` placement at `z = 2485`, on the far side of `x = −3188`.
  - In the capture, the explosion is drawn over the tan tower beside it and under the large dark-green hill at the left; `0x03DD` (beside the explosion, 20.7–21.7 m) matches the tower and `0x0262` (10.4 m deep, to the left) matches the hill, by position.
  - `MODEL_0262.SOD` has a collision-box list (header word 8 = `0x0438`); `MODEL_03DD.SOD` has none (word 8 = 0).
- **Verdict**: the replay gives tower, explosion, hill: the order the capture shows.
  The tower is separated from the explosion by the plane `x = −3188` (node `0x7BBE`), and the hill is ordered against it by the depth compare of the leaf both reach (`0x7BE0`), not by a plane.
  Not checked: whether slot 11 is probed (`SIF_MOVES`) and recorded a bucket at `0x0262` (with one bucket a cut plane sends the entry to its centre's side, the extent-1 path); the exact `SP_1NODE` gate; that `0x03DD` and `0x0262` are the tower and the hill beyond position; a run.
- **Lives in**: [`scene-walk-actors.md` § 4](../../../research/playone-exe/scene-walk-actors.md#4-ctry-tick-871).

## 2026-11-18: which stock shapes carry buckets, counted statically

- **Question**: Which of the game's shapes have a collision box coded 1 to 7, and does each one's display list run `OP_IPG` type 4 with the matching `w = 2 × code`?
- **Method**: static.
  `mise run re-tool -- xref 0x09FC` and `-- disasm 0x28A0 0x2F40` on the unpatched load image.
  The DGROUP tables were read at image `0xD510`, where the draw walk's table `0x554` holds its handlers (`0x1E89`, `0x20A7`, …); an earlier read at `0x163D0` found zeros, which was the wrong base.
  `DS:0x09FC` gives types 0, 2 and 4 to `0x28DB`, `0x2979` and `0x2A96`, which advance `SI` by `0xC`, `0x10` and `0xC`, as the [`memory-map.md`](../../../research/playone-exe/memory-map.md) row for `0x09FC..0x0A13` already said.
  A scratch script (not committed) walked every shape of `SUPERSET.ALL` (`mise run superset-all`; `all_archive.archive_chunks`, first word `0x000C`) from the word at file offset 8, as `0x2886` walks the segment word `+0xA`.
  - Types 0 and 4 lead to a nested list at `+0xA` (`0x2922`, `0x295D`, `0x2AD3`, `0x2B0E`); type 2 carries the code word at `+0xE`, which leads to a nested list when above 8.
  - Every nested list was walked as if in the first context `0x09FC`, the walk an actor with no collision list of its own makes (`DI = 0`, set at `0x285B`). With an actor list, the nested lists go through the actor's records (`0x0A02`, `0x0A08`, `0x0A0E`) and come back to `0x09FC` only after an actor record overlaps (`0x2BD9`, `0x2CA2`, `0x2DAA`, `0x2E74`, `0x2F3A`); a second pass counted the coded boxes in each top list alone.
  - The script took the pointer as file offset 2 lower, then 0, then 2 higher. Only 2 lower ends every list at `0xFFFF`.
  For each shape with a code 1 to 7, `./target/release/stuntreel sod-trace --archive target/linked/superset/SUPERSET.ALL --shape <id>` listed the `IPG 0004 w` steps of its traced path, and a scan of the shape's words from byte `0xA` listed every `0x0063, 0x0004, w` triple.
  `scene_tree.placements(scene_tree.tree_segment(image))` on the load image gave the shapes placed at an `SP_LEAF`.
  FreeFlight's `SIDATA/SCENERY1..6.RES` were compared with the game's `RES/` by SHA-256.
  Nothing was run in DOSBox.
- **Result**:
  - 2,516 shapes, 1,279 with a collision-list pointer. Every list ends at `0xFFFF` when the pointer is read as file offset 2 lower; none does at the file offset itself or 2 higher. The lists hold 333 records of type 0, 3,781 of type 2 and 173 of type 4, nested lists included.
  - 83 shapes have a box coded 1 to 7. All 83 have a code-1 box, and codes 2 to 7 appear in 32, 21, 12, 8, 4 and 2 shapes.
  - In the top lists alone: 68 of the 83 shapes have a coded box, 51 have a code-1 box, and codes 2 to 6 appear in 18, 7, 4, 4 and 2 shapes. The other 15 have coded boxes only in nested lists.
  - 75 of the 83: the traced path runs `OP_IPG` type 4 with `w` for each of the shape's codes, and with no other `w`.
  - The other 8 have a code whose `w` no type-4 triple in their bytes carries: `0x024A` (`w` 2 and 4), `0x02DE` (6 and 8), and `0x03FD`, `MISCELLA.RES`'s `0x3F08`, `0x3F18`, `0x3F1E` and `0x3F24`, and `STRUCTUR.RES`'s `0x4059` (2).
  - 77 shapes hold a type-4 triple, all among the 83, so no shape has a bucket without a coded box.
  - The image's tree places 72 of the 83 at an `SP_LEAF`, `0x024A`, `0x02DE` and `0x03FD` among them: 846 of its 68,035 distinct leaf placements.
  - FreeFlight's six `SCENERY*.RES` are byte-identical to the game's, so they add no shapes.
- **Verdict**: buckets are common in the stock shapes that carry coded boxes. 75 of 83 trace a bucket for every code, and none traces a bucket without its code. Three tree shapes and five others have a code whose bucket their display list never runs.
  For an actor with a collision list of its own, a nested list's codes count only once one of its records overlaps; 15 of the 83 shapes have coded boxes only there.
  Not checked: the display-list branches `sod-trace` does not take; the shapes of `corpus/siarchive` beyond FreeFlight (`local-windows`); whether a probe ever records the missing `w`.
- **Lives in**: [`scene-walk-actors.md` § 5](../../../research/playone-exe/scene-walk-actors.md#5-which-shapes-carry-buckets).
