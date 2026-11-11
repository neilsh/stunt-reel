# Journal: the OP_TAP shapes and their anchors

## 2026-11-11: how OP_TAP places its points

- **Question**: Does our decode resolve `OP_TAP` anchors the way `PLAYONE` does ([#254](https://github.com/neilsh/stunt-reel/issues/254))? `vm.rs` wrote each anchor's raw `(-x, -y, z)` into the register as shape units, and the world then added the tree's placement.
- **Method**: `mise run disasm` over the handler `0xAD88..0xAE66`, its transform `0xAE67..0xAF30`, the light setup `0x9100..0x9130`, the scene walk's object path `0x2194..0x2290` and the normaliser `0x31CF..0x3239`. `mise run xref` for `0x806E`, `0x8084` and `0x0EC0`. Base `ffec64b`.
- **Result**:
  - The handler loads the anchor's cached 32-bit position, shifts it right by `16 - [0x806E]` and subtracts `[0x8084..0x8088]` (`0xADAC..0xADF5`). On a stale stamp, `0xAE67` first computes the position as `0x80C0 · anchor + [0x41D4]`.
  - The scene walk normalises the object's 32-bit view position at `0x31CF`, which returns 16-bit words and a shift `CL`. `0x21B2..0x21BC` stores the words, rotated by `0x0824:06B0`, at `[0x8084..0x8088]`. The light setup `0x9100`, called from `0x21F9`, stores `CL` at `[0x806E]` (`0x9113`). So a register is the anchor less the object's origin, in the units `VECTORS` points are shifted to.
  - The cache stamp is per frame, and anchors 156, 157 and 160 are each tapped by two shapes. So the cached position cannot depend on the object, and `0x80C0`/`0x41D4` are the camera's (inference).
  - In the shape's frame, an unrotated shape placed at `p` with lift `ground_y_offset >> scale_index` therefore gets `(anchor - p) << scale_index - ground_y_offset`. Our decode used the anchor's metres as shape units and ignored `p`. At scale 6 that shrank each tapped point 64 times toward the island origin and then moved it by the placement, which explains the 3 to 197 m heights and the -13 to +233 m misses of the issue.
- **Verdict**: control. We did not resolve the anchors as `PLAYONE` does. `vm.rs` now writes the anchor in shape units less the lift. `world.rs` (`anchored_models`) decodes each TAP shape again against the anchor table less its placement, since some streams build a point from the origin itself (`0x0403`: `CLRV; SUBV 0`; `0x0208`: `CLRV; PUTV`). Tests: `test_tap_points_land_on_their_anchors_in_island_metres`, `test_anchored_models_load_tapped_points_less_the_placement`.
- **Lives in**: [`sod-vm.md` § 4](../../../research/playone-exe/sod-vm.md#4-register-side-effects), [`memory-map.md`](../../../research/playone-exe/memory-map.md) § 3.

## 2026-11-11: what the 14 TAP shapes are

- **Question**: Resolved as `PLAYONE` resolves them, are `SCENERY3.RES` #1, 2, 5 and 6 (`0x0402`, `0x0403`, `0x0406`, `0x0407`) the flat airfield tiles that [`world-scene.md`](../../../research/playone-exe/world-scene.md) section 3 named by colour? If so, ADR 0035's decal rule should take them.
- **Method**: A scratch script walked the image's scene tree (`scene_tree.placements`) for each TAP shape's placement. It replayed each stream from `stuntreel sod-trace` on `SUPERSET.ALL` with the `TAP` rule above and `ANCHORPT.DAT`, which equals the image's table at every anchor used. It then listed the `MAP.BIN` patches (`scene_tree.parse_map_bin`) that hold each anchor.
- **Result**: The tree places each of the 14 shapes once. Every one has `ground_y_offset` 0 and scale 6, except `0x0204`, `0x0405` and `0x0407`.
  - `0x0402` at `(1432, 78, 3304)` (x, height, z): `(1216, 0, 3296)`, `(1648, 155, 3312)`, `(1648, 1, 3312)`.
  - `0x0406`: `(1648, 155, 3312)`, `(1984, 0, 3328)`, `(1648, 1, 3312)`.
  - `0x0403`: `(1120, 0, 3872)`, `(1538, 196, 3906)`, `(1538, 0, 3906)`. `0x0407`: `(1538, 196, 3906)`, `(1792, 0, 3968)`, `(1538, 0, 3906)`.
  - `0x0404`: `(1059, 0, 4448)`, `(1427, 293, 4506)`, `(1427, 0, 4506)`. `0x0408`: `(1427, 293, 4506)`, `(1633, 0, 4512)`, `(1427, 1, 4506)`.
  - `0x0405`: `(1835, 82, 2301)`, `(2047, 0, 2305)`, `(1835, 0, 2301)`.
  - `0x0202`, `0x0203`, `0x0205`, `0x0207`: x constant, peaks 58, 115, 100 and 93 m. `0x0206` and `0x0208` (60 and 93 m) lie on one line in plan.
  - `0x0204`: four triangles over anchors 14 (115 m), 185 (0 m), 193 (148 m) and its origin at `(1280, 0, -6592)`.
  - The `0x04xx` anchors are corners of `MAP.BIN` hill patches 105–123, coloured 192–198, which are the shapes' own `0xC0`–`0xC6`.
- **Verdict**: rejected, for the tile reading. The four shapes are vertical, two-sided triangles from a hill's foot to its ridge, not flat tiles, so ADR 0035's rule rightly leaves them out. Their colours matched the airfield tiles' only because the hill patches share the range. The shapes are drawn as `PLAYONE` places them; no decal change.
- **Lives in**: [`sod-vm.md` § 5](../../../research/playone-exe/sod-vm.md#5-hill-fins), [`world-scene.md` § 6.2](../../../research/playone-exe/world-scene.md#62-a-rule-for-ground-lying-props).

## 2026-11-11: rescoring both films

- **Question**: Does loading the `OP_TAP` anchors less the shape's origin change either reference film?
- **Method**: `mise run parity` at `ffec64b` without the change, then `mise run parity -- --films ctry,intro` with it, in a cloud session on lavapipe (Mesa llvmpipe, no GPU). `stuntreel parity --compare --compare-test` scored the new render against the old one. A temporary `eprintln!` in `build_world`, removed before the commit, listed which TAP shapes the scene walk places.
- **Result**: Both films are unchanged at every scored frame. `CTRY` stays 0.8967 SSIM, IoU 0.9897, index agreement 0.901 (114 of 121 scored). `INTRO` stays 0.8339, IoU 0.9856, index agreement 0.831 (209 of 347 scored). The verdict line reads `changed 0/121` and `changed 0/347`. On `CTRY` the walk places no TAP shape: each lies under an `SP_1NODE` whose far stand-in our path-distance rule draws instead. On `INTRO` it places `0x0402`, `0x0403` and `0x0404`, which now decode to their fins (`0x0402`: from `(-216, -78, -8)` to `(-216, 77, 8)` about its placement). Neither the old misplaced points nor the fins reach a scored pixel. These are lavapipe scores (`research/parity/lavapipe.md`), so they are provisional; no GPU run was made.
- **Verdict**: control. The change is kept because it follows the handler (section 4 of `sod-vm.md`), not for a score. No expected score changes.
- **Lives in**: [`world-scene.md`](../../../research/playone-exe/world-scene.md) open question 3.
