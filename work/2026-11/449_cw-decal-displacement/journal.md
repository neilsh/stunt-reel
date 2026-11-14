# Journal

## 2026-11-13: why BOMB's truck flips, and decals stacked in stream order

- **Question**: The first round (released claim on [#449](https://github.com/neilsh/stunt-reel/issues/449)) moved each `[I5]` decal toward its front (`FrontFace::Cw`) side and lost 0.0025 on `BOMB` at ticks 2058-2179, where the truck `0x4142` turned its white side panel dark blue. Which decal-to-base match flips, and does matching on front normals with decals stacked in stream order keep `BOMB` while fixing the direction?
- **Method**: On `ba11061e`, a temporary dump in `identify_coplanar_decals` printed, for `0x4142` in `BOMB.ALL` (`stuntreel shape-views --shapes 4142`), each polygon's palette, stored normal, front normal and the earlier polygon it matched. Then one sweep on the evidence track over `DBG_DECAL_FRONT`:
  - `0`: today (stored normals, matched against the already displaced earlier polygons, `eps` along the stored normal);
  - `2`: front normals for matching and displacement (the triage brief's option 1), still matched against displaced polygons;
  - `3`: as `2`, matched against the undisplaced polygons;
  - `4`: as `3`, each decal one level above the highest earlier coplanar polygon it overlaps, displaced `level * eps` toward its front (option 2, stream-order stacking).

  Track `evidence`: `POLYZ` (`0x9B78`) fills through the flat filler `0x7571`, which draws a row only where the vertices run clockwise on screen (`jl` at `0x75A1`) and stores pixels with no depth test, so within a shape a later coplanar polygon covers an earlier one ([`sod-vm.md`](../../../research/playone-exe/sod-vm.md) § 8.9, the pines paragraph, and the `0x7511` row). Flags, quoted before the run, the target for attribution only: `mise run sweep -- --var DBG_DECAL_FRONT=0,2,3,4 --track evidence --target bomb:2058-2179 --images work/2026-11/449_cw-decal-displacement/images --topic decal-stack`.

- **Result**: The dump shows why the first round flipped the truck. `0x4142`'s side section paints `137` (`0x0BCC`), `59` (`0x0BDC`), then the `224` disc (`0x0BEC`). `137` matches a wheel disc on the same side plane (`0x0A76`) and so is itself a decal, displaced 1 mm. `main` then compares `59` with the *displaced* `137`, 1 mm off its plane, finds no match and leaves `59` a base polygon. Moving decals inward (today's stored normal) hid `137` behind `59`; moving them outward (the first round) put `137` in front, so the panel turned `137`. The disc's visible copy (front normal outward) matched nothing under stored normals and its culled copy did; front-normal matching swaps them. Sweep (`build/scratch`, RTX 4070 Laptop GPU), film mean SSIM, `0` / `2` / `3` / `4`:

  | Film | `0` | `2` | `3` | `4` |
  |---|---|---|---|---|
  | CTRY | 0.9049 | 0.9048 | 0.9055 | 0.9071 |
  | INTRO | 0.8469 | 0.8469 | 0.8468 | 0.8467 |
  | LAND | 0.8666 | 0.8666 | 0.8695 | 0.8696 |
  | BALLOON | 0.8137 | 0.8137 | 0.8137 | 0.8137 |
  | TRAINTNL | 0.8572 | 0.8572 | 0.8580 | 0.8597 |
  | BOMB | 0.8219 | 0.8192 | 0.8242 | 0.8234 |
  | LOCATION | 0.8161 | 0.8162 | 0.8164 | 0.8163 |

  Winner line: `DBG_DECAL_FRONT=4 adopts (evidence, film means; target idx +0.0108 attribution; worst target frame +0.0006 bomb:2080; 69 frames down >0.005, listed)`. `2` reproduces the first round's `BOMB` fall; `3` restores `59` but its decals, all 1 mm out, tie with each other and the tie breaks by depth rounding, not draw order: the disc lost to `59` in a notch and the island to the disc (worst target frame -0.0885), so stacking (`4`) is what keeps the stream's order. The 69 frames of `4` that fall by more than 0.005: `LOCATION` 4709 (-0.0205) and its neighbours, where `0x037C`'s field (`169`, level 2) loses to its border (`50`, level 1) about 100 m from the eye: with `Depth24Plus` and a 0.5 m near plane one depth step there is a few millimetres, so 1 mm levels do not separate (5 cm levels in a probe restored the field). `LAND` 573 and 518-562 (-0.013 to -0.010), where the aircraft's shadow, lifted 1 mm (`scene.rs`), now lies under runway decals at levels 2 and above, while the runway itself turns the capture's grey. `BOMB` 1100-1900 and 2800-2900 (about -0.006 each), a distant town whose stacked decals fight at the same depth resolution. `INTRO` 1299-1343 and `TRAINTNL` 1024, small markings, not inspected one by one.
- **Verdict**: `4` adopted by the film-mean branch of the evidence track. The falls above are known costs of geometric levels, examined in the next entry.
- **Lives in**: [`world-scene.md`](../../../research/playone-exe/world-scene.md) section 6.6.

## 2026-11-13: stack a decal only on polygons whose area it covers

- **Question**: The previous entry's adopted variant stacks a decal one level above every earlier coplanar polygon whose *bounding box* it meets, so edge-adjacent decals (two triangles of one marking, stripes side by side) climb levels they never needed: up to level 20 (2 cm) in `LOCATION.ALL`, 8 in `BOMB.ALL` and `LAND.ALL`. Does stacking only on polygons whose area the decal really overlaps keep the gains with lower stacks, and recover the guard falls of the previous entry (`LAND` 573, `LOCATION` 4709)?
- **Method**: On `ba11061e` plus the previous entry's change, behind `DBG_DECAL_FRONT`: `0` is `main`, `4` the previous entry's bounding-box stacking, `6` stacking only on earlier coplanar polygons that share area with the decal by more than `1e-4` m (no separating axis among the two polygons' edge normals, projected into the plane). A polygon that only touches its matches is still a decal, at level 1. Level histogram with `6`: `LOCATION.ALL` up to 15, `LAND.ALL` up to 2, `BOMB.ALL` up to 4. Track `evidence`, the same rule as the previous entry (the filler covers only the pixels it fills). Flags, quoted before the run, targets for attribution only: `mise run sweep -- --var DBG_DECAL_FRONT=0,4,6 --track evidence --target bomb:2058-2179 --target land:518-573 --target location:4699-4819 --images work/2026-11/449_cw-decal-displacement/images --topic decal-overlap`.
- **Result**: Film mean SSIM, `0` / `4` / `6`:

  | Film | `0` | `4` | `6` |
  |---|---|---|---|
  | CTRY | 0.9049 | 0.9071 | 0.9070 |
  | INTRO | 0.8469 | 0.8467 | 0.8469 |
  | LAND | 0.8666 | 0.8696 | 0.8695 |
  | BALLOON | 0.8137 | 0.8137 | 0.8137 |
  | TRAINTNL | 0.8572 | 0.8597 | 0.8597 |
  | BOMB | 0.8219 | 0.8234 | 0.8250 |
  | LOCATION | 0.8161 | 0.8163 | 0.8164 |

  Winner line: `DBG_DECAL_FRONT=6 adopts (evidence, film means; target idx +0.0307 attribution; worst target frame -0.0205 location:4709; 21 frames down >0.005, listed) (noise floor +/-0.002; winner is ~within noise)`; the noise remark compares `6` with `4`, not with `main`. 21 frames fall by more than 0.005, against 69 for `4`. `LOCATION` 4709 (-0.0205), 4809-4819, 3191-3279, 2212, 2740, 4170 and 4599-4764 are `0x037C`-like far stacks past the depth buffer's resolution (previous entry). `LAND` 573 (-0.0110) and 518 (-0.0094) are the aircraft's shadow under runway decals, while the runway turns the capture's grey. `BOMB` 2048 (-0.0121) is the edge frame before the truck shot, where our camera sits off the capture's; `BOMB` 1167 (-0.0086) is the distant town. `INTRO` 2982 and 1156 and `TRAINTNL` 1024 (about -0.006 each) are small markings. Pictures of the winner: `images/*-decal-overlap*.png`.
- **Verdict**: `6` adopted by the film-mean branch of the evidence track, in place of `4`. The far-stack and shadow costs stay open in [`world-scene.md`](../../../research/playone-exe/world-scene.md) open question 6.
- **Lives in**: [`world-scene.md`](../../../research/playone-exe/world-scene.md) section 6.6, [`SPEC.md`](../../../docs/SPEC.md) `[I5]`.
