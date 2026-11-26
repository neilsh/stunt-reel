# Journal

## 2026-11-26: a shape's primitives at their placement's depth, one rank step apart, in list order

`[Bounded Observation]`

- **Question**: does a GPU form that draws a shape's `SPHERE`s, and the polygons around them, in list order, while the shape still depth-tests against other objects, raise the reference films' scores, and does it conflict with the SPEC § 2.1 non-goal on a painter?
- **Track**: heuristic.
  The rule behind it (a shape's primitives paint in list order, [`render-model.md`](../../../research/parity/render-model.md) § 2) is read in [#1030](../1030_close-shape-order/journal.md#2026-11-24-list-order-explains-the-bomb-trees-not-the-canyon-rock) off a CPU painter checked against the capture, not cited at an image offset for this form.
- **Form** (`DBG_SPHERE_ORDER`, not committed; the diff is [`switches/DBG_SPHERE_ORDER.diff`](switches/DBG_SPHERE_ORDER.diff), written against `main` at `25eb9586`):
  - The decoder marks each `OP_SPHERE`'s 20 faces.
    A shape holding one gives each primitive a list-order rank, 1 to 255, in the vertex's padding byte: a sphere's 20 faces share one rank, every other polygon has its own.
    The weld key includes the rank.
  - A baked world prop's vertex carries its placement's origin in the apex stream; a shape drawn in place uses its model origin.
  - The vertex shader sets a ranked vertex's depth to its origin's depth plus 4.8e-7 (8 steps of `Depth24Plus`) times its rank, so a later primitive is nearer than an earlier one and a shape is still tested against other objects at its origin's depth.
    The compare stays `Greater`, so no pipeline changes.
    A corner an outline collapses to the screen centre (a back-facing polygon's, and a perfdisk-skipped disc's) keeps its own depth.
- **Target frames** (the issue's): `--target bomb:2070-2179 --target bomb:2289-2388`, the two ranges that hold ticks 2080 and 2300.
- **Command** (GPU, RTX 4070 Laptop; `main` at `25eb9586` with the uncommitted switch): `mise run sweep -- --var DBG_SPHERE_ORDER=0,1 --track heuristic --record work/2026-11/1066_sphere-list-order --topic <words> --images work/2026-11/1066_sphere-list-order/images --target bomb:2070-2179 --target bomb:2289-2388`.
  The flags were typed in the command; this entry was written after the sweeps.
- **First run** ([`sweeps/flat-depth-by-list-rank.toml`](sweeps/flat-depth-by-list-rank.toml)): `winner: DBG_SPHERE_ORDER=1 adopts (heuristic target idx +0.0172, 21/21 frames up; films ok; worst target frame +0.0039 bomb:2102; 18 frames down >0.005, listed)`.
  Seven of those 18 frames are `balloon` 376 to 441, down 0.0211 to 0.0315: the capture | baseline | variant picture of `balloon` 386 ([picture](images/balloon-386-flat-depth-by-list-rank-guard.png)) shows olive streaks fanning from the pilot over the ground, which the baseline does not draw.
  `[Hypothesis]`: they are outline corners a back-facing polygon collapses to the screen centre, which the variant gave a real depth, so a quad whose corners did not all collapse drew a wedge from the centre.
  The streaks are gone with collapsed corners left at their own depth, and the second run measures that form; the cause was not isolated further (skipping every line corner also removed them).
- **Result** ([`sweeps/flat-depth-by-list-rank-collapsed-corners-kept.toml`](sweeps/flat-depth-by-list-rank-collapsed-corners-kept.toml); `mise run judge -- --recheck` on it prints the same winner line): `winner: DBG_SPHERE_ORDER=1 adopts (heuristic target idx +0.0172, 21/21 frames up; films ok; worst target frame +0.0039 bomb:2102; 7 frames down >0.005, listed)`.

  | Film | `0` (`main`) | `1` | Δ |
  |---|---|---|---|
  | ctry | 0.9439 | 0.9442 | +0.0003 |
  | intro | 0.9069 | 0.9069 | +0.0000 |
  | land | 0.9312 | 0.9313 | +0.0002 |
  | balloon | 0.9068 | 0.9081 | +0.0013 |
  | traintnl | 0.9164 | 0.9164 | +0.0000 |
  | bomb | 0.9085 | 0.9113 | +0.0028 |
  | location | 0.8967 | 0.8970 | +0.0003 |

  - Target pictures, capture | baseline | variant: 2102 (the smallest gain, +0.0039; [picture](images/bomb-2102-flat-depth-by-list-rank-collapsed-corners-kept.png)), [2157](images/bomb-2157-flat-depth-by-list-rank-collapsed-corners-kept.png), [2311](images/bomb-2311-flat-depth-by-list-rank-collapsed-corners-kept.png), [2344](images/bomb-2344-flat-depth-by-list-rank-collapsed-corners-kept.png) and [2377](images/bomb-2377-flat-depth-by-list-rank-collapsed-corners-kept.png): in 2344 the variant's tree shows the trunk through the leaf clusters, as the capture does.
  - No film falls; no film rises by 0.002 or more except `bomb`, so the film-mean branch does not adopt and the target branch does: the pooled target index agreement rises by 0.0172, every one of the 21 scored target frames rises, and each range's own target mean rises.
  - The seven frames down more than 0.005 are `location` 1651 to 1772 (six frames, down 0.0057 to 0.0145) and `intro` 2718 (−0.0059).
    `intro` 2718 ([picture](images/intro-2718-flat-depth-by-list-rank-collapsed-corners-kept-guard.png)): a dark slanted bar draws over the aircraft's body in the variant where the baseline hides it behind the body, and the capture shows neither.
    `[Hypothesis]`: by its position the bar is a propeller blade; the picture does not show which primitive it is.
    `location` 1717 ([picture](images/location-1717-flat-depth-by-list-rank-collapsed-corners-kept-guard.png)): the forest's tree shapes cover each other in another order; the capture's trees are discs and ours stay polygons, so the picture does not show which order is nearer.
    Not found: why `location` loses where `bomb`'s trees gain.
  - Frames outside the target that moved more than 0.005: `intro` 1, `balloon` 18, `bomb` 54, `location` 16, the other three films none (the sweep's count, both directions).
- **SPEC § 2.1**: the form is not a CPU rasterizer or a painter's sort, and the draws stay in the GPU depth buffer, so the non-goal's "no CPU software rasterizer" is not broken.
  It does make depth within one shape a list-order rank instead of geometry, which [`SPEC.md`](../../../docs/SPEC.md) § 2.1 words as "Painter's Algorithm / BSP sorting give way to … depth buffering" and which [ADR 0045](../../../docs/adr/0045-flat-ground-is-painted-in-walk-order.md) already does for the flat ground.
  If adopted it needs an ADR amending that line, and the issue's own condition applies: the only form found needs per-draw flattened depth, so **the owner decides before it is adopted**.
- **Verdict**: the sweep's winner line says the form adopts, but guard 2 of [`loop-rules.md`](../../../.agents/skills/improving-render-parity/loop-rules.md) asks the entry to explain every frame that falls by more than 0.005, and that is NOT met for the seven frames (`location` 1651 to 1772 and `intro` 2718): the `location` cause was not found and the `intro` reading is a hypothesis.
  That is one reason the owner decides, and the form is not adopted, awaiting the owner.
  Productionising it would change the seam contracts (a rank in `SodVertex`'s padding byte, a per-vertex origin on `SodModelIr`), so it also needs [`changing-seam-contracts`](../../../.agents/skills/changing-seam-contracts/SKILL.md) and a lavapipe repin.
  The prototype's switch, the thread-local rank map and the weld-key offset are not fit to commit.
- **Lives in**: [`prop-shape-loss.md`](../../../research/parity/prop-shape-loss.md) § 2.3.

## 2026-11-26: the `location` falls are ground covering flattened canopies; `intro` 2718 is the aircraft's `SORT` order

`[Bounded Observation]`

- **Question**: why do the seven frames the list-order form loses (`location` 1651 to 1772, `intro` 2718) fall, the guard 2 explanation the entry above left open?
- **Track**: heuristic, as above; the same `--target bomb:2070-2179 --target bomb:2289-2388`, typed in the commands, not written here first.
- **Port** ([`switches/DBG_SPHERE_ORDER-lavapipe.diff`](switches/DBG_SPHERE_ORDER-lavapipe.diff), not committed under `crates/`; `main` at `c2e0aa9`): `main` now spends `SodVertex`'s padding byte on `decal_tie`, so the port keeps the tie in bit 0 and the rank in bits 1 to 7, which caps it at 127 where the GPU prototype capped it at 255.
  Bit 7 of a raw polygon's flags is now `VERTEX_FLAG_PRESHADED`, so the sphere mark moved to `0x20` (a line-end bit no filled polygon carries).
  `DBG_SPHERE_PULL=<cm>` moves the depth origin that far toward the eye, through the model uniform's last word; `DBG_SORT_TRACE` prints each ranked shape's polygon, rank and `OP_SORT` counts.
- **Recheck on lavapipe** ([`sweeps/lavapipe-recheck.toml`](sweeps/lavapipe-recheck.toml); `mise run judge -- --recheck` prints the same line): `winner: DBG_SPHERE_ORDER=1 adopts (heuristic target idx +0.0172, 21/21 frames up; films ok; worst target frame +0.0039 bomb:2102; 12 frames down >0.005, listed)`.
  The 12 are the GPU's seven at about the same size, plus `bomb` 1618, 1662, 1706 and 1728 (−0.0053 to −0.0081) and `location` 3378 (−0.0056).
  On the GPU the four `bomb` frames fell by 0.0038, rose by 0.0007, fell by 0.0042 and fell by 0.0021, under the listing bar.
  In `bomb` 1706 ([picture](images/bomb-1706-lavapipe-recheck-guard.png)) the pixels that change are the town on the horizon and the aircraft's wing roots; `[Hypothesis]`: the town blocks are ranked shapes (bomb's include shapes of 447 to 474 polygons whose ranks reach the port's 127 cap), and their buildings now cover each other by block origin and list order.
- **`location`: the ground covers the near half of a flattened canopy.**
  `location` 1717, capture | `0` | `1` ([picture](images/location-1717-lavapipe-recheck-guard.png)): in the variant many tree canopies end in a horizontal edge, below which the ground's colour shows where the baseline draws the rest of the canopy.
  The forest tree is `MODEL_07AF`, two spheres and no other primitive (40 polygons, ranks 1 and 2).
  Every primitive of it draws at its placement origin's depth, the trunk's foot on the ground, while the near side of a wide canopy lies nearer the eye than that foot and projects below it on screen; there the terrain between the canopy's near edge and the foot is nearer than the origin and wins the depth test.
  Moving the origin 5 m toward the eye removes the edges (capture | pull 0 | pull 5 m, both ordered: [picture](images/location-1717-lavapipe-pull-0-500.png)).
- **Pull sweep** ([`sweeps/lavapipe-origin-pulled-toward-eye.toml`](sweeps/lavapipe-origin-pulled-toward-eye.toml), `--var DBG_SPHERE_ORDER=0,1 --var DBG_SPHERE_PULL=0,500,1500`; its winner line is the unpulled form's, above, and `judge --recheck` reproduces it):

  | Variant | ctry | intro | land | balloon | traintnl | bomb | location | target idx | frames down >0.005 |
  |---|---|---|---|---|---|---|---|---|---|
  | `0` (`main`) | 0.9441 | 0.9069 | 0.9340 | 0.9067 | 0.9160 | 0.9083 | 0.8975 | | |
  | `1`, pull 0 | 0.9444 | 0.9069 | 0.9341 | 0.9081 | 0.9160 | 0.9108 | 0.8977 | +0.0172 | 12 |
  | `1`, pull 5 m | 0.9444 | 0.9068 | 0.9340 | 0.9079 | 0.9160 | 0.9109 | 0.8979 | +0.0171 | 7 |
  | `1`, pull 15 m | 0.9443 | 0.9067 | 0.9339 | 0.9078 | 0.9160 | 0.9072 | 0.8979 | −0.0073 | 58 |

  At 5 m all seven `location` frames of the unpulled list (1651 to 1772 and 3378) leave it and `bomb`'s target gain stays; `location` 2905, 6513 and 6689 (−0.0054, −0.0082, −0.0177) join it, their cause not looked at.
  At 15 m `bomb` falls by more than 0.005 on 51 frames, 38 of them by the same 0.0091 or 0.0145 in its opening ticks 12 to 420: a constant pull draws far shapes over nearer ones.
  So the `location` falls come from flattening to the placement's foot; a depth nearer the shape's own near side (its bounding sphere's nearest point, say) is the form to try, not a fixed pull.
- **`intro` 2718: the aircraft's `OP_SORT` branches run in a fixed order.**
  Capture | `0` | `1` ([picture](images/intro-2718-lavapipe-recheck-guard.png)): the capture shows only the propeller's upper tip above the fuselage, the baseline hides the blade behind it, and the variant draws the whole blade over it; pulling the origin changes nothing there.
  The aircraft, `MODEL_7F19` (177 polygons), holds a sphere, so it is ranked, and holds three `OP_SORT`s.
  `PLAYONE` runs a `SORT`'s two branches in the order its facing flag picks ([`sod-opcodes.md`](../../../research/formats/sod-opcodes.md) row 44), and our VM always runs the branch after the operands first (`sort` in `crates/stunt-core/src/sod/vm.rs`), so the list rank is right from one side only.
  `[Hypothesis]`: the propeller and the fuselage sit in one `SORT`'s two branches; which branch holds which was not read.
- **Verdict**: guard 2's seven frames are now explained, six by a picture and a sweep that removes them, one by a hypothesis that names the opcode.
  The form as measured is still not adopted, awaiting the owner; before it is worth adopting it needs a depth from the shape's near side rather than its foot, and the VM to run `SORT` branches in facing order (a change that touches every shape, not only ranked ones).
- **Lives in**: [`prop-shape-loss.md`](../../../research/parity/prop-shape-loss.md) § 2.3.
