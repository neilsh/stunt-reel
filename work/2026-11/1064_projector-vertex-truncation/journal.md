# Journal: drawing vertices where PLAYONE's projector truncates them

## 2026-11-25: the world mesh slides in the horizontal plane, shapes in their facet's

`[Bounded Observation]`

- **Question**: Does the shipped form of [#1027](../1027_projection-truncation/journal.md#2026-11-24-the-shipped-projector-rounding-against-main), which slides each snapped vertex in its own facet's plane, adopt once the world mesh (terrain, ocean and props, scenery class 1 to 3) slides in the horizontal plane through the vertex, as `4` of #1027 did, while a shape's vertices keep their facet's plane?
- **Why this form**: `4` raised `balloon` by 0.0065 and failed `draw_order::a_decal_wins_over_its_base_near_and_far`, a shape's decal on a facet tilted about the vertical; the shipped form passes that test and lowers `balloon` by 0.0043.
  `[Hypothesis]`: the `balloon` loss is the river, a flat prop on sloped terrain, whose vertices slide in a horizontal plane while the terrain's facet slides in its tilted one, so their depth tie breaks; if so, giving the whole world mesh one plane (horizontal) restores it, and no shape's decal sits on the world mesh.
- **Track**: evidence-backed, offsets as in #1027 ([`sod-vm-lines-spans.md` § 8.14](../../../research/playone-exe/sod-vm-lines-spans.md#814-projected-points-are-truncated-toward-the-centre)): `0x9CF1`, `0x9D3A`, `0xAE67`.
- **Variants** (`DBG_PROJ`, not committed; the shader of `proto/1027-projector-rounding` at `f2e12e39` rebased on `main`, whose camera uniform no longer holds `inv_rotation_proj`, so the ray through the snapped pixel comes from the projection's rows): `0`, `main`'s projection (baseline); `1`, the shipped form; `2`, `1` with every world-mesh vertex's slide plane horizontal.
- **Target frames**: the four of #1027, `--target traintnl:12-12 --target bomb:331-331 --target location:683-683 --target balloon:540-540`.
- **Command**: `mise run sweep -- --var DBG_PROJ=0,1,2 --track evidence --record work/2026-11/1064_projector-vertex-truncation --topic world horizontal --images work/2026-11/1064_projector-vertex-truncation/images` with the targets above, on the GPU.
- **Result** (GPU, RTX 4070 Laptop; `main` at `16483bbb` with the uncommitted switch; figures in [`sweeps/world-horizontal.toml`](sweeps/world-horizontal.toml)): none adopts, `winner: none adopts (best DBG_PROJ=2: film-mean guard balloon -0.0024)`.

  | Variant | ctry | intro | land | balloon | traintnl | bomb | location |
  |---|---|---|---|---|---|---|---|
  | `0` (main) | 0.9385 | 0.8937 | 0.9248 | 0.9059 | 0.9107 | 0.8957 | 0.8863 |
  | `1` (shipped) | 0.9458 | 0.9083 | 0.9333 | 0.9016 | 0.9170 | 0.9070 | 0.8939 |
  | `2` (world horizontal) | 0.9440 | 0.9069 | 0.9311 | 0.9035 | 0.9163 | 0.9085 | 0.8967 |

  - `2` moves `balloon` from −0.0043 (`1`) to −0.0024 against `0`, so the world mesh's plane explains about 0.0019 of the loss; the other six films rise by 0.0055 to 0.0132 (under `1`, 0.0063 to 0.0146).
  - The guard fails by 0.0004, so the hypothesis is partly confirmed: the rest of `balloon`'s fall is not the world mesh's plane.

## 2026-11-25: facets near horizontal slide horizontally

`[Bounded Observation]`

- **Question**: Does `balloon` pass the guard when a facet close to horizontal, in the world mesh or a shape, slides in the horizontal plane through its vertices while a steeper one keeps its own plane?
- **Why**: [`4` of #1027](../1027_projection-truncation/journal.md#2026-11-24-the-projector-rounding-with-an-unsnapped-fallback) slid every vertex horizontally and raised `balloon` by 0.0065; a decal and its base, one plane, keep their tie under any plane they share, and the vertices of a near-horizontal facet leave its own plane little by sliding horizontally.
- **Track**: evidence-backed, as above.
- **Variants** (`DBG_PROJ`, not committed): `0`, `main`; `2`, as the entry above (the world mesh horizontal, every shape facet in its own plane); `3`, every facet of the world mesh or a shape whose normal is within about 26 degrees of vertical (|n.y| ≥ 0.9 |n|) slides horizontally, any other in its own plane; `4`, the same within 60 degrees (|n.y| ≥ 0.5 |n|).
- **Target frames**: as above.
- **Command**: `mise run sweep -- --var DBG_PROJ=0,2,3,4 --track evidence --record work/2026-11/1064_projector-vertex-truncation --topic "shape facets near horizontal" --images work/2026-11/1064_projector-vertex-truncation/images --target traintnl:12-12 --target bomb:331-331 --target location:683-683 --target balloon:540-540` on the GPU.
- **Result** (GPU, the same adapter; `main` at `16483bbb` with the uncommitted switch; figures in [`sweeps/shape-facets-near-horizontal.toml`](sweeps/shape-facets-near-horizontal.toml)): `3` adopts, `winner: DBG_PROJ=3 adopts (evidence, film means; target idx +0.0042 attribution; worst target frame -0.0185 traintnl:12; 327 frames down >0.005, listed) (noise floor +/-0.002; winner is ~within noise)`; the noise note is `3`'s margin over `2`.

  | Variant | ctry | intro | land | balloon | traintnl | bomb | location | mean |
  |---|---|---|---|---|---|---|---|---|
  | `0` (main) | 0.9385 | 0.8937 | 0.9248 | 0.9059 | 0.9107 | 0.8957 | 0.8863 | 0.9079 |
  | `2` | 0.9440 | 0.9069 | 0.9311 | 0.9035 | 0.9163 | 0.9085 | 0.8967 | 0.9153 |
  | `3` (26 degrees) | 0.9452 | 0.9066 | 0.9314 | 0.9052 | 0.9171 | 0.9073 | 0.8945 | 0.9153 |
  | `4` (60 degrees) | 0.9447 | 0.9069 | 0.9349 | 0.9107 | 0.9173 | 0.9066 | 0.8952 | 0.9166 |

  - `3` moves `balloon` to −0.0007 against `0`, inside the 0.002 the evidence track allows, and raises the other six films by 0.0064 (`traintnl`) to 0.0129 (`intro`); `2` to `3` recovers 0.0017 of `balloon`'s 0.0024, so the near-horizontal facets' plane explains most of what the world mesh's did not.
  - `4` scores higher on the mean (0.9166) and on `balloon` (+0.0048), but `ctry` and `bomb` sit 0.0005 and 0.0007 below `3`; a facet 60 degrees from horizontal moves further from the vertex's own plane than one 26 degrees from it, so `4` is left as an open threshold question in the note.
  - The worst movers are `balloon` 298 (−0.0572), `location` 2630 (−0.0421) and 6326 (−0.0392); `balloon` 298 was also `1`'s worst of #1027, and none of the movers was attributed.

## 2026-11-25: the world mesh and near-horizontal shape facets together

`[Bounded Observation]`

- **Question**: Does the form that combines the two rounds above, the whole world mesh sliding horizontally (`2`) and every near-horizontal shape facet sliding horizontally too (`3`'s threshold), adopt?
  It is the shader the implementation commits (`e5e4d689`), and it was not swept as such: `2` has the world mesh and `3` the threshold, each without the other.
- **Why**: `2` and `3` each recovered part of `balloon`'s fall against the facet-plane form (−0.0024 and −0.0007 against −0.0043), by different vertices.
- **Track**: evidence-backed, as above; the third and last round of the [loop's cap](../../../.agents/skills/running-unattended/loop-and-bounds.md#implementing-an-issue-and-bounding-rounds).
- **Variants** (`DBG_PROJ`, not committed): `0`, `main`; `1`, the shader as committed.
- **Target frames**: as above.
- **Command**: `mise run sweep -- --var DBG_PROJ=0,1 --track evidence --record work/2026-11/1064_projector-vertex-truncation --topic "world and shape facets horizontal" --images work/2026-11/1064_projector-vertex-truncation/images --target traintnl:12-12 --target bomb:331-331 --target location:683-683 --target balloon:540-540` on the GPU.

- **Result** (GPU, the same adapter; `main` at `16483bbb` with the uncommitted switch, `1` being `e5e4d689`'s shader; figures in [`sweeps/world-and-shape-facets-horizontal.toml`](sweeps/world-and-shape-facets-horizontal.toml)): `1` adopts, `winner: DBG_PROJ=1 adopts (evidence, film means; target idx +0.0046 attribution; worst target frame -0.0185 traintnl:12; 297 frames down >0.005, listed)`.

  | Variant | ctry | intro | land | balloon | traintnl | bomb | location | mean |
  |---|---|---|---|---|---|---|---|---|
  | `0` (main) | 0.9385 | 0.8937 | 0.9248 | 0.9059 | 0.9107 | 0.8957 | 0.8863 | 0.9079 |
  | `1` (shipped) | 0.9439 | 0.9069 | 0.9312 | 0.9068 | 0.9164 | 0.9085 | 0.8967 | 0.9158 |

  - Every film rises, `balloon` by 0.0009 and the others by 0.0057 (`traintnl`) to 0.0132 (`intro`); the world mesh's plane and the shape facets' plane each recovered part of `balloon`'s fall, and together they take it from −0.0043 under the facet-plane form to +0.0009.
  - The worst movers are `balloon` 298 (−0.0572 under `3`, the sweep's worst mover of the round before), `location` and `ctry` frames; the sweep lists 297 frames down by more than 0.005, none attributed.
  - Pictures (capture, `main`, `1`): the targets [`traintnl` 12](images/traintnl-12-world-and-shape-facets-horizontal.png), [`bomb` 331](images/bomb-331-world-and-shape-facets-horizontal.png), [`location` 683](images/location-683-world-and-shape-facets-horizontal.png) and [`balloon` 540](images/balloon-540-world-and-shape-facets-horizontal.png), and each film's worst mover, `-guard`, in the same folder.
- **Shipped as** `1`, with no switch (`e5e4d689`): `slide_normal` returns world up for a world-mesh vertex (`scenery_class` ≠ 0) and for a shape facet whose normal is within 0.9 of vertical.
  `draw_order::a_decal_on_a_near_horizontal_facet_wins_over_its_base_near_and_far` pins a decal on a facet 24 degrees from horizontal, beside the existing steep-facet decal test, the tile-on-terrain and actor-on-scenery tests, the ZLINETO test and `lines::a_polygon_within_one_pixel_draws_it_either_way`; all pass on the GPU.

## 2026-11-25: the shipped form on the canonical lavapipe

`[Bounded Observation]`

- **Question**: Do the shipped shader's scores on the canonical lavapipe agree with `3`'s on the GPU, and what do the pins become?
- **Command**: `mise run parity -- --software-only` on `e5e4d689` with `crates/` clean, in Ubuntu 24.04 under WSL (`llvmpipe (LLVM 20.1.2, 256 bits)`), then `mise run parity-repin -- --class lavapipe`.
- **Result**: against the pins of `4b5c69c` (`main`'s `crates/` is `4833af84`, so the pins lag it; the table below is a change since those pins, not since `main`):

  | Film | ctry | intro | land | balloon | traintnl | bomb | location |
  |---|---|---|---|---|---|---|---|
  | pinned | 0.9385 | 0.8937 | 0.9248 | 0.9059 | 0.9107 | 0.8957 | 0.8863 |
  | shipped | 0.9439 | 0.9069 | 0.9310 | 0.9067 | 0.9164 | 0.9080 | 0.8967 |

  - Every film rises on lavapipe, `balloon` by 0.0008; the GPU's `3` put `balloon` at −0.0007 against `main` (a different adapter and baseline, so the two are not one comparison).
  - The pins were repinned to `a160e577` (`git rev-parse e5e4d689:crates`) in `b60aba3a`.

## Handoff

- **Adopted**: the world mesh and near-horizontal shape facets slide in the horizontal plane, steeper shape facets in their own, on the pixel `PLAYONE`'s projectors truncate each vertex to ([`sod-vm-lines-spans.md` § 8.14](../../../research/playone-exe/sod-vm-lines-spans.md#814-projected-points-are-truncated-toward-the-centre)); the forms tried and not adopted are in its Ruled out.
- **Open**: the slide threshold (60 degrees, tried without the world-mesh rule, scored a higher mean and a higher `balloon` but a lower `bomb`); `parity_probe.py register` on #990's ticks, to see whether the backdrop's one-row shift is gone; the PR's evidence is the pictures of the third entry.
