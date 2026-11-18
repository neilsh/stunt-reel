# Journal: CTRY tick 871 replay

## 2026-11-18: the CTRY tick 871 explosion replayed through the image's tree

- **Question**: Which `SP_LEAF` does the `CTRY` tick 871 explosion's pending-list entry reach in the image's scenery tree, which planes separate it from the tower and the foreground hill, and does that order (over the tower, under the hill) follow?
- **Method**: static, film data plus the unpatched load image (`mise run unlzexe`; `mise run re-tool -- disasm` over `0x1E89..0x20A7` and `0x1AD8..0x1B88`).
  The slot and eye positions came from `FilmTimeline::sample(871.0)` on `corpus/stisldem/VAULT/CTRY.FLM` (a scratch example, not committed): slot 11, shape `0x0107`, at DOS `(−3192.69, −1.88, 2489.42)` m; eye at `(−3170.51, −2.89, 2493.34)`, looking at `(−4154.64, 41.88, 2322.00)`.
  A scratch walker (not committed) followed the draw walk from `SS:0` with `scene_tree.tree_segment`, splitting the one-entry list as the handlers do: `SP_XPLANE`/`SP_ZPLANE` (`0x1EF2`) compare the plane's world coordinate (`[0x2A6A+bx] + [0x49F4+bx] + [bp+6]`) with the slot's high word, child `+2` taking the greater side and `+4` the lesser, the eye's side walked last; a cut slot with no bucket goes to the eye's side (`0x1F46`).
  `SP_HSLOPE`/`SP_VSLOPE` (`0x200B`, `0x2059`) put a point on `+2` when `(a × slope × 2 >> 16) + coord ≥ b`.
  The `SP_1NODE` gate was taken as near when the view depth is under `2 × splitdist` (default lens, [`lod.md` § 2.2](../../../research/playone-exe/lod.md#22-how-the-lens-scales-the-projection)); the five on the list's path were each at most 13% of that.
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
